import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import timedelta

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
            .str.lower()
        )

        # =========================
        # 🔹 AUTO RENAME (ROBUST)
        # =========================
        df = df.rename(columns={
            "date": "Date",
            "particulars": "Particulars",
            "received": "Received",
            "issued": "Issued",
            "value": "Value",
            # "closing stock": "Closing Stock",
            "balance": "Closing Stock"   # ✅ Handles your case
        })
        st.write(df)
        # =========================
        # 🔹 VALIDATION
        # =========================
        required_cols = ["Date", "Received", "Issued", "Closing Stock"]

        missing = [col for col in required_cols if col not in df.columns]
        if missing:
            st.error(f"Missing columns: {missing}")
            st.stop()

        # =========================
        # 🔹 DATA CLEANING
        # =========================
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

        numeric_cols = ["Received", "Issued", "Value", "Closing Stock"]

        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df[numeric_cols] = df[numeric_cols].fillna(0)

        df = df.sort_values("Date")

        # =========================
        # 🔹 DAILY SUMMARY
        # =========================
        daily_summary = df.groupby("Date").agg({
            "Received": "sum",
            "Issued": "sum"
        }).reset_index()

        daily_summary["Net Movement"] = daily_summary["Received"] - daily_summary["Issued"]

        # Last transaction = closing stock
        closing_stock_daily = df.groupby("Date")["Closing Stock"].last().reset_index()

        daily_summary = daily_summary.merge(closing_stock_daily, on="Date", how="left")

        daily_summary.rename(columns={
            "Received": "Total Received",
            "Issued": "Total Issued",
            "Closing Stock": "Closing_Stock"
        }, inplace=True)

        # =========================
        # 🔹 OPTIONAL VIEW
        # =========================
        if st.checkbox("Show Daily Summary"):
            st.dataframe(daily_summary)

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
        min_stock = daily_summary["Closing_Stock"].min()

        if avg_consumption <= 0:
            avg_consumption = 0.0001

        # =========================
        # 🔹 SIDEBAR INPUTS
        # =========================
        st.sidebar.header("⚙️ Planning Inputs")

        lead_time = st.sidebar.number_input("Lead Time (days)", value=5)
        min_stock_input = st.sidebar.number_input("Minimum Safety Stock", value=int(min_stock))

        st.sidebar.header("📈 Forecast Settings")
        forecast_days = st.sidebar.slider("Forecast Days", 7, 60, 30)

        st.sidebar.header("🧪 What-If Simulator")
        demand_change_pct = st.sidebar.slider("Demand Change (%)", -50, 100, 0, 10)

        adjusted_consumption = avg_consumption * (1 + demand_change_pct / 100)

        # =========================
        # 🔹 METRICS
        # =========================
        days_left = current_stock / avg_consumption
        reorder_point = avg_consumption * lead_time

        st.subheader("📌 Key Metrics")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Current Stock", int(current_stock))
        col2.metric("Avg Daily Consumption", round(avg_consumption, 2))
        col3.metric("Days Left", int(days_left))
        col4.metric("Reorder Point", int(reorder_point))

        # =========================
        # 🔹 REORDER DECISION
        # =========================
        st.subheader("📦 Reorder Decision")

        if current_stock <= reorder_point:
            st.error("🚨 Reorder Now!")
        elif current_stock <= reorder_point * 1.5:
            st.warning("⚠️ Approaching reorder level")
        else:
            st.success("✅ No immediate action required")

        # =========================
        # 🔹 FORECAST
        # =========================
        last_date = daily_summary["Date"].max()

        forecast_data = []
        for i in range(1, forecast_days + 1):
            future_date = last_date + timedelta(days=i)
            projected_stock = current_stock - (adjusted_consumption * i)
            forecast_data.append([future_date, projected_stock])

        forecast_df = pd.DataFrame(forecast_data, columns=["Date", "Forecast_Stock"])

        base_forecast = [
            current_stock - (avg_consumption * i)
            for i in range(1, forecast_days + 1)
        ]

        # Stock-out detection
        stockout_date = None
        for i in range(len(forecast_df)):
            if forecast_df.iloc[i]["Forecast_Stock"] <= 0:
                stockout_date = forecast_df.iloc[i]["Date"]
                break

        st.subheader("🔮 Forecast Insight")

        if stockout_date:
            days_to_stockout = (stockout_date - last_date).days
            st.error(f"🚨 Stock-out in {days_to_stockout} days ({stockout_date.date()})")
        else:
            st.success("✅ No stock-out risk")

        # =========================
        # 🔹 CHART
        # =========================
        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=daily_summary["Date"],
            y=daily_summary["Closing_Stock"],
            mode="lines+markers",
            name="Actual"
        ))

        fig.add_trace(go.Scatter(
            x=forecast_df["Date"],
            y=forecast_df["Forecast_Stock"],
            mode="lines",
            name="Forecast",
            line=dict(dash="dot")
        ))

        fig.add_trace(go.Scatter(
            x=forecast_df["Date"],
            y=base_forecast,
            mode="lines",
            name="Base",
            line=dict(dash="dash", color="gray")
        ))

        fig.add_trace(go.Scatter(
            x=list(daily_summary["Date"]) + list(forecast_df["Date"]),
            y=[reorder_point] * (len(daily_summary) + len(forecast_df)),
            mode="lines",
            name="Reorder Point",
            line=dict(dash="dash", color="blue")
        ))

        # Zones
        zone_25 = min_stock_input * 0.25
        zone_75 = min_stock_input * 0.75

        fig.add_shape(type="rect",
            x0=daily_summary["Date"].min(), x1=forecast_df["Date"].max(),
            y0=0, y1=zone_25,
            fillcolor="red", opacity=0.2, line_width=0)

        fig.add_shape(type="rect",
            x0=daily_summary["Date"].min(), x1=forecast_df["Date"].max(),
            y0=zone_25, y1=zone_75,
            fillcolor="orange", opacity=0.2, line_width=0)

        fig.add_shape(type="rect",
            x0=daily_summary["Date"].min(), x1=forecast_df["Date"].max(),
            y0=zone_75, y1=min_stock_input,
            fillcolor="green", opacity=0.2, line_width=0)

        fig.update_layout(template="simple_white")

        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Error: {e}")
