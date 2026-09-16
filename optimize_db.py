"""
One-off fix: run ANALYZE on an existing olist.db to build query planner
statistics (sqlite_stat1), without re-importing all the CSVs from scratch.

Run once:  python optimize_db.py
"""

import sqlite3
import time

conn = sqlite3.connect("olist.db")
print("Running ANALYZE...")
start = time.time()
conn.execute("ANALYZE;")
conn.commit()
conn.close()
print(f"Done in {time.time() - start:.2f}s. Query planner statistics are now up to date.")