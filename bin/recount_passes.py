#!/usr/bin/env python3
"""Detect passes in stored 1 s data with the firmware's rule; optionally write them.

    recount_passes.py --location outdoor --start 2026-10-13T04:08:00Z --end 2026-10-13T06:15:06Z
    recount_passes.py ... --write                     # save as pass points tagged src=backfill
    recount_passes.py ... --start-db 10 --end-db 5    # try other thresholds (dry run)

Undo a backfill:  hactl.py influx "DELETE FROM noise WHERE src='backfill'" --db noise
Same rule as esphome/noise-common.yaml: background = quietest LAeq of the last 60 s;
a pass starts at LAFmax >= bg + start-db, ends below bg + end-db or after max-s.
"""
import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hactl  # noqa: E402


def detect(rows, start_db, end_db, max_s, window=60):
    """rows: [(unix_s, laeq, lafmax)] in time order -> [(peak_t, peak, bg)]."""
    hist, passes, cur, last_t = [], [], None, None
    for t, laeq, lafmax in rows:
        if last_t is not None and t - last_t > window:   # data gap (reboot/outage): start fresh
            hist, cur = [], None
        last_t = t
        hist = (hist + [laeq])[-window:]
        if len(hist) < 10:
            continue
        bg = min(hist)
        if cur is None:
            if lafmax >= bg + start_db:
                cur = {"start": t, "peak_t": t, "peak": lafmax, "bg": bg}
        else:
            if lafmax > cur["peak"]:
                cur["peak"], cur["peak_t"] = lafmax, t
            if lafmax < cur["bg"] + end_db or t - cur["start"] >= max_s:
                passes.append((cur["peak_t"], cur["peak"], cur["bg"]))
                cur = None
    return passes


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--location", required=True)
    p.add_argument("--start", required=True, help="RFC3339, e.g. 2026-10-13T04:08:00Z")
    p.add_argument("--end", required=True)
    p.add_argument("--start-db", type=float, default=8.0)
    p.add_argument("--end-db", type=float, default=4.0)
    p.add_argument("--max-s", type=float, default=30)
    p.add_argument("--write", action="store_true")
    a = p.parse_args()

    q = (f"SELECT laeq_1s, lafmax_1s FROM noise WHERE location='{a.location}' "
         f"AND time >= '{a.start}' AND time < '{a.end}'")
    series = hactl.influx(q, "noise")["results"][0].get("series")
    rows = [(t / 1000, x, m) for t, x, m in (series[0]["values"] if series else []) if x is not None and m is not None]
    passes = detect(rows, a.start_db, a.end_db, a.max_s)
    hours = (rows[-1][0] - rows[0][0]) / 3600 if len(rows) > 1 else 0
    print(f"{a.location}: {len(rows)} s of data, {len(passes)} passes"
          + (f" ({len(passes) / hours:.0f}/h)" if hours else ""))
    for t, peak, bg in sorted(passes, key=lambda x: -x[1])[:5]:
        print(f"  loudest: {datetime.datetime.fromtimestamp(t):%H:%M:%S}  {peak:.1f} dB (+{peak - bg:.0f} over {bg:.1f})")
    if not a.write or not passes:
        return

    lines = "".join(f"noise,location={a.location},src=backfill pass_lafmax={peak:.1f},pass_bg={bg:.1f} {int(t)}\n"
                    for t, peak, bg in passes)
    source = hactl.addon(hactl.INFLUX_ADDON, "get", "/chronograf/v1/sources")["sources"][0]
    hactl.addon(hactl.INFLUX_ADDON, "post", source["links"]["write"] + "?db=noise&precision=s", lines.encode())
    print(f"wrote {len(passes)} passes (tag src=backfill)")


if __name__ == "__main__":
    main()
