"""Day map page: session levels and statistical day targets for NQ / ES futures."""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import daymap
import gex
import theme

TH = theme.apply()
PRODUCTS = {  # ticker, kind, decimals, chart gaps to hide (hours)
    "NQ": {"ticker": "NQ=F", "kind": "futures", "dp": 0, "gap": [17, 18]},
    "ES": {"ticker": "ES=F", "kind": "futures", "dp": 0, "gap": [17, 18]},
    "QQQ": {"ticker": "QQQ", "kind": "etf", "dp": 2, "gap": [20, 4]},
    "SPY": {"ticker": "SPY", "kind": "etf", "dp": 2, "gap": [20, 4]},
    "SPX": {"ticker": "^GSPC", "kind": "index", "dp": 0, "gap": [16, 9.5]},
}
GREEN, RED, GOLD, GRAY, BLUE = "#3fb950", "#f85149", "#d29922", "#8b949e", "#58a6ff"
LEVEL_STYLE = {  # name prefix -> (colour, dash, width)
    "PIVOT": (GOLD, "dash", 2),
    "UT1": (GREEN, "solid", 2), "UT2": (GREEN, "solid", 1), "FUT": (GREEN, "dot", 1),
    "DT1": (RED, "solid", 2), "DT2": (RED, "solid", 1), "FDT": (RED, "dot", 1),
    "PDH": (GRAY, "dot", 1), "PDL": (GRAY, "dot", 1), "PDC": (GRAY, "dash", 1),
    "PVWAP": ("#a371f7", "dash", 2), "PMID": ("#79c0ff", "dashdot", 1),
    "ONH": (BLUE, "dot", 1), "ONL": (BLUE, "dot", 1), "GBX": (GRAY, "dashdot", 1),
}


@st.cache_data(ttl=90, show_spinner="Loading price bars…")
def load_bars(ticker, prepost):
    try:
        import yfinance as yf

        h = yf.Ticker(ticker).history(period="59d", interval="5m", prepost=prepost)
        if h is None or h.empty:
            return None
        h.index = h.index.tz_convert(gex.ET)
        return gex.clean_candles(h)
    except Exception:
        return None


# ---------------------------------------------------------------- controls
c1, c2, c3 = st.columns([1.6, 2.4, 1])
sym = c1.segmented_control("Product", list(PRODUCTS), default="NQ", label_visibility="collapsed") or "NQ"
P = PRODUCTS[sym]
KIND, DP = P["kind"], P["dp"]
pre_label = {"futures": "Overnight", "etf": "Premarket", "index": None}[KIND]


def amt(x, signed=False):
    """Move sizes: points for futures/SPX, dollars for QQQ/SPY."""
    sign = ("+" if x >= 0 else "−") if signed else ""
    return f"{sign}${abs(x):,.2f}" if KIND == "etf" else f"{sign}{abs(x):,.{DP}f} pts"

with st.sidebar:
    vwap_choice = st.selectbox(
        "Prior day VWAP", ["From 6 pm, at 4:00 close", "From 6 pm, at 5:00 close", "Regular hours (9:30–4:00)"],
        help="'From 6 pm' matches TradingView's standard session VWAP on NQ1! / ES1!. "
             "QQQ and SPY always use the regular-hours VWAP; SPX has no volume, so no VWAP.",
        disabled=KIND != "futures",
    )
VWAP_MODE = {"From 6 pm, at 4:00 close": "1600", "From 6 pm, at 5:00 close": "1700",
             "Regular hours (9:30–4:00)": "rth"}[vwap_choice]

view = c2.segmented_control(
    "View", ["Yesterday → today"] + ([f"{pre_label} → today"] if pre_label else []) + ["Last 2h"],
    default="Yesterday → today", label_visibility="collapsed",
) or "Yesterday → today"
if c3.button("Refresh data", width="stretch"):
    load_bars.clear()

h = load_bars(P["ticker"], KIND == "etf")
if h is None or len(h) < 300:
    st.error(f"Couldn't load {sym} bars from Yahoo right now. Press Refresh data in a minute.")
    st.stop()

now = datetime.now(gex.ET)
m = daymap.build_map(h, now, VWAP_MODE, KIND)
st_ = m["stats"]
day = pd.Timestamp(m["day"])
status = ("SESSION CLOSED" if m["rth_done"] else "LIVE SESSION" if m["rth_started"]
          else "TOMORROW · OVERNIGHT" if day.date() > now.date() else "PRE-MARKET")

