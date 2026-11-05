"""Gamma map. Run locally with:  streamlit run app.py
This file only sets up the pages and the shared Dark / Light switch."""
import streamlit as st

st.set_page_config(page_title="Gamma map", page_icon="📈", layout="wide")

pages = st.navigation([
    st.Page("gex_page.py", title="GEX levels", icon="📈", default=True),
    st.Page("day_map.py", title="Day map", icon="🗺️"),
])

with st.sidebar:
    st.segmented_control("Theme", ["Dark", "Light"], default="Dark", key="chart_theme")

pages.run()
