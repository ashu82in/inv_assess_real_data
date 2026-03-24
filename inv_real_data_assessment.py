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
        # 🔥 DEMAND + ROP (FIXED)
        # =========================
        mean_demand = daily["Total Issued"].mean()
        std_demand = daily["Total Issued"].std()

        z = norm.ppf(service_level / 100)

        rop = (mean_demand * lead_time) + (z * std_demand * np.sqrt(lead_time))

        daily["ROP"] = rop

        # =========================
        # FIFO AGE + DEAD STOCK
        # =========================
        layers = []
        ages = []
        dead_values = []

        first_date = full_dates[0]

        opening_qty = df.iloc[0]["Closing Stock"] - (df.iloc[0]["Received"] - df.iloc[0]["Issued"])

        if opening_qty > 0:
            layers.append({
                "qty": opening_qty,
                "date": first_date - pd.Timedelta(days=opening_age_days),
                "rate": df.iloc[0]["Rate"]
            })

        grouped = df.groupby("Date").agg({"Received": "sum", "Issued": "sum"})

        for d in full_dates:
            r = grouped.loc[d]["Received"] if d in grouped.index else 0
            i = grouped.loc[d]["Issued"] if d in grouped.index else 0

            if r > 0:
                rate = df[df["Date"] == d]["Rate"].mean()
                layers.append({"qty": r, "date": d, "rate": rate})

            while i > 0 and layers:
                if layers[0]["qty"] <= i:
                    i -= layers[0]["qty"]
                    layers.pop(0)
                else:
                    layers[0]["qty"] -= i
                    i = 0

            total_qty = sum(l["qty"] for l in layers)

            if total_qty == 0:
                ages.append(0)
                dead_values.append(0)
            else:
                weighted = sum(l["qty"] * (d - l["date"]).days for l in layers)
                ages.append(weighted / total_qty)

                dead_val = sum(
                    l["qty"] * l["rate"]
                    for l in layers
                    if (d - l["date"]).days >= dead_days
                )
                dead_values.append(dead_val)

        daily["Avg Age"] = ages
        daily["Dead Stock Value"] = dead_values

        # =========================
        # PURCHASE / SALES
        # =========================
        daily["Purchase Qty"] = daily["Total Received"]
        daily["Sales Qty"] = -daily["Total Issued"]

        # =========================
        # WORKING CAPITAL
        # =========================
        daily["Working Capital"] = daily["Inventory Value"]

        # =========================
        # METRICS
        # =========================
        st.subheader("📌 Key Metrics")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Inventory Value", int(daily.iloc[-1]["Inventory Value"]))
        col2.metric("Reorder Point", int(rop))
        col3.metric("Dead Stock ₹", int(daily.iloc[-1]["Dead Stock Value"]))
        col4.metric("Avg Age", int(daily.iloc[-1]["Avg Age"]))

        # =========================
        # INVENTORY
        # =========================
        st.subheader("📦 Inventory Quantity")

        fig_qty = go.Figure()
        fig_qty.add_trace(go.Scatter(x=daily["Date"], y=daily["Closing_Stock"], name="Stock"))
        fig_qty.add_trace(go.Scatter(x=daily["Date"], y=[rop]*len(daily),
                                    name="ROP", line=dict(color="purple", dash="dot")))

        st.plotly_chart(fig_qty, use_container_width=True)

        # =========================
        # WORKING CAPITAL
        # =========================
        st.subheader("💰 Working Capital")

        st.line_chart(daily.set_index("Date")["Working Capital"])

        # =========================
        # AGE GRAPH (FIXED)
        # =========================
        st.subheader("⏳ Inventory Age")

        fig_age = go.Figure()

        fig_age.add_trace(go.Scatter(
            x=daily["Date"], y=daily["Avg Age"],
            name="Age", yaxis="y1"
        ))

        fig_age.add_trace(go.Bar(
            x=daily["Date"], y=daily["Purchase Qty"],
            name="Purchases", marker=dict(color="#006400"),
            opacity=0.6, yaxis="y2"
        ))

        fig_age.add_trace(go.Bar(
            x=daily["Date"], y=daily["Sales Qty"],
            name="Sales", marker=dict(color="#8B0000"),
            opacity=0.6, yaxis="y2"
        ))

        fig_age.update_layout(
            template="plotly_dark",
            barmode="relative",
            yaxis=dict(title="Age"),
            yaxis2=dict(overlaying="y", side="right", title="Movement")
        )

        st.plotly_chart(fig_age, use_container_width=True)

        # =========================
        # DEAD STOCK TREND
        # =========================
        st.subheader("💀 Dead Stock Value")

        st.line_chart(daily.set_index("Date")["Dead Stock Value"])

    except Exception as e:
        st.error(str(e))