st.markdown(
    f'<div style="display:flex;align-items:baseline;gap:14px;margin:6px 0 4px">'
    f'<span style="font-size:2rem;font-weight:700;color:{TH["fg"]}">{sym} · {day:%a %m/%d}</span>'
    f'<span style="font-size:0.8rem;padding:2px 8px;border:1px solid {TH["border"]};border-radius:4px;'
    f'color:{TH["muted"]};letter-spacing:.05em">{status}</span></div>',
    unsafe_allow_html=True,
)
st.caption(f"Yahoo 5-min bars (delayed) · last bar {h.index[-1]:%a %I:%M %p} ET"
           + (" · includes premarket and after-hours" if KIND == "etf" else ""))

# ---------------------------------------------------------------- summary + cards
lines = daymap.bluf(m, fmt=amt)
if lines:
    st.markdown(
        f'<div class="card" style="margin-bottom:14px"><div class="lbl" style="font-weight:700;'
        f'letter-spacing:.1em">SUMMARY</div><div style="color:{TH["fg"]};line-height:1.7;margin-top:4px">'
        + "<br>".join(lines) + "</div></div>",
        unsafe_allow_html=True,
    )


def card(label, value, sub="", color=None):
    style = f' style="color:{color}"' if color else ""
    return f'<div class="card"><div class="lbl">{label}</div><div class="val"{style}>{value}</div><div class="sub">{sub}</div></div>'


cur, prev, last = m["cur"], m["prev"], m["last"]
cards = []
if prev is not None:
    chg = last - prev["c"]
    cards.append(card("Last", f"{last:,.2f}", f"{chg:+,.2f} ({chg / prev['c'] * 100:+.2f}%) vs yesterday's close",
                      GREEN if chg >= 0 else RED))
else:
    cards.append(card("Last", f"{last:,.2f}"))
if not np.isnan(cur["onh"]):
    onr = cur["onh"] - cur["onl"]
    pos = (last - cur["onl"]) / onr if onr else 0.5
    where = ("above the overnight high" if pos > 1 else "below the overnight low" if pos < 0 else
             "now in the top third" if pos > 2 / 3 else "now in the bottom third" if pos < 1 / 3
             else "now in the middle third")
    where = where.replace("overnight", pre_label.lower())
    cards.append(card(pre_label, amt(onr), f"{onr / last * 100:.2f}% · {where}"))
cards.append(card(
    ("9:30 open" if KIND == "index" else "9:29 lock") if m["locked"] else "Pivot (provisional)", f"{m['anchor']:,.2f}",
    "anchor for today's targets" if m["locked"] else
    ("locks at the 9:30 open" if KIND == "index" else "follows price until 9:29 ET, then locks"),
    GOLD,
))
if st_:
    a = m["anchor"]
    cards.append(card("A normal day", amt(st_["range_med"] * a),
                      f"high usually {amt(st_['up']['lo'] * a, True)} to {amt(st_['up']['hi'] * a, True)} · "
                      f"low usually {amt(-st_['dn']['lo'] * a, True)} to {amt(-st_['dn']['hi'] * a, True)}"))
    cards.append(card("Based on", f"{st_['n']} sessions", "last ~60 days of regular-hours trading"))
st.markdown('<div class="cards">' + "".join(cards) + "</div>", unsafe_allow_html=True)

# ---------------------------------------------------------------- chart
tagged = daymap.tag_sessions(h, KIND)
if pre_label and view == f"{pre_label} → today":
    cd = h[tagged["tday"] == m["day"]]
elif view == "Last 2h":
    cd = h[h.index >= h.index[-1] - timedelta(hours=2)]
else:  # yesterday's regular session through now
    start = (pd.Timestamp(prev.name).tz_localize(gex.ET) + timedelta(hours=9, minutes=30)
             if prev is not None else h.index[-1] - timedelta(days=1))
    cd = h[h.index >= start]
if cd.empty:
    cd = h.tail(150)

