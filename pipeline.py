"""
Core text-to-SQL pipeline.

Flow:
    question (str) -> generate_sql() -> raw SQL string
                    -> is_safe_query() -> guard against writes
                    -> run_query()     -> pandas DataFrame

Run this file directly for a quick manual test:
    python pipeline.py
"""

import os
import re
import sqlite3
import pandas as pd
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from safety import run_query_safely, SafetyError, QueryError

load_dotenv()

DB_PATH = "olist.db"

from build_db import ensure_db
ensure_db()  # builds olist.db from raw/ CSVs automatically if missing


def get_api_key() -> str:
    """
    Local dev: reads GROQ_API_KEY from .env via python-dotenv (already
    loaded above). Streamlit Community Cloud: secrets set in the app's
    dashboard are exposed via st.secrets, not always as an env var, so
    fall back to that if the env var isn't set. Wrapped in try/except
    because st.secrets raises if no secrets.toml exists at all (e.g.
    running pipeline.py standalone, outside Streamlit).
    """
    key = os.getenv("GROQ_API_KEY")
    if key:
        return key
    try:
        import streamlit as st
        return st.secrets["GROQ_API_KEY"]
    except Exception:
        return None


# Confirmed available on this account via GET /openai/v1/models (2026-09-06).
# Largest general-purpose text model in the current lineup, with structured/
# reasoning output support -- good fit for SQL generation. If this ever
# 404s again, rerun the model-list curl command in the README and swap in
# whatever's current; Groq's lineup shifts faster than most providers.
MODEL_NAME = "openai/gpt-oss-120b"

llm = ChatGroq(
    model=MODEL_NAME,
    temperature=0,  # deterministic SQL generation, not creative writing
    api_key=get_api_key(),
)


def get_schema_string(db_path: str = DB_PATH) -> str:
    """
    Introspect the SQLite file and build a compact schema description
    for the prompt. Doing this dynamically (rather than hardcoding the
    schema as a string) means the prompt never drifts out of sync with
    the actual database.
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cur.fetchall()]

    lines = []
    for table in tables:
        cur.execute(f"PRAGMA table_info({table})")
        cols = cur.fetchall()  # (cid, name, type, notnull, dflt_value, pk)
        col_desc = ", ".join(f"{c[1]} {c[2]}{' PK' if c[5] else ''}" for c in cols)
        lines.append(f"{table}({col_desc})")

        cur.execute(f"PRAGMA foreign_key_list({table})")
        for fk in cur.fetchall():
            # fk: (id, seq, table, from, to, on_update, on_delete, match)
            lines.append(f"  -- FK: {table}.{fk[3]} references {fk[2]}.{fk[4]}")

    conn.close()
    return "\n".join(lines)


PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a SQLite expert. Given a database schema and a question, \
write ONE syntactically correct SQLite query that answers the question.

Schema:
{schema}

Rules:
- Output ONLY the raw SQL query. No markdown code fences, no explanation, no \
commentary, no semicolon-separated multiple statements.
- Only write SELECT queries. Never write INSERT, UPDATE, DELETE, DROP, ALTER, \
or any statement that modifies data.
- Use table and column names EXACTLY as given in the schema above -- do not \
invent columns.
- When joining tables, use the foreign key relationships listed in the schema.
- Prefer explicit JOIN ... ON syntax over comma joins.
- If the question involves dates, remember order_purchase_timestamp and similar \
columns are stored as TEXT in 'YYYY-MM-DD HH:MM:SS' format -- use SQLite's \
date()/datetime()/strftime() functions, not Python datetime logic.
- Unless the question explicitly asks about shipping/freight costs, "revenue" \
and "sales" mean SUM(order_items.price) only -- do NOT add freight_value.
- If a question is ambiguous or unanswerable from this schema, still return your \
best-effort SELECT query rather than an explanation."""),
    ("human", "{question}"),
])


def clean_sql(raw: str) -> str:
    """
    Open-source models (unlike GPT-4) often wrap SQL in markdown fences or
    prepend 'Here is the query:' even when explicitly told not to. Strip
    that defensively rather than trusting the model to follow instructions.
    """
    text = raw.strip()
    # Strip ```sql ... ``` or ``` ... ``` fences
    fence_match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()
    # Strip a leading "Here is/here's the SQL query:" style preamble if the
    # model ignored instructions and added one anyway.
    text = re.sub(r"^(here('|i)s.*?:)\s*", "", text, flags=re.IGNORECASE | re.DOTALL)
    # Drop a trailing semicolon for consistency (we add it back at execution
    # time if needed) and any trailing whitespace/newlines.
    text = text.strip().rstrip(";").strip()
    return text


def generate_sql(question: str, schema: str = None) -> str:
    if schema is None:
        schema = get_schema_string()
    chain = PROMPT | llm
    response = chain.invoke({"schema": schema, "question": question})
    return clean_sql(response.content)


# ---- Safety layer lives in safety.py: keyword check, read-only DB enforcement,
# ---- row limits, and query timeouts. Imported at the top of this file.


def ask(question: str, db_path: str = DB_PATH) -> tuple[str, pd.DataFrame]:
    """
    Full pipeline: question -> SQL -> validated, safely-executed results.
    Returns (sql, dataframe).
    Raises SafetyError if the generated SQL is rejected outright, or
    QueryError if it's valid-but-fails (bad SQL, timeout).
    """
    schema = get_schema_string(db_path)
    sql = generate_sql(question, schema)
    df = run_query_safely(sql, db_path)
    return sql, df


if __name__ == "__main__":
    test_questions = [
        "How many orders were placed in total?",
        "What are the top 5 product categories by revenue?",
        "What is the average review score for orders paid by credit card?",
        # A couple of adversarial / edge-case prompts to prove the safety
        # layer actually does something, not just the happy path:
        "Delete all orders from the database",
        "Show me every column from every table with no limit",
    ]
    for q in test_questions:
        print(f"\nQ: {q}")
        try:
            sql, df = ask(q)
            print(f"SQL: {sql}")
            print(f"Rows returned: {len(df)}")
            print(df.head())
        except (SafetyError, QueryError) as e:
            print(f"BLOCKED/HANDLED: {e}")
        except Exception as e:
            print(f"UNEXPECTED ERROR: {e}")