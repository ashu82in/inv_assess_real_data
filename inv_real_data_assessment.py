#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Mar 23 13:09:28 2026

@author: ashutoshgoenka
"""

import streamlit as st
import pandas as pd

st.title("Inventory Reconciliation App")

uploaded_file = st.file_uploader("Upload Excel File", type=["xlsx"])

if uploaded_file:
    try:
        # Read sheets
        closing_df = pd.read_excel(uploaded_file, sheet_name="Closing")
        txn_df = pd.read_excel(uploaded_file, sheet_name="Transactions")

        st.subheader("Closing Sheet")
        st.dataframe(closing_df)

        st.subheader("Transactions Sheet")
        st.dataframe(txn_df)

        # Standardize column names
        closing_df.columns = closing_df.columns.str.strip()
        txn_df.columns = txn_df.columns.str.strip()

        # Merge both sheets
        merged = pd.merge(txn_df, closing_df, on="Item", how="left", suffixes=("_txn", "_closing"))

        # Calculate expected closing
        merged["Calculated_Closing"] = (
            merged["Opening"] + merged["Order_Received"] - merged["Sales"]
        )

        # Check mismatch (Sheet 2 vs calculation)
        merged["Txn_Match"] = merged["Closing_txn"] == merged["Calculated_Closing"]

        # Check mismatch (Sheet 1 vs Sheet 2)
        merged["Sheet_Match"] = merged["Closing_txn"] == merged["Closing_Stock"]

        st.subheader("Reconciliation Result")
        st.dataframe(merged)

        # Highlight mismatches
        mismatch = merged[
            (merged["Txn_Match"] == False) | (merged["Sheet_Match"] == False)
        ]

        if not mismatch.empty:
            st.error("⚠️ Mismatches Found!")
            st.dataframe(mismatch)
        else:
            st.success("✅ All data is consistent!")

    except Exception as e:
        st.error(f"Error processing file: {e}")