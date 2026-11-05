"""Shared Dark / Light theme for every page (colours, page CSS, chart styling)."""
import streamlit as st

CSS = """
<style>
/* ---- whole-page theme (follows the Dark / Light switch) ---- */
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stHeader"],
[data-testid="stBottomBlockContainer"] {background-color:@BG@ !important; color:@FG@;}
[data-testid="stSidebar"], [data-testid="stSidebarContent"] {background-color:@SIDE@ !important;}
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp p, .stApp li, .stApp label,
[data-testid="stWidgetLabel"] *, [data-testid="stSidebar"] * {color:@FG@;}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * {color:@MUTED@ !important;}
.stApp input, [data-baseweb="input"], [data-baseweb="input"] > div, [data-baseweb="base-input"],
[data-testid="stNumberInputContainer"] {background-color:@CARD@ !important; color:@FG@ !important;}
[data-testid="stNumberInputStepDown"], [data-testid="stNumberInputStepUp"] {background-color:@CARD@ !important; color:@FG@ !important;}
/* buttons: segmented controls + Refresh */
.stApp [data-testid="stButtonGroup"] button, .stApp .stButton button,
.stApp button[kind="secondary"], .stApp button[kind^="segmented_control"] {
  background-color:@CARD@ !important; color:@MUTED@ !important; border-color:@BORDER@ !important;
  transition:background-color .15s, color .15s;}
.stApp [data-testid="stButtonGroup"] button *, .stApp .stButton button * {color:inherit !important;}
.stApp [data-testid="stButtonGroup"] button:hover, .stApp .stButton button:hover {
  color:@FG@ !important; border-color:@ACCENT@ !important;}
.stApp [data-testid="stButtonGroup"] button[kind$="Active"],
.stApp [data-testid="stButtonGroup"] button[aria-checked="true"],
.stApp [data-testid="stButtonGroup"] button[aria-pressed="true"],
.stApp button[kind="segmented_controlActive"] {
  background-color:@ACTIVE@ !important; color:@FG@ !important; border-color:@ACCENT@ !important;
  font-weight:600;}
[data-testid="stCode"] pre, [data-testid="stCode"] code {background-color:@CARD@ !important; color:@FG@ !important;}
[data-testid="stHeader"] button, [data-testid="stToolbar"] * {color:@FG@ !important;}
hr {border-color:@BORDER@ !important;}
[data-testid="stAlertContainer"] {background-color:@CARD@ !important; border:1px solid @BORDER@;}
[data-testid="stAlertContainer"] * {color:@FG@ !important;}
.block-container {padding-top: 3.5rem;}
.cards {display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:14px; margin:8px 0 18px;}
.card {background:@CARD@; border:1px solid @BORDER@; border-radius:8px; padding:16px 20px;}
.card .lbl {color:@MUTED@; font-size:0.85rem; letter-spacing:0.02em;}
.card .val {color:@FG@; font-size:1.7rem; font-weight:600; margin:4px 0; font-variant-numeric:tabular-nums;}
.card.pos {border-color:#3fb950;} .card.neg {border-color:#f85149;} .card.mix {border-color:#d29922;}
.card .sub {color:@MUTED@; font-size:0.85rem; line-height:1.4;}
.note {color:@MUTED@; font-size:0.85rem; background:@CARD@; border:1px solid @BORDER@;
       border-radius:8px; padding:10px 14px;}
.kgrid {display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:18px 28px;}
.ktitle {color:@MUTED@; font-size:0.85rem; margin-bottom:6px;}
.ktable {width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; font-size:0.92rem;}
.ktable td {padding:7px 6px; border-top:1px solid @BORDER@; color:@FG@; white-space:nowrap;}
.ktable tr:first-child td {border-top:none;}
.ktable td.num {text-align:right;}
.dim {color:@DIM@;}
.kblock {background:@CARD@; border:1px solid @BORDER@; border-radius:8px; padding:12px 16px;}
</style>
"""


def palette(dark):
    return {
        "template": "plotly_dark" if dark else "plotly_white",
        "bg": "#0d1117" if dark else "#ffffff",
        "card": "#161b22" if dark else "#f6f8fa",
        "side": "#010409" if dark else "#f6f8fa",
        "accent": "#58a6ff" if dark else "#0969da",
        "active": "#1f3a5f" if dark else "#ddf4ff",
        "border": "#2a313c" if dark else "#d0d7de",
        "fg": "#e8edf3" if dark else "#1f2328",
        "muted": "#9aa4b2" if dark else "#59636e",
        "dim": "#8b949e" if dark else "#6e7781",
        "spot": "#c9d1d9" if dark else "#424a53",
        "zero": "#6e7681" if dark else "#afb8c1",
    }


def apply():
    """Inject the page CSS for the current theme and return its palette."""
    th = palette(st.session_state.get("chart_theme", "Dark") != "Light")
    css = CSS
    for tok, key in [("@BG@", "bg"), ("@ACCENT@", "accent"), ("@ACTIVE@", "active"), ("@SIDE@", "side"),
                     ("@CARD@", "card"), ("@BORDER@", "border"), ("@FG@", "fg"), ("@MUTED@", "muted"),
                     ("@DIM@", "dim")]:
        css = css.replace(tok, th[key])
    st.markdown(css, unsafe_allow_html=True)
    return th


def style(fig, th, **kw):
    fig.update_layout(template=th["template"], paper_bgcolor=th["bg"], plot_bgcolor=th["bg"],
                      font_color=th["fg"], **kw)
    return fig
