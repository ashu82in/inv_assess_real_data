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
        }, inplace=True)

        required = ["Date", "Received", "Issued", "Closing Stock", "Rate"]
        if not all(c in df.columns for c in required):
            st.error("Missing required columns")
            st.stop()

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
        opening_age_days = st.sidebar.number_input("Average Age of Opening Inventory (days)", value=30)
        stockout_threshold = st.sidebar.number_input("Stock-out Threshold", value=0)
        reorder_point = st.sidebar.number_input("Reorder Point", value=0)
        dead_days = st.sidebar.number_input("Dead Stock Threshold (days)", value=90)

        # =========================
        # 🔹 VALUE
        # =========================
        df["Net Qty"] = df["Received"] - df["Issued"]
        df["Net Value"] = df["Net Qty"] * df["Rate"]
        df["Inventory Value"] = opening_inventory + df["Net Value"].cumsum()

        # =========================
        # 🔹 DATE RANGE
        # =========================
        full_dates = pd.date_range(df["Date"].min(), df["Date"].max())
        df_grouped = df.groupby("Date").agg({"Received": "sum", "Issued": "sum"})

        # =========================
        # 🔹 FIFO ENGINE
        # =========================
        inventory_layers = []
        age_list, bucket_data, dead_list = [], [], []

        first_date = full_dates[0]

        opening_qty = df.iloc[0]["Closing Stock"] - (df.iloc[0]["Received"] - df.iloc[0]["Issued"])

        if opening_qty > 0:
            inventory_layers.append({
                "qty": opening_qty,
                "date": first_date - pd.Timedelta(days=opening_age_days),
                "rate": df.iloc[0]["Rate"]
            })

        for current_date in full_dates:

            if current_date in df_grouped.index:
                received = df_grouped.loc[current_date]["Received"]
                issued = df_grouped.loc[current_date]["Issued"]
            else:
                received = 0
                issued = 0

            if received > 0:
                day_rate = df[df["Date"] == current_date]["Rate"].mean()
                inventory_layers.append({
                    "qty": received,
                    "date": current_date,
                    "rate": day_rate
                })

            qty_to_issue = issued
            while qty_to_issue > 0 and inventory_layers:
                layer = inventory_layers[0]
                if layer["qty"] <= qty_to_issue:
                    qty_to_issue -= layer["qty"]
                    inventory_layers.pop(0)
                else:
                    layer["qty"] -= qty_to_issue
                    qty_to_issue = 0

            total_qty = sum(l["qty"] for l in inventory_layers)

            if total_qty == 0:
                avg_age = 0
            else:
                weighted_age = sum(
                    l["qty"] * (current_date - l["date"]).days for l in inventory_layers
                )
                avg_age = weighted_age / total_qty

            age_list.append(avg_age)

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

        # =========================
        # 🔹 STOCK + REORDER
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
        # 🔹 PURCHASE & SALES
        # =========================
        daily["Purchase Qty"] = daily["Total Received"]
        daily["Sales Qty"] = -daily["Total Issued"]

        # =========================
        # 🔹 METRICS
        # =========================
        st.subheader("📌 Key Metrics")

        col1, col2, col3, col4, col5, col6 = st.columns(6)

        col1.metric("Inventory Value", int(daily.iloc[-1]["Inventory Value"]))
        col2.metric("Dead Stock ₹", int(daily.iloc[-1]["Dead Value"]))
        col3.metric("Locked Capital %", round(daily.iloc[-1]["Locked %"], 1))
        col4.metric("Avg Age", int(daily.iloc[-1]["Avg Age"]))
        col5.metric("Stock-out Days", int(stockout_days))
        col6.metric("Reorder Days", int(reorder_days))

        # =========================
        # 🔹 INVENTORY AGE GRAPH (FINAL)
        # =========================
        st.subheader("⏳ Inventory Age (with Purchases & Sales)")

        fig_age = go.Figure()

        fig_age.add_trace(go.Scatter(
            x=daily["Date"],
            y=daily["Avg Age"],
            mode="lines+markers",
            name="Avg Age",
            line=dict(width=3),
            yaxis="y1"
        ))

        fig_age.add_trace(go.Bar(
            x=daily["Date"],
            y=daily["Purchase Qty"],
            name="Purchases",
            marker=dict(color="green"),
            opacity=0.25,
            yaxis="y2"
        ))

        fig_age.add_trace(go.Bar(
            x=daily["Date"],
            y=daily["Sales Qty"],
            name="Sales",
            marker=dict(color="red"),
            opacity=0.25,
            yaxis="y2"
        ))

        fig_age.update_layout(
            template="simple_white",
            barmode="relative",
            yaxis=dict(title="Avg Age"),
            yaxis2=dict(overlaying="y", side="right", title="Movement")
        )

        st.plotly_chart(fig_age, use_container_width=True)

    except Exception as e:
        st.error(str(e))
