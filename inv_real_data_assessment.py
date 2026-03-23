import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import timedelta

st.set_page_config(layout="wide")

st.title("📊 Inventory Intelligence Dashboard")

# =========================
# 🔹 FILE UPLOAD
# =========================
uploaded_file = st.file_uploader("Upload Inventory File", type=["xlsx"])

if uploaded_file:
    try:
        df = pd.read_excel(uploaded_file)

        # Clean column names
        df.columns = df.columns.str.strip()

        # Validate columns
        required_cols = ["Date", "Closing_Stock"]
        if not all(col in df.columns for col in required_cols):
            st.error("File must contain: Date, Closing_Stock")
            st.stop()

        # Process data
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.sort_values("Date")

        # =========================
        # 🔹 CONSUMPTION
        # =========================
        df["Consumption"] = df["Closing_Stock"].shift(1) - df["Closing_Stock"]
        df = df.dropna()

        avg_consumption = df["Consumption"].mean()
        current_stock = df.iloc[-1]["Closing_Stock"]
        min_stock = df["Closing_Stock"].min()

        # =========================
        # 🔹 SIDEBAR INPUTS
        # =========================
        st.sidebar.header("⚙️ Planning Inputs")

        lead_time = st.sidebar.number_input("Lead Time (days)", value=5)
        min_stock_input = st.sidebar.number_input("Minimum Safety Stock", value=int(min_stock))

        st.sidebar.header("📈 Forecast Settings")
        forecast_days = st.sidebar.slider("Forecast Horizon (Days)", 7, 60, 30)

        st.sidebar.header("🧪 What-If Simulator")
        demand_change_pct = st.sidebar.slider(
            "Change in Demand (%)",
            min_value=-50,
            max_value=100,
            value=0,
            step=10
        )

        adjusted_consumption = avg_consumption * (1 + demand_change_pct / 100)

        # =========================
        # 🔹 METRICS
        # =========================
        days_left = current_stock / avg_consumption if avg_consumption > 0 else 0
        reorder_point = avg_consumption * lead_time

        st.subheader("📌 Key Metrics")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Current Stock", int(current_stock))
        col2.metric("Avg Daily Consumption", round(avg_consumption, 2))
        col3.metric("Days of Inventory Left", int(days_left))
        col4.metric("Reorder Point", int(reorder_point))

        # =========================
        # 🔹 HEALTH STATUS
        # =========================
        st.subheader("🧠 Inventory Health")

        if days_left < 5:
            st.error("🚨 Critical: Stock will run out very soon!")
        elif days_left < 10:
            st.warning("⚠️ Warning: Inventory running low")
        else:
            st.success("✅ Healthy inventory levels")

        # =========================
        # 🔹 REORDER DECISION
        # =========================
        st.subheader("📦 Reorder Decision")

        if current_stock <= reorder_point:
            st.error("🚨 Reorder Now! Stock is below reorder point")
        elif current_stock <= reorder_point * 1.5:
            st.warning("⚠️ Approaching reorder level")
        else:
            st.success("✅ No immediate action required")

        # =========================
        # 🔹 FORECAST
        # =========================
        last_date = df["Date"].max()

        forecast_data = []
        for i in range(1, forecast_days + 1):
            future_date = last_date + timedelta(days=i)
            projected_stock = current_stock - (adjusted_consumption * i)
            forecast_data.append([future_date, projected_stock])

        forecast_df = pd.DataFrame(forecast_data, columns=["Date", "Forecast_Stock"])

        # Base forecast
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

        if demand_change_pct > 0:
            st.info(f"📈 Demand increased by {demand_change_pct}%")
        elif demand_change_pct < 0:
            st.info(f"📉 Demand decreased by {abs(demand_change_pct)}%")
        else:
            st.info("No demand change applied")

        if stockout_date:
            days_to_stockout = (stockout_date - last_date).days
            st.error(f"🚨 Stock-out in {days_to_stockout} days ({stockout_date.date()})")
        else:
            st.success("✅ No stock-out risk in forecast period")

        # =========================
        # 🔹 CHART
        # =========================
        st.subheader("📈 Stock Trend with Forecast")

        fig = go.Figure()

        # Actual
        fig.add_trace(go.Scatter(
            x=df["Date"],
            y=df["Closing_Stock"],
            mode="lines+markers",
            name="Actual Stock"
        ))

        # Scenario forecast
        fig.add_trace(go.Scatter(
            x=forecast_df["Date"],
            y=forecast_df["Forecast_Stock"],
            mode="lines",
            name="Scenario Forecast",
            line=dict(dash="dot")
        ))

        # Base forecast
        fig.add_trace(go.Scatter(
            x=forecast_df["Date"],
            y=base_forecast,
            mode="lines",
            name="Base Forecast",
            line=dict(dash="dash", color="gray")
        ))

        # Reorder line
        fig.add_trace(go.Scatter(
            x=list(df["Date"]) + list(forecast_df["Date"]),
            y=[reorder_point] * (len(df) + len(forecast_df)),
            mode="lines",
            name="Reorder Point",
            line=dict(dash="dash", color="blue")
        ))

        # Zones
        zone_25 = min_stock_input * 0.25
        zone_75 = min_stock_input * 0.75

        fig.add_shape(type="rect",
            x0=df["Date"].min(), x1=forecast_df["Date"].max(),
            y0=0, y1=zone_25,
            fillcolor="red", opacity=0.2, line_width=0)

        fig.add_shape(type="rect",
            x0=df["Date"].min(), x1=forecast_df["Date"].max(),
            y0=zone_25, y1=zone_75,
            fillcolor="orange", opacity=0.2, line_width=0)

        fig.add_shape(type="rect",
            x0=df["Date"].min(), x1=forecast_df["Date"].max(),
            y0=zone_75, y1=min_stock_input,
            fillcolor="green", opacity=0.2, line_width=0)

        fig.update_layout(
            xaxis_title="Date",
            yaxis_title="Stock Level",
            template="simple_white"
        )

        st.plotly_chart(fig, use_container_width=True)

        # =========================
        # 🔹 OPTIONAL RAW DATA
        # =========================
        if st.checkbox("Show Raw Data"):
            st.dataframe(df)

    except Exception as e:
        st.error(f"Error processing file: {e}")
