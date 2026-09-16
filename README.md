# Text-to-SQL Data Analysis Agent

Ask questions about a real e-commerce dataset in plain English. The app generates SQL, validates and safely executes it, and shows you both the query and the results — as a stat card, table, or chart depending on what fits.

**Live demo:** _add your Streamlit Community Cloud link here after deploying_

---

## The problem

Business stakeholders want answers from data but don't write SQL. Analysts spend a lot of time translating "what were our best categories last quarter" into joins and aggregations. This project explores how far an open-source LLM can close that gap — turning natural language into correct, safely-executed SQL against a real relational database — while being honest about where it still needs a human in the loop.

## Dataset

[Olist Brazilian E-Commerce](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) — ~100k real orders (2016–2018) from a Brazilian marketplace, spread across 8 related tables (customers, orders, order items, payments, reviews, products, sellers, category translations). Prices are in Brazilian Real (R$), the dataset's real currency.

## Architecture

```
Natural language question
        │
        ▼
  Schema introspection  (reads live table/column/FK info from SQLite)
        │
        ▼
  LangChain + Groq (openai/gpt-oss-120b)  →  generates SQL
        │
        ▼
  Safety layer:
    1. Keyword/pattern check (SELECT-only, no DROP/DELETE/etc, no stacked
       statements, no inline comments)
    2. Read-only DB connection (SQLite URI mode=ro) — can't write even if
       step 1 were somehow bypassed
    3. Row limit (1,000 rows) + query timeout (25s, via a watchdog thread —
       not signal.alarm, which doesn't exist on Windows)
        │
        ▼
  Streamlit UI: SQL shown transparently, results as a stat card / table /
  chart (Bar, Line, Pie, or Histogram, auto-selected by result shape)
```

## Tech stack

| Layer | Tool |
|---|---|
| Database | SQLite (read-only connections) |
| LLM | Groq API, `openai/gpt-oss-120b` |
| Orchestration | LangChain |
| Frontend | Streamlit + Plotly |
| Data | pandas |

## Features

- Natural-language question → generated SQL → live results
- Generated SQL always shown, never hidden
- Three-layer safety validation (see architecture above)
- Auto-formatted currency (R$) and auto-selected chart type based on result shape
- A pre-built "Dashboard Overview" tab (revenue trend, top categories, payment breakdown, top states) that loads instantly with no LLM call
- "Pin to Dashboard" — save any chart from a question onto the dashboard for the session
- 19-question hand-verified evaluation set with documented failure modes (below)

## Setup

**1. Clone and set up the environment** (Python 3.11 recommended — newer versions can hit numpy wheel issues on Windows):

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
cd YOUR_REPO_NAME
python -m venv venv
venv\Scripts\Activate.ps1        # Windows
source venv/bin/activate         # macOS/Linux
pip install -r requirements.txt
```

**2. Get a free Groq API key** at [console.groq.com](https://console.groq.com) → API Keys → Create API Key.

**3. Add it to a `.env` file** in the project root:

```
GROQ_API_KEY=your_key_here
```

**4. Run it:**

```bash
streamlit run app.py
```

The database (`olist.db`) is **not** committed to this repo (it's 115MB, over GitHub's size-friendly range) — it's built automatically from the CSVs in `raw/` the first time you run the app, via `build_db.py`. This takes about 15–20 seconds on first run only.

## Database schema

8 tables: `customers`, `sellers`, `category_translation`, `products`, `orders`, `order_items`, `order_payments`, `order_reviews` — with proper primary/foreign keys, indexes on every join column, and query-planner statistics (`ANALYZE`) built in.

## Safety & validation

Three independent layers protect the database, in order:
1. **Prompt-level** — the model is instructed to only write SELECT statements (soft guard)
2. **Text validation** — rejects non-SELECT statements, forbidden keywords (DROP/DELETE/UPDATE/etc), stacked statements, and inline SQL comments (hard guard)
3. **Database-level** — the connection itself is opened read-only via SQLite's URI mode, so even a hypothetical bypass of layer 2 physically cannot write to the database

Plus a 1,000-row cap and a 25-second timeout (thread-based, since `signal.alarm` isn't available on Windows) to prevent runaway queries.

## Evaluation

19 hand-verified questions across five difficulty tiers (simple, filter, join, aggregation, subquery), each checked against a reference SQL query I wrote and confirmed against the real database.

**Score: 16/19 correct (84%)**

| Tier | Questions | Correct |
|---|---|---|
| Simple | 4 | 3 |
| Filter | 4 | 3 |
| Join | 4 | 4 |
| Aggregation | 3 | 3 |
| Subquery | 4 | 3 |

Full question-by-question log: [`eval_results.md`](eval_results.md)

### Documented failure modes

**1. `customer_id` vs `customer_unique_id` confusion** (2 of 3 failures)
In this dataset, `customer_id` is unique *per order* — `customer_unique_id` is the actual repeat-customer identifier. The model has no way to know this from column names alone, and incorrectly used `customer_id` for "how many customers have placed more than one order," returning 0 instead of the correct 2,997. This is a genuine schema-semantics gap that better prompting alone can't fully close without adding column-level descriptions to the schema.

**2. Case-sensitivity assumption**
Asked for freight value paid by customers in "Rio de Janeiro (RJ)," the model added `customer_city = 'Rio de Janeiro'` (title case) on top of the correctly-generated `customer_state = 'RJ'` filter. The actual data stores city names in lowercase (`'rio de janeiro'`), and SQLite's `=` is case-sensitive, so the extra filter silently matched zero rows — arguably worse than an error, since it looks like a valid answer.

**3. Ambiguous "percentage of orders" question** (not a model failure)
Asked what percentage of orders used installment payments, the model computed "% of orders with at least one installment payment," while my reference query computed "% of individual payment records with installments" — a genuinely different denominator. On reflection the model's interpretation better matches the question as worded; this is a lesson about eval-question precision, not a model shortcoming.

### Model note

Development originally targeted `llama-3.3-70b-versatile` and `llama-3.1-8b-instant`, both listed in Groq's general documentation — neither was available on the account actually used for this project (`model_not_found`). The final model, `openai/gpt-oss-120b`, was selected after querying `GET /openai/v1/models` directly to see what was actually accessible. Worth knowing if you fork this: **verify current model availability for your own account** rather than trusting model names from documentation or tutorials, Groq's lineup and per-account access shifts quickly.

## Known limitations

- No column-level semantic descriptions in the schema (see failure mode #1) — a natural next step would be adding brief column comments to the prompt
- Case-sensitivity of filter values isn't hinted to the model (failure mode #2)
- Single-turn only — no conversation memory across questions
- Read-only by design — this is intentional, not a limitation to fix

## Project structure

```
├── app.py                 # Streamlit frontend
├── pipeline.py             # Core text-to-SQL pipeline (schema, prompt, LLM call)
├── safety.py               # Validation & safety layer
├── build_db.py              # Builds olist.db from raw/ CSVs
├── eval_questions.py        # 19-question evaluation bank with reference SQL
├── run_eval.py               # Evaluation harness
├── eval_results.md           # Evaluation output/scoring
├── requirements.txt
├── .streamlit/config.toml    # Theme
└── raw/                      # Source CSVs (Olist dataset)
```