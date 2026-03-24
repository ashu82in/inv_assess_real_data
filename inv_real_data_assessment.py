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
        # 🔹 USER INPUTS
        # =========================
        st.sidebar.header("⚙️ Settings")

        opening_inventory = st.sidebar.number_input(
            "Opening Inventory Value",
            value=0
        )

        stockout_threshold = st.sidebar.number_input(
            "Stock-out Threshold",
            value=0
        )

        # =========================
        # 🔹 VALUE LOGIC (CORRECT)
        # =========================
        df["Net Quantity Movement"] = df["Received"] - df["Issued"]
        df["Net Value Movement"] = df["Net Quantity Movement"] * df["Rate"]

        # Running inventory value
        df["Total Inventory"] = opening_inventory + df["Net Value Movement"].cumsum()

        # =========================
        # 🔹 DAILY SUMMARY
        # =========================
        daily_summary = df.groupby("Date").agg({
            "Received": "sum",
            "Issued": "sum",
            "Total Inventory": "last"
        }).reset_index()

        daily_summary["Net Movement"] = (
            daily_summary["Received"] - daily_summary["Issued"]
        )

        daily_summary.rename(columns={
            "Received": "Total Received",
            "Issued": "Total Issued",
            "Total Inventory": "Inventory_Value"
        }, inplace=True)

        # =========================
        # 🔹 CLOSING STOCK
        # =========================
        closing_stock_daily = df.groupby("Date")["Closing Stock"].last().reset_index()

        daily_summary = daily_summary.merge(closing_stock_daily, on="Date", how="left")

        daily_summary.rename(columns={
            "Closing Stock": "Closing_Stock"
        }, inplace=True)

        # =========================
        # 🔹 HANDLE MISSING DATES
        # =========================
        full_dates = pd.date_range(
            start=daily_summary["Date"].min(),
            end=daily_summary["Date"].max()
        )

        full_df = pd.DataFrame({"Date": full_dates})

        daily_summary = full_df.merge(daily_summary, on="Date", how="left")

        # Fill no-transaction days
        daily_summary["Total Received"] = daily_summary["Total Received"].fillna(0)
        daily_summary["Total Issued"] = daily_summary["Total Issued"].fillna(0)
        daily_summary["Net Movement"] = daily_summary["Net Movement"].fillna(0)

        # Carry forward stock & value
        daily_summary["Closing_Stock"] = daily_summary["Closing_Stock"].ffill()
        daily_summary["Inventory_Value"] = daily_summary["Inventory_Value"].ffill()

        # Edge case handling
        daily_summary["Closing_Stock"] = daily_summary["Closing_Stock"].fillna(0)
        daily_summary["Inventory_Value"] = daily_summary["Inventory_Value"].fillna(opening_inventory)

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
        # 🔹 STOCK-OUT DAYS
        # =========================
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

        current_value = daily_summary.iloc[-1]["Inventory_Value"]

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
        # 🔹 QUANTITY CHART
        # =========================
        st.subheader("📦 Inventory Quantity Trend")

        fig_qty = go.Figure()

        fig_qty.add_trace(go.Scatter(
            x=daily_summary["Date"],
            y=daily_summary["Closing_Stock"],
            mode="lines+markers",
            name="Stock"
        ))

        fig_qty.add_trace(go.Scatter(
            x=daily_summary["Date"],
            y=[stockout_threshold] * len(daily_summary),
            mode="lines",
            name="Stock-out Threshold",
            line=dict(dash="dash", color="red")
        ))

        fig_qty.update_layout(template="simple_white")

        st.plotly_chart(fig_qty, use_container_width=True)

        # =========================
        # 🔹 VALUE CHART
        # =========================
        st.subheader("💰 Inventory Value Trend")

        fig_val = go.Figure()

        fig_val.add_trace(go.Scatter(
            x=daily_summary["Date"],
            y=daily_summary["Inventory_Value"],
            mode="lines+markers",
            name="Inventory Value"
        ))

        fig_val.update_layout(template="simple_white")

        st.plotly_chart(fig_val, use_container_width=True)

        # =========================
        # 🔹 OPTIONAL TABLE
        # =========================
        if st.checkbox("Show Daily Summary"):
            st.dataframe(daily_summary)

    except Exception as e:
        st.error(f"Error: {e}")
