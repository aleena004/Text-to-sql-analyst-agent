"""
Evaluation question bank for the text-to-SQL pipeline.

Each entry has a hand-written reference_sql that has been verified against
the real olist.db (see chat history / dev notes). expected is the ground
truth result computed from that reference query, included so the harness
(and a human) can sanity-check without re-deriving it every time.

Difficulty tiers, per the project plan:
  simple     - single table, no joins
  filter     - single table with a WHERE clause
  join       - 2-3 table join
  aggregation - GROUP BY / AVG / HAVING
  subquery   - correlated subquery, EXISTS, or nested aggregation
"""

EVAL_QUESTIONS = [
    {
        "id": "Q1", "difficulty": "simple",
        "question": "How many orders were placed in total?",
        "reference_sql": "SELECT COUNT(*) FROM orders",
        "expected": 99441,
    },
    {
        "id": "Q2", "difficulty": "simple",
        "question": "How many unique customers are there?",
        "reference_sql": "SELECT COUNT(DISTINCT customer_unique_id) FROM customers",
        "expected": 96096,
        "note": "customer_unique_id, not customer_id -- see Q19 for why this distinction matters.",
    },
    {
        "id": "Q3", "difficulty": "simple",
        "question": "How many products are there in the catalog?",
        "reference_sql": "SELECT COUNT(*) FROM products",
        "expected": 32951,
    },
    {
        "id": "Q4", "difficulty": "simple",
        "question": "What are the possible order statuses?",
        "reference_sql": "SELECT DISTINCT order_status FROM orders",
        "expected": "8 distinct statuses (delivered, shipped, canceled, ...)",
    },
    {
        "id": "Q5", "difficulty": "filter",
        "question": "How many orders were canceled?",
        "reference_sql": "SELECT COUNT(*) FROM orders WHERE order_status = 'canceled'",
        "expected": 625,
    },
    {
        "id": "Q6", "difficulty": "filter",
        "question": "How many orders were placed in 2017?",
        "reference_sql": "SELECT COUNT(*) FROM orders WHERE strftime('%Y', order_purchase_timestamp) = '2017'",
        "expected": 45101,
    },
    {
        "id": "Q7", "difficulty": "filter",
        "question": "How many customers are located in Sao Paulo (SP) state?",
        "reference_sql": "SELECT COUNT(*) FROM customers WHERE customer_state = 'SP'",
        "expected": 41746,
    },
    {
        "id": "Q8", "difficulty": "filter",
        "question": "How many products belong to the 'toys' category?",
        "reference_sql": (
            "SELECT COUNT(*) FROM products p "
            "JOIN category_translation ct ON p.product_category_name = ct.product_category_name "
            "WHERE ct.product_category_name_english = 'toys'"
        ),
        "expected": 1411,
        "note": "Tests whether the model knows to use category_translation for the English name.",
    },
    {
        "id": "Q9", "difficulty": "join",
        "question": "What are the top 5 product categories by revenue?",
        "reference_sql": (
            "SELECT ct.product_category_name_english, SUM(oi.price) rev "
            "FROM order_items oi JOIN products p ON oi.product_id=p.product_id "
            "JOIN category_translation ct ON p.product_category_name=ct.product_category_name "
            "GROUP BY ct.product_category_name_english ORDER BY rev DESC LIMIT 5"
        ),
        "expected": "health_beauty (1,258,681.34) tops the list",
        "note": "Revenue = SUM(price) only, per project convention -- excludes freight_value.",
    },
    {
        "id": "Q10", "difficulty": "join",
        "question": "Which seller has sold the most items?",
        "reference_sql": "SELECT seller_id, COUNT(*) n FROM order_items GROUP BY seller_id ORDER BY n DESC LIMIT 1",
        "expected": "seller 6560211a19b47992c3666cc44a7e94c0 with 2033 items",
    },
    {
        "id": "Q11", "difficulty": "join",
        "question": "What is the total freight value paid by customers in Rio de Janeiro (RJ)?",
        "reference_sql": (
            "SELECT SUM(oi.freight_value) FROM order_items oi "
            "JOIN orders o ON oi.order_id=o.order_id "
            "JOIN customers c ON o.customer_id=c.customer_id WHERE c.customer_state='RJ'"
        ),
        "expected": 305589.31,
    },
    {
        "id": "Q12", "difficulty": "join",
        "question": "List the top 5 customers by total amount spent.",
        "reference_sql": (
            "SELECT c.customer_unique_id, SUM(oi.price) spent FROM customers c "
            "JOIN orders o ON c.customer_id=o.customer_id "
            "JOIN order_items oi ON o.order_id=oi.order_id "
            "GROUP BY c.customer_unique_id ORDER BY spent DESC LIMIT 5"
        ),
        "expected": "top spender: 13,440.00",
        "note": "Should group by customer_unique_id, not customer_id, to correctly identify the same real person.",
    },
    {
        "id": "Q13", "difficulty": "aggregation",
        "question": "What is the average delivery time in days from purchase to delivery for delivered orders?",
        "reference_sql": (
            "SELECT AVG(julianday(order_delivered_customer_date)-julianday(order_purchase_timestamp)) "
            "FROM orders WHERE order_status='delivered'"
        ),
        "expected": 12.56,
        "note": "Tests whether the model uses julianday() correctly for date arithmetic in SQLite.",
    },
    {
        "id": "Q14", "difficulty": "aggregation",
        "question": "What is the average review score for orders paid by credit card?",
        "reference_sql": (
            "SELECT AVG(r.review_score) FROM order_reviews r WHERE EXISTS "
            "(SELECT 1 FROM order_payments p WHERE p.order_id=r.order_id AND p.payment_type='credit_card')"
        ),
        "expected": 4.09,
    },
    {
        "id": "Q15", "difficulty": "aggregation",
        "question": "Which payment type is used most frequently?",
        "reference_sql": "SELECT payment_type, COUNT(*) n FROM order_payments GROUP BY payment_type ORDER BY n DESC LIMIT 1",
        "expected": "credit_card (76,795 uses)",
    },
    {
        "id": "Q16", "difficulty": "subquery",
        "question": "How many orders were delivered late (after the estimated delivery date)?",
        "reference_sql": (
            "SELECT COUNT(*) FROM orders WHERE order_delivered_customer_date IS NOT NULL "
            "AND order_delivered_customer_date > order_estimated_delivery_date"
        ),
        "expected": 7827,
    },
    {
        "id": "Q17", "difficulty": "subquery",
        "question": "Which product category has the highest average review score, among categories with at least 20 reviews?",
        "reference_sql": (
            "SELECT ct.product_category_name_english, AVG(r.review_score) avgscore "
            "FROM order_reviews r JOIN orders o ON r.order_id=o.order_id "
            "JOIN order_items oi ON o.order_id=oi.order_id "
            "JOIN products p ON oi.product_id=p.product_id "
            "JOIN category_translation ct ON p.product_category_name=ct.product_category_name "
            "GROUP BY ct.product_category_name_english HAVING COUNT(*) >= 20 "
            "ORDER BY avgscore DESC LIMIT 1"
        ),
        "expected": "books_general_interest (4.45 avg)",
        "note": "The HAVING COUNT(*) >= 20 filter is explicitly stated in the question to avoid a "
                "single 5-star review in a tiny category winning by default.",
    },
    {
        "id": "Q18", "difficulty": "subquery",
        "question": "What percentage of orders were paid using installments (more than one payment installment)?",
        "reference_sql": "SELECT 100.0*SUM(CASE WHEN payment_installments>1 THEN 1 ELSE 0 END)/COUNT(*) FROM order_payments",
        "expected": 49.42,
    },
    {
        "id": "Q19", "difficulty": "subquery",
        "question": "How many customers have placed more than one order?",
        "reference_sql": (
            "SELECT COUNT(*) FROM (SELECT c.customer_unique_id FROM customers c "
            "JOIN orders o ON c.customer_id = o.customer_id "
            "GROUP BY c.customer_unique_id HAVING COUNT(*) > 1)"
        ),
        "expected": 2997,
        "note": (
            "KNOWN DATASET QUIRK: customer_id is unique PER ORDER in this dataset -- "
            "customer_unique_id is the real repeat-customer identifier. A model that "
            "groups by customer_id instead will incorrectly return 0. This is left "
            "unhinted in the prompt deliberately, as a genuine test case."
        ),
    },
]