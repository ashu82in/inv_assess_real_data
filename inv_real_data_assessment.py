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
        # 🔹 CLEAN COLUMNS
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
        reorder_point = st.sidebar.number_input("Reorder Point", value=0)
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
        # 🔹 DATE RANGE
        # =========================
        full_dates = pd.date_range(df["Date"].min(), df["Date"].max())
        df_grouped = df.groupby("Date").agg({"Received": "sum", "Issued": "sum"})

        # =========================
        # 🔹 FIFO ENGINE (TRUE AGE)
        # =========================
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

            # Add inventory layer
            if received > 0:
                day_rate = df[df["Date"] == current_date]["Rate"].mean()
                inventory_layers.append({
                    "qty": received,
                    "date": current_date,
                    "rate": day_rate
                })

            # Remove inventory (FIFO)
            qty_to_issue = issued
            while qty_to_issue > 0 and inventory_layers:
                layer = inventory_layers[0]
                if layer["qty"] <= qty_to_issue:
                    qty_to_issue -= layer["qty"]
                    inventory_layers.pop(0)
                else:
                    layer["qty"] -= qty_to_issue
                    qty_to_issue = 0

            # Skip age until opening stock is exhausted
            if opening_remaining > 0:
                opening_remaining -= issued
                age_list.append(None)
                bucket_data.append([current_date, 0, 0, 0, 0])
                dead_list.append(0)
                continue

            total_qty = sum(l["qty"] for l in inventory_layers)

            # TRUE AGE
            if total_qty == 0:
                avg_age = 0
            else:
                weighted_age = sum(
                    l["qty"] * (current_date - l["date"]).days for l in inventory_layers
                )
                avg_age = weighted_age / total_qty

            age_list.append(avg_age)

            # VALUE BUCKETS
            b1 = b2 = b3 = b4 = dead_val = 0

            for l in inventory_layers:
                age = (current_date - l["date"]).days
                value = l["qty"] * l["rate"]

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
        st.write(age_df)
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

        daily = pd.DataFrame({"Date": full_dates}).merge(daily, on="Date", how="left")
        daily = daily.merge(age_df, on="Date", how="left")
        daily = daily.merge(bucket_df, on="Date", how="left")
        daily = daily.merge(dead_df, on="Date", how="left")

        # Fill missing values
        daily["Closing_Stock"] = daily["Closing_Stock"].ffill().fillna(0)
        daily["Inventory Value"] = daily["Inventory Value"].ffill().fillna(opening_inventory)
        daily["Avg Age"] = daily["Avg Age"].ffill()

        # =========================
        # 🔹 STOCK-OUT & REORDER
        # =========================
        daily["Stockout Flag"] = daily["Closing_Stock"] <= stockout_threshold
        daily["Reorder Flag"] = daily["Closing_Stock"] <= reorder_point

        stockout_days = daily["Stockout Flag"].sum()
        reorder_days = daily["Reorder Flag"].sum()

        # =========================
        # 🔹 WORKING CAPITAL
        # =========================
        daily["Locked %"] = (daily["90+"] / daily["Inventory Value"]) * 100

        # =========================
        # 🔹 METRICS
        # =========================
        st.subheader("📌 Key Metrics")

        col1, col2, col3, col4, col5, col6 = st.columns(6)

        col1.metric("Inventory Value", int(daily.iloc[-1]["Inventory Value"]))
        col2.metric("Dead Stock ₹", int(daily.iloc[-1]["Dead Value"]))
        col3.metric("Locked Capital %", round(daily.iloc[-1]["Locked %"], 1))
        col4.metric("Avg Age", int(daily["Avg Age"].mean()))
        col5.metric("Stock-out Days", int(stockout_days))
        col6.metric("Reorder Days", int(reorder_days))

        # =========================
        # 🔹 INVENTORY CHART
        # =========================
        st.subheader("📦 Inventory Quantity")

        fig_qty = go.Figure()

        fig_qty.add_trace(go.Scatter(
            x=daily["Date"],
            y=daily["Closing_Stock"],
            mode="lines+markers",
            name="Stock"
        ))

        fig_qty.add_trace(go.Scatter(
            x=daily["Date"],
            y=[stockout_threshold]*len(daily),
            name="Stock-out Threshold",
            line=dict(dash="dash", color="red")
        ))

        fig_qty.add_trace(go.Scatter(
            x=daily["Date"],
            y=[reorder_point]*len(daily),
            name="Reorder Point",
            line=dict(dash="dot", color="orange")
        ))

        st.plotly_chart(fig_qty, use_container_width=True)

        # =========================
        # 🔹 OTHER CHARTS
        # =========================
        st.subheader("💰 Inventory Value")
        st.line_chart(daily.set_index("Date")["Inventory Value"])

        st.subheader("💸 Working Capital Lock")
        st.line_chart(daily.set_index("Date")["Locked %"])

        st.subheader("⏳ Inventory Age")
        st.line_chart(daily.set_index("Date")["Avg Age"])

        st.subheader("📊 Aging Buckets (₹)")
        st.bar_chart(daily.set_index("Date")[["0-30", "31-60", "61-90", "90+"]])

        # =========================
        # 🔹 REORDER ALERT TABLE
        # =========================
        st.subheader("📦 Reorder Alerts")

        reorder_df = daily[daily["Reorder Flag"]]

        if not reorder_df.empty:
            st.warning("Reorder required on these dates")
            st.dataframe(reorder_df[["Date", "Closing_Stock"]])
        else:
            st.success("No reorder required")

        # =========================
        # 🔹 SUPPLIER & CUSTOMER
        # =========================
        if "Party" in df.columns:

            st.subheader("🏭 Purchases by Supplier")
            sup = df[df["Received"] > 0].groupby(["Date", "Party"])["Purchase Value"].sum().unstack().fillna(0)
            st.bar_chart(sup)

            st.subheader("🧾 Sales by Customer")
            cust = df[df["Issued"] > 0].groupby(["Date", "Party"])["Sales Value"].sum().unstack().fillna(0)
            st.bar_chart(cust)

            st.subheader("🏭 Supplier Pareto")
            st.bar_chart(df[df["Received"] > 0].groupby("Party")["Purchase Value"].sum().sort_values(ascending=False))

            st.subheader("🧾 Customer Pareto")
            st.bar_chart(df[df["Issued"] > 0].groupby("Party")["Sales Value"].sum().sort_values(ascending=False))

        # =========================
        # 🔹 SKU ANALYSIS
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

    except Exception as e:
        st.error(str(e))
