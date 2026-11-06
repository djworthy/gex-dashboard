"""Session levels and statistical day targets for NQ / ES futures (5-minute bars, ET)."""
from datetime import time

import numpy as np
import pandas as pd

RTH_OPEN, RTH_CLOSE, GLOBEX_OPEN = time(9, 30), time(16, 0), time(18, 0)
PREMARKET_OPEN = time(4, 0)
# kind: "futures" (overnight from 6 pm), "etf" (premarket from 4 am), "index" (regular hours only)
PCTS = {"1": 50, "2": 75, "F": 90}  # UT1/DT1 = median day, UT2/DT2 = big day, FUT/FDT = extreme day


def tag_sessions(h, kind="futures"):
    """Label every bar with its trading day and part (rth / on = overnight or premarket)."""
    df = h.copy()
    idx = df.index
    t = pd.Series(idx.time, index=idx)
    df["rth"] = ((t >= RTH_OPEN) & (t < RTH_CLOSE)).values
    if kind == "futures":  # bars from 18:00 belong to the next trading day
        shift = pd.to_timedelta((idx.hour >= 18).astype(int), unit="D")
        df["tday"] = (idx.normalize() + shift).date
        df["on"] = ((t >= GLOBEX_OPEN) | (t < RTH_OPEN)).values
    else:
        df["tday"] = idx.normalize().date
        df["on"] = (((t >= PREMARKET_OPEN) & (t < RTH_OPEN)).values if kind == "etf"
                    else np.zeros(len(df), dtype=bool))
    return df


def sessions(h, kind="futures"):
    """One row per trading day: overnight/premarket + RTH OHLC and the 9:29 lock price."""
    df = tag_sessions(h, kind)
    rows = []
    has_vol = "Volume" in df.columns

    def vwap(frame):
        if not has_vol or frame.empty or frame["Volume"].sum() <= 0:
            return np.nan
        typical = (frame["High"] + frame["Low"] + frame["Close"]) / 3
        return float((typical * frame["Volume"]).sum() / frame["Volume"].sum())

    for d, g in df.groupby("tday", sort=True):
        on, rth = g[g["on"]], g[g["rth"]]
        t = pd.Series(g.index.time, index=g.index)
        after_close = ((t >= RTH_CLOSE) & (t < GLOBEX_OPEN)).values  # 4:00-5:00 pm
        lock = on["Close"].iloc[-1] if len(on) and on.index[-1].time() < RTH_OPEN else np.nan
        if np.isnan(lock) and len(rth):  # no trading before the bell (index): use the 9:30 open
            lock = rth["Open"].iloc[0]
        rows.append({
            "tday": d,
            "gbx": on["Open"].iloc[0] if len(on) else np.nan,
            "onh": on["High"].max() if len(on) else np.nan,
            "onl": on["Low"].min() if len(on) else np.nan,
            "lock": lock,
            "o": rth["Open"].iloc[0] if len(rth) else np.nan,
            "h": rth["High"].max() if len(rth) else np.nan,
            "l": rth["Low"].min() if len(rth) else np.nan,
            "c": rth["Close"].iloc[-1] if len(rth) else np.nan,
            "vwap_1600": vwap(g[~after_close]),  # anchored 6:00 pm, read at the 4:00 pm close
            "vwap_1700": vwap(g),                # anchored 6:00 pm, read at the 5:00 pm session end
            "vwap_rth": vwap(rth),               # regular hours only, 9:30-4:00
            "rth_bars": len(rth),
            "rth_last": rth.index[-1] if len(rth) else None,
        })
    return pd.DataFrame(rows).set_index("tday")


def stats(sess, min_bars=60):
    """Distribution of how far the RTH session travelled from the 9:29 lock (as % of the lock)."""
    full = sess[(sess["rth_bars"] >= min_bars) & sess["lock"].notna()]
    if len(full) < 10:
        return None
    up = (full["h"] - full["lock"]) / full["lock"]
    dn = (full["lock"] - full["l"]) / full["lock"]
    rng = (full["h"] - full["l"]) / full["lock"]
    onr = (full["onh"] - full["onl"]) / full["lock"]
    q = lambda s, p: float(np.percentile(s, p))
    return {
        "n": len(full),
        "up": {k: q(up, p) for k, p in PCTS.items()} | {"lo": q(up, 25), "hi": q(up, 75)},
        "dn": {k: q(dn, p) for k, p in PCTS.items()} | {"lo": q(dn, 25), "hi": q(dn, 75)},
        "range_med": q(rng, 50),
        "on_ranges": onr.values,
    }


VWAP_MODES = {
    "1600": ("vwap_1600", "VWAP from 6:00 pm, at the 4:00 close"),
    "1700": ("vwap_1700", "VWAP from 6:00 pm, at the 5:00 session end"),
    "rth": ("vwap_rth", "regular-hours VWAP (9:30-4:00)"),
}


