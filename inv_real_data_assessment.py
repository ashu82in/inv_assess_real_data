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
        # 🔧 SIDEBAR INPUTS
        # =========================
        st.sidebar.header("🎯 Inventory Policy Inputs")

        lead_time = st.sidebar.number_input("Lead Time (days)", value=3)
        service_level = st.sidebar.slider("Service Level (%)", 80, 99, 95)
        dead_days = st.sidebar.number_input("Dead Stock Threshold (days)", value=90)

        st.sidebar.header("⚙️ Additional Settings")

        opening_inventory = st.sidebar.number_input("Opening Inventory Value", value=0)
        opening_age_days = st.sidebar.number_input("Opening Inventory Age (days)", value=30)
        reorder_point_manual = st.sidebar.number_input("Manual Reorder Point", value=0)

        st.sidebar.subheader("📦 Safety Stock Control")
        use_manual_ss = st.sidebar.checkbox("Use Manual Safety Stock")
        manual_ss = st.sidebar.number_input("Manual Safety Stock", value=0)

        # =========================
        # LOAD DATA
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
            "particulars": "Party"
        }, inplace=True)

        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"])

        for col in ["Received", "Issued", "Rate", "Closing Stock"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

        df = df.sort_values("Date").reset_index(drop=True)

        # =========================
        # VALUE CALCULATION
        # =========================
        df["Net Qty"] = df["Received"] - df["Issued"]
        df["Net Value"] = df["Net Qty"] * df["Rate"]
        df["Inventory Value"] = opening_inventory + df["Net Value"].cumsum()

        # =========================
        # DATE RANGE
        # =========================
        full_dates = pd.date_range(df["Date"].min(), df["Date"].max())
        df_grouped = df.groupby("Date").agg({"Received": "sum", "Issued": "sum"})

        # =========================
        # FIFO ENGINE
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

            received = df_grouped.loc[current_date]["Received"] if current_date in df_grouped.index else 0
            issued = df_grouped.loc[current_date]["Issued"] if current_date in df_grouped.index else 0

            if received > 0:
                rate = df[df["Date"] == current_date]["Rate"].mean()
                inventory_layers.append({
                    "qty": received,
                    "date": current_date,
                    "rate": rate
                })

            qty_to_issue = issued
            while qty_to_issue > 0 and inventory_layers:
                if inventory_layers[0]["qty"] <= qty_to_issue:
                    qty_to_issue -= inventory_layers[0]["qty"]
                    inventory_layers.pop(0)
                else:
                    inventory_layers[0]["qty"] -= qty_to_issue
                    qty_to_issue = 0

            total_qty = sum(l["qty"] for l in inventory_layers)

            if total_qty == 0:
                avg_age = 0
            else:
                avg_age = sum(
                    l["qty"] * (current_date - l["date"]).days for l in inventory_layers
                ) / total_qty

            age_list.append(avg_age)

            b1 = b2 = b3 = b4 = dead_val = 0

            for l in inventory_layers:
                age = (current_date - l["date"]).days
                value = l["qty"] * l["rate"]

                if age <= 30: b1 += value
                elif age <= 60: b2 += value
                elif age <= 90: b3 += value
                else: b4 += value

                if age >= dead_days:
                    dead_val += value

            bucket_data.append([current_date, b1, b2, b3, b4])
            dead_list.append(dead_val)

        # =========================
        # DAILY
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

        daily["Closing_Stock"] = daily["Closing_Stock"].ffill().fillna(0)
        daily["Inventory Value"] = daily["Inventory Value"].ffill().fillna(opening_inventory)
        daily["Total Received"] = daily["Total Received"].fillna(0)
        daily["Total Issued"] = daily["Total Issued"].fillna(0)

        daily["Avg Age"] = age_list
        daily["Dead Value"] = dead_list

        # =========================
        # ROP
        # =========================
        mean_demand = daily["Total Issued"].mean()
        std_demand = daily["Total Issued"].std()
        z = norm.ppf(service_level / 100)

        calc_ss = z * std_demand * np.sqrt(lead_time)
        safety_stock = manual_ss if use_manual_ss else calc_ss

        rop = (mean_demand * lead_time) + safety_stock
        daily["ROP"] = rop

        # =========================
        # WORKING CAPITAL
        # =========================
        daily["Locked %"] = (daily["Dead Value"] / daily["Inventory Value"]) * 100

        # =========================
        # PURCHASE / SALES
        # =========================
        daily["Purchase Qty"] = daily["Total Received"]
        daily["Sales Qty"] = -daily["Total Issued"]

        # =========================
        # KPI
        # =========================
        st.subheader("📊 Key Business Metrics")

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Inventory Value", int(daily.iloc[-1]["Inventory Value"]))
        c2.metric("Reorder Point", int(rop))
        c3.metric("Safety Stock", int(safety_stock))
        c4.metric("Avg Demand", round(mean_demand, 1))
        c5.metric("Demand Variability", round(std_demand, 1))

        c6, c7, c8, c9, c10 = st.columns(5)
        c6.metric("Min Inventory", int(daily["Closing_Stock"].min()))
        c7.metric("Average Age", int(daily["Avg Age"].mean()))
        c8.metric("Dead Stock ₹", int(daily.iloc[-1]["Dead Value"]))
        c9.metric("Locked %", round(daily.iloc[-1]["Locked %"], 1))
        c10.metric("Service Level (%)", int(service_level))

        # =========================
        # INVENTORY QUANTITY
        # =========================
        st.subheader("📦 Inventory Quantity")

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=daily["Date"], y=daily["Closing_Stock"], name="Stock"))
        fig.add_trace(go.Scatter(x=daily["Date"], y=[rop]*len(daily), name="Stat ROP",
                                 line=dict(color="purple", dash="dot")))
        fig.add_trace(go.Scatter(x=daily["Date"], y=[reorder_point_manual]*len(daily),
                                 name="Manual ROP", line=dict(dash="dash")))

        st.plotly_chart(fig, use_container_width=True)

        # =========================
        # INVENTORY VALUE
        # =========================
        st.subheader("💰 Inventory Value")
        st.line_chart(daily.set_index("Date")["Inventory Value"])

        # =========================
        # AGE GRAPH (DUAL AXIS)
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
        # AGING BUCKETS
        # =========================
        st.subheader("📊 Aging Buckets")

        bucket_df = pd.DataFrame(bucket_data, columns=["Date", "0-30", "31-60", "61-90", "90+"])
        bucket_df.set_index("Date", inplace=True)
        st.bar_chart(bucket_df)

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

            st.subheader("🏭 Supplier Purchase Trend")
            supplier_df = df[df["Received"] > 0].copy()
            supplier_df["Value"] = supplier_df["Received"] * supplier_df["Rate"]

            sup = supplier_df.groupby(["Date", "Party"])["Value"].sum().unstack().fillna(0)
            st.bar_chart(sup)

            st.subheader("🧾 Customer Sales Trend")
            customer_df = df[df["Issued"] > 0].copy()
            customer_df["Value"] = customer_df["Issued"] * customer_df["Rate"]

            cust = customer_df.groupby(["Date", "Party"])["Value"].sum().unstack().fillna(0)
            st.bar_chart(cust)

            st.subheader("🏭 Supplier Pareto")
            st.bar_chart(supplier_df.groupby("Party")["Value"].sum().sort_values(ascending=False))

            st.subheader("🧾 Customer Pareto")
            st.bar_chart(customer_df.groupby("Party")["Value"].sum().sort_values(ascending=False))

