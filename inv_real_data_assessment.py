import streamlit as st
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(layout="wide")

st.title("📊 Inventory Intelligence Dashboard")

uploaded_file = st.file_uploader("Upload Transaction File", type=["xlsx"])

if uploaded_file:
    try:
        # =========================
        # 🔹 READ FILE
        # =========================
        df = pd.read_excel(uploaded_file, engine="openpyxl")

        # =========================
        # 🔹 CLEAN COLUMN NAMES
        # =========================
        df.columns = (
            df.columns
            .str.strip()
            .str.replace("'", "", regex=False)
            .str.replace('"', "", regex=False)
            .str.replace("_", " ")
            .str.lower()
        )

        # =========================
        # 🔹 STANDARDIZE COLUMNS
        # =========================
        if "balance" in df.columns:
            df.rename(columns={"balance": "Closing Stock"}, inplace=True)

        df.rename(columns={
            "date": "Date",
            "particulars": "Particulars",
            "received": "Received",
            "issued": "Issued",
            "value": "Value",
            "rate": "Rate",
            "closing stock": "Closing Stock"
        }, inplace=True)

        # =========================
        # 🔹 VALIDATION
        # =========================
        required_cols = ["Date", "Received", "Issued", "Closing Stock", "Rate"]

        missing = [col for col in required_cols if col not in df.columns]
        if missing:
            st.error(f"Missing columns: {missing}")
            st.write("Detected:", df.columns.tolist())
            st.stop()

        # =========================
        # 🔹 DATA CLEANING
        # =========================
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

        numeric_cols = ["Received", "Issued", "Value", "Closing Stock", "Rate"]

        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df[numeric_cols] = df[numeric_cols].fillna(0)

        df = df.sort_values("Date")

        # =========================
        # 🔹 VALUE CALCULATION
        # =========================
        df["Purchase Value"] = df["Received"] * df["Rate"]
        df["Sales Value"] = df["Issued"] * df["Rate"]
        df["Net Value Movement"] = df["Purchase Value"] - df["Sales Value"]

        # =========================
        # 🔹 DAILY SUMMARY
        # =========================
        daily_summary = df.groupby("Date").agg({
            "Received": "sum",
            "Issued": "sum",
            "Purchase Value": "sum",
            "Sales Value": "sum",
            "Net Value Movement": "sum"
        }).reset_index()

        daily_summary["Net Movement"] = (
            daily_summary["Received"] - daily_summary["Issued"]
        )

        # Closing stock (last transaction of day)
        closing_stock_daily = df.groupby("Date")["Closing Stock"].last().reset_index()

        daily_summary = daily_summary.merge(closing_stock_daily, on="Date", how="left")

        daily_summary.rename(columns={
            "Received": "Total Received",
            "Issued": "Total Issued",
            "Closing Stock": "Closing_Stock"
        }, inplace=True)

        # =========================
        # 🔹 INVENTORY VALUE
        # =========================
        daily_summary["Inventory Value"] = daily_summary["Net Value Movement"].cumsum()

        # =========================
        # 🔹 CONSUMPTION
        # =========================
        daily_summary["Consumption"] = (
            daily_summary["Closing_Stock"].shift(1) - daily_summary["Closing_Stock"]
        )

        daily_summary = daily_summary.dropna()

        if daily_summary.empty:
            st.error("Not enough data to analyze")
            st.stop()

        avg_consumption = daily_summary["Consumption"].mean()
        current_stock = daily_summary.iloc[-1]["Closing_Stock"]
        avg_inventory = daily_summary["Closing_Stock"].mean()

        if avg_consumption <= 0:
            avg_consumption = 0.0001

        # =========================
        # 🔹 STOCK-OUT THRESHOLD
        # =========================
        st.sidebar.header("⚙️ Settings")

        stockout_threshold = st.sidebar.number_input(
            "Stock-out Threshold",
            value=0
        )

        stockout_days = (
            daily_summary["Closing_Stock"] <= stockout_threshold
        ).sum()

        # =========================
        # 🔹 INVENTORY AGE
        # =========================
        inventory_age = avg_inventory / avg_consumption

        # =========================
        # 🔹 METRICS
        # =========================
        st.subheader("📌 Key Metrics")

        current_value = daily_summary.iloc[-1]["Inventory Value"]

        col1, col2, col3, col4, col5 = st.columns(5)

        col1.metric("Current Stock", int(current_stock))
        col2.metric("Avg Daily Consumption", round(avg_consumption, 2))
        col3.metric("Inventory Age (Days)", int(inventory_age))
        col4.metric("Stock-out Days", int(stockout_days))
        col5.metric("Inventory Value", int(current_value))

        # =========================
        # 🔹 INSIGHTS
        # =========================
        st.subheader("🧠 Insights")

        if stockout_days > 0:
            st.error(f"🚨 Stock-out occurred on {stockout_days} days")
        else:
            st.success("✅ No stock-out risk observed")

        # =========================
        # 🔹 STOCK CHART
        # =========================
        st.subheader("📦 Inventory Quantity Trend")

        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=daily_summary["Date"],
            y=daily_summary["Closing_Stock"],
            mode="lines+markers",
            name="Stock"
        ))

        fig.add_trace(go.Scatter(
            x=daily_summary["Date"],
            y=[stockout_threshold] * len(daily_summary),
            mode="lines",
            name="Stock-out Threshold",
            line=dict(dash="dash", color="red")
        ))

        fig.update_layout(template="simple_white")

        st.plotly_chart(fig, use_container_width=True)

        # =========================
        # 🔹 VALUE CHART
        # =========================
        st.subheader("💰 Inventory Value Trend")

        fig_value = go.Figure()

        fig_value.add_trace(go.Scatter(
            x=daily_summary["Date"],
            y=daily_summary["Inventory Value"],
            mode="lines+markers",
            name="Inventory Value"
        ))

        fig_value.add_trace(go.Scatter(
            x=daily_summary["Date"],
            y=daily_summary["Purchase Value"],
            mode="lines",
            name="Purchase Value",
            line=dict(dash="dot", color="green")
        ))

        fig_value.add_trace(go.Scatter(
            x=daily_summary["Date"],
            y=daily_summary["Sales Value"],
            mode="lines",
            name="Sales Value",
            line=dict(dash="dot", color="red")
        ))

        fig_value.update_layout(template="simple_white")

        st.plotly_chart(fig_value, use_container_width=True)

        # =========================
        # 🔹 OPTIONAL TABLE
        # =========================
        if st.checkbox("Show Daily Summary"):
            st.dataframe(daily_summary)

    except Exception as e:
        st.error(f"Error: {e}")