def build_map(h, now, vwap_mode="1600", kind="futures"):
    """Everything the Day map page needs for the current trading day."""
    if kind != "futures":
        vwap_mode = "rth"  # stocks/ETFs use the regular-hours session VWAP
    sess = sessions(h, kind)
    cur_day = sess.index[-1]
    cur = sess.iloc[-1]
    last_done = cur["rth_bars"] > 0 and cur["rth_last"] is not None and cur["rth_last"].time() >= time(15, 55)
    evening = now.date() > cur_day or now.time() >= GLOBEX_OPEN
    if kind != "futures" and last_done and evening:
        # no evening session for stocks/ETFs/index: from 6 pm, preview the next session
        hist, prev = sess, cur
        cur_day = (pd.Timestamp(cur_day) + pd.offsets.BDay(1)).date()
        cur = pd.Series({c: np.nan for c in sess.columns} | {"rth_bars": 0, "rth_last": None}, name=cur_day)
    else:
        hist = sess.iloc[:-1]  # history excludes the current day
        done = hist[hist["rth_bars"] > 0]
        prev = done.iloc[-1] if len(done) else None
    st_ = stats(hist) if len(hist) else None
    last = float(h["Close"].iloc[-1])

    rth_started = cur["rth_bars"] > 0
    rth_done = rth_started and cur["rth_last"] is not None and cur["rth_last"].time() >= time(15, 55)
    locked = rth_started and not np.isnan(cur["lock"])
    anchor = float(cur["lock"]) if locked else last

    levels = []
    if st_:
        levels.append(("PIVOT", anchor, "9:29 lock" if locked else "pivot (locks at 9:29)"))
        for k, name in [("1", "UT1"), ("2", "UT2"), ("F", "FUT")]:
            levels.append((name, anchor * (1 + st_["up"][k]),
                           {"1": "median day high", "2": "big day high (75th pct)", "F": "extreme day high (90th pct)"}[k]))
        for k, name in [("1", "DT1"), ("2", "DT2"), ("F", "FDT")]:
            levels.append((name, anchor * (1 - st_["dn"][k]),
                           {"1": "median day low", "2": "big day low (75th pct)", "F": "extreme day low (90th pct)"}[k]))
    if prev is not None:
        d = pd.Timestamp(prev.name).strftime("%a %m/%d").upper()
        levels += [("PDH", prev["h"], f"{d} high"), ("PDL", prev["l"], f"{d} low"), ("PDC", prev["c"], f"{d} close"),
                   ("PMID", (prev["h"] + prev["l"]) / 2, f"{d} midpoint (high + low) ÷ 2")]
        col, desc = VWAP_MODES[vwap_mode]
        if not np.isnan(prev[col]):
            levels.append(("PVWAP", prev[col], f"{d} {desc}"))
    if not np.isnan(cur["onh"]):
        part = "overnight" if kind == "futures" else "premarket"
        levels += [("ONH", cur["onh"], f"{part} high"), ("ONL", cur["onl"], f"{part} low")]
        if kind == "futures":
            levels.append(("GBX", cur["gbx"], "Globex open 18:00"))
    if rth_started:
        levels += [("RTHH", cur["h"], "today's high so far" if not rth_done else "today's high"),
                   ("RTHL", cur["l"], "today's low so far" if not rth_done else "today's low")]

    return {
        "day": cur_day, "last": last, "anchor": anchor, "locked": locked,
        "rth_started": rth_started, "rth_done": rth_done,
        "cur": cur, "prev": prev, "stats": st_, "levels": levels, "kind": kind,
    }


def bluf(m, fmt=lambda x: f"{x:,.0f} pts"):
    """Two plain-English summary lines, like a trader's morning note."""
    cur, prev, last, st_ = m["cur"], m["prev"], m["last"], m["stats"]
    out = []
    if not np.isnan(cur["onh"]):
        onr = cur["onh"] - cur["onl"]
        pos = (last - cur["onl"]) / onr if onr else 0.5
        third = "top third" if pos > 2 / 3 else "bottom third" if pos < 1 / 3 else "middle third"
        part = "Overnight" if m.get("kind", "futures") == "futures" else "Premarket"
        line = f"{part} ran {fmt(onr)} ({onr / last * 100:.2f}%)"
        if st_ is not None and len(st_["on_ranges"]):
            pct = (st_["on_ranges"] < onr / last).mean() * 100
            line += (f", bigger than {pct:.0f}% of the last {st_['n']} sessions" if pct >= 50
                     else f", smaller than {100 - pct:.0f}% of the last {st_['n']} sessions")
        if not m["rth_started"]:
            line += f"; price is in the {third} of it"
        out.append(line + ".")
    if prev is not None:
        chg = last - prev["c"]
        where = ("above yesterday's high" if last > prev["h"] else
                 "below yesterday's low" if last < prev["l"] else "inside yesterday's range")
        took = []
        if cur["onh"] > prev["h"] or (m["rth_started"] and cur["h"] > prev["h"]):
            took.append("yesterday's high")
        if cur["onl"] < prev["l"] or (m["rth_started"] and cur["l"] < prev["l"]):
            took.append("yesterday's low")
        s = f"Last {last:,.2f}, {chg:+,.2f} ({chg / prev['c'] * 100:+.2f}%) vs yesterday's close, {where}"
        if took:
            s += "; already took " + " and ".join(took)
        out.append(s + ".")
    if m["rth_started"] and st_:
        rng = cur["h"] - cur["l"]
        norm = st_["range_med"] * m["anchor"]
        out.append(f"Day range so far {fmt(rng)}, {rng / norm * 100:.0f}% of a normal day ({fmt(norm)}).")
    return out
