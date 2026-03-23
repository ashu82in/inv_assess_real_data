import streamlit as st
import pandas as pd

st.title("Single SKU Inventory Analyzer")

uploaded_file = st.file_uploader("Upload Inventory File", type=["xlsx"])

if uploaded_file:
    try:
        df = pd.read_excel(uploaded_file)

        # Clean column names
        df.columns = df.columns.str.strip()

        # Validate columns
        required_cols = ["Date", "Closing_Stock"]
        missing = [col for col in required_cols if col not in df.columns]

        if missing:
            st.error(f"Missing columns: {missing}")
            st.stop()

        # Convert Date
        df["Date"] = pd.to_datetime(df["Date"])

        # Sort by Date
        df = df.sort_values("Date")

        st.subheader("Uploaded Data")
        st.dataframe(df)

        # Calculate Consumption
        df["Consumption"] = df["Closing_Stock"].shift(1) - df["Closing_Stock"]

        # Remove first row NaN
        df = df.dropna()

        # Metrics
        avg_consumption = df["Consumption"].mean()
        max_consumption = df["Consumption"].max()
        min_stock = df["Closing_Stock"].min()

        col1, col2, col3 = st.columns(3)

        col1.metric("Avg Daily Consumption", round(avg_consumption, 2))
        col2.metric("Max Consumption (Spike)", round(max_consumption, 2))
        col3.metric("Minimum Stock", min_stock)

        # Stock-out detection
        stock_out_days = df[df["Closing_Stock"] <= 0]

        if not stock_out_days.empty:
            st.error("⚠️ Stock-out detected!")
            st.dataframe(stock_out_days)

        # Sudden drop detection
        threshold = avg_consumption * 2
        anomalies = df[df["Consumption"] > threshold]

        if not anomalies.empty:
            st.warning("⚠️ Sudden consumption spikes detected")
            st.dataframe(anomalies)

        # Plot trend
        st.subheader("Stock Trend")
        st.line_chart(df.set_index("Date")["Closing_Stock"])

        # Show final table
        st.subheader("Processed Data")
        st.dataframe(df)

    except Exception as e:
        st.error(f"Error processing file: {e}")
