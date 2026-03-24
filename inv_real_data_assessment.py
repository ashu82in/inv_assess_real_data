import streamlit as st
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(layout="wide")
st.title("📊 Inventory Intelligence Dashboard")

uploaded_file = st.file_uploader("Upload Transaction File", type=["xlsx"])

if uploaded_file:
    try:
        # =========================
        # 🔹 LOAD DATA
        # =========================
        df = pd.read_excel(uploaded_file, engine="openpyxl")

        # =========================
        # 🔹 CLEAN COLUMN NAMES
        # =========================
        df.columns = (
            df.columns.str.strip()
            .str.replace("'", "", regex=False)
            .str.replace('"', "", regex=False)
            .str.replace("_", " ")
            .str.lower()
        )

        if "balance" in df.columns:
            df.rename(columns={"balance": "Closing Stock"}, inplace=True)

        df.rename(columns={
            "date": "Date",
            "received": "Received",
            "issued": "Issued",
            "rate": "Rate",
            "closing stock": "Closing Stock",
            "particulars": "Party",
            "sku": "SKU"
        }, inplace=True)

        required = ["Date", "Received", "Issued", "Closing Stock", "Rate"]
        if not all(c in df.columns for c in required):
            st.error("Missing required columns")
            st.write(df.columns)
            st.stop()

        # =========================
        # 🔹 CLEAN DATA
        # =========================
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"])

        for col in ["Received", "Issued", "Rate", "Closing Stock"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        df = df.sort_values("Date").reset_index(drop=True)

        # =========================
        # 🔹 SETTINGS
        # =========================
        st.sidebar.header("⚙️ Settings")
        opening_inventory = st.sidebar.number_input("Opening Inventory Value", value=0)
        stockout_threshold = st.sidebar.number_input("Stock-out Threshold", value=0)
        dead_days = st.sidebar.number_input("Dead Stock Threshold (days)", value=90)

        # =========================
        # 🔹 VALUE CALCULATION
        # =========================
        df["Net Qty"] = df["Received"] - df["Issued"]
        df["Net Value"] = df["Net Qty"] * df["Rate"]
        df["Inventory Value"] = opening_inventory + df["Net Value"].cumsum()

        df["Purchase Value"] = df["Received"] * df["Rate"]
        df["Sales Value"] = df["Issued"] * df["Rate"]

        # =========================
        # 🔹 DATE ENGINE
        # =========================
        df_grouped = df.groupby("Date").agg({"Received": "sum", "Issued": "sum"})
        full_dates = pd.date_range(df["Date"].min(), df["Date"].max())

        inventory_layers = []
        age_list, bucket_data, dead_list = [], [], []

        opening_qty = df.iloc[0]["Closing Stock"] - (df.iloc[0]["Received"] - df.iloc[0]["Issued"])
        opening_remaining = max(opening_qty, 0)

        for current_date in full_dates:

            if current_date in df_grouped.index:
                received = df_grouped.loc[current_date]["Received"]
                issued = df_grouped.loc[current_date]["Issued"]
            else:
                received = 0
                issued = 0

            if received > 0:
                inventory_layers.append({"qty": received, "date": current_date})

            qty_to_issue = issued
            while qty_to_issue > 0 and inventory_layers:
                layer = inventory_layers[0]
                if layer["qty"] <= qty_to_issue:
                    qty_to_issue -= layer["qty"]
                    inventory_layers.pop(0)
                else:
                    layer["qty"] -= qty_to_issue
                    qty_to_issue = 0

            if opening_remaining > 0:
                opening_remaining -= issued
                age_list.append(None)
                bucket_data.append([current_date, 0, 0, 0, 0])
                dead_list.append(0)
                continue

            total_qty = sum(l["qty"] for l in inventory_layers)

            if total_qty == 0:
                age_list.append(0)
            else:
                weighted_age = sum(l["qty"] * (current_date - l["date"]).days for l in inventory_layers)
                age_list.append(weighted_age / total_qty)

            b1 = b2 = b3 = b4 = dead_val = 0

            for l in inventory_layers:
                age = (current_date - l["date"]).days
                value = l["qty"] * df["Rate"].iloc[-1]

                if age <= 30:
                    b1 += value
                elif age <= 60:
                    b2 += value
                elif age <= 90:
                    b3 += value
                else:
                    b4 += value

                if age >= dead_days:
                    dead_val += value

            bucket_data.append([current_date, b1, b2, b3, b4])
            dead_list.append(dead_val)

        age_df = pd.DataFrame({"Date": full_dates, "Avg Age": age_list})
        bucket_df = pd.DataFrame(bucket_data, columns=["Date", "0-30", "31-60", "61-90", "90+"])
        dead_df = pd.DataFrame({"Date": full_dates, "Dead Value": dead_list})

        # =========================
        # 🔹 DAILY
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

        daily = pd.DataFrame({"Date": full_dates}).merge(daily, on="Date", how="left")
        daily = daily.merge(age_df, on="Date", how="left")
        daily = daily.merge(bucket_df, on="Date", how="left")
        daily = daily.merge(dead_df, on="Date", how="left")

        daily["Closing_Stock"] = daily["Closing_Stock"].ffill().fillna(0)
        daily["Inventory Value"] = daily["Inventory Value"].ffill().fillna(opening_inventory)
        daily["Avg Age"] = daily["Avg Age"].ffill()

        daily["Locked %"] = (daily["90+"] / daily["Inventory Value"]) * 100

        # =========================
        # 🔹 METRICS
        # =========================
        st.subheader("📌 Key Metrics")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Inventory Value", int(daily.iloc[-1]["Inventory Value"]))
        col2.metric("Dead Stock ₹", int(daily.iloc[-1]["Dead Value"]))
        col3.metric("Locked Capital %", round(daily.iloc[-1]["Locked %"], 1))
        col4.metric("Avg Age", int(daily["Avg Age"].mean()))

        # =========================
        # 🔹 CHARTS
        # =========================
        st.subheader("📦 Inventory Quantity")
        st.line_chart(daily.set_index("Date")["Closing_Stock"])

        st.subheader("💰 Inventory Value")
        st.line_chart(daily.set_index("Date")["Inventory Value"])

        st.subheader("💸 Working Capital Lock")
        st.line_chart(daily.set_index("Date")["Locked %"])

        st.subheader("⏳ Inventory Age")
        st.line_chart(daily.set_index("Date")["Avg Age"])

        st.subheader("📊 Aging Buckets")
        st.bar_chart(daily.set_index("Date")[["0-30", "31-60", "61-90", "90+"]])

        # =========================
        # 🔹 SUPPLIER VS CUSTOMER
        # =========================
        if "Party" in df.columns:

            st.subheader("🏭 Purchases by Supplier")
            sup = df[df["Received"] > 0].groupby(["Date", "Party"])["Purchase Value"].sum().unstack().fillna(0)
            st.bar_chart(sup)

            st.subheader("🧾 Sales by Customer")
            cust = df[df["Issued"] > 0].groupby(["Date", "Party"])["Sales Value"].sum().unstack().fillna(0)
            st.bar_chart(cust)

        # =========================
        # 🔹 PARETO
        # =========================
        if "Party" in df.columns:

            st.subheader("🏭 Supplier Pareto")
            sup_p = df[df["Received"] > 0].groupby("Party")["Purchase Value"].sum().sort_values(ascending=False)
            st.bar_chart(sup_p)

            st.subheader("🧾 Customer Pareto")
            cust_p = df[df["Issued"] > 0].groupby("Party")["Sales Value"].sum().sort_values(ascending=False)
            st.bar_chart(cust_p)

        # =========================
        # 🔹 SKU
        # =========================
        if "SKU" in df.columns:
            st.subheader("📦 SKU Analysis")
            st.dataframe(df.groupby("SKU")["Net Value"].sum().reset_index())

        # =========================
        # 🔹 CASH FLOW
        # =========================
        st.subheader("💸 Cash Flow")

        st.metric("Cash Inflow", int((df["Issued"] * df["Rate"]).sum()))
        st.metric("Cash Outflow", int((df["Received"] * df["Rate"]).sum()))

        if st.checkbox("Show Data"):
            st.dataframe(daily)

    except Exception as e:
        st.error(str(e))
