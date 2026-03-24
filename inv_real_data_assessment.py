import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from scipy.stats import norm

st.set_page_config(layout="wide")
st.title("📊 Inventory Intelligence Dashboard")

uploaded_file = st.file_uploader("Upload Transaction File", type=["xlsx"])

if uploaded_file:
    try:
        # =========================
        # LOAD DATA
        # =========================
        df = pd.read_excel(uploaded_file, engine="openpyxl")

        df.columns = (
            df.columns.str.strip()
            .str.replace("'", "", regex=False)
            .str.replace('"', "", regex=False)
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
            "particulars": "Party"
        }, inplace=True)

        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"])

        for col in ["Received", "Issued", "Rate", "Closing Stock"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        df = df.sort_values("Date").reset_index(drop=True)

        # =========================
        # SETTINGS
        # =========================
        st.sidebar.header("⚙️ Settings")

        opening_inventory = st.sidebar.number_input("Opening Inventory Value", value=0)
        opening_age_days = st.sidebar.number_input("Opening Inventory Age (days)", value=30)
        lead_time = st.sidebar.number_input("Lead Time (days)", value=3)
        service_level = st.sidebar.slider("Service Level (%)", 80, 99, 95)
        dead_days = st.sidebar.number_input("Dead Stock Threshold (days)", value=90)

        # =========================
        # VALUE
        # =========================
        df["Net Qty"] = df["Received"] - df["Issued"]
        df["Net Value"] = df["Net Qty"] * df["Rate"]
        df["Inventory Value"] = opening_inventory + df["Net Value"].cumsum()

        # =========================
        # DAILY
        # =========================
        full_dates = pd.date_range(df["Date"].min(), df["Date"].max())

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

        daily["Closing_Stock"] = daily["Closing_Stock"].ffill().fillna(0)
        daily["Inventory Value"] = daily["Inventory Value"].ffill().fillna(opening_inventory)
        daily["Total Received"] = daily["Total Received"].fillna(0)
        daily["Total Issued"] = daily["Total Issued"].fillna(0)

        # =========================
        # DEMAND STATS
        # =========================
        mean_demand = daily["Total Issued"].mean()
        std_demand = daily["Total Issued"].std()

        z_value = norm.ppf(service_level / 100)
        rop = (mean_demand * lead_time) + (z_value * std_demand * np.sqrt(lead_time))

        daily["ROP"] = rop

        # =========================
        # ZONES
        # =========================
        daily["Zone"] = "Healthy"
        daily.loc[daily["Closing_Stock"] <= 0, "Zone"] = "Stock-out"
        daily.loc[daily["Closing_Stock"] <= rop, "Zone"] = "Reorder"
        daily.loc[daily["Closing_Stock"] > 1.5 * rop, "Zone"] = "Overstock"

        # =========================
        # FIFO AGE
        # =========================
        inventory_layers = []
        age_list = []

        first_date = full_dates[0]

        opening_qty = df.iloc[0]["Closing Stock"] - (df.iloc[0]["Received"] - df.iloc[0]["Issued"])

        if opening_qty > 0:
            inventory_layers.append({
                "qty": opening_qty,
                "date": first_date - pd.Timedelta(days=opening_age_days)
            })

        grouped = df.groupby("Date").agg({"Received": "sum", "Issued": "sum"})

        for d in full_dates:
            r = grouped.loc[d]["Received"] if d in grouped.index else 0
            i = grouped.loc[d]["Issued"] if d in grouped.index else 0

            if r > 0:
                inventory_layers.append({"qty": r, "date": d})

            while i > 0 and inventory_layers:
                if inventory_layers[0]["qty"] <= i:
                    i -= inventory_layers[0]["qty"]
                    inventory_layers.pop(0)
                else:
                    inventory_layers[0]["qty"] -= i
                    i = 0

            total_qty = sum(l["qty"] for l in inventory_layers)

            if total_qty == 0:
                age_list.append(0)
            else:
                weighted = sum(l["qty"] * (d - l["date"]).days for l in inventory_layers)
                age_list.append(weighted / total_qty)

        daily["Avg Age"] = age_list

        # =========================
        # PURCHASE / SALES
        # =========================
        daily["Purchase Qty"] = daily["Total Received"]
        daily["Sales Qty"] = -daily["Total Issued"]

        # =========================
        # METRICS
        # =========================
        st.subheader("📌 Key Metrics")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Inventory Value", int(daily.iloc[-1]["Inventory Value"]))
        col2.metric("Reorder Point", int(rop))
        col3.metric("Avg Demand", round(mean_demand, 1))
        col4.metric("Demand Variability", round(std_demand, 1))

        # =========================
        # INVENTORY CHART
        # =========================
        st.subheader("📦 Inventory Quantity")

        fig_qty = go.Figure()
        fig_qty.add_trace(go.Scatter(x=daily["Date"], y=daily["Closing_Stock"], name="Stock"))
        fig_qty.add_trace(go.Scatter(x=daily["Date"], y=[rop]*len(daily),
                                    name="ROP", line=dict(color="purple", dash="dot")))
        st.plotly_chart(fig_qty, use_container_width=True)

        # =========================
        # VALUE
        # =========================
        st.subheader("💰 Inventory Value")
        st.line_chart(daily.set_index("Date")["Inventory Value"])

        # =========================
        # AGE
        # =========================
        st.subheader("⏳ Inventory Age")

        fig_age = go.Figure()
        fig_age.add_trace(go.Scatter(x=daily["Date"], y=daily["Avg Age"], name="Age"))

        fig_age.add_trace(go.Bar(x=daily["Date"], y=daily["Purchase Qty"],
                                 name="Purchases", marker=dict(color="#006400"), opacity=0.6))

        fig_age.add_trace(go.Bar(x=daily["Date"], y=daily["Sales Qty"],
                                 name="Sales", marker=dict(color="#8B0000"), opacity=0.6))

        st.plotly_chart(fig_age, use_container_width=True)

        # =========================
        # ZONE
        # =========================
        st.subheader("📊 Inventory Zone Distribution")
        st.bar_chart(daily["Zone"].value_counts())

        # =========================
        # HISTOGRAM
        # =========================
        st.subheader("📊 Inventory Distribution")

        fig_hist = go.Figure()
        fig_hist.add_trace(go.Histogram(x=daily["Closing_Stock"], nbinsx=20))
        fig_hist.add_vline(x=rop, line_dash="dot", line_color="purple")

        st.plotly_chart(fig_hist, use_container_width=True)

        # =========================
        # SUPPLIER & CUSTOMER
        # =========================
        if "Party" in df.columns:

            st.subheader("🏭 Purchases by Supplier")
            sup = df[df["Received"] > 0].groupby(["Date", "Party"])["Received"].sum().unstack().fillna(0)
            st.bar_chart(sup)

            st.subheader("🧾 Sales by Customer")
            cust = df[df["Issued"] > 0].groupby(["Date", "Party"])["Issued"].sum().unstack().fillna(0)
            st.bar_chart(cust)

            st.subheader("🏭 Supplier Pareto")
            st.bar_chart(df[df["Received"] > 0].groupby("Party")["Received"].sum().sort_values(ascending=False))

            st.subheader("🧾 Customer Pareto")
            st.bar_chart(df[df["Issued"] > 0].groupby("Party")["Issued"].sum().sort_values(ascending=False))

    except Exception as e:
        st.error(str(e))