fig = go.Figure(go.Candlestick(
    x=cd.index, open=cd["Open"], high=cd["High"], low=cd["Low"], close=cd["Close"],
    increasing_line_color=GREEN, decreasing_line_color=RED, name=sym,
))
lv = {name: px for name, px, _ in m["levels"]}
if st_:  # shaded "usual" zones for the day's high and low
    a = m["anchor"]
    fig.add_hrect(y0=a * (1 + st_["up"]["lo"]), y1=a * (1 + st_["up"]["hi"]), fillcolor=GREEN,
                  opacity=0.10, line_width=0)
    fig.add_hrect(y0=a * (1 - st_["dn"]["hi"]), y1=a * (1 - st_["dn"]["lo"]), fillcolor=RED,
                  opacity=0.10, line_width=0)
y_lo, y_hi = float(cd["Low"].min()), float(cd["High"].max())
for name, px, _ in m["levels"]:
    if name not in LEVEL_STYLE:
        continue
    color, dash, width = LEVEL_STYLE[name]
    fig.add_hline(y=px, line_color=color, line_dash=dash, line_width=width,
                  annotation_text=f"{name} {px:,.2f}", annotation_position="right",
                  annotation_font_color=color, annotation_font_size=11)
    if abs(px - last) <= last * 0.02:
        y_lo, y_hi = min(y_lo, px), max(y_hi, px)
for ts, text in [(pd.Timestamp(m["day"]).tz_localize(gex.ET) + timedelta(hours=9, minutes=30), "9:30 bell")]:
    if cd.index[0] <= ts:
        fig.add_shape(type="line", x0=ts, x1=ts, y0=0, y1=1, yref="paper",
                      line=dict(color=TH["dim"], width=1, dash="dot"))
        fig.add_annotation(x=ts, y=1, yref="paper", text=text, showarrow=False,
                           font=dict(color=TH["dim"], size=11), yanchor="bottom")
pad = (y_hi - y_lo) * 0.05 or 1
theme.style(fig, TH, height=620, showlegend=False, dragmode="pan", xaxis_rangeslider_visible=False,
            margin=dict(l=10, r=150, t=20, b=10))
fig.update_xaxes(rangebreaks=[dict(bounds=P["gap"], pattern="hour"), dict(bounds=["sat", "mon"] if KIND != "futures" else ["sat", "sun"])])
fig.update_yaxes(range=[y_lo - pad, y_hi + pad], tickformat=f",.{DP}f")
st.plotly_chart(fig, width="stretch", config={"scrollZoom": True}, theme=None)
if st_:
    st.caption("Shaded zones: where the day's high (green) and low (red) usually land, the middle half of the last "
               f"{st_['n']} sessions. Scroll to zoom, drag to pan, double-click to reset.")

# ---------------------------------------------------------------- the map table
st.markdown("#### The map")
rows = "".join(
    f'<tr><td style="color:{LEVEL_STYLE.get(n, (TH["fg"],))[0]};font-weight:600">{n}</td>'
    f'<td class="dim">{desc}</td><td class="num">{px:,.2f}</td>'
    f'<td class="num" style="color:{GREEN if px >= last else RED}">{px - last:+,.2f}</td>'
    f'<td class="num dim">{(px - last) / last * 100:+.2f}%</td></tr>'
    for n, px, desc in sorted(m["levels"], key=lambda r: -r[1])
)
head = ('<tr><td class="dim">Level</td><td class="dim"></td><td class="num dim">Price</td>'
        '<td class="num dim">Away</td><td class="num dim"></td></tr>')
st.markdown(f'<div class="kblock"><table class="ktable">{head}{rows}</table></div>', unsafe_allow_html=True)

# ---------------------------------------------------------------- TradingView export
st.markdown("#### TradingView day map")
tv = [f"ASOF,{sym} day map · {day:%Y-%m-%d}"] + [
    f"{n},{px:.2f}" for n, px, _ in m["levels"] if n in LEVEL_STYLE
]
st.code(";".join(tv), language=None, wrap_lines=True)
st.caption(f"Paste into the Day Map indicator's **Day map levels** box on a **{sym}** chart "
           + ("(NQ1! / ES1!)." if KIND == "futures" else "(SPX on TradingView is SP:SPX)." if KIND == "index" else "."))

st.markdown(
    '<div class="note">UT/DT targets are statistics from recent history: UT1/DT1 = a median day, UT2/DT2 = a big day '
    "(75th percentile), FUT/FDT = an extreme day (90th percentile), measured from the 9:29 price. "
    "They describe how far price usually travels, not where it will go. Not trading advice.</div>",
    unsafe_allow_html=True,
)
