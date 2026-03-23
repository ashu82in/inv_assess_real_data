import streamlit as st
import pandas as pd

st.set_page_config(layout="wide")

st.title("📊 Inventory Intelligence Dashboard")

uploaded_file = st.file_uploader("Upload Inventory File", type=["xlsx"])

if uploaded_file:
    try:
        df = pd.read_excel(uploaded_file)

        # Clean columns
        df.columns = df.columns.str.strip()

        # Validate
        required_cols = ["Date", "Closing_Stock"]
        if not all(col in df.columns for col in required_cols):
            st.error("File must contain: Date, Closing_Stock")
            st.stop()

        # Process data
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.sort_values("Date")

        df["Consumption"] = df["Closing_Stock"].shift(1) - df["Closing_Stock"]
        df = df.dropna()

        # Metrics
        avg_consumption = df["Consumption"].mean()
        current_stock = df.iloc[-1]["Closing_Stock"]
        min_stock = df["Closing_Stock"].min()

        # Avoid division error
        days_left = current_stock / avg_consumption if avg_consumption > 0 else 0

        # =========================
        # 🔹 TOP METRICS
        # =========================
        st.subheader("📌 Key Metrics")

        col1, col2, col3, col4 = st.columns(4)

        col1.metric("Current Stock", int(current_stock))
        col2.metric("Avg Daily Consumption", round(avg_consumption, 2))
        col3.metric("Days of Inventory Left", int(days_left))
        col4.metric("Minimum Stock Level", int(min_stock))

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
        # 🔹 ALERTS
        # =========================
        st.subheader("⚡ Key Alerts")

        # Stock-out
        stock_out_days = df[df["Closing_Stock"] <= 0]
        if not stock_out_days.empty:
            st.error(f"Stock-out occurred on {len(stock_out_days)} days")

        # Sudden spikes
        threshold = avg_consumption * 2
        anomalies = df[df["Consumption"] > threshold]

        if not anomalies.empty:
            st.warning(f"Unusual consumption spikes detected ({len(anomalies)} days)")

        if stock_out_days.empty and anomalies.empty:
            st.success("No major issues detected")

        # =========================
        # 🔹 TREND CHART
        # =========================
        st.subheader("📈 Stock Trend")

        st.line_chart(df.set_index("Date")["Closing_Stock"])

        # =========================
        # 🔹 OPTIONAL RAW DATA
        # =========================
        if st.checkbox("Show Raw Data"):
            st.dataframe(df)

    except Exception as e:
        st.error(f"Error processing file: {e}")
