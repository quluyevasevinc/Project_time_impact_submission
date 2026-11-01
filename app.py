from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="VM Time & Impact",
    layout="wide"
)

html = Path(__file__).with_name("dashboard.html").read_text(
    encoding="utf-8"
)

components.html(html, height=1200, scrolling=True)
