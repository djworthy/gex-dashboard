"""Data fetching and gamma-exposure math for the dashboard."""
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from scipy.stats import norm

ET = ZoneInfo("America/New_York")
CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
OCC_RE = r"^([A-Z]+)(\d{6})([CP])(\d{8})$"
YEAR_SECONDS = 365 * 24 * 3600
MIN_T = 15 * 60 / YEAR_SECONDS  # never let time-to-expiry fall below 15 minutes
RATE = 0.04


# ---------------------------------------------------------------- data
def fetch_cboe_chain(symbol: str):
    """Download CBOE's free (~15 min delayed) option chain.
    Returns (options DataFrame, underlying price, timestamp string)."""
    r = requests.get(
        CBOE_URL.format(sym=symbol),
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    r.raise_for_status()
    payload = r.json()
    data = payload["data"]
    spot = float(data.get("current_price") or data.get("close"))
    df = pd.DataFrame(data["options"])

    parts = df["option"].str.extract(OCC_RE)
    df["root"] = parts[0]
    df["expiry"] = pd.to_datetime(parts[1], format="%y%m%d", errors="coerce").dt.date
    df["type"] = parts[2]
    df["strike"] = pd.to_numeric(parts[3], errors="coerce") / 1000

    for col in ["bid", "ask", "iv", "open_interest", "volume", "delta", "gamma"]:
        df[col] = pd.to_numeric(df.get(col, 0), errors="coerce").fillna(0)

    df = df.dropna(subset=["expiry", "strike", "type"])
    prev = data.get("prev_day_close")
    prev = float(prev) if prev not in (None, "", 0) else None
    return df, spot, payload.get("timestamp", ""), prev


def fetch_futures_price(ticker: str):
    """Delayed futures price from Yahoo (NQ=F / ES=F). Returns None on failure."""
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(period="2d", interval="1m")
        if len(hist):
            return float(hist["Close"].dropna().iloc[-1])
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- prep
def prepare(df: pd.DataFrame, window_days, now=None):
    """Keep live, quoted options inside the selected expiry window and add T (years)."""
    now = now or datetime.now(ET)
    today = now.date()
    out = df[df["iv"] > 0].copy()

    expiry_dt = pd.to_datetime(out["expiry"].astype(str)) + pd.Timedelta(hours=16)
    expiry_dt = expiry_dt.dt.tz_localize(ET)
    secs = (expiry_dt - now).dt.total_seconds()
    out["T"] = np.maximum(secs / YEAR_SECONDS, MIN_T)
    out = out[secs > 0]  # drop anything already expired

    if window_days == 0:
        # nearest live expiry: today's during the session, the next one after the close
        if not out.empty:
            out = out[out["expiry"] == out["expiry"].min()]
    elif window_days is not None:
        out = out[out["expiry"] <= today + timedelta(days=window_days)]
    return out


# ---------------------------------------------------------------- greeks
def _d1(S, K, T, iv):
    return (np.log(S / K) + (RATE + iv**2 / 2) * T) / (iv * np.sqrt(T))


def bs_gamma(S, K, T, iv):
    return norm.pdf(_d1(S, K, T, iv)) / (S * iv * np.sqrt(T))


def bs_delta(S, K, T, iv, is_call):
    nd = norm.cdf(_d1(S, K, T, iv))
    return np.where(is_call, nd, nd - 1)


def dealer_sign(df):
    # The big assumption: dealers long calls (+), short puts (-).
    return np.where(df["type"] == "C", 1.0, -1.0)


def weights(df, weight):
    return df["volume"].values if weight == "volume" else df["open_interest"].values


def gex_per_option(df, S, weight="volume"):
    """Signed dollar gamma per 1% move for each option row."""
    g = bs_gamma(S, df["strike"].values, df["T"].values, df["iv"].values)
    return dealer_sign(df) * g * weights(df, weight) * 100 * S**2 * 0.01


def net_delta(df, S, weight="volume"):
    d = bs_delta(S, df["strike"].values, df["T"].values, df["iv"].values, df["type"].values == "C")
    return float(np.sum(dealer_sign(df) * d * weights(df, weight) * 100 * S))


def gamma_profile(df, S, weight="volume", pct=0.05, n=241):
    """Total net gamma recomputed at a grid of hypothetical spot prices."""
    grid = np.linspace(S * (1 - pct), S * (1 + pct), n)
    K, T, iv = df["strike"].values, df["T"].values, df["iv"].values
    sw = dealer_sign(df) * weights(df, weight)
    g = bs_gamma(grid[:, None], K[None, :], T[None, :], iv[None, :])
    totals = (g * sw[None, :]).sum(axis=1) * 100 * grid**2 * 0.01
    return grid, totals


def gamma_flip(grid, totals, S):
    """Spot level where total net gamma crosses zero (closest crossing to spot)."""
    idx = np.where(np.diff(np.sign(totals)) != 0)[0]
    if len(idx) == 0:
        return None
    flips = []
    for i in idx:  # linear interpolation between grid points
        x0, x1, y0, y1 = grid[i], grid[i + 1], totals[i], totals[i + 1]
        flips.append(x0 - y0 * (x1 - x0) / (y1 - y0))
    flips = np.array(flips)
    return float(flips[np.argmin(np.abs(flips - S))])


def by_strike(df, S, weight="volume"):
    return (
        df.assign(gex=gex_per_option(df, S, weight))
        .groupby("strike", as_index=False)["gex"].sum()
    )


def poles(strikes_df):
    if strikes_df.empty:
        return None, None
    neg = strikes_df.loc[strikes_df["gex"].idxmin()]
    pos = strikes_df.loc[strikes_df["gex"].idxmax()]
    return float(neg["strike"]), float(pos["strike"])


def atm_stats(df, S):
    """ATM IV, 1-sigma move, and straddle price from the nearest quoted expiry."""
    if df.empty:
        return None
    nearest = df[df["expiry"] == df["expiry"].min()]
    k = nearest.loc[(nearest["strike"] - S).abs().idxmin(), "strike"]
    atm = nearest[nearest["strike"] == k]
    iv = float(atm["iv"].mean())
    T = float(atm["T"].iloc[0])
    mids = (atm["bid"] + atm["ask"]) / 2
    return {
        "iv": iv,
        "expiry": nearest["expiry"].iloc[0],
        "move_1sd": S * iv * np.sqrt(T),
        "straddle": float(mids.sum()) if len(atm) == 2 else None,
    }


def fmt_big(x):
    if x is None:
        return "—"
    a = abs(x)
    for div, suf, dp in [(1e12, "T", 2), (1e9, "B", 2), (1e6, "M", 1), (1e3, "k", 1)]:
        if a >= div:
            return f"{x / div:.{dp}f}{suf}"
    return f"{x:.0f}"


def strike_table(df, S):
    """One row per strike with volume, OI, gamma and delta exposure."""
    is_call = df["type"].values == "C"
    d = bs_delta(S, df["strike"].values, df["T"].values, df["iv"].values, is_call)
    t = df.assign(
        call_vol=np.where(is_call, df["volume"], 0),
        put_vol=np.where(is_call, 0, df["volume"]),
        call_oi=np.where(is_call, df["open_interest"], 0),
        put_oi=np.where(is_call, 0, df["open_interest"]),
        gex_vol=gex_per_option(df, S, "volume"),
        gex_oi=gex_per_option(df, S, "oi"),
        delta_vol=dealer_sign(df) * d * df["volume"].values * 100 * S,
    )
    cols = ["call_vol", "put_vol", "call_oi", "put_oi", "gex_vol", "gex_oi", "delta_vol"]
    out = t.groupby("strike", as_index=False)[cols].sum()
    out["volume"] = out["call_vol"] + out["put_vol"]
    out["oi"] = out["call_oi"] + out["put_oi"]
    out["dealer_pos"] = out["call_oi"] - out["put_oi"]  # assumed: long calls, short puts
    return out


def market_open(now=None):
    now = now or datetime.now(ET)
    return now.weekday() < 5 and time(9, 30) <= now.time() < time(16, 0)


def daily_expected_move(df_all, S, prev_close=None, now=None):
    """Full-session 1-sigma move from the next day's ATM IV.
    Anchored on yesterday's close during market hours, otherwise on the latest price."""
    now = now or datetime.now(ET)
    nxt = df_all[df_all["expiry"] > now.date()]
    if nxt.empty:
        return None
    nearest = nxt[nxt["expiry"] == nxt["expiry"].min()]
    k = nearest.loc[(nearest["strike"] - S).abs().idxmin(), "strike"]
    iv = float(nearest.loc[nearest["strike"] == k, "iv"].mean())
    anchor = prev_close if (market_open(now) and prev_close) else S
    move = anchor * iv * np.sqrt(1 / 252)
    return {"anchor": anchor, "iv": iv, "move": move, "anchored_on": "prior close" if anchor != S else "last price"}


def clean_candles(h, k=6.0):
    """Repair obviously bad bars from free data feeds (e.g. a last bar whose open is
    hundreds of points away from the previous close). Real session-open gaps are kept."""
    h = h.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    h = h[(h[["Open", "High", "Low", "Close"]] > 0).all(axis=1)]
    if len(h) < 5:
        return h
    rng = (h["High"] - h["Low"]).abs()
    typical = rng.rolling(50, min_periods=5).median().bfill().fillna(rng.median())
    tol = k * typical.clip(lower=rng[rng > 0].median() if (rng > 0).any() else 1.0)

    prev_close = h["Close"].shift(1)
    step = h.index.to_series().diff()
    normal_step = step.median()
    after_gap = step > normal_step * 1.5          # first bar after a pause: real gaps allowed
    bad_open = ((h["Open"] - prev_close).abs() > tol) & ~after_gap & prev_close.notna()
    h.loc[bad_open, "Open"] = prev_close[bad_open]

    body_hi = h[["Open", "Close"]].max(axis=1)
    body_lo = h[["Open", "Close"]].min(axis=1)
    h["High"] = np.maximum(np.minimum(h["High"], body_hi + tol), body_hi)
    h["Low"] = np.minimum(np.maximum(h["Low"], body_lo - tol), body_lo)
    return h
