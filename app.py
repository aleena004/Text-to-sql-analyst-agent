"""
Streamlit front-end for the Olist text-to-SQL demo.

Run with:  streamlit run app.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from pipeline import ask, get_schema_string
from safety import SafetyError, QueryError

st.set_page_config(page_title="Text-to-SQL: Olist E-Commerce", page_icon="🛒", layout="wide")

EXAMPLE_QUESTIONS = [
    "How many orders were placed in total?",
    "What are the top 5 product categories by revenue?",
    "What is the average review score for orders paid by credit card?",
    "Which 10 customers have spent the most money?",
    "How many orders were delivered late (after the estimated delivery date)?",
    "What percentage of orders were paid in installments?",
]

# Column-name substrings that indicate a monetary value. The Olist dataset
# is priced in Brazilian Real (R$) since it's a Brazilian marketplace --
# this is the accurate currency for this data, not a placeholder.
CURRENCY_KEYWORDS = ["price", "revenue", "payment_value", "freight_value", "amount", "sales", "cost", "total_value"]
CURRENCY_SYMBOL = "R$"

# Monotone blue scale -- a professional/BI-tool look instead of a rainbow
# palette. Dark to light, used across all categorical charts (bar/pie).
CHART_COLORS = ["#1E3A8A", "#2563EB", "#3B82F6", "#60A5FA", "#93C5FD", "#BFDBFE", "#DBEAFE"]


def is_currency_column(col_name: str) -> bool:
    lowered = col_name.lower()
    return any(kw in lowered for kw in CURRENCY_KEYWORDS)


def format_compact(value, is_money: bool = False) -> str:
    """Abbreviate large numbers (1.4M instead of 1,400,000) so KPI cards
    never overflow/truncate their fixed-width box."""
    prefix = f"{CURRENCY_SYMBOL} " if is_money else ""
    if not isinstance(value, (int, float)):
        return str(value)
    abs_v = abs(value)
    if abs_v >= 1_000_000:
        return f"{prefix}{value/1_000_000:.1f}M"
    if abs_v >= 1_000:
        return f"{prefix}{value/1_000:.1f}K"
    return f"{prefix}{value:,.2f}" if isinstance(value, float) else f"{prefix}{value:,}"


def build_column_config(df: pd.DataFrame) -> dict:
    """Format any detected monetary column with the R$ currency prefix."""
    config = {}
    for col in df.columns:
        if is_currency_column(col) and pd.api.types.is_numeric_dtype(df[col]):
            config[col] = st.column_config.NumberColumn(
                col, format=f"{CURRENCY_SYMBOL} %.2f"
            )
    return config


def render_result(df: pd.DataFrame, key_prefix: str = "result", question: str = None):
    """
    Choose the clearest way to display a result based on its shape:
    - A single cell (e.g. COUNT(*)) -> a big stat card, not a 1x1 table
      with a meaningless "0" row index.
    - A single row with multiple columns -> a row of stat cards.
    - A chartable shape (one numeric + one label column, <=50 rows) ->
      a table plus a chart, with a type selector (Bar/Line/Pie) defaulting
      to Line when the label column looks like a date/time.
    - Everything else -> a real table only, index hidden.
    Chartable/distribution results get a "Pin to Dashboard" button.
    """
    if df.shape == (1, 1):
        col_name = df.columns[0]
        value = df.iloc[0, 0]
        display_value = f"{CURRENCY_SYMBOL} {value:,.2f}" if is_currency_column(col_name) and isinstance(value, (int, float)) else (
            f"{value:,.2f}" if isinstance(value, float) else f"{value:,}" if isinstance(value, int) else str(value)
        )
        st.metric(label=col_name, value=display_value)
        return

    if len(df) == 1:
        cols = st.columns(len(df.columns))
        for c, col_name in zip(cols, df.columns):
            value = df.iloc[0][col_name]
            is_money = is_currency_column(col_name)
            if isinstance(value, (int, float)):
                display_value = f"{CURRENCY_SYMBOL} {value:,.2f}" if is_money else (
                    f"{value:,.2f}" if isinstance(value, float) else f"{value:,}"
                )
            else:
                display_value = str(value)
            with c:
                with st.container(border=True):
                    st.metric(label=col_name, value=display_value)
        return

    st.dataframe(
        df, use_container_width=True, hide_index=True,
        column_config=build_column_config(df),
    )

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    other_cols = [c for c in df.columns if c not in numeric_cols]
    is_distribution = len(numeric_cols) == 1 and len(other_cols) == 0 and len(df) > 1
    is_chartable = len(numeric_cols) == 1 and len(other_cols) == 1 and len(df) <= 50

    if is_distribution:
        st.caption("📊 Histogram — value distribution")
        render_chart(df, "Histogram", key_prefix)
        _render_pin_button(df, "Histogram", key_prefix, question)
        return

    if not is_chartable:
        return

    label_col = other_cols[0]
    default_type = "Line" if is_time_like_column(label_col, df[label_col]) else "Bar"
    options = ["Bar", "Line", "Pie"]
    chart_type = st.radio(
        "Chart type", options, index=options.index(default_type),
        horizontal=True, key=f"{key_prefix}_charttype", label_visibility="collapsed",
    )
    render_chart(df, chart_type, key_prefix)
    _render_pin_button(df, chart_type, key_prefix, question)


def _render_pin_button(df: pd.DataFrame, chart_type: str, key_prefix: str, question: str):
    """Small button that saves this chart into session state so it can be
    displayed on the Dashboard Overview tab too. Session-only: resets on
    a full page reload, same as the rest of the chat history."""
    if "pinned_charts" not in st.session_state:
        st.session_state.pinned_charts = {}
    already_pinned = key_prefix in st.session_state.pinned_charts
    label = "📌 Pinned to Dashboard" if already_pinned else "📌 Pin to Dashboard"
    if st.button(label, key=f"{key_prefix}_pin", disabled=already_pinned):
        st.session_state.pinned_charts[key_prefix] = {
            "df": df, "chart_type": chart_type,
            "title": question or "Custom chart",
        }
        st.rerun()


def render_chart(df: pd.DataFrame, chart_type: str, key_prefix: str):
    """
    Render df as a bar, line, pie, or histogram. Caller has already
    confirmed the shape fits.
    """
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    other_cols = [c for c in df.columns if c not in numeric_cols]

    if chart_type == "Histogram":
        value_col = numeric_cols[0]
        is_money = is_currency_column(value_col)
        fig = px.histogram(df, x=value_col, color_discrete_sequence=[CHART_COLORS[1]])
        fig.update_traces(
            hovertemplate=(f"{CURRENCY_SYMBOL} " if is_money else "") + "%{x}<br>count: %{y}<extra></extra>",
        )
        fig.update_layout(
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            font_color="#1E293B", margin=dict(t=30, b=10),
            xaxis_title=f"{value_col} ({CURRENCY_SYMBOL})" if is_money else value_col,
            yaxis_title="Count",
        )
        st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_chart")
        return

    label_col, value_col = other_cols[0], numeric_cols[0]
    is_money = is_currency_column(value_col)
    y_title = f"{value_col} ({CURRENCY_SYMBOL})" if is_money else value_col
    value_fmt = f"{CURRENCY_SYMBOL} %{{y:,.2f}}" if is_money else "%{y:,.0f}"

    if chart_type == "Pie":
        plot_df = df.copy().sort_values(value_col, ascending=False)
        # More than 5 slices gets visually noisy -- keep the top 5 and
        # fold the rest into a single "Other" slice.
        if len(plot_df) > 5:
            top = plot_df.iloc[:5]
            other_total = plot_df.iloc[5:][value_col].sum()
            plot_df = pd.concat([
                top,
                pd.DataFrame({label_col: ["Other"], value_col: [other_total]}),
            ], ignore_index=True)

        fig = px.pie(
            plot_df, names=label_col, values=value_col,
            color_discrete_sequence=CHART_COLORS, hole=0.4,
        )
        hover_fmt = f"{CURRENCY_SYMBOL} %{{value:,.2f}}" if is_money else "%{value:,.0f}"
        fig.update_traces(
            textinfo="percent",
            textposition="inside",
            hovertemplate=f"<b>%{{label}}</b><br>{value_col}: {hover_fmt}<extra></extra>",
        )
    elif chart_type == "Line":
        plot_df = df.copy()
        # Try to make the x-axis actually sort chronologically rather than
        # however the rows happened to come back from SQL.
        try:
            plot_df[label_col] = pd.to_datetime(plot_df[label_col])
            plot_df = plot_df.sort_values(label_col)
        except (ValueError, TypeError):
            pass
        fig = px.line(plot_df, x=label_col, y=value_col, markers=True,
                       color_discrete_sequence=CHART_COLORS)
        fig.update_traces(
            hovertemplate=f"<b>%{{x}}</b><br>{y_title}: {value_fmt}<extra></extra>",
        )
    else:  # Bar
        fig = px.bar(
            df.sort_values(value_col, ascending=False),
            x=label_col, y=value_col, color=label_col,
            color_discrete_sequence=CHART_COLORS, text=value_col,
        )
        fig.update_traces(
            texttemplate=value_fmt, textposition="outside",
            hovertemplate=f"<b>%{{x}}</b><br>{y_title}: {value_fmt}<extra></extra>",
        )

    fig.update_layout(
        showlegend=(chart_type == "Pie"),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font_color="#1E293B",
        margin=dict(t=30, b=10),
    )
    if chart_type != "Pie":
        fig.update_layout(xaxis_title=label_col, yaxis_title=y_title)
    st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_chart")

def is_time_like_column(col_name: str, series: pd.Series) -> bool:
    """Heuristic: does this column look like it represents a point in time?"""
    lowered = col_name.lower()
    if any(kw in lowered for kw in ["date", "month", "year", "week", "day", "time"]):
        return True
    try:
        pd.to_datetime(series, errors="raise")
        return True
    except (ValueError, TypeError):
        return False


@st.cache_data(ttl=3600)
def get_kpis(db_path: str) -> dict:
    """
    Headline stats shown at the top of the page, so the app reads as a
    dashboard on load rather than an empty chat box. Cached for 1 hour
    since these are slow-changing aggregates over a static dataset.
    """
    import sqlite3
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    kpis = {
        "Total Orders": conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
        "Total Revenue": conn.execute("SELECT SUM(price) FROM order_items").fetchone()[0],
        "Unique Customers": conn.execute("SELECT COUNT(DISTINCT customer_unique_id) FROM customers").fetchone()[0],
        "Avg Review Score": conn.execute("SELECT AVG(review_score) FROM order_reviews").fetchone()[0],
        "Avg Delivery Days": conn.execute(
            "SELECT AVG(julianday(order_delivered_customer_date)-julianday(order_purchase_timestamp)) "
            "FROM orders WHERE order_status='delivered'"
        ).fetchone()[0],
    }
    conn.close()
    return kpis


def render_kpi_header(db_path: str = "olist.db"):
    kpis = get_kpis(db_path)
    cards = [
        ("Total Orders", format_compact(kpis["Total Orders"])),
        ("Total Revenue", format_compact(kpis["Total Revenue"], is_money=True)),
        ("Avg Review Score", f"{kpis['Avg Review Score']:.2f} / 5"),
        ("Avg Delivery Time", f"{kpis['Avg Delivery Days']:.1f} days"),
    ]
    cards_html = "".join(
        f"""<div style="flex:1; border:2px solid #2563EB; border-radius:10px;
                padding:1rem 1.25rem; background:#F8FAFC; min-width:0;">
            <div style="color:#2563EB; font-weight:700; font-size:0.8rem;
                 text-transform:uppercase; letter-spacing:0.04em; white-space:nowrap;">{label}</div>
            <div style="color:#1E3A8A; font-weight:700; font-size:1.9rem; margin-top:0.3rem;
                 white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">{value}</div>
        </div>"""
        for label, value in cards
    )
    st.markdown(
        f'<div style="display:flex; gap:0.9rem; margin-bottom:0.5rem;">{cards_html}</div>',
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=3600)
def get_dashboard_data(db_path: str) -> dict:
    """Pre-built queries for the Dashboard Overview tab -- run directly
    against the DB, no LLM call needed, so this tab loads instantly."""
    import sqlite3
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    data = {
        "revenue_trend": pd.read_sql_query(
            "SELECT strftime('%Y-%m', o.order_purchase_timestamp) AS month, SUM(oi.price) AS revenue "
            "FROM orders o JOIN order_items oi ON o.order_id=oi.order_id "
            "WHERE o.order_status != 'canceled' GROUP BY month ORDER BY month", conn),
        "top_categories": pd.read_sql_query(
            "SELECT ct.product_category_name_english AS category, SUM(oi.price) AS revenue "
            "FROM order_items oi JOIN products p ON oi.product_id=p.product_id "
            "JOIN category_translation ct ON p.product_category_name=ct.product_category_name "
            "GROUP BY category ORDER BY revenue DESC LIMIT 5", conn),
        "payment_type": pd.read_sql_query(
            "SELECT payment_type, COUNT(*) AS count FROM order_payments "
            "GROUP BY payment_type ORDER BY count DESC", conn),
        "top_states": pd.read_sql_query(
            "SELECT c.customer_state AS state, COUNT(*) AS orders FROM orders o "
            "JOIN customers c ON o.customer_id=c.customer_id GROUP BY state ORDER BY orders DESC LIMIT 5", conn),
    }
    conn.close()
    return data


def render_dashboard_tab(db_path: str = "olist.db"):
    data = get_dashboard_data(db_path)

    row1_col1, row1_col2 = st.columns(2)
    with row1_col1, st.container(border=True):
        st.subheader("Revenue Trend")
        render_chart(data["revenue_trend"], "Line", "dash_revenue")
    with row1_col2, st.container(border=True):
        st.subheader("Top 5 Categories by Revenue")
        render_chart(data["top_categories"], "Bar", "dash_categories")

    row2_col1, row2_col2 = st.columns(2)
    with row2_col1, st.container(border=True):
        st.subheader("Payment Type Breakdown")
        render_chart(data["payment_type"], "Pie", "dash_payment")
    with row2_col2, st.container(border=True):
        st.subheader("Top 5 States by Order Volume")
        render_chart(data["top_states"], "Bar", "dash_states")

    if st.session_state.get("pinned_charts"):
        st.divider()
        st.subheader("📌 Pinned from Your Questions")
        st.caption("These came from questions you asked in the chat tab. They reset when the page reloads.")
        for key_prefix, pin in list(st.session_state.pinned_charts.items()):
            with st.container(border=True):
                col_title, col_unpin = st.columns([5, 1])
                col_title.markdown(f"**{pin['title']}**")
                if col_unpin.button("✕ Unpin", key=f"unpin_{key_prefix}"):
                    del st.session_state.pinned_charts[key_prefix]
                    st.rerun()
                render_chart(pin["df"], pin["chart_type"], f"pinned_{key_prefix}")


# ---- Session state: chat history persists across reruns within a session ----
if "history" not in st.session_state:
    st.session_state.history = []  # list of dicts: {question, sql, df, error}


# ---- Sidebar: schema reference + example questions ----
with st.sidebar:
    st.header("🛒 Olist E-Commerce DB")
    st.caption(
        "Ask questions in plain English about a Brazilian e-commerce marketplace: "
        "orders, customers, products, payments, and reviews."
    )

    st.subheader("Try an example")
    for q in EXAMPLE_QUESTIONS:
        if st.button(q, use_container_width=True, key=f"example_{q}"):
            st.session_state.pending_question = q

    with st.expander("📋 Database schema"):
        st.code(get_schema_string(), language="text")

    if st.session_state.history:
        if st.button("🗑️ Clear conversation", use_container_width=True):
            st.session_state.history = []
            st.rerun()


# ---- Main area ----
st.title("Ask questions about the Olist e-commerce dataset")
st.caption(
    "Natural language → SQL → results, powered by Groq (open-source LLM) + LangChain + SQLite. "
    "The generated SQL is always shown so you can verify what actually ran."
)

render_kpi_header()
st.divider()

tab_chat, tab_dashboard = st.tabs(["💬 Ask a Question", "📊 Dashboard Overview"])

with tab_dashboard:
    render_dashboard_tab()

with tab_chat:
    # Render existing conversation history
    for idx, turn in enumerate(st.session_state.history):
        with st.chat_message("user"):
            st.write(turn["question"])
        with st.chat_message("assistant"):
            if turn["error"]:
                st.error(turn["error"])
            else:
                st.code(turn["sql"], language="sql")
                if turn["df"] is not None and len(turn["df"]) > 0:
                    render_result(turn["df"], key_prefix=f"turn_{idx}", question=turn["question"])
                else:
                    st.info("Query ran successfully but returned no rows.")


def handle_question(question: str):
    st.session_state.history.append({"question": question, "sql": None, "df": None, "error": None})
    with st.spinner("Generating SQL and running it..."):
        try:
            sql, df = ask(question)
            st.session_state.history[-1]["sql"] = sql
            st.session_state.history[-1]["df"] = df
        except SafetyError as e:
            st.session_state.history[-1]["error"] = f"🚫 Query blocked by safety layer: {e}"
        except QueryError as e:
            st.session_state.history[-1]["error"] = f"⚠️ Query failed: {e}"
        except Exception as e:
            st.session_state.history[-1]["error"] = f"⚠️ Unexpected error: {e}"


# Handle a sidebar example-question click (set on the previous rerun)
if "pending_question" in st.session_state:
    q = st.session_state.pop("pending_question")
    handle_question(q)
    st.rerun()

# Chat input box
user_question = st.chat_input("Ask a question about orders, customers, products, or payments...")
if user_question:
    handle_question(user_question)
    st.rerun()