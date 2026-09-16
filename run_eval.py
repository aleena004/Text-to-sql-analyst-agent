"""
Runs the full text-to-SQL pipeline against every question in eval_questions.py,
executes the reference SQL for comparison, and writes a report.

Run with:  python run_eval.py

This does NOT auto-grade correctness -- SQL has many valid phrasings for the
same question (different column aliases, JOIN vs WHERE-based joins, etc.), so
exact string or even exact-dataframe matching would produce false negatives.
Instead this prints both results side by side and asks you to confirm or
reject each one. Your judgments get saved to eval_results.md, which is what
you'll paste an accuracy number and failure-mode notes from into the README.
"""

import time
from pipeline import ask
from safety import SafetyError, QueryError
from eval_questions import EVAL_QUESTIONS
import sqlite3
import pandas as pd

DB_PATH = "olist.db"


def run_reference(sql: str) -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    try:
        return pd.read_sql_query(sql, conn)
    finally:
        conn.close()


def main():
    results = []

    print(f"Running {len(EVAL_QUESTIONS)} evaluation questions...\n")
    print("=" * 80)

    for item in EVAL_QUESTIONS:
        print(f"\n[{item['id']}] ({item['difficulty']}) {item['question']}")
        if item.get("note"):
            print(f"  note: {item['note']}")

        # --- Reference (ground truth) ---
        ref_df = run_reference(item["reference_sql"])
        print(f"\n  REFERENCE SQL:\n    {item['reference_sql']}")
        print(f"  REFERENCE RESULT:\n{ref_df.head(5).to_string(index=False)}")
        print(f"  (expected: {item['expected']})")

        # --- Generated (model) ---
        start = time.time()
        try:
            gen_sql, gen_df = ask(item["question"], DB_PATH)
            elapsed = time.time() - start
            print(f"\n  GENERATED SQL ({elapsed:.1f}s):\n    {gen_sql}")
            print(f"  GENERATED RESULT:\n{gen_df.head(5).to_string(index=False)}")
            status = "ran"
        except (SafetyError, QueryError) as e:
            gen_sql, gen_df, elapsed = None, None, time.time() - start
            print(f"\n  GENERATED: BLOCKED/FAILED -> {e}")
            status = "failed"
        except Exception as e:
            gen_sql, gen_df, elapsed = None, None, time.time() - start
            print(f"\n  GENERATED: UNEXPECTED ERROR -> {e}")
            status = "error"

        # --- Manual verdict ---
        verdict = input("\n  Correct? [y/n/p(artial)]: ").strip().lower()
        note = input("  Note (optional, press enter to skip): ").strip()

        results.append({
            "id": item["id"],
            "difficulty": item["difficulty"],
            "question": item["question"],
            "status": status,
            "generated_sql": gen_sql,
            "verdict": verdict,
            "note": note,
            "time_s": round(elapsed, 1),
        })
        print("=" * 80)

    # --- Write report ---
    correct = sum(1 for r in results if r["verdict"] == "y")
    total = len(results)
    print(f"\n\nFINAL SCORE: {correct}/{total} correct")

    with open("eval_results.md", "w", encoding="utf-8") as f:
        f.write("# Evaluation Results\n\n")
        f.write(f"**Score: {correct}/{total} correct**\n\n")
        f.write("| ID | Difficulty | Question | Verdict | Time (s) | Note |\n")
        f.write("|---|---|---|---|---|---|\n")
        for r in results:
            v = {"y": "✅", "n": "❌", "p": "⚠️ partial"}.get(r["verdict"], r["verdict"])
            f.write(f"| {r['id']} | {r['difficulty']} | {r['question']} | {v} | {r['time_s']} | {r['note']} |\n")

        f.write("\n## Generated SQL log\n\n")
        for r in results:
            f.write(f"### {r['id']}: {r['question']}\n")
            f.write(f"```sql\n{r['generated_sql'] or '-- ' + r['status']}\n```\n\n")

    print("Full report written to eval_results.md")


if __name__ == "__main__":
    main()