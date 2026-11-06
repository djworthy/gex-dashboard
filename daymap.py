"""Session levels and statistical day targets for NQ / ES futures (5-minute bars, ET)."""
from datetime import time

import numpy as np
import pandas as pd

RTH_OPEN, RTH_CLOSE, GLOBEX_OPEN = time(9, 30), time(16, 0), time(18, 0)
PCTS = {"1": 50, "2": 75, "F": 90}  # UT1/DT1 = median day, UT2/DT2 = big day, FUT/FDT = extreme day


def tag_sessions(h):
    """Label every bar with its trading day (bars from 18:00 belong to the next day) and part."""
    df = h.copy()
    idx = df.index
    t = pd.Series(idx.time, index=idx)
    shift = pd.to_timedelta((idx.hour >= 18).astype(int), unit="D")
    df["tday"] = (idx.normalize() + shift).date
    df["rth"] = ((t >= RTH_OPEN) & (t < RTH_CLOSE)).values
    df["on"] = ((t >= GLOBEX_OPEN) | (t < RTH_OPEN)).values
    return df


def sessions(h):
    """One row per trading day: overnight + RTH OHLC and the 9:29 lock price."""
    df = tag_sessions(h)
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
        rows.append({
            "tday": d,
            "gbx": on["Open"].iloc[0] if len(on) else np.nan,
            "onh": on["High"].max() if len(on) else np.nan,
            "onl": on["Low"].min() if len(on) else np.nan,
            "lock": on["Close"].iloc[-1] if len(on) and on.index[-1].time() < RTH_OPEN else np.nan,
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


def build_map(h, now, vwap_mode="1600"):
    """Everything the Day map page needs for the current trading day."""
    sess = sessions(h)
    st_ = stats(sess.iloc[:-1]) if len(sess) > 1 else None  # history excludes the current day
    cur_day = sess.index[-1]
    cur = sess.iloc[-1]
    done = sess[(sess.index < cur_day) & (sess["rth_bars"] > 0)]
    prev = done.iloc[-1] if len(done) else None
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
        levels += [("ONH", cur["onh"], "overnight high"), ("ONL", cur["onl"], "overnight low"),
                   ("GBX", cur["gbx"], "Globex open 18:00")]
    if rth_started:
        levels += [("RTHH", cur["h"], "today's high so far" if not rth_done else "today's high"),
                   ("RTHL", cur["l"], "today's low so far" if not rth_done else "today's low")]

    return {
        "day": cur_day, "last": last, "anchor": anchor, "locked": locked,
        "rth_started": rth_started, "rth_done": rth_done,
        "cur": cur, "prev": prev, "stats": st_, "levels": levels,
    }


def bluf(m, unit="pts"):
    """Two plain-English summary lines, like a trader's morning note."""
    cur, prev, last, st_ = m["cur"], m["prev"], m["last"], m["stats"]
    out = []
    if not np.isnan(cur["onh"]):
        onr = cur["onh"] - cur["onl"]
        pos = (last - cur["onl"]) / onr if onr else 0.5
        third = "top third" if pos > 2 / 3 else "bottom third" if pos < 1 / 3 else "middle third"
        line = f"Overnight ran {onr:,.0f} {unit} ({onr / last * 100:.2f}%)"
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
        out.append(f"Day range so far {rng:,.0f} {unit}, {rng / norm * 100:.0f}% of a normal day ({norm:,.0f}).")
    return out
