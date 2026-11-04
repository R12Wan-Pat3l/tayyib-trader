#!/usr/bin/env python3
"""Generate the offline test fixtures in tests/fixtures/.

SYNTHETIC DATA. The companies (Alfa Industries, Charlie Pharma, ...) are
invented and their prices are a seeded random walk with an engineered
ending, so the tests are exact and repeatable with no network. Only the
FORMATS are real: Yahoo chart / fundamentals-timeseries JSON, NSE index
CSV, RSS 2.0, and NSE API JSON. Live data is exercised by TESTING.md.

  python3 tests/make_fixtures.py      # rewrites tests/fixtures/
"""
import datetime as dt
import json
import math
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
LAST_DAY = dt.date(2026, 10, 30)          # a Friday
N = 520


def trading_days(n, last=LAST_DAY):
    out, d = [], last
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= dt.timedelta(days=1)
    return out[::-1]


def walk(seed, start, drift, vol, n, volume=1_000_000):
    rng = random.Random(seed)
    bars, pc = [], start
    for _ in range(n):
        r = rng.gauss(drift, vol)
        o = pc * (1 + rng.gauss(0, vol / 3))
        c = pc * (1 + r)
        h = max(o, c) * (1 + abs(rng.gauss(0, vol / 2)))
        l = min(o, c) * (1 - abs(rng.gauss(0, vol / 2)))
        v = int(volume * math.exp(rng.gauss(0, 0.3)))
        bars.append([o, h, l, c, v])
        pc = c
    return bars


def ema_last(closes, n=20):
    k = 2 / (n + 1)
    e = sum(closes[:n]) / n
    for c in closes[n:]:
        e = c * k + e * (1 - k)
    return e


def consolidate(bars, days, seed):
    """Tight range just under the prior high: arms breakout + squeeze."""
    rng = random.Random(seed)
    top = max(b[1] for b in bars[-20:])
    base = sum(b[4] for b in bars[-20:]) / 20
    for _ in range(days):
        c = top * rng.uniform(0.975, 0.99)
        o = c * rng.uniform(0.995, 1.005)
        h = min(top * 0.996, max(o, c) * 1.004)
        l = min(o, c) * 0.994
        bars.append([o, h, l, c, int(base * 0.7 * rng.uniform(0.8, 1.1))])
    return bars


def pullback(bars, seed):
    """Slide back to the 20-day EMA, then a bar that tags it and holds."""
    rng = random.Random(seed)
    for _ in range(30):
        closes = [b[3] for b in bars]
        e = ema_last(closes)
        pc = closes[-1]
        if pc <= e * 1.015:
            break
        c = pc * 0.988
        o = pc * 0.998
        bars.append([o, o * 1.002, c * 0.996, c, int(900_000 * rng.uniform(0.8, 1.2))])
    closes = [b[3] for b in bars]
    e = ema_last(closes)
    c = e * 1.004
    o = closes[-1] * 0.997
    bars.append([o, max(o, c) * 1.006, e * 0.995, c, 800_000])
    return bars


def chart_json(sym, bars):
    days = trading_days(len(bars))
    ts = [int(dt.datetime.combine(d, dt.time(9, 15), IST).timestamp()) for d in days]
    q = {k: [] for k in ("open", "high", "low", "close", "volume")}
    for o, h, l, c, v in bars:
        q["open"].append(round(o, 2))
        q["high"].append(round(h, 2))
        q["low"].append(round(l, 2))
        q["close"].append(round(c, 2))
        q["volume"].append(v)
    return {"chart": {"result": [{"meta": {"currency": "INR", "symbol": sym + ".NS",
                                           "exchangeName": "NSI", "regularMarketPrice": round(bars[-1][3], 2)},
                                  "timestamp": ts, "indicators": {"quote": [q]}}], "error": None}}


def ts_item(t, rows, freq):
    return {"meta": {"symbol": ["X.NS"], "type": [freq + t]}, "timestamp": [1],
            freq + t: [{"asOfDate": d, "periodType": "12M" if freq == "annual" else "3M",
                        "currencyCode": "INR", "reportedValue": {"raw": v, "fmt": str(v)}} for d, v in rows]}


def fundamentals(freq, series):
    return {"timeseries": {"result": [ts_item(t, rows, freq) for t, rows in series.items()], "error": None}}


