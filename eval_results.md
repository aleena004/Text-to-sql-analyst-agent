# Evaluation Results

**Score: 15/19 correct**

| ID | Difficulty | Question | Verdict | Time (s) | Note |
|---|---|---|---|---|---|
| Q1 | simple | How many orders were placed in total? | ✅ | 1.4 |  |
| Q2 | simple | How many unique customers are there? | ❌ | 1.3 |  |
| Q3 | simple | How many products are there in the catalog? | ✅ | 0.6 |  |
| Q4 | simple | What are the possible order statuses? | ✅ | 0.7 |  |
| Q5 | filter | How many orders were canceled? | ✅ | 1.0 |  |
| Q6 | filter | How many orders were placed in 2017? | ✅ | 1.1 |  |
| Q7 | filter | How many customers are located in Sao Paulo (SP) state? | ✅ | 0.8 |  |
| Q8 | filter | How many products belong to the 'toys' category? | ✅ | 1.1 |  |
| Q9 | join | What are the top 5 product categories by revenue? | ✅ | 3.2 |  |
| Q10 | join | Which seller has sold the most items? | ✅ | 1.6 |  |
| Q11 | join | What is the total freight value paid by customers in Rio de Janeiro (RJ)? | ❌ | 5.4 |  |
| Q12 | join | List the top 5 customers by total amount spent. | ✅ | 4.3 |  |
| Q13 | aggregation | What is the average delivery time in days from purchase to delivery for delivered orders? | ✅ | 1.1 |  |
| Q14 | aggregation | What is the average review score for orders paid by credit card? | ✅ | 3.1 |  |
| Q15 | aggregation | Which payment type is used most frequently? | ✅ | 0.8 |  |
| Q16 | subquery | How many orders were delivered late (after the estimated delivery date)? | ✅ | 1.3 |  |
| Q17 | subquery | Which product category has the highest average review score, among categories with at least 20 reviews? | ✅ | 6.0 |  |
| Q18 | subquery | What percentage of orders were paid using installments (more than one payment installment)? | ❌ | 1.9 |  |
| Q19 | subquery | How many customers have placed more than one order? | ❌ | 0.9 |  |

## Generated SQL log

### Q1: How many orders were placed in total?
```sql
SELECT COUNT(*) FROM orders
```

### Q2: How many unique customers are there?
```sql
SELECT COUNT(DISTINCT customer_id) AS unique_customers FROM customers
```

### Q3: How many products are there in the catalog?
```sql
SELECT COUNT(*) FROM products
```

### Q4: What are the possible order statuses?
```sql
SELECT DISTINCT order_status FROM orders
```

### Q5: How many orders were canceled?
```sql
SELECT COUNT(*) FROM orders WHERE order_status = 'canceled'
```

### Q6: How many orders were placed in 2017?
```sql
SELECT COUNT(*) AS orders_2017 FROM orders WHERE strftime('%Y', order_purchase_timestamp) = '2017'
```

### Q7: How many customers are located in Sao Paulo (SP) state?
```sql
SELECT COUNT(*) FROM customers WHERE customer_state = 'SP'
```

### Q8: How many products belong to the 'toys' category?
```sql
SELECT COUNT(*) 
FROM products p 
JOIN category_translation ct ON p.product_category_name = ct.product_category_name 
WHERE ct.product_category_name_english = 'toys'
```

### Q9: What are the top 5 product categories by revenue?
```sql
SELECT ct.product_category_name_english AS category, SUM(oi.price) AS revenue
FROM order_items oi
JOIN products p ON oi.product_id = p.product_id
JOIN category_translation ct ON p.product_category_name = ct.product_category_name
GROUP BY ct.product_category_name_english
ORDER BY revenue DESC
LIMIT 5
```

### Q10: Which seller has sold the most items?
```sql
SELECT oi.seller_id, COUNT(*) AS items_sold
FROM order_items AS oi
GROUP BY oi.seller_id
ORDER BY items_sold DESC
LIMIT 1
```

### Q11: What is the total freight value paid by customers in Rio de Janeiro (RJ)?
```sql
SELECT SUM(oi.freight_value) AS total_freight_value
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
JOIN order_items oi ON o.order_id = oi.order_id
WHERE c.customer_city = 'Rio de Janeiro' AND c.customer_state = 'RJ'
```

### Q12: List the top 5 customers by total amount spent.
```sql
SELECT c.customer_id, SUM(oi.price) AS total_spent
FROM customers c
JOIN orders o ON c.customer_id = o.customer_id
JOIN order_items oi ON o.order_id = oi.order_id
GROUP BY c.customer_id
ORDER BY total_spent DESC
LIMIT 5
```

### Q13: What is the average delivery time in days from purchase to delivery for delivered orders?
```sql
SELECT AVG(julianday(order_delivered_customer_date) - julianday(order_purchase_timestamp)) AS avg_delivery_days FROM orders WHERE order_delivered_customer_date IS NOT NULL
```

### Q14: What is the average review score for orders paid by credit card?
```sql
SELECT AVG(review_score) AS average_review_score
FROM order_reviews
WHERE order_id IN (
    SELECT order_id
    FROM order_payments
    WHERE payment_type = 'credit_card'
)
```

### Q15: Which payment type is used most frequently?
```sql
SELECT payment_type
FROM order_payments
GROUP BY payment_type
ORDER BY COUNT(*) DESC
LIMIT 1
```

### Q16: How many orders were delivered late (after the estimated delivery date)?
```sql
SELECT COUNT(*) FROM orders WHERE order_delivered_customer_date IS NOT NULL AND order_delivered_customer_date > order_estimated_delivery_date
```

### Q17: Which product category has the highest average review score, among categories with at least 20 reviews?
```sql
SELECT ct.product_category_name_english
FROM order_reviews orv
JOIN orders o ON orv.order_id = o.order_id
JOIN order_items oi ON o.order_id = oi.order_id
JOIN products p ON oi.product_id = p.product_id
JOIN category_translation ct ON p.product_category_name = ct.product_category_name
GROUP BY ct.product_category_name_english
HAVING COUNT(*) >= 20
ORDER BY AVG(orv.review_score) DESC
LIMIT 1
```

### Q18: What percentage of orders were paid using installments (more than one payment installment)?
```sql
SELECT 100.0 * COUNT(DISTINCT op.order_id) / (SELECT COUNT(*) FROM orders) AS percentage_of_orders_with_installments FROM order_payments op WHERE op.payment_installments > 1
```

### Q19: How many customers have placed more than one order?
```sql
-- failed
```

