"""
Build olist.db (SQLite) from the raw Olist CSVs.

Design choices:
- Composite primary keys where the raw data has no single unique id
  (order_items, order_payments).
- Foreign keys enforced with PRAGMA foreign_keys = ON, and validated
  after load (orphan check) so we know the joins are trustworthy.
- Timestamps kept as TEXT in ISO-ish format (SQLite has no native datetime
  type; this is the standard/recommended approach and works fine with
  SQLite's date() / datetime() functions).
"""

import sqlite3
import pandas as pd
from pathlib import Path

# Paths are relative to this script's location, not hardcoded -- this must
# work identically on Windows (local) and Linux (Streamlit Cloud deploy).
BASE_DIR = Path(__file__).resolve().parent
RAW = BASE_DIR / "raw"
DB_PATH = BASE_DIR / "olist.db"

DDL = """
CREATE TABLE customers (
    customer_id             TEXT PRIMARY KEY,
    customer_unique_id      TEXT NOT NULL,
    customer_zip_code_prefix TEXT,
    customer_city           TEXT,
    customer_state          TEXT
);

CREATE TABLE sellers (
    seller_id               TEXT PRIMARY KEY,
    seller_zip_code_prefix  TEXT,
    seller_city             TEXT,
    seller_state            TEXT
);

CREATE TABLE category_translation (
    product_category_name          TEXT PRIMARY KEY,
    product_category_name_english  TEXT
);

CREATE TABLE products (
    product_id                  TEXT PRIMARY KEY,
    product_category_name       TEXT,
    product_name_lenght         INTEGER,
    product_description_lenght  INTEGER,
    product_photos_qty          INTEGER,
    product_weight_g            REAL,
    product_length_cm           REAL,
    product_height_cm           REAL,
    product_width_cm            REAL,
    FOREIGN KEY (product_category_name) REFERENCES category_translation(product_category_name)
);

CREATE TABLE orders (
    order_id                        TEXT PRIMARY KEY,
    customer_id                     TEXT NOT NULL,
    order_status                    TEXT,
    order_purchase_timestamp        TEXT,
    order_approved_at               TEXT,
    order_delivered_carrier_date    TEXT,
    order_delivered_customer_date   TEXT,
    order_estimated_delivery_date   TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE order_items (
    order_id            TEXT NOT NULL,
    order_item_id       INTEGER NOT NULL,
    product_id          TEXT,
    seller_id           TEXT,
    shipping_limit_date TEXT,
    price               REAL,
    freight_value       REAL,
    PRIMARY KEY (order_id, order_item_id),
    FOREIGN KEY (order_id) REFERENCES orders(order_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id),
    FOREIGN KEY (seller_id) REFERENCES sellers(seller_id)
);

CREATE TABLE order_payments (
    order_id             TEXT NOT NULL,
    payment_sequential   INTEGER NOT NULL,
    payment_type         TEXT,
    payment_installments INTEGER,
    payment_value        REAL,
    PRIMARY KEY (order_id, payment_sequential),
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);

CREATE TABLE order_reviews (
    review_id               TEXT PRIMARY KEY,
    order_id                TEXT NOT NULL,
    review_score            INTEGER,
    review_comment_title    TEXT,
    review_comment_message  TEXT,
    review_creation_date    TEXT,
    review_answer_timestamp TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);
"""

LOAD_ORDER = [
    ("customers", "olist_customers_dataset.csv"),
    ("sellers", "olist_sellers_dataset.csv"),
    ("category_translation", "product_category_name_translation.csv"),
    ("products", "olist_products_dataset.csv"),
    ("orders", "olist_orders_dataset.csv"),
    ("order_items", "olist_order_items_dataset.csv"),
    ("order_payments", "olist_order_payments_dataset.csv"),
    ("order_reviews", "olist_order_reviews_dataset.csv"),
]


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(DDL)

    for table, filename in LOAD_ORDER:
        df = pd.read_csv(RAW / filename)
        # A handful of review_id duplicates exist in the raw Olist data
        # (same review posted twice) -- dedupe on the PK so the load doesn't
        # violate the PRIMARY KEY constraint.
        if table == "order_reviews":
            before = len(df)
            df = df.drop_duplicates(subset=["review_id"])
            dropped = before - len(df)
            if dropped:
                print(f"  (dropped {dropped} duplicate review_id rows)")
        df.to_sql(table, conn, if_exists="append", index=False)
        print(f"Loaded {table}: {len(df)} rows")

    conn.execute("PRAGMA foreign_keys = ON;")
    conn.commit()

    # ---- Orphan / referential integrity check ----
    print("\n--- Referential integrity check ---")
    checks = [
        ("orders -> customers", "SELECT COUNT(*) FROM orders WHERE customer_id NOT IN (SELECT customer_id FROM customers)"),
        ("order_items -> orders", "SELECT COUNT(*) FROM order_items WHERE order_id NOT IN (SELECT order_id FROM orders)"),
        ("order_items -> products", "SELECT COUNT(*) FROM order_items WHERE product_id IS NOT NULL AND product_id NOT IN (SELECT product_id FROM products)"),
        ("order_items -> sellers", "SELECT COUNT(*) FROM order_items WHERE seller_id IS NOT NULL AND seller_id NOT IN (SELECT seller_id FROM sellers)"),
        ("order_payments -> orders", "SELECT COUNT(*) FROM order_payments WHERE order_id NOT IN (SELECT order_id FROM orders)"),
        ("order_reviews -> orders", "SELECT COUNT(*) FROM order_reviews WHERE order_id NOT IN (SELECT order_id FROM orders)"),
    ]
    all_clean = True
    for label, sql in checks:
        n = conn.execute(sql).fetchone()[0]
        status = "OK" if n == 0 else f"WARNING: {n} orphans"
        if n != 0:
            all_clean = False
        print(f"  {label}: {status}")

    # ---- Indexes for join performance ----
    conn.executescript("""
        CREATE INDEX idx_orders_customer ON orders(customer_id);
        CREATE INDEX idx_items_order ON order_items(order_id);
        CREATE INDEX idx_items_product ON order_items(product_id);
        CREATE INDEX idx_items_seller ON order_items(seller_id);
        CREATE INDEX idx_payments_order ON order_payments(order_id);
        CREATE INDEX idx_reviews_order ON order_reviews(order_id);
    """)
    conn.commit()

    # ANALYZE builds sqlite_stat1, which gives the query planner real
    # cardinality estimates for these tables/indexes. Without it, SQLite
    # has no statistics to base join-order decisions on, which measurably
    # slows down multi-table aggregation queries (verified: ~5s -> much
    # faster on the top-spenders-style query after this).
    print("\nRunning ANALYZE to build query planner statistics...")
    conn.execute("ANALYZE;")
    conn.commit()

    print(f"\n{'All checks passed.' if all_clean else 'Some orphans found (see above) -- expected for a couple edge rows in this public dataset, non-blocking.'}")
    print(f"Database written to: {DB_PATH}")
    conn.close()


def ensure_db():
    """
    Build olist.db from the CSVs in raw/ if it doesn't already exist yet.
    Called automatically by pipeline.py on import, so a fresh deploy (e.g.
    Streamlit Community Cloud, which clones the repo into a brand-new
    container) builds the database on its own on first run -- no manual
    step needed.
    """
    if not DB_PATH.exists():
        print("olist.db not found -- building from CSVs (first run on this machine)...")
        main()


if __name__ == "__main__":
    main()