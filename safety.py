"""
Validation & safety layer for the text-to-SQL pipeline.

Defense in depth, in order:
  1. Keyword/pattern check on the SQL text itself (fast, catches obvious cases)
  2. The DB connection is opened in TRUE READ-ONLY mode at the SQLite level,
     so even if a write statement somehow slipped past #1, SQLite itself
     will refuse to execute it.
  3. A row LIMIT is enforced so a runaway SELECT can't return millions of
     rows into memory.
  4. A timeout aborts any query that runs too long (e.g. an accidental
     cross join), using sqlite3's interrupt() from a watchdog thread --
     this works cross-platform (signal.alarm does not exist on Windows).

Any failure anywhere in this pipeline raises SafetyError or QueryError with
a clean, user-facing message -- never a raw traceback.
"""

import re
import sqlite3
import threading
import pandas as pd

FORBIDDEN_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "REPLACE", "ATTACH", "DETACH", "PRAGMA", "VACUUM",
    "REINDEX", "GRANT", "REVOKE",
]

MAX_ROWS = 1000
DEFAULT_TIMEOUT_SECONDS = 25


class SafetyError(Exception):
    """Raised when a query is rejected before ever touching the database."""
    pass


class QueryError(Exception):
    """Raised when a query is safe but fails to execute (bad SQL, timeout)."""
    pass


def is_safe_query(sql: str) -> tuple[bool, str]:
    """Static check on the SQL text. Returns (is_safe, reason_if_not)."""
    if not sql or not sql.strip():
        return False, "Empty query."

    stripped = sql.strip().upper()

    if not (stripped.startswith("SELECT") or stripped.startswith("WITH")):
        return False, "Query must start with SELECT or WITH (a CTE feeding a SELECT)."

    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", stripped):
            return False, f"Forbidden keyword detected: {kw}"

    # Reject stacked statements (e.g. "SELECT 1; DROP TABLE orders")
    body = sql.strip().rstrip(";")
    if ";" in body:
        return False, "Multiple statements are not allowed."

    # Reject inline comments, a common SQL-injection-style smuggling trick
    if "--" in sql or "/*" in sql:
        return False, "Inline comments are not allowed in generated SQL."

    return True, ""


def enforce_row_limit(sql: str, max_rows: int = MAX_ROWS) -> str:
    """
    Ensure the query never returns more than max_rows.
    - If there's no LIMIT clause, append one.
    - If there IS a LIMIT clause with a larger value, cap it.
    LIMIT is always the last clause in a SELECT, so a tail-anchored regex
    is sufficient and doesn't need a full SQL parser.
    """
    body = sql.strip().rstrip(";")
    match = re.search(r"\bLIMIT\s+(\d+)\s*$", body, re.IGNORECASE)
    if match:
        existing_limit = int(match.group(1))
        if existing_limit > max_rows:
            body = body[: match.start()] + f"LIMIT {max_rows}"
        return body
    return f"{body} LIMIT {max_rows}"


def _run_with_timeout(sql: str, db_path: str, timeout_seconds: int) -> pd.DataFrame:
    """
    Execute sql against db_path in true read-only mode, aborting via
    conn.interrupt() from a watchdog thread if it runs past timeout_seconds.
    """
    # mode=ro at the SQLite URI level: the connection physically cannot
    # write to the database file, regardless of what SQL text reaches it.
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)

    result = {"df": None, "error": None}
    timed_out = threading.Event()

    timer = threading.Timer(timeout_seconds, lambda: (not timed_out.is_set()) and conn.interrupt())
    timer.daemon = True
    timer.start()

    try:
        result["df"] = pd.read_sql_query(sql, conn)
    except Exception as e:
        # pandas wraps the underlying sqlite3 error in its own
        # pandas.errors.DatabaseError (not the raw sqlite3 exception), so we
        # catch broadly here and inspect the message rather than the type --
        # this is already scoped to a validated SELECT-only query, so a
        # broad catch is safe: anything that goes wrong here is a query
        # execution failure, never a security concern.
        if "interrupted" in str(e).lower():
            result["error"] = QueryError(
                f"Query timed out after {timeout_seconds}s. Try narrowing the question "
                "(add a filter, or ask for a smaller date range)."
            )
        else:
            result["error"] = QueryError(f"SQL error: {e}")
    finally:
        timed_out.set()
        timer.cancel()
        conn.close()

    if result["error"]:
        raise result["error"]
    return result["df"]


def run_query_safely(
    sql: str,
    db_path: str,
    max_rows: int = MAX_ROWS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> pd.DataFrame:
    """
    Full safety pipeline: validate -> cap rows -> execute with timeout.
    Raises SafetyError for rejected queries, QueryError for execution failures.
    """
    is_safe, reason = is_safe_query(sql)
    if not is_safe:
        raise SafetyError(reason)

    limited_sql = enforce_row_limit(sql, max_rows)
    return _run_with_timeout(limited_sql, db_path, timeout_seconds)