# =========================================================
        # 📄 FULL PROFESSIONAL PDF & EXCEL EXPORT
        # =========================================================
        st.sidebar.markdown("---")
        st.sidebar.subheader("📥 Final Report Exports")

        from fpdf import FPDF
        import matplotlib.pyplot as plt
        import tempfile
        import io

        def create_full_pdf(df_daily, df_raw, bucket_df, total_val, dead_val, avg_age, rop_val):
            pdf = FPDF()
            pdf.set_auto_page_break(auto=True, margin=15)
            
            # --- PAGE 1: EXECUTIVE SUMMARY ---
            pdf.add_page()
            pdf.set_font("Arial", 'B', 24)
            pdf.cell(0, 20, "Inventory Intelligence Report", ln=True, align='C')
            pdf.set_font("Arial", '', 10)
            pdf.cell(0, 5, f"Period: {df_daily['Date'].min().date()} to {df_daily['Date'].max().date()}", ln=True, align='C')
            pdf.ln(10)

            # Metrics
            pdf.set_fill_color(240, 245, 255)
            pdf.set_font("Arial", 'B', 14)
            pdf.cell(0, 10, " 1. Executive Summary Metrics", ln=True, fill=True)
            pdf.ln(2)
            pdf.set_font("Arial", '', 12)
            pdf.cell(95, 12, f" Total Inventory Value: {int(total_val):,}", border=1)
            pdf.cell(95, 12, f" Dead Stock Value: {int(dead_val):,}", ln=True, border=1)
            pdf.cell(95, 12, f" Average Stock Age: {int(avg_age)} Days", border=1)
            pdf.cell(95, 12, f" Reorder Point (ROP): {int(rop_val)} Units", ln=True, border=1)
            pdf.ln(10)

            # Trend Graph
            pdf.set_font("Arial", 'B', 14)
            pdf.cell(0, 10, " 2. Inventory Level & ROP Trend", ln=True)
            plt.figure(figsize=(10, 4))
            plt.plot(df_daily["Date"], df_daily["Closing_Stock"], color='#1f77b4', label="Stock Level")
            plt.axhline(y=rop_val, color='r', linestyle='--', label="ROP")
            plt.grid(True, alpha=0.3)
            plt.legend()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                plt.savefig(tmp.name, dpi=150, bbox_inches='tight')
                pdf.image(tmp.name, x=10, y=pdf.get_y(), w=190)
            plt.close()
            
            # --- PAGE 2: AGING & DISTRIBUTION ---
            pdf.add_page()
            pdf.set_font("Arial", 'B', 14)
            pdf.cell(0, 10, " 3. Inventory Aging (Value Distribution)", ln=True, fill=True)
            pdf.ln(5)
            
            temp_bucket = bucket_df.copy()
            temp_bucket.index = pd.to_datetime(temp_bucket.index)
            temp_bucket = temp_bucket.resample('W').mean() 

            fig, ax = plt.subplots(figsize=(10, 5))
            temp_bucket.plot(kind='bar', stacked=True, ax=ax)
            plt.xticks(rotation=45)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                plt.savefig(tmp.name, dpi=150, bbox_inches='tight')
                pdf.image(tmp.name, x=10, y=pdf.get_y(), w=190)
            plt.close()

            pdf.set_y(pdf.get_y() + 90) # Gap to prevent overlap

            pdf.set_font("Arial", 'B', 14)
            pdf.cell(0, 10, " 4. Stock Level Distribution", ln=True, fill=True)
            plt.figure(figsize=(10, 4))
            plt.hist(df_daily["Closing_Stock"], bins=20, color='skyblue', edgecolor='black', alpha=0.7)
            plt.axvline(rop_val, color='red', linestyle='dashed', label='ROP')
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                plt.savefig(tmp.name, dpi=150, bbox_inches='tight')
                pdf.image(tmp.name, x=10, y=pdf.get_y() + 5, w=190)
            plt.close()

            # --- PAGE 3: SUPPLIER & CUSTOMER ANALYSIS ---
            if "Party" in df_raw.columns:
                pdf.add_page()
                pdf.set_font("Arial", 'B', 16)
                pdf.cell(0, 15, "Supplier & Customer Analysis", ln=True, align='C')
                pdf.ln(5)

                # Supplier Pareto
                pdf.set_font("Arial", 'B', 12)
                pdf.cell(0, 10, " 5. Top Suppliers by Purchase Value", ln=True, fill=True)
                sup_data = df_raw[df_raw["Received"] > 0].copy()
                sup_data["Value"] = sup_data["Received"] * sup_data["Rate"]
                sup_pareto = sup_data.groupby("Party")["Value"].sum().sort_values(ascending=False).head(10)
                
                plt.figure(figsize=(10, 4))
                sup_pareto.plot(kind='bar', color='green', alpha=0.7)
                plt.title("Top 10 Suppliers")
                plt.ylabel("Total Value")
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                    plt.savefig(tmp.name, dpi=150, bbox_inches='tight')
                    pdf.image(tmp.name, x=10, y=pdf.get_y() + 5, w=190)
                plt.close()

                pdf.set_y(pdf.get_y() + 85) # Gap

                # Customer Pareto
                pdf.set_font("Arial", 'B', 12)
                pdf.cell(0, 10, " 6. Top Customers by Sales Value", ln=True, fill=True)
                cust_data = df_raw[df_raw["Issued"] > 0].copy()
                cust_data["Value"] = cust_data["Issued"] * cust_data["Rate"]
                cust_pareto = cust_data.groupby("Party")["Value"].sum().sort_values(ascending=False).head(10)
                
                plt.figure(figsize=(10, 4))
                cust_pareto.plot(kind='bar', color='red', alpha=0.7)
                plt.title("Top 10 Customers")
                plt.ylabel("Total Value")
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                    plt.savefig(tmp.name, dpi=150, bbox_inches='tight')
                    pdf.image(tmp.name, x=10, y=pdf.get_y() + 5, w=190)
                plt.close()

            return pdf.output(dest='S')

        # --- Sidebar UI Controls ---
        col_pdf, col_excel = st.sidebar.columns(2)

        with col_pdf:
            if st.button("🛠️ Build PDF"):
                try:
                    pdf_output = create_full_pdf(daily, df, bucket_df, daily.iloc[-1]["Inventory Value"], daily.iloc[-1]["Dead Value"], daily["Avg Age"].mean(), rop)
                    st.download_button(label="📥 Download PDF", data=bytes(pdf_output), file_name="Inventory_Full_Report.pdf", mime="application/pdf")
                except Exception as e:
                    st.error(f"PDF Error: {e}")

        with col_excel:
            if st.button("🛠️ Build Excel"):
                # Excel logic (using your existing to_excel function)
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    daily.to_excel(writer, index=False, sheet_name='Summary')
                    df.to_excel(writer, index=False, sheet_name='RawData')
                st.download_button(label="📥 Download Excel", data=output.getvalue(), file_name="Inventory_Data.xlsx")

    
    except Exception as e:
        st.error(str(e))
