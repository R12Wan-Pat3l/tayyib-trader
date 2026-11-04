#!/usr/bin/env python3
"""tayyib-results: what changed in the quarterly results, and in the halal ratios.

Quarterly revenue, operating profit, net profit and EPS with QoQ and YoY
growth (matched by date; '-' when the comparison quarter is missing), from
Yahoo's fundamentals feed (usually consolidated figures, not labelled by Yahoo) (free, unofficial: Indian coverage
can have gaps; check the filing on NSE/BSE for anything that matters).
Then the TASIS-style halal ratios for the latest year against the year
before, so you see a stock drifting toward the limits before it is dropped.
Writes trader/results/SYMBOL.json.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tayyib_core as tc  # noqa: E402

Q_TYPES = ("TotalRevenue", "OperatingIncome", "NetIncome", "DilutedEPS")


def growth(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return round((cur - prev) / abs(prev) * 100, 1)


def months_back(d, m):
    """'2026-09-30', 3 -> '2026-06' (year-month of the quarter m months earlier)."""
    y, mo = int(d[:4]), int(d[5:7]) - m
    while mo <= 0:
        y, mo = y - 1, mo + 12
    return "%04d-%02d" % (y, mo)


def quarter_table(q, n):
    """Growth is matched by date, so a quarter missing from the feed gives '-' rather
    than a growth figure measured against the wrong quarter."""
    dates = sorted({d for rows in q.values() for d, _ in rows})
    vals = {k: {d[:7]: v for d, v in rows} for k, rows in q.items()}
    table = []
    for d in dates:
        row = {"quarter": d}
        for t in Q_TYPES:
            v = vals.get(t, {}).get(d[:7])
            row[t] = v
            row[t + "_qoq"] = growth(v, vals.get(t, {}).get(months_back(d, 3)))
            row[t + "_yoy"] = growth(v, vals.get(t, {}).get(months_back(d, 12)))
        rev, op = row.get("TotalRevenue"), row.get("OperatingIncome")
        row["op_margin_pct"] = round(op / rev * 100, 1) if rev and op is not None else None
        table.append(row)
    return table[-n:]


def drift(annual, cfg):
    dates = sorted({d for rows in annual.values() for d, _ in rows})
    if not dates:
        return None, None
    now = tc.financial_screen(annual, cfg)
    prev = None
    if len(dates) >= 2:
        cut = {k: [r for r in rows if r[0] <= dates[-2]] for k, rows in annual.items()}
        prev = tc.financial_screen({k: v for k, v in cut.items() if v}, cfg)
    return now, prev


def crore(x):
    return "-" if x is None else "%.1f cr" % (x / 1e7)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("symbol")
    p.add_argument("--quarters", type=int, default=6)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    cfg = tc.load_config()
    sym = tc.normalize_symbol(a.symbol)
    errors = []
    try:
        q = tc.fetch_fundamentals(sym, "quarterly", Q_TYPES)
    except tc.FetchError as e:
        q, _ = {}, errors.append("quarterly: %s" % e)
    try:
        annual = tc.fetch_fundamentals(sym, "annual")
    except tc.FetchError as e:
        annual, _ = {}, errors.append("annual: %s" % e)
    table = quarter_table(q, a.quarters) if q else []
    now, prev = drift(annual, cfg) if annual else (None, None)
    h = cfg["halal"]
    limits = {"debt_to_assets_pct": h["max_debt_to_assets_pct"],
              "noncompliant_income_pct": h["max_noncompliant_income_pct"],
              "cash_receivables_to_assets_pct": h["max_cash_receivables_to_assets_pct"]}
    flags = []
    if now:
        for k, lim in limits.items():
            v = now["ratios"].get(k)
            if v is not None and v >= 0.8 * lim:
                flags.append("%s at %.2f%% is within 20%% of the %.0f%% limit" % (k, v, lim))
            pv = (prev or {}).get("ratios", {}).get(k)
            if v is not None and pv is not None and v > pv * 1.25 and v - pv > 1:
                flags.append("%s rose from %.2f%% to %.2f%%" % (k, pv, v))
    out = {"symbol": sym, "asof": tc.now_ist().isoformat(timespec="minutes"), "quarters": table,
           "halal_now": now, "halal_prev_year": prev, "halal_flags": flags, "errors": errors,
           "halal_universe": tc.halal_status(sym)["status"]}
    tc.write_json(os.path.join("results", "%s.json" % sym), out)
    if a.json:
        return tc.print_json(out)
    print("%s quarterly results (Rs crore; growth %%; Yahoo does not say consolidated or standalone,"
          " usually consolidated)" % sym)
    if table:
        print("  %-10s %10s %7s %7s %10s %7s %10s %7s %7s %8s" % ("quarter", "revenue", "qoq", "yoy", "op.profit",
                                                                 "margin", "net", "qoq", "yoy", "eps"))
        f = lambda x: "-" if x is None else "%+.1f" % x
        for r in table:
            print("  %-10s %10s %7s %7s %10s %7s %10s %7s %7s %8s" % (
                r["quarter"], crore(r["TotalRevenue"]), f(r["TotalRevenue_qoq"]), f(r["TotalRevenue_yoy"]),
                crore(r["OperatingIncome"]), "-" if r["op_margin_pct"] is None else "%.1f" % r["op_margin_pct"],
                crore(r["NetIncome"]), f(r["NetIncome_qoq"]), f(r["NetIncome_yoy"]),
                "-" if r["DilutedEPS"] is None else "%.2f" % r["DilutedEPS"]))
    else:
        print("  no quarterly data")
    if now:
        print("Halal ratios (latest annual %s): %s -> %s" % (now["as_of"], now["ratios"], now["status"]))
        if prev:
            print("  year before (%s): %s -> %s" % (prev["as_of"], prev["ratios"], prev["status"]))
    for fl in flags:
        print("  HALAL-WATCH: %s" % fl)
    for e in errors:
        print("  (%s)" % e)


if __name__ == "__main__":
    main()