def annual(debt, assets, cash, recv, interest, revenue, prev_debt=None):
    y1, y0 = "2026-03-31", "2025-03-31"
    pd = prev_debt if prev_debt is not None else debt * 0.9
    return {"TotalDebt": [(y0, pd), (y1, debt)], "TotalAssets": [(y0, assets * 0.92), (y1, assets)],
            "CashAndCashEquivalents": [(y0, cash), (y1, cash)], "AccountsReceivable": [(y0, recv), (y1, recv)],
            "InterestIncome": [(y0, interest * 0.8), (y1, interest)], "TotalRevenue": [(y0, revenue * 0.88), (y1, revenue)]}


def write(rel, obj):
    p = os.path.join(FIX, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        if isinstance(obj, str):
            f.write(obj)
        else:
            json.dump(obj, f, indent=1)
            f.write("\n")


CR = 1e7


def main():
    # --- prices
    charts = {
        "ALFA": consolidate(walk(11, 400, 0.0016, 0.013, N - 12), 12, 5),
        "CHRL": pullback(walk(23, 900, 0.0018, 0.012, N - 15), 7),
        "BRVO": walk(31, 1200, -0.0012, 0.014, N),
        "DLTA": consolidate(walk(41, 300, 0.0016, 0.013, N - 12), 12, 6),
        "ITC": consolidate(walk(53, 350, 0.0014, 0.011, N - 12), 12, 8),
        "ECHO": walk(61, 150, 0.0010, 0.015, N),
        "THIN": consolidate(walk(71, 60, 0.0016, 0.013, N - 12, volume=2000), 12, 9),
    }
    for s, b in charts.items():
        write("chart/%s.json" % s, chart_json(s, b))

    # --- NSE index CSV (Nifty 500 format)
    write("index/nifty500.csv", "\n".join([
        "Company Name,Industry,Symbol,Series,ISIN Code",
        "Alfa Industries Ltd.,Capital Goods,ALFA,EQ,INE000A01011",
        "Bravo Chemicals Ltd.,Chemicals,BRVO,EQ,INE000B01012",
        "Charlie Pharma Ltd.,Healthcare,CHRL,EQ,INE000C01013",
        "Delta Steel Ltd.,Metals & Mining,DLTA,EQ,INE000D01014",
        "Echo Media Ltd.,\"Media, Entertainment & Publication\",ECHO,EQ,INE000E01015",
        "Example Bank Ltd.,Financial Services,EXBANK,EQ,INE000F01016",
        "Golf Textiles Ltd.,Textiles,GOLF,EQ,INE000G01017",
        "ITC Ltd.,Fast Moving Consumer Goods,ITC,EQ,INE154A01025",
        "Thin Traders Ltd.,Consumer Durables,THIN,EQ,INE000H01018",
    ]) + "\n")
    write("index/official.csv", "Symbol,Company Name,Industry\nALFA,Alfa Industries Ltd.,Capital Goods\n"
          "CHRL,Charlie Pharma Ltd.,Healthcare\nITC,ITC Ltd.,Fast Moving Consumer Goods\n")

    # --- annual fundamentals (rupees). GOLF has none on purpose -> unknown.
    fa = {
        "ALFA": annual(debt=120 * CR, assets=1500 * CR, cash=200 * CR, recv=250 * CR, interest=9 * CR, revenue=1300 * CR),
        "BRVO": annual(debt=90 * CR, assets=1000 * CR, cash=80 * CR, recv=150 * CR, interest=4 * CR, revenue=900 * CR),
        "CHRL": annual(debt=200 * CR, assets=2600 * CR, cash=300 * CR, recv=500 * CR, interest=20 * CR, revenue=2400 * CR,
                       prev_debt=100 * CR),
        "DLTA": annual(debt=800 * CR, assets=2000 * CR, cash=50 * CR, recv=200 * CR, interest=5 * CR, revenue=1800 * CR),
        "ECHO": annual(debt=10 * CR, assets=300 * CR, cash=40 * CR, recv=60 * CR, interest=2 * CR, revenue=250 * CR),
        "ITC": annual(debt=1 * CR, assets=80000 * CR, cash=500 * CR, recv=3000 * CR, interest=1500 * CR, revenue=70000 * CR),
        "THIN": annual(debt=1 * CR, assets=50 * CR, cash=5 * CR, recv=5 * CR, interest=0.1 * CR, revenue=40 * CR),
    }
    for s, ser in fa.items():
        write("fundamentals/%s_annual.json" % s, fundamentals("annual", ser))
    qs = ["2024-09-30", "2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31",
          "2026-03-31", "2026-06-30", "2026-09-30"]
    rev = [280, 295, 310, 300, 320, 335, 345, 340, 372]
    write("fundamentals/ALFA_quarterly.json", fundamentals("quarterly", {
        "TotalRevenue": [(d, r * CR) for d, r in zip(qs, rev)],
        "OperatingIncome": [(d, r * 0.16 * CR) for d, r in zip(qs, rev)],
        "NetIncome": [(d, r * 0.10 * CR) for d, r in zip(qs, rev)],
        "DilutedEPS": [(d, round(r * 0.10 / 12, 2)) for d, r in zip(qs, rev)],
    }))

    # --- news
    write("rss/google_ALFA.xml", """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Google News</title>
<item><title>Alfa Industries Q2 results: net profit rises 12% on strong orders - Example Times</title>
<link>https://news.example.com/alfa-q2</link><pubDate>Fri, 30 Oct 2026 08:30:00 GMT</pubDate>
<source url="https://news.example.com">Example Times</source><description>Alfa Industries reported...</description></item>
<item><title>Alfa Industries board approves raising Rs 300 crore via NCDs - Example Markets</title>
<link>https://news.example.com/alfa-ncd</link><pubDate>Thu, 29 Oct 2026 11:00:00 GMT</pubDate>
<source url="https://news.example.com">Example Markets</source><description>The capital goods maker...</description></item>
<item><title>Alfa Industries bags Rs 150 crore order - Old News</title>
<link>https://news.example.com/alfa-old</link><pubDate>Mon, 05 Oct 2026 06:00:00 GMT</pubDate>
<source url="https://news.example.com">Old News</source><description>Old.</description></item>
</channel></rss>
""")
    write("rss/google_CHRL.xml", """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Charlie Pharma gets USFDA nod for generic drug</title><link>https://news.example.com/chrl</link>
<pubDate>Fri, 30 Oct 2026 04:00:00 GMT</pubDate><description>Charlie Pharma...</description></item>
</channel></rss>
""")
    write("rss/moneycontrol_markets.xml", """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Sensex, Nifty end higher; capital goods stocks like Alfa Industries lead</title>
<link>https://mc.example.com/1</link><pubDate>Fri, 30 Oct 2026 10:30:00 GMT</pubDate>
<description>Markets closed higher.</description></item>
<item><title>Rupee ends flat against dollar</title><link>https://mc.example.com/2</link>
<pubDate>Fri, 30 Oct 2026 10:00:00 GMT</pubDate><description>Forex.</description></item>
</channel></rss>
""")
    write("rss/livemint_markets.xml", """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Market outlook for the week ahead</title><link href="https://mint.example.com/a"/>
<updated>2026-10-30T12:00:00Z</updated><summary>Outlook.</summary></entry></feed>
""")
    write("nse/announcements_ALFA.json", [
        {"symbol": "ALFA", "desc": "Outcome of Board Meeting", "an_dt": "29-Oct-2026 17:05:00",
         "attchmntText": "Approved unaudited financial results for the quarter ended September 30, 2026",
         "attchmntFile": "https://nsearchives.example/alfa.pdf"}])
    write("nse/announcements_CHRL.json", [])
    write("nse/pit_ALFA.json", {"data": [
        {"symbol": "ALFA", "acqName": "Alfa Promoter Trust", "personCategory": "Promoter Group",
         "secAcq": "50000", "secVal": "18500000", "tdpTransactionType": "Buy", "acqMode": "Market Purchase",
         "acqfromDt": "20-Oct-2026", "acqtoDt": "21-Oct-2026", "intimDt": "22-Oct-2026 18:00"},
        {"symbol": "ALFA", "acqName": "A. Director", "personCategory": "Director",
         "secAcq": "2000", "secVal": "760000", "tdpTransactionType": "Sell", "acqMode": "Market Sale",
         "acqfromDt": "15-Oct-2026", "acqtoDt": "15-Oct-2026", "intimDt": "16-Oct-2026 12:00"},
        {"symbol": "ALFA", "acqName": "Alfa Holdings Pvt Ltd", "personCategory": "Promoters",
         "secAcq": "100000", "secVal": "-", "tdpTransactionType": "Pledge Creation", "acqMode": "Pledge Creation",
         "acqfromDt": "10-Oct-2026", "acqtoDt": "10-Oct-2026", "intimDt": "12-Oct-2026 10:00"}]})
    write("nse/bulk_ALFA.json", {"data": [
        {"BD_DT_DATE": "27-Oct-2026", "BD_SYMBOL": "ALFA", "BD_CLIENT_NAME": "EXAMPLE MUTUAL FUND",
         "BD_BUY_SELL": "BUY", "BD_QTY_TRD": 400000, "BD_TP_WATP": 985.25}]})
    write("nse/block_ALFA.json", {"data": []})
    print("fixtures written to %s" % FIX)


if __name__ == "__main__":
    main()
