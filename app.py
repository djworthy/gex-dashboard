"""Gamma exposure dashboard. Run locally with:  streamlit run app.py"""
from datetime import datetime

import numpy as np
import plotly.graph_objects as go
import streamlit as st

import gex

st.set_page_config(page_title="Gamma map", page_icon="📈", layout="wide")

PRODUCTS = {
    "NQ · QQQ": {"chain": "QQQ", "future": "NQ=F", "mode": "ratio"},
    "ES · SPX": {"chain": "_SPX", "future": "ES=F", "mode": "basis"},
}
WINDOWS = {"0DTE": 0, "1D": 1, "7D": 7, "31D": 31, "91D": 91, "All": None}

CSS = """
<style>
.block-container {padding-top: 2rem;}
.cards {display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:14px; margin:8px 0 18px;}
.card {background:#161b22; border:1px solid #2a313c; border-radius:8px; padding:16px 20px;}
.card .lbl {color:#9aa4b2; font-size:0.85rem; letter-spacing:0.02em;}
.card .val {color:#e8edf3; font-size:1.7rem; font-weight:600; margin:4px 0; font-variant-numeric:tabular-nums;}
.card .sub {color:#9aa4b2; font-size:0.85rem; line-height:1.4;}
.note {color:#9aa4b2; font-size:0.85rem; background:#161b22; border:1px solid #2a313c;
       border-radius:8px; padding:10px 14px;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def card(label, value, sub=""):
    return f'<div class="card"><div class="lbl">{label}</div><div class="val">{value}</div><div class="sub">{sub}</div></div>'


@st.cache_data(ttl=60, show_spinner="Loading option chain…")
def load_chain(symbol):
    return gex.fetch_cboe_chain(symbol)


@st.cache_data(ttl=60, show_spinner=False)
def load_future(ticker):
    return gex.fetch_futures_price(ticker)


# ---------------------------------------------------------------- controls
c1, c2, c3 = st.columns([1.2, 2.2, 1])
product = c1.segmented_control("Product", list(PRODUCTS), default="NQ · QQQ", label_visibility="collapsed") or "NQ · QQQ"
window = c2.segmented_control("Expiry window", list(WINDOWS), default="0DTE", label_visibility="collapsed") or "0DTE"
if c3.button("Refresh data", width="stretch"):
    st.cache_data.clear()

with st.sidebar:
    st.header("Settings")
    weight = st.radio("Weight gamma by", ["volume", "open interest"], index=0)
    weight = "volume" if weight == "volume" else "oi"
    manual_fut = st.number_input(
        "Futures price override (0 = auto)", min_value=0.0, value=0.0, step=1.0,
        help="Use this if the automatic futures price fails to load.",
    )
    chart_range = st.slider("Chart range around spot (%)", 1, 15, 4)

cfg = PRODUCTS[product]

# ---------------------------------------------------------------- data
try:
    raw, spot, stamp = load_chain(cfg["chain"])
except Exception as e:
    st.error(f"Couldn't download the {cfg['chain']} chain from CBOE: {e}. Press Refresh data to try again.")
    st.stop()

fut = manual_fut or load_future(cfg["future"])
if fut:
    if cfg["mode"] == "ratio":       # QQQ -> NQ: multiply
        ratio, add = fut / spot, 0.0
    else:                            # SPX -> ES: add the basis
        ratio, add = 1.0, fut - spot
    unit = "futures pts"
else:
    ratio, add = 1.0, 0.0
    unit = f"{cfg['chain'].strip('_')} pts"
    st.warning("Futures price unavailable, so levels are shown in the underlying's own prices. Enter one in the sidebar to convert.")


def to_fut(x):
    return None if x is None else x * ratio + add


df = gex.prepare(raw, WINDOWS[window])
if df.empty:
    st.info(f"No live options in the {window} window right now (markets closed or no expiry today). Pick a longer window.")
    st.stop()

# ---------------------------------------------------------------- metrics
grid, totals = gex.gamma_profile(df, spot, weight, pct=max(chart_range, 5) / 100)
flip_vol = gex.gamma_flip(*gex.gamma_profile(df, spot, "volume", pct=0.08), spot)
flip_oi = gex.gamma_flip(*gex.gamma_profile(df, spot, "oi", pct=0.08), spot)
strikes = gex.by_strike(df, spot, weight)
pole_neg, pole_pos = gex.poles(strikes)
atm = gex.atm_stats(df, spot)

net_g_vol = gex.gex_per_option(df, spot, "volume").sum()
net_g_oi = gex.gex_per_option(df, spot, "oi").sum()
net_d_vol = gex.net_delta(df, spot, "volume")

calls, puts = df[df["type"] == "C"], df[df["type"] == "P"]
cv, pv = calls["volume"].sum(), puts["volume"].sum()
coi, poi = calls["open_interest"].sum(), puts["open_interest"].sum()

f_spot = to_fut(spot)
fmt = lambda x: "—" if x is None else f"{x:,.0f}" if f_spot > 1000 else f"{x:,.2f}"

flip_main = flip_vol if weight == "volume" else flip_oi
if flip_main is None:
    flip_sub = "no zero crossing within ±8%"
else:
    flip_sub = f"by volume · by OI {fmt(to_fut(flip_oi))} · spot is {'above' if spot > flip_main else 'below'}"

if atm:
    lo, hi = to_fut(spot - atm["move_1sd"]), to_fut(spot + atm["move_1sd"])
    em_val = f"{fmt(lo)}–{fmt(hi)}"
    em_sub = f"±{atm['move_1sd'] * ratio:,.0f} pts 1σ"
    if atm["straddle"]:
        em_sub += f" · straddle ±{atm['straddle'] * ratio:,.0f}"
    iv_val, iv_sub = f"{atm['iv'] * 100:.1f}%", f"ATM, expiry {atm['expiry']}"
else:
    em_val = em_sub = iv_val = iv_sub = "—"

st.caption(f"{cfg['chain'].strip('_')} chain · CBOE delayed data · {stamp} · {len(df):,} options in window · levels in {unit}")

html = '<div class="cards">' + "".join([
    card("Futures spot", fmt(f_spot), f"underlying {spot:,.2f}" + (f" · ratio {ratio:.3f}" if cfg["mode"] == "ratio" else f" · basis {add:+.1f}")),
    card("Gamma flip", fmt(to_fut(flip_main)), flip_sub),
    card(f"Poles ({'volume' if weight == 'volume' else 'OI'})", f"{fmt(to_fut(pole_neg))} / {fmt(to_fut(pole_pos))}", "largest negative / positive gamma strikes"),
    card("Expected move", em_val, em_sub),
    card("ATM IV", iv_val, iv_sub),
    card("Call / put volume", f"{gex.fmt_big(cv)} / {gex.fmt_big(pv)}", f"put/call {pv / cv:.2f} · OI {gex.fmt_big(coi)} / {gex.fmt_big(poi)}" if cv else ""),
    card("Net gamma × volume", gex.fmt_big(net_g_vol), f"× OI {gex.fmt_big(net_g_oi)} · net delta × volume {gex.fmt_big(net_d_vol)}"),
]) + "</div>"
st.markdown(html, unsafe_allow_html=True)

# ---------------------------------------------------------------- charts
lo_k, hi_k = spot * (1 - chart_range / 100), spot * (1 + chart_range / 100)
view = strikes[(strikes["strike"] >= lo_k) & (strikes["strike"] <= hi_k)]


def vline(fig, x, text, color):
    if x is not None:
        fig.add_vline(x=to_fut(x), line_dash="dot", line_color=color,
                      annotation_text=text, annotation_position="top")


left, right = st.columns(2)

fig = go.Figure(go.Bar(
    x=view["strike"] * ratio + add, y=view["gex"],
    marker_color=np.where(view["gex"] >= 0, "#3fb950", "#f85149"),
    hovertemplate="strike %{x:,.0f}<br>gamma $%{y:,.0f}<extra></extra>",
))
vline(fig, spot, "spot", "#e8edf3")
vline(fig, flip_main, "flip", "#d29922")
fig.update_layout(title="Net gamma by strike", template="plotly_dark", height=420,
                  margin=dict(l=10, r=10, t=50, b=10), xaxis_title=unit, yaxis_title="$ per 1% move")
left.plotly_chart(fig, width="stretch")

mask = (grid >= lo_k) & (grid <= hi_k)
fig2 = go.Figure(go.Scatter(x=grid[mask] * ratio + add, y=totals[mask], line=dict(color="#58a6ff", width=2)))
fig2.add_hline(y=0, line_color="#6e7681")
vline(fig2, spot, "spot", "#e8edf3")
vline(fig2, flip_main, "flip", "#d29922")
fig2.update_layout(title="Total net gamma if spot moved here", template="plotly_dark", height=420,
                   margin=dict(l=10, r=10, t=50, b=10), xaxis_title=unit, yaxis_title="$ per 1% move")
right.plotly_chart(fig2, width="stretch")

st.markdown(
    '<div class="note">The dealer sign is assumed (dealers long calls, short puts), which real positioning often contradicts. '
    "Data is ~15 minutes delayed. Treat this as a map, not a trading signal.</div>",
    unsafe_allow_html=True,
)
