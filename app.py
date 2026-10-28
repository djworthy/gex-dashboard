"""Gamma exposure dashboard. Run locally with:  streamlit run app.py"""
import time
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
.block-container {padding-top: 3.5rem;}
.cards {display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:14px; margin:8px 0 18px;}
.card {background:#161b22; border:1px solid #2a313c; border-radius:8px; padding:16px 20px;}
.card .lbl {color:#9aa4b2; font-size:0.85rem; letter-spacing:0.02em;}
.card .val {color:#e8edf3; font-size:1.7rem; font-weight:600; margin:4px 0; font-variant-numeric:tabular-nums;}
.card.pos {border-color:#3fb950;} .card.neg {border-color:#f85149;} .card.mix {border-color:#d29922;}
.card .sub {color:#9aa4b2; font-size:0.85rem; line-height:1.4;}
.note {color:#9aa4b2; font-size:0.85rem; background:#161b22; border:1px solid #2a313c;
       border-radius:8px; padding:10px 14px;}
.kgrid {display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:18px 28px;}
.ktitle {color:#9aa4b2; font-size:0.85rem; margin-bottom:6px;}
.ktable {width:100%; border-collapse:collapse; font-variant-numeric:tabular-nums; font-size:0.92rem;}
.ktable td {padding:7px 6px; border-top:1px solid #2a313c; color:#e8edf3; white-space:nowrap;}
.ktable tr:first-child td {border-top:none;}
.ktable td.num {text-align:right;}
.dim {color:#8b949e;}
.kblock {background:#161b22; border:1px solid #2a313c; border-radius:8px; padding:12px 16px;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def card(label, value, sub="", color=None, cls=""):
    style = f' style="color:{color}"' if color else ""
    return f'<div class="card {cls}"><div class="lbl">{label}</div><div class="val"{style}>{value}</div><div class="sub">{sub}</div></div>'


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
    st.divider()
    auto = st.toggle("Auto-refresh", value=False, help="Reloads fresh data on a timer while the page is open.")
    every = st.radio("Every", ["1 min", "2 min", "5 min"], index=1, horizontal=True, disabled=not auto)
    st.caption(f"Last updated {datetime.now(gex.ET):%I:%M:%S %p} ET")

cfg = PRODUCTS[product]

# ---------------------------------------------------------------- auto-refresh
st.session_state["last_run"] = time.time()
interval = {"1 min": 60, "2 min": 120, "5 min": 300}[every] if auto else None


@st.fragment(run_every=interval)
def auto_refresher():
    # Runs quietly on the timer; once enough time has passed, pull fresh data and redraw the whole page.
    if interval and time.time() - st.session_state.get("last_run", 0) >= interval - 2:
        load_chain.clear()
        load_future.clear()
        st.rerun()


auto_refresher()

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
next_session = WINDOWS[window] == 0 and not df.empty and df["expiry"].min() > datetime.now(gex.ET).date()
if next_session:
    st.info(f"Today's 0DTE options have expired, so this shows the next session's expiry "
            f"({df['expiry'].min():%a %m/%d}). Volume is light until it opens, so open-interest weighting "
            "(sidebar) is usually more meaningful right now.")
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

net_main = net_g_vol if weight == "volume" else net_g_oi
net_pos = net_main > 0
above_flip = None if flip_main is None else spot > flip_main
if above_flip is None or above_flip == net_pos:
    regime, r_color, r_cls = ("Positive", "#3fb950", "pos") if net_pos else ("Negative", "#f85149", "neg")
    r_hint = "expect tighter, mean-reverting ranges" if net_pos else "expect wider, trending moves"
else:
    regime, r_color, r_cls = "Mixed", "#d29922", "mix"
    r_hint = "net gamma and flip disagree"
r_sub = (f"net gamma {gex.fmt_big(net_main)} · spot {'above' if above_flip else 'below'} flip · " if above_flip is not None
         else f"net gamma {gex.fmt_big(net_main)} · ") + r_hint + " (dealer sign assumed)"

st.caption(f"{cfg['chain'].strip('_')} chain · CBOE delayed data · {stamp} · {len(df):,} options in window · levels in {unit}")

html = '<div class="cards">' + "".join([
    card("Futures spot", fmt(f_spot), f"underlying {spot:,.2f}" + (f" · ratio {ratio:.3f}" if cfg["mode"] == "ratio" else f" · basis {add:+.1f}")),
    card("Gamma flip", fmt(to_fut(flip_main)), flip_sub),
    card(f"Poles ({'volume' if weight == 'volume' else 'OI'})", f"{fmt(to_fut(pole_neg))} / {fmt(to_fut(pole_pos))}", "largest negative / positive gamma strikes"),
    card("Expected move", em_val, em_sub),
    card("ATM IV", iv_val, iv_sub),
    card("Call / put volume", f"{gex.fmt_big(cv)} / {gex.fmt_big(pv)}", f"put/call {pv / cv:.2f} · OI {gex.fmt_big(coi)} / {gex.fmt_big(poi)}" if cv else ""),
    card("Net gamma × volume", gex.fmt_big(net_g_vol), f"× OI {gex.fmt_big(net_g_oi)} · net delta × volume {gex.fmt_big(net_d_vol)}"),
    card("Gamma regime", regime, r_sub, r_color, r_cls),
]) + "</div>"
st.markdown(html, unsafe_allow_html=True)

# ---------------------------------------------------------------- charts
lo_k, hi_k = spot * (1 - chart_range / 100), spot * (1 + chart_range / 100)
table = gex.strike_table(df, spot)
view = table[(table["strike"] >= lo_k) & (table["strike"] <= hi_k)]


def vline(fig, x, text, color, side="right"):
    if x is not None:
        fig.add_vline(x=to_fut(x), line_dash="dot", line_color=color,
                      annotation_text=text, annotation_position=f"top {side}",
                      annotation_font_color=color)


def hline(fig, y, text, color, dash="dot"):
    if y is not None:
        fig.add_hline(y=to_fut(y), line_dash=dash, line_color=color, line_width=1,
                      annotation_text=text, annotation_position="right",
                      annotation_font_color=color, annotation_font_size=11)


GREEN, RED = "#3fb950", "#f85149"
left, right = st.columns([1, 1.15])

with left:
    st.markdown("#### Strike profile")
    mode = st.segmented_control(
        "View", ["Gamma volume", "Delta volume", "Dealer position", "Open interest"],
        default="Gamma volume", label_visibility="collapsed",
    ) or "Gamma volume"
    y = view["strike"] * ratio + add
    fig = go.Figure()
    if mode == "Open interest":
        fig.add_bar(y=y, x=view["call_oi"], orientation="h", name="calls", marker_color=GREEN,
                    hovertemplate="%{y:,.0f}<br>call OI %{x:,.0f}<extra></extra>")
        fig.add_bar(y=y, x=-view["put_oi"], orientation="h", name="puts", marker_color=RED,
                    customdata=view["put_oi"], hovertemplate="%{y:,.0f}<br>put OI %{customdata:,.0f}<extra></extra>")
        fig.update_layout(barmode="relative")
        xlab, note = "contracts", "Open interest per strike. Right/green = calls, left/red = puts."
    else:
        col, xlab, note = {
            "Gamma volume": ("gex_vol", "$ gamma per 1% move",
                             "Gamma × volume per strike. Right/green = positive, left/red = negative."),
            "Delta volume": ("delta_vol", "$ delta",
                             "Assumed dealer delta × volume per strike."),
            "Dealer position": ("dealer_pos", "contracts",
                                "Assumed dealer contracts per strike (call OI minus put OI)."),
        }[mode]
        vals = view[col]
        fig.add_bar(y=y, x=vals, orientation="h", marker_color=np.where(vals >= 0, GREEN, RED),
                    hovertemplate="%{y:,.0f}<br>%{x:,.3s}<extra></extra>")
    hline(fig, spot, f"spot {fmt(f_spot)}", "#c9d1d9", "solid")
    hline(fig, flip_main, f"flip {fmt(to_fut(flip_main))}", "#d29922", "dash")
    if atm:
        hline(fig, spot + atm["move_1sd"], f"EM ↑ {fmt(hi)}", "#58a6ff")
        hline(fig, spot - atm["move_1sd"], f"EM ↓ {fmt(lo)}", "#58a6ff")
    fig.update_layout(template="plotly_dark", height=560, showlegend=False, bargap=0.15,
                      margin=dict(l=10, r=110, t=10, b=10), xaxis_title=xlab, dragmode="pan")
    fig.update_yaxes(tickformat=",.0f")
    st.plotly_chart(fig, width="stretch", config={"scrollZoom": True})
    st.caption(note + " Lines: spot, gamma flip, expected move. Scroll to zoom, drag to pan, double-click to reset.")


def rows_html(frame, kind):
    out = []
    for _, r in frame.iterrows():
        k = f'{r["strike"]:,g}'
        if kind == "vol":
            right_txt = f'{gex.fmt_big(r["volume"])} <span class="dim">({gex.fmt_big(r["call_vol"])}c / {gex.fmt_big(r["put_vol"])}p)</span>'
        elif kind == "oi":
            right_txt = f'{gex.fmt_big(r["oi"])} <span class="dim">({gex.fmt_big(r["call_oi"])}c / {gex.fmt_big(r["put_oi"])}p)</span>'
        else:
            right_txt = gex.fmt_big(r["gex_vol"])
        out.append(f'<tr><td>{k}</td><td class="dim">≈ {fmt(to_fut(r["strike"]))}</td><td class="num">{right_txt}</td></tr>')
    return "".join(out)


def block(title, frame, kind):
    return f'<div class="kblock"><div class="ktitle">{title}</div><table class="ktable">{rows_html(frame, kind)}</table></div>'


with right:
    st.markdown("#### Key strikes")
    pos_g = table[table["gex_vol"] > 0].nlargest(5, "gex_vol")
    neg_g = table[table["gex_vol"] < 0].nsmallest(5, "gex_vol")
    st.markdown(
        '<div class="kgrid">'
        + block("Most volume", table.nlargest(6, "volume"), "vol")
        + block("Most open interest", table.nlargest(6, "oi"), "oi")
        + block("Largest + gamma × volume", pos_g, "gex")
        + block("Largest − gamma × volume", neg_g, "gex")
        + "</div>",
        unsafe_allow_html=True,
    )

mask = (grid >= lo_k) & (grid <= hi_k)
fig2 = go.Figure(go.Scatter(x=grid[mask] * ratio + add, y=totals[mask], line=dict(color="#58a6ff", width=2)))
fig2.add_hline(y=0, line_color="#6e7681")
vline(fig2, spot, "spot", "#8b949e", "right" if flip_main is None or spot >= flip_main else "left")
vline(fig2, flip_main, "flip", "#d29922", "left" if flip_main is None or spot >= flip_main else "right")
fig2.update_layout(title="Total net gamma if spot moved here", template="plotly_dark", height=420,
                   margin=dict(l=10, r=10, t=50, b=10), xaxis_title=unit, yaxis_title="$ per 1% move")
st.plotly_chart(fig2, width="stretch")

# ---------------------------------------------------------------- TradingView export
st.markdown("#### TradingView levels")
tv_units = st.radio(
    "Your TradingView chart is", ["Futures (NQ1! / ES1!)", "Underlying (QQQ / SPX)"],
    horizontal=True,
)
use_fut = tv_units.startswith("Futures") and fut is not None
conv = (lambda x: to_fut(x)) if use_fut else (lambda x: x)


def num(x):
    return f"{x:.2f}".rstrip("0").rstrip(".")


gcol = "gex_vol" if weight == "volume" else "gex_oi"
max_abs = table[gcol].abs().max() or 1
lv = [f"ASOF,{cfg['chain'].strip('_')} {window} · {stamp}", f"TAG,{window} ({df['expiry'].min():%m/%d})"]
if flip_main is not None:
    lv.append(f"HVL,{num(conv(flip_main))}")
for i, (_, r) in enumerate(table[table[gcol] > 0.03 * max_abs].nlargest(7, gcol).iterrows(), 1):
    lv.append(f"C{i},{num(conv(r['strike']))},{r[gcol] / max_abs:.2f}")
for i, (_, r) in enumerate(table[table[gcol] < -0.03 * max_abs].nsmallest(5, gcol).iterrows(), 1):
    lv.append(f"P{i},{num(conv(r['strike']))},{r[gcol] / max_abs:.2f}")
if atm:
    lv.append(f"EM+,{num(conv(spot + atm['move_1sd']))}")
    lv.append(f"EM-,{num(conv(spot - atm['move_1sd']))}")
st.code(";".join(lv), language=None, wrap_lines=True)
st.caption("Click the copy icon on the box, then paste it into the GEX Levels indicator's settings in TradingView. "
           "Levels follow the product, expiry window and weighting selected above. Re-copy whenever you want fresh levels.")

st.markdown(
    '<div class="note">The dealer sign is assumed (dealers long calls, short puts), which real positioning often contradicts. '
    "Data is ~15 minutes delayed. Treat this as a map, not a trading signal.</div>",
    unsafe_allow_html=True,
)
