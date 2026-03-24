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
            "received": "Received",
            "issued": "Issued",
            "rate": "Rate",
            "closing stock": "Closing Stock"
        }, inplace=True)

        required_cols = ["Date", "Received", "Issued", "Closing Stock", "Rate"]
        if not all(col in df.columns for col in required_cols):
            st.error("Missing required columns")
            st.write(df.columns)
            st.stop()

        # =========================
        # 🔹 DATA CLEANING
        # =========================
        df["Date"] = pd.to_datetime(df["Date"])
        for col in ["Received", "Issued", "Rate", "Closing Stock"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        df = df.sort_values("Date").reset_index(drop=True)

        # =========================
        # 🔹 USER INPUTS
        # =========================
        st.sidebar.header("⚙️ Settings")

        opening_inventory = st.sidebar.number_input("Opening Inventory Value", value=0)
        stockout_threshold = st.sidebar.number_input("Stock-out Threshold", value=0)

        # =========================
        # 🔹 VALUE CALCULATION
        # =========================
        df["Net Qty"] = df["Received"] - df["Issued"]
        df["Net Value"] = df["Net Qty"] * df["Rate"]
        df["Inventory Value"] = opening_inventory + df["Net Value"].cumsum()

        # =========================
        # 🔹 PREP GROUPED DATA
        # =========================
        df_grouped = df.groupby("Date").agg({
            "Received": "sum",
            "Issued": "sum"
        }).reset_index().set_index("Date")

        full_dates = pd.date_range(df["Date"].min(), df["Date"].max())

        # =========================
        # 🔹 AGE + BUCKET ENGINE
        # =========================
        inventory_layers = []
        age_list = []
        bucket_data = []

        opening_qty = df.iloc[0]["Closing Stock"] - (df.iloc[0]["Received"] - df.iloc[0]["Issued"])
        opening_remaining = max(opening_qty, 0)

        for current_date in full_dates:

            if current_date in df_grouped.index:
                received = df_grouped.loc[current_date]["Received"]
                issued = df_grouped.loc[current_date]["Issued"]
            else:
                received = 0
                issued = 0

            # Add stock
            if received > 0:
                inventory_layers.append({"qty": received, "date": current_date})

            # Remove stock FIFO
            qty_to_issue = issued
            while qty_to_issue > 0 and inventory_layers:
                layer = inventory_layers[0]
                if layer["qty"] <= qty_to_issue:
                    qty_to_issue -= layer["qty"]
                    inventory_layers.pop(0)
                else:
                    layer["qty"] -= qty_to_issue
                    qty_to_issue = 0

            # Opening stock logic
            if opening_remaining > 0:
                opening_remaining -= issued
                age_list.append(None)
                bucket_data.append([current_date, None, None, None, None])
                continue

            total_qty = sum(layer["qty"] for layer in inventory_layers)

            # AGE
            if total_qty == 0:
                age_list.append(0)
            else:
                weighted_age = sum(
                    layer["qty"] * (current_date - layer["date"]).days
                    for layer in inventory_layers
                )
                age_list.append(weighted_age / total_qty)

            # BUCKETS
            b1 = b2 = b3 = b4 = 0

            for layer in inventory_layers:
                age = (current_date - layer["date"]).days
                qty = layer["qty"]

                if age <= 30:
                    b1 += qty
                elif age <= 60:
                    b2 += qty
                elif age <= 90:
                    b3 += qty
                else:
                    b4 += qty

            bucket_data.append([current_date, b1, b2, b3, b4])

        age_df = pd.DataFrame({"Date": full_dates, "Avg Age": age_list})
        bucket_df = pd.DataFrame(bucket_data, columns=["Date", "0-30", "31-60", "61-90", "90+"])

        # =========================
        # 🔹 DAILY SUMMARY
        # =========================
        daily = df.groupby("Date").agg({
            "Received": "sum",
            "Issued": "sum",
            "Inventory Value": "last",
            "Closing Stock": "last"
        }).reset_index()

        daily.rename(columns={
            "Received": "Total Received",
            "Issued": "Total Issued",
            "Closing Stock": "Closing_Stock"
        }, inplace=True)

        # Merge all
        daily = pd.DataFrame({"Date": full_dates}).merge(daily, on="Date", how="left")
        daily = daily.merge(age_df, on="Date", how="left")
        daily = daily.merge(bucket_df, on="Date", how="left")

        # Fill values
        daily["Total Received"] = daily["Total Received"].fillna(0)
        daily["Total Issued"] = daily["Total Issued"].fillna(0)
        daily["Closing_Stock"] = daily["Closing_Stock"].ffill().fillna(0)
        daily["Inventory Value"] = daily["Inventory Value"].ffill().fillna(opening_inventory)
        daily["Avg Age"] = daily["Avg Age"].ffill()

        # =========================
        # 🔹 METRICS
        # =========================
        current_stock = daily.iloc[-1]["Closing_Stock"]
        current_value = daily.iloc[-1]["Inventory Value"]
        avg_age = daily["Avg Age"].mean()
        stockout_days = (daily["Closing_Stock"] <= stockout_threshold).sum()

        st.subheader("📌 Key Metrics")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Current Stock", int(current_stock))
        col2.metric("Inventory Value", int(current_value))
        col3.metric("Avg Inventory Age", int(avg_age))
        col4.metric("Stock-out Days", int(stockout_days))

        # =========================
        # 🔹 CHARTS
        # =========================
        st.subheader("📦 Inventory Quantity")
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(x=daily["Date"], y=daily["Closing_Stock"]))
        st.plotly_chart(fig1, use_container_width=True)

        st.subheader("💰 Inventory Value")
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=daily["Date"], y=daily["Inventory Value"]))
        st.plotly_chart(fig2, use_container_width=True)

        st.subheader("⏳ Inventory Age")
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(x=daily["Date"], y=daily["Avg Age"]))
        st.plotly_chart(fig3, use_container_width=True)

        st.subheader("📊 Aging Buckets")
        fig4 = go.Figure()
        fig4.add_bar(x=daily["Date"], y=daily["0-30"], name="0-30")
        fig4.add_bar(x=daily["Date"], y=daily["31-60"], name="31-60")
        fig4.add_bar(x=daily["Date"], y=daily["61-90"], name="61-90")
        fig4.add_bar(x=daily["Date"], y=daily["90+"], name="90+")
        fig4.update_layout(barmode="stack")
        st.plotly_chart(fig4, use_container_width=True)

        if st.checkbox("Show Data"):
            st.dataframe(daily)

    except Exception as e:
        st.error(f"Error: {e}")
