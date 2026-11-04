"""Saves each product's 9:45 ET levels to snapshots/YYYY-MM-DD.json.
Run by the GitHub Action in .github/workflows/snapshot.yml (or by hand: python snapshot.py --force)."""
import json
import sys
from datetime import datetime, time
from pathlib import Path

import gex

PRODUCTS = {
    "NQ · QQQ": {"chain": "QQQ", "future": "NQ=F", "mode": "ratio"},
    "ES · SPX": {"chain": "_SPX", "future": "ES=F", "mode": "basis"},
    "ES · SPY": {"chain": "SPY", "future": "ES=F", "mode": "ratio"},
}


def main():
    force = "--force" in sys.argv
    now = datetime.now(gex.ET)
    in_window = now.weekday() < 5 and time(9, 40) <= now.time() <= time(11, 30)
    if not (in_window or force):
        print(f"{now:%a %H:%M} ET is outside the 9:40–11:30 window, nothing to do.")
        return

    out = Path(__file__).parent / "snapshots" / f"{now:%Y-%m-%d}.json"
    if out.exists() and not force:
        print(f"{out.name} already saved today.")
        return

    day = {}
    for name, cfg in PRODUCTS.items():
        try:
            raw, spot, stamp, extras = gex.fetch_cboe_chain(cfg["chain"])
            fut = gex.fetch_futures_price(cfg["future"])
            snap = gex.build_snapshot(raw, spot, extras, fut, cfg["mode"], now)
            if snap:
                snap["data_stamp"] = stamp
                day[name] = snap
                print(f"saved {name}: spot {spot}, expiry {snap['expiry']}")
            else:
                print(f"{name}: no live options, skipped")
        except Exception as e:  # keep going so one bad product doesn't lose the others
            print(f"{name}: failed ({e})")

    if not day:
        print("Nothing saved (market holiday or data unavailable).")
        sys.exit(1)  # make the run show a red X so problems are visible
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(day, indent=1, default=str))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
