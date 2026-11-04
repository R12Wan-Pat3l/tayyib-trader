"""tayyib_core: the shared library behind every tayyib-trader skill.

Standard library only, Python 3.8+. The canonical copy lives in
core/tayyib_core.py; `python3 tools/sync_core.py` copies it into every skill
folder so each skill still works when its folder is copied on its own.
Do not edit the copies inside the skill folders: edit this file and sync.

What lives here:
  config + the trader/ folder   load_config, read_json, write_json
  time (IST, NSE sessions)      now_ist, is_trading_day, add_trading_days
  network + offline fixtures    fetch, fetch_json, NSESession
  prices                        get_daily_bars (Yahoo Finance, .NS / .BO)
  indicators                    sma, ema, rsi, atr
  setups                        detect, detect_all (swing + delivery)
  exit plans                    plan_trade
  Indian charges                order_charges, round_trip
  halal screening               business_screen, financial_screen, halal_status
  news                          parse_feed
  hard rules                    guard_order (CNC only, no shorts, no F&O)
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import http.cookiejar
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

VERSION = "0.1.4"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30), "IST")

# ---------------------------------------------------------------------------
# The trader/ folder and config
# ---------------------------------------------------------------------------


def data_dir():
    """Where every skill reads and writes its files. TAYYIB_DIR overrides."""
    return os.path.abspath(os.environ.get("TAYYIB_DIR", "trader"))


def path(*parts):
    p = os.path.join(data_dir(), *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def read_json(name, default=None):
    p = name if os.path.isabs(name) else os.path.join(data_dir(), name)
    if not os.path.exists(p):
        return default
    with open(p, "r", encoding="utf-8-sig") as f:   # -sig: Notepad / PowerShell write a BOM
        return json.load(f)


def write_json(name, obj):
    p = name if os.path.isabs(name) else path(name)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, default=str)
        f.write("\n")
    os.replace(tmp, p)
    return p


DEFAULT_CONFIG = {
    # money
    "capital": 100000,
    "max_risk_per_trade_pct": 1.0,      # of capital, at the stop price
    "max_risk_per_trade_rs": None,      # optional hard cap in rupees
    "max_position_pct": 20.0,           # of capital in any one stock
    "max_open_positions": 6,
    "max_portfolio_heat_pct": 6.0,      # total open risk across positions
    "max_positions_per_industry": 2,
    "min_reward_risk": 1.5,             # net of all charges (a 2R plan nets ~1.6-1.9R)
    "cash_available": None,             # defaults to capital minus open positions
    # market
    "exchange": "NSE",
    "tick_size": 0.05,
    "min_price": 20,
    "min_turnover_rs": 20000000,        # 20-day avg traded value, Rs 2 crore
    "holidays": [],                     # "YYYY-MM-DD" NSE trading holidays
    # trade styles
    "modes": {
        "swing": {"atr_mult_cap": 3.0, "atr_fallback": 2.0, "min_stop_atr": 0.75,
                  "max_stop_pct": 10.0, "target_r": 2.0, "max_hold_days": 20},
        "delivery": {"max_stop_pct": 15.0, "min_stop_atr": 1.5,
                     "target_r": 3.0, "max_hold_days": 250},
    },
    # charges (equity delivery). Verify against your broker's charges page.
    "broker": "zerodha",
    "brokers": {
        "zerodha": {"brokerage_pct": 0.0, "brokerage_min": 0.0, "brokerage_cap": 0.0,
                    "dp_charge_per_sell": 15.34},
        "groww": {"brokerage_pct": 0.1, "brokerage_min": 5.0, "brokerage_cap": 20.0,
                  "dp_charge_per_sell": 15.34},
        "custom": {"brokerage_pct": 0.0, "brokerage_min": 0.0, "brokerage_cap": 0.0,
                   "dp_charge_per_sell": 15.34},
    },
    "charges": {
        "stt_pct": 0.1,                 # delivery: on buy and on sell
        "exchange_txn_pct": 0.00297,    # NSE
        "sebi_fee_pct": 0.0001,         # Rs 10 per crore
        "ipft_pct": 0.0001,             # NSE investor protection fund
        "stamp_duty_buy_pct": 0.015,
        "gst_pct": 18.0,                # on brokerage + exchange (incl. IPFT) + SEBI
    },
    # halal
    "halal": {
        "require_compliant": True,      # BLOCK anything not 'compliant'
        "allow_review": False,          # treat 'review' as BLOCK unless true
        "list_max_age_days": 120,       # warn when the list is older
        "auto_rebuild_days": 30,        # tayyib-daily rebuilds the list when older (0 = never)
        "max_debt_to_assets_pct": 25.0,         # TASIS
        "max_noncompliant_income_pct": 3.0,     # TASIS
        "max_cash_receivables_to_assets_pct": 90.0,  # TASIS
        "noncompliant_investment_return_pct": 8.0,
        "list_url": None,               # optional CSV URL of a Shariah list
        "parent_list_url": "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv",
    },
    # news
    "news": {
        "feeds": {
            "moneycontrol_markets": "https://www.moneycontrol.com/rss/marketreports.xml",
            "moneycontrol_business": "https://www.moneycontrol.com/rss/business.xml",
            "et_markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
            "livemint_markets": "https://www.livemint.com/rss/markets",
        },
        "google_news": True,
        "nse_announcements": True,
    },
    "user_agent": "tayyib-trader/0.1 (+https://github.com/R12Wan-Pat3l/tayyib-trader)",
}


def deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config():
    """Defaults, overlaid with trader/config.json if it exists."""
    user = read_json("config.json", {}) or {}
    return deep_merge(DEFAULT_CONFIG, user)


# ---------------------------------------------------------------------------
# Time: IST and NSE sessions
# ---------------------------------------------------------------------------


def now_ist():
    """Current time in IST. TAYYIB_NOW="YYYY-MM-DD HH:MM" pins it (tests)."""
    pinned = os.environ.get("TAYYIB_NOW")
    if pinned:
        return dt.datetime.strptime(pinned, "%Y-%m-%d %H:%M").replace(tzinfo=IST)
    return dt.datetime.now(IST)


def today_ist():
    return now_ist().date()


def parse_date(s):
    return dt.datetime.strptime(s[:10], "%Y-%m-%d").date()


def is_trading_day(d, cfg=None):
    cfg = cfg or load_config()
    if d.weekday() >= 5:
        return False
    return d.isoformat() not in set(cfg.get("holidays") or [])


def add_trading_days(d, n, cfg=None):
    cfg = cfg or load_config()
    cur, left = d, n
    while left > 0:
        cur += dt.timedelta(days=1)
        if is_trading_day(cur, cfg):
            left -= 1
    return cur


def market_status(now=None, cfg=None):
    """'pre-open' 9:00-9:15, 'open' 9:15-15:30, otherwise 'closed'."""
    now = now or now_ist()
    if not is_trading_day(now.date(), cfg):
        return "closed"
    t = now.hour * 60 + now.minute
    if 9 * 60 <= t < 9 * 60 + 15:
        return "pre-open"
    if 9 * 60 + 15 <= t < 15 * 60 + 30:
        return "open"
    return "closed"


# ---------------------------------------------------------------------------
# Network, with an offline fixture mode for tests
# ---------------------------------------------------------------------------


class FetchError(Exception):
    pass


def fixtures_dir():
    """When TAYYIB_FIXTURES is set, every fetch reads a local file instead."""
    return os.environ.get("TAYYIB_FIXTURES")


def _read_fixture(fixture):
    root = fixtures_dir()
    if not fixture:
        raise FetchError("offline mode: this request has no fixture")
    p = os.path.join(root, fixture)
    if not os.path.exists(p):
        raise FetchError("offline mode: missing fixture %s" % fixture)
    with open(p, "rb") as f:
        return f.read()


def fetch(url, fixture=None, headers=None, timeout=20, retries=2, opener=None):
    """GET a URL and return bytes. Polite: one user agent, backoff on 429/5xx."""
    if fixtures_dir():
        return _read_fixture(fixture)
    cfg_ua = DEFAULT_CONFIG["user_agent"]
    hdrs = {"User-Agent": cfg_ua, "Accept": "*/*", "Accept-Encoding": "gzip"}
    hdrs.update(headers or {})
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            op = opener.open if opener else urllib.request.urlopen
            with op(req, timeout=timeout) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise FetchError("%s -> HTTP %s" % (url, e.code))
        except (urllib.error.URLError, OSError) as e:
            last = e
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
    raise FetchError("%s -> %s" % (url, last))


def fetch_json(url, fixture=None, **kw):
    body = fetch(url, fixture=fixture, **kw)
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError:
        raise FetchError("%s did not return JSON" % url)


BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


class NSESession:
    """nseindia.com's JSON API needs cookies from a page visit first.

    These endpoints are public but unofficial: they can change or block
    automated clients without notice. Keep request rates low."""

    BASE = "https://www.nseindia.com"

    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.warm = False

    def _warm(self):
        if self.warm or fixtures_dir():
            return
        fetch(self.BASE + "/", headers={"User-Agent": BROWSER_UA, "Accept": "text/html"},
              opener=self.opener)
        self.warm = True

    def get_json(self, api_path, params=None, fixture=None):
        if fixtures_dir():
            return json.loads(_read_fixture(fixture).decode("utf-8"))
        self._warm()
        q = ("?" + urllib.parse.urlencode(params)) if params else ""
        body = fetch(self.BASE + api_path + q, opener=self.opener, headers={
            "User-Agent": BROWSER_UA, "Accept": "application/json",
            "Referer": self.BASE + "/"})
        return json.loads(body.decode("utf-8"))


# ---------------------------------------------------------------------------
# Symbols
# ---------------------------------------------------------------------------

_DERIV = re.compile(r"^[A-Z&\-]+\d{2}[A-Z]{3}(\d+(\.\d+)?)?(FUT|CE|PE)$")


def normalize_symbol(s):
    s = (s or "").strip().upper()
    for suf in (".NS", ".BO", "-EQ", ":NSE", ":BSE"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    if s.startswith("NSE:") or s.startswith("BSE:"):
        s = s[4:]
    return s


def is_derivative(sym):
    s = (sym or "").upper()
    return bool(_DERIV.match(s)) or s.endswith("FUT")


def yahoo_symbol(sym, exchange="NSE"):
    return normalize_symbol(sym) + (".BO" if exchange == "BSE" else ".NS")


def parse_symbols(arg):
    return [normalize_symbol(x) for x in re.split(r"[,\s]+", arg or "") if x.strip()]


# ---------------------------------------------------------------------------
# Prices (Yahoo Finance chart endpoint: free, unofficial)
# ---------------------------------------------------------------------------


def parse_yahoo_chart(obj):
    """Yahoo chart JSON -> (bars, meta). Bars are dicts with an IST date."""
    try:
        res = obj["chart"]["result"][0]
    except (KeyError, IndexError, TypeError):
        err = (obj or {}).get("chart", {}).get("error") if isinstance(obj, dict) else None
        raise FetchError("no chart data%s" % (": %s" % err if err else ""))
    meta = res.get("meta", {}) or {}
    ts = res.get("timestamp") or []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    bars = []
    for k, t in enumerate(ts):
        try:
            o, h, l, c = q["open"][k], q["high"][k], q["low"][k], q["close"][k]
            v = q.get("volume", [0] * len(ts))[k] or 0
        except (KeyError, IndexError):
            continue
        if None in (o, h, l, c):
            continue
        d = dt.datetime.fromtimestamp(t, IST).date().isoformat()
        bar = {"date": d, "open": float(o), "high": float(h), "low": float(l),
               "close": float(c), "volume": int(v)}
        if bars and bars[-1]["date"] == d:
            bars[-1] = bar
        else:
            bars.append(bar)
    return bars, meta


def get_daily_bars(sym, range_="2y", exchange="NSE", use_cache=True):
    """Daily OHLCV for an NSE (or BSE) stock. Cached per day in trader/cache/."""
    sym = normalize_symbol(sym)
    cache_name = os.path.join("cache", "bars_%s_%s_%s.json" % (sym, exchange, range_))
    if use_cache and not fixtures_dir():
        c = read_json(cache_name)
        if c and c.get("fetched") == today_ist().isoformat() and market_status() == "closed":
            return c["bars"], c.get("meta", {})
    ysym = yahoo_symbol(sym, exchange)
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=1d"
           % (urllib.parse.quote(ysym), range_))
    bars, meta = parse_yahoo_chart(fetch_json(url, fixture="chart/%s.json" % sym))
    if not fixtures_dir():
        write_json(cache_name, {"fetched": today_ist().isoformat(), "bars": bars, "meta": meta})
    return bars, meta


def last_price(sym, exchange="NSE"):
    bars, meta = get_daily_bars(sym, range_="5d", exchange=exchange, use_cache=False)
    p = meta.get("regularMarketPrice")
    return float(p) if p else bars[-1]["close"]


# ---------------------------------------------------------------------------
# Indicators (lists aligned to bars; None until enough history)
# ---------------------------------------------------------------------------


def sma(vals, n):
    out, s = [None] * len(vals), 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(vals, n):
    out = [None] * len(vals)
    if len(vals) < n:
        return out
    k = 2.0 / (n + 1)
    e = sum(vals[:n]) / n
    out[n - 1] = e
    for i in range(n, len(vals)):
        e = vals[i] * k + e * (1 - k)
        out[i] = e
    return out


def rsi(closes, n=14):
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    out[n] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def atr(bars, n=14):
    out = [None] * len(bars)
    if len(bars) <= n:
        return out
    trs = [bars[0]["high"] - bars[0]["low"]]
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[1:n + 1]) / n
    out[n] = a
    for i in range(n + 1, len(bars)):
        a = (a * (n - 1) + trs[i]) / n
        out[i] = a
    return out


def indicators(bars):
    closes = [b["close"] for b in bars]
    vols = [float(b["volume"]) for b in bars]
    return {
        "close": closes,
        "sma20": sma(closes, 20), "sma50": sma(closes, 50), "sma200": sma(closes, 200),
        "ema20": ema(closes, 20), "rsi14": rsi(closes, 14), "atr14": atr(bars, 14),
        "vol20": sma(vols, 20), "vol5": sma(vols, 5),
    }


# ---------------------------------------------------------------------------
# Tick rounding
# ---------------------------------------------------------------------------


def round_tick(p, tick=0.05, mode="nearest"):
    q = p / tick
    q = math.ceil(q - 1e-9) if mode == "up" else math.floor(q + 1e-9) if mode == "down" else round(q)
    return round(q * tick, 2)


# ---------------------------------------------------------------------------
# Setups. Each is evaluated on the close of bar i and arms a buy-stop
# trigger for the next sessions. Nothing here is a prediction.
# ---------------------------------------------------------------------------

SWING_SETUPS = ("breakout", "pullback", "oversold", "squeeze")
DELIVERY_SETUPS = ("trend",)
SETUP_INFO = {
    "breakout": "within 3% of the 20-day high in an uptrend; buy-stop just above that high",
    "pullback": "uptrend pulled back to the 20-day EMA; buy-stop above the pullback day's high",
    "oversold": "RSI(14) dipped under 35 above the 200-day average, then a green day",
    "squeeze": "the last 10 days' range shrank to under half the prior 30 days' in an uptrend",
    "trend": "long-term uptrend (above a rising 200-day average, near the 52-week high) for delivery",
}


def _ok(*xs):
    return all(x is not None for x in xs)


def detect(setup, bars, ind, i, tick=0.05):
    """Return a signal dict if `setup` is armed at the close of bar i."""
    if i < 200 or i >= len(bars):
        return None
    c = ind["close"][i]
    s50, s200, e20 = ind["sma50"][i], ind["sma200"][i], ind["ema20"][i]
    a, r = ind["atr14"][i], ind["rsi14"][i]
    if not _ok(s50, s200, e20, a, r):
        return None
    hi = lambda k0, k1: max(b["high"] for b in bars[k0:k1 + 1])
    lo = lambda k0, k1: min(b["low"] for b in bars[k0:k1 + 1])
    uptrend = c > s50 > s200 and s50 > (ind["sma50"][i - 10] or s50)
    sig = None
    if setup == "breakout" and uptrend:
        h20 = hi(i - 19, i)
        dist = (h20 - c) / c
        if 0 <= dist <= 0.03:
            dry = (ind["vol5"][i] or 1) / (ind["vol20"][i] or 1)
            score = 50 + (3 - dist * 100) * 6 + min(20, (c / s200 - 1) * 60) + (10 if dry < 0.9 else 0)
            sig = {"trigger": h20 * 1.002, "invalidation": lo(i - 4, i),
                   "score": score, "notes": "20-day high %.2f, %.1f%% away, volume %s"
                   % (h20, dist * 100, "drying up" if dry < 0.9 else "normal")}
    elif setup == "pullback" and uptrend:
        b = bars[i]
        if b["low"] <= e20 * 1.01 and c >= e20 * 0.985 and 35 <= r <= 58:
            score = 55 + (58 - r) + min(20, (c / s200 - 1) * 60)
            sig = {"trigger": b["high"] * 1.002, "invalidation": lo(i - 2, i) * 0.998,
                   "score": score, "notes": "touched the 20 EMA %.2f, RSI %.0f" % (e20, r)}
    elif setup == "oversold" and c > s200:
        rmin = min(x for x in ind["rsi14"][i - 3:i + 1] if x is not None)
        if rmin < 35 and bars[i]["close"] > bars[i]["open"]:
            score = 45 + (35 - rmin) * 2 + min(15, (c / s200 - 1) * 40)
            sig = {"trigger": bars[i]["high"] * 1.002, "invalidation": lo(i - 5, i),
                   "score": score, "notes": "RSI low %.0f, green close above the 200-day" % rmin}
    elif setup == "squeeze" and uptrend:
        r10 = hi(i - 9, i) - lo(i - 9, i)
        rp = hi(i - 39, i - 10) - lo(i - 39, i - 10)
        if rp > 0 and r10 < 0.5 * rp and r10 / c < 0.08:
            score = 50 + (0.5 - r10 / rp) * 80 + min(15, (c / s200 - 1) * 40)
            sig = {"trigger": hi(i - 9, i) * 1.002, "invalidation": lo(i - 9, i),
                   "score": score, "notes": "10-day range %.1f%% vs prior %.1f%%"
                   % (r10 / c * 100, rp / c * 100)}
    elif setup == "trend":
        s200_prev = ind["sma200"][i - 20]
        if i >= 251 and s200_prev and c > s200 and s50 > s200 and s200 > s200_prev:
            h52 = hi(i - 251, i)
            ret6 = c / ind["close"][i - 126] - 1
            if c >= 0.85 * h52 and ret6 > 0:
                score = 50 + (c / h52 - 0.85) * 200 + min(20, ret6 * 50)
                sig = {"trigger": bars[i]["high"] * 1.002, "invalidation": max(lo(i - 19, i), s200 * 0.97),
                       "score": score, "notes": "%.1f%% below the 52-week high, 6-month return %.1f%%"
                       % ((1 - c / h52) * 100, ret6 * 100)}
    if not sig:
        return None
    sig.update({
        "setup": setup, "date": bars[i]["date"], "close": round(c, 2),
        "trigger": round_tick(sig["trigger"], tick, "up"),
        "invalidation": round_tick(sig["invalidation"], tick, "down"),
        "atr": round(a, 2), "score": round(sig["score"], 1),
        "valid_days": 5 if setup == "trend" else 3,
        "mode": "delivery" if setup in DELIVERY_SETUPS else "swing",
    })
    if sig["invalidation"] >= sig["trigger"]:
        return None
    return sig


def detect_all(bars, mode="swing", i=None, setups=None, tick=0.05):
    ind = indicators(bars)
    i = len(bars) - 1 if i is None else i
    names = setups or (SWING_SETUPS if mode == "swing" else DELIVERY_SETUPS if mode == "delivery"
                       else SWING_SETUPS + DELIVERY_SETUPS)
    out = [s for s in (detect(n, bars, ind, i, tick) for n in names) if s]
    return sorted(out, key=lambda s: -s["score"])


def liquidity_ok(bars, cfg):
    ind_v = sma([float(b["volume"]) for b in bars], 20)[-1]
    if ind_v is None:
        return False, "less than 20 days of data"
    c = bars[-1]["close"]
    turnover = ind_v * c
    if c < cfg["min_price"]:
        return False, "price %.2f under min_price %s" % (c, cfg["min_price"])
    if turnover < cfg["min_turnover_rs"]:
        return False, "20-day avg turnover %s under %s" % (fmt_rs(turnover, 0), fmt_rs(cfg["min_turnover_rs"], 0))
    return True, "avg turnover %s" % fmt_rs(turnover, 0)


# ---------------------------------------------------------------------------
# Exit plan: stop, target, time stop, trailing rules
# ---------------------------------------------------------------------------


def plan_trade(sig, cfg, entry=None):
    """Stop and target for a signal, set before entry."""
    mode = sig.get("mode", "swing")
    m = cfg["modes"][mode]
    tick = cfg.get("tick_size", 0.05)
    entry = float(entry or sig["trigger"])
    a = float(sig["atr"])
    stop = float(sig["invalidation"])
    method = "structure (setup invalidation)"
    if mode == "swing":
        if entry - stop > m["atr_mult_cap"] * a:
            stop, method = entry - m["atr_fallback"] * a, "%.1f x ATR (structure too wide)" % m["atr_fallback"]
        if entry - stop < m["min_stop_atr"] * a:
            stop, method = entry - m["min_stop_atr"] * a, "%.2f x ATR (structure too tight)" % m["min_stop_atr"]
        cap = m.get("max_stop_pct")
        if cap and stop < entry * (1 - cap / 100.0):
            stop, method = entry * (1 - cap / 100.0), "%.0f%% max swing stop (structure/ATR wider)" % cap
    else:
        if entry - stop < m["min_stop_atr"] * a:
            stop, method = entry - m["min_stop_atr"] * a, "%.1f x ATR minimum" % m["min_stop_atr"]
        floor_ = entry * (1 - m["max_stop_pct"] / 100.0)   # the cap is applied last: it always wins
        if stop < floor_:
            stop, method = floor_, "%.0f%% max stop" % m["max_stop_pct"]
    # a stop set by a % cap rounds up to the tick so it never sits past the cap
    stop = round_tick(stop, tick, "up" if "max" in method and "stop" in method else "down")
    risk = round(entry - stop, 2)
    if risk <= 0:
        raise ValueError("stop %.2f is not below entry %.2f" % (stop, entry))
    target = round_tick(entry + m["target_r"] * risk, tick, "up")
    start = parse_date(sig["date"])
    plan = {
        "symbol": sig.get("symbol"), "mode": mode, "setup": sig["setup"],
        "signal_date": sig["date"], "entry": round(entry, 2), "entry_type": "buy-stop (trigger)",
        "valid_until": add_trading_days(start, sig.get("valid_days", 3), cfg).isoformat(),
        "stop": stop, "stop_method": method, "target": target, "target_r": m["target_r"],
        "risk_per_share": risk, "max_hold_days": m["max_hold_days"],
        "product": "CNC",
    }
    if mode == "swing":
        plan["trail"] = ["at +1R move the stop to entry (breakeven)",
                         "at +1.5R trail the stop under the 20-day EMA, checked on closing basis",
                         "exit after %d trading days if neither stop nor target hit" % m["max_hold_days"]]
    else:
        plan["trail"] = ["review (not auto-sell) at the target: %.1fR" % m["target_r"],
                         "exit on a weekly close below the 200-day average",
                         "re-check halal status every quarter (results can change the ratios)"]
    return plan


# ---------------------------------------------------------------------------
# Paper tracking: what actually happened to a planned trade
# ---------------------------------------------------------------------------

FINAL_OUTCOMES = ("TARGET", "STOP", "BREAKEVEN", "TIME EXIT", "NOT TRIGGERED")


def trade_outcome(bars, plan, cfg, today=None):
    """Follow a plan on the real daily bars after its signal date, with the plan's own rules:
    buy-stop fills at max(open, entry) within valid_until; a fill day that touches the stop and
    closes under the entry is a stop; gaps through the stop fill at the open; a day touching both
    stop and target counts as the stop; swing trades move the stop to breakeven at +1R; time stop
    after max_hold_days. -> dict with status, dates, prices, R and rupee P&L after charges."""
    today = today or today_ist().isoformat()
    sig, entry, stop, target = plan["date"], float(plan["entry"]), float(plan["stop"]), float(plan["target"])
    valid_until, max_days = plan.get("valid_until") or sig, int(plan.get("max_hold_days") or 20)
    qty = int(plan.get("qty") or 0)
    after = [b for b in bars if b["date"] > sig]
    out = {"status": "WAITING", "filled": None, "fill": None, "exited": None, "exit": None,
           "days": None, "r": None, "pnl_rs": None, "last": after[-1]["close"] if after else None,
           "checked": today}
    k_fill = None
    for k, b in enumerate(after):
        if b["date"] > valid_until:
            break
        if b["high"] >= entry:
            k_fill = k
            break
    if k_fill is None:
        last_date = after[-1]["date"] if after else sig
        if last_date >= valid_until or today > valid_until:
            out["status"] = "NOT TRIGGERED"
        return out
    b = after[k_fill]
    fill = max(b["open"], entry)
    risk = fill - stop
    out.update(filled=b["date"], fill=round(fill, 2))
    if risk <= 0:
        out.update(status="STOP", exited=b["date"], exit=round(b["open"], 2), days=1)
    else:
        cur_stop, res, n = stop, None, 0
        if b["low"] <= stop and b["close"] < fill:
            res = ("STOP", stop, b["date"], 1)
        else:
            for x in after[k_fill + 1:]:
                n += 1
                o, h, l, c = x["open"], x["high"], x["low"], x["close"]
                hit = "BREAKEVEN" if cur_stop >= fill else "STOP"
                if o <= cur_stop:
                    res = (hit, o, x["date"], n + 1)
                elif o >= target:
                    res = ("TARGET", o, x["date"], n + 1)
                elif l <= cur_stop:
                    res = (hit, cur_stop, x["date"], n + 1)
                elif h >= target:
                    res = ("TARGET", target, x["date"], n + 1)
                elif plan.get("mode") == "swing" and h >= fill + risk and cur_stop < fill:
                    cur_stop = fill
                if not res and n + 1 >= max_days:
                    res = ("TIME EXIT", c, x["date"], n + 1)
                if res:
                    break
        if res:
            out.update(status=res[0], exit=round(res[1], 2), exited=res[2], days=res[3])
            px = res[1]
        else:
            out.update(status="OPEN", days=len(after) - k_fill)
            px = after[-1]["close"]
        q = qty or 100
        pnl = q * (px - fill) - round_trip(fill, px, q, cfg)
        out["r"] = round(pnl / (q * risk), 2)
        if qty:
            out["pnl_rs"] = round(pnl, 2)
    return out


# ---------------------------------------------------------------------------
# Indian equity-delivery charges
# ---------------------------------------------------------------------------


def order_charges(side, price, qty, cfg):
    """Approximate charges for one CNC order leg. Verify with your broker."""
    ch = cfg["charges"]
    br = cfg["brokers"].get(cfg.get("broker", "zerodha"), cfg["brokers"]["custom"])
    turnover = price * qty
    brokerage = 0.0
    if br.get("brokerage_pct"):
        brokerage = turnover * br["brokerage_pct"] / 100.0
        if br.get("brokerage_cap"):
            brokerage = min(brokerage, br["brokerage_cap"])
        brokerage = max(brokerage, br.get("brokerage_min", 0.0))
    stt = turnover * ch["stt_pct"] / 100.0
    exch = turnover * ch["exchange_txn_pct"] / 100.0
    sebi = turnover * ch["sebi_fee_pct"] / 100.0
    ipft = turnover * ch.get("ipft_pct", 0) / 100.0
    stamp = turnover * ch["stamp_duty_buy_pct"] / 100.0 if side == "BUY" else 0.0
    gst = (brokerage + exch + ipft + sebi) * ch["gst_pct"] / 100.0   # IPFT is part of the transaction charge
    dp = br.get("dp_charge_per_sell", 0.0) if side == "SELL" else 0.0
    parts = {"brokerage": brokerage, "stt": stt, "exchange": exch, "sebi": sebi,
             "ipft": ipft, "stamp_duty": stamp, "gst": gst, "dp_charge": dp}
    total = round(sum(parts.values()), 2)          # sum unrounded parts, then round once
    parts = {k: round(v, 2) for k, v in parts.items()}
    parts["total"] = total
    return parts


def round_trip(entry, exit_price, qty, cfg):
    b = order_charges("BUY", entry, qty, cfg)
    s = order_charges("SELL", exit_price, qty, cfg)
    return round(b["total"] + s["total"], 2)


# ---------------------------------------------------------------------------
# Halal screening
# ---------------------------------------------------------------------------

# Well-known NSE symbols whose core business is impermissible. Not exhaustive:
# the business screen below also checks industry and company-name keywords.
KNOWN_EXCLUDED = {
    "ITC": "tobacco (cigarettes)", "GODFRYPHLP": "tobacco", "VSTIND": "tobacco",
    "UBL": "alcohol (beer)", "UNITDSPR": "alcohol (spirits)", "RADICO": "alcohol (spirits)",
    "TI": "alcohol (spirits)", "GLOBUSSPR": "alcohol", "DELTACORP": "casinos / gambling",
}
EXCLUDED_INDUSTRIES = ("financial services",)   # banks, NBFCs, insurers, lenders
REVIEW_INDUSTRIES = ("media, entertainment & publication", "media & entertainment")
EXCLUDE_WORDS = ("bank", "insurance", "assurance", "breweries", "brewery", "distiller",
                 "spirit", "liquor", "tobacco", "cigarette", "casino", "blender", "wine")
REVIEW_WORDS = ("finance", "financial", "fincorp", "finserv", "capital", "credit",
                "invest", "hotel", "resort", "entertainment", "media", "film", "gaming",
                "leisure")

STATUSES = ("compliant", "review", "excluded", "unknown")


def business_screen(sym, name="", industry=""):
    """First pass: is the core business permissible? -> (status, reasons)."""
    sym = normalize_symbol(sym)
    n, ind = (name or "").lower(), (industry or "").lower()
    if sym in KNOWN_EXCLUDED:
        return "excluded", ["core business: %s" % KNOWN_EXCLUDED[sym]]
    if any(ind.startswith(x) for x in EXCLUDED_INDUSTRIES):
        return "excluded", ["industry '%s': interest-based finance" % industry]
    words = re.findall(r"[a-z]+", n)
    has = lambda w: any(x.startswith(w) for x in words)    # "distillers" matches "distiller"
    for w in EXCLUDE_WORDS:
        if has(w):
            return "excluded", ["company name contains '%s'" % w]
    reasons = []
    if any(ind.startswith(x) for x in REVIEW_INDUSTRIES):
        reasons.append("industry '%s' needs a manual look" % industry)
    for w in REVIEW_WORDS:
        if has(w):
            reasons.append("company name contains '%s': check what it actually does" % w)
    return ("review", reasons) if reasons else ("pass", ["business screen passed"])


FUNDAMENTAL_TYPES = ("TotalDebt", "TotalAssets", "CashAndCashEquivalents",
                     "AccountsReceivable", "InterestIncome", "InterestIncomeNonOperating",
                     "TotalRevenue", "OtherShortTermInvestments", "OtherNonOperatingIncomeExpenses",
                     "OtherIncomeExpense")


def fetch_fundamentals(sym, freq="annual", types=FUNDAMENTAL_TYPES, exchange="NSE"):
    """Yahoo fundamentals-timeseries -> {type: [(as_of_date, value), ...]} oldest first."""
    ysym = yahoo_symbol(sym, exchange)
    p2 = int(time.time()) if not fixtures_dir() else 1893456000
    tlist = ",".join(freq + t for t in types)
    url = ("https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/%s"
           "?symbol=%s&type=%s&period1=1262304000&period2=%d"
           % (urllib.parse.quote(ysym), urllib.parse.quote(ysym), tlist, p2))
    obj = fetch_json(url, fixture="fundamentals/%s_%s.json" % (normalize_symbol(sym), freq))
    return parse_fundamentals(obj, freq)


def parse_fundamentals(obj, freq="annual"):
    out = {}
    for res in ((obj or {}).get("timeseries") or {}).get("result") or []:
        tname = ((res.get("meta") or {}).get("type") or [None])[0]
        if not tname:
            continue
        rows = []
        for item in res.get(tname) or []:
            if not item:
                continue
            v = (item.get("reportedValue") or {}).get("raw")
            if v is None:
                continue
            rows.append((item.get("asOfDate"), float(v)))
        if rows:
            out[tname[len(freq):] if tname.startswith(freq) else tname] = sorted(rows)
    return out


def latest(f, key):
    rows = f.get(key) or []
    return rows[-1][1] if rows else None


def financial_screen(f, cfg):
    """TASIS-style ratios from the latest annual numbers.

    debt / total assets                       < 25%
    (interest income + 8% of interest-bearing
     investments) / total income              < 3%
    (cash + receivables) / total assets       < 90%
    -> {"status", "ratios", "reasons", "as_of"}"""
    h = cfg["halal"]
    debt, assets = latest(f, "TotalDebt"), latest(f, "TotalAssets")
    cash, recv = latest(f, "CashAndCashEquivalents"), latest(f, "AccountsReceivable")
    interest = latest(f, "InterestIncome")
    if interest is None:
        interest = latest(f, "InterestIncomeNonOperating")
    sti = latest(f, "OtherShortTermInvestments") or 0.0
    rev = latest(f, "TotalRevenue")
    as_of = max([r[-1][0] for r in f.values() if r] or [None]) if f else None
    ratios, reasons, missing = {}, [], []
    if debt is not None and assets:
        ratios["debt_to_assets_pct"] = round(debt / assets * 100, 2)
    else:
        missing.append("debt/total assets")
    if rev:
        assumed = sti * h["noncompliant_investment_return_pct"] / 100.0
        nci = (interest or 0.0) + assumed
        # Total income as Indian annual reports define it: revenue + other income. Yahoo splits
        # "other income" into interest (reported separately) and a leftover "other" figure that
        # excludes interest, so: revenue + interest + max(other, 0). Yahoo does not break out
        # treasury / mutual-fund gains, so this can still read slightly high (the strict side).
        other = latest(f, "OtherNonOperatingIncomeExpenses")
        if other is None:
            other = latest(f, "OtherIncomeExpense")
        total_income = rev + (interest or 0.0) + max(other or 0.0, 0.0)
        ratios_basis = ("revenue + interest + other income" if other is not None
                        else "revenue + interest (other income not reported)")
        # Two figures, shown side by side:
        #   interest_income_pct      interest the company actually reported
        #   noncompliant_income_pct  that plus an ASSUMED 8% return on short-term investments (TASIS-style)
        ratios["interest_income_pct"] = round((interest or 0.0) / total_income * 100, 2)
        ratios["noncompliant_income_pct"] = round(nci / total_income * 100, 2)
        ratios["assumed_return_pct"] = round(assumed / total_income * 100, 2)
        ratios["total_income_basis"] = ratios_basis
        if interest is None:
            reasons.append("interest income not reported: non-compliant income ratio is a lower bound")
    else:
        missing.append("revenue")
    if assets and (cash is not None or recv is not None):
        ratios["cash_receivables_to_assets_pct"] = round(((cash or 0) + (recv or 0)) / assets * 100, 2)
    else:
        missing.append("cash+receivables/total assets")
    fail = []
    if ratios.get("debt_to_assets_pct", 0) >= h["max_debt_to_assets_pct"]:
        fail.append("debt is %.1f%% of total assets (limit %.0f%%)"
                    % (ratios["debt_to_assets_pct"], h["max_debt_to_assets_pct"]))
    lim = h["max_noncompliant_income_pct"]
    income_fail = ratios.get("noncompliant_income_pct", 0) >= lim
    assumption_only = income_fail and ratios.get("interest_income_pct", 0) < lim
    if income_fail:
        fail.append("non-compliant income is %.2f%% of total income (limit %.0f%%): reported interest "
                    "%.2f%% + assumed 8%% return on short-term investments %.2f%%"
                    % (ratios["noncompliant_income_pct"], lim, ratios["interest_income_pct"],
                       ratios["assumed_return_pct"]))
    if ratios.get("cash_receivables_to_assets_pct", 0) >= h["max_cash_receivables_to_assets_pct"]:
        fail.append("cash + receivables are %.1f%% of total assets (limit %.0f%%)"
                    % (ratios["cash_receivables_to_assets_pct"], h["max_cash_receivables_to_assets_pct"]))
    only_income = len(fail) == 1 and income_fail
    if only_income and assumption_only:
        # Reported interest passes; only the assumed return on investments tips it over. The real
        # return on those investments is in the annual report's "Other income" note.
        status = "review"
        reasons = fail + ["reported interest %.2f%% passes; only the assumed 8%% return pushes it over. "
                          "Check the annual report's Other income note (treasury / mutual fund gains)"
                          % ratios["interest_income_pct"]] + reasons
    elif only_income and ratios["noncompliant_income_pct"] < 2 * lim:
        # Reported interest itself is over the limit, but by under 2x: free data may lump other
        # income into "interest". Review (still blocked by default), not straight to excluded.
        status = "review"
        reasons = fail + ["reported interest is over the limit by under 2x: verify with an "
                          "official Shariah list or the annual report"] + reasons
    elif fail:
        status = "excluded"
        reasons = fail + reasons
    elif missing:
        status = "unknown"
        reasons = ["missing data: " + ", ".join(missing)] + reasons
    else:
        status = "compliant"
        reasons = ["all three TASIS-style ratios within limits"] + reasons
    return {"status": status, "ratios": ratios, "reasons": reasons, "as_of": as_of}


def load_universe():
    return read_json("halal_universe.json", {"stocks": {}}) or {"stocks": {}}


def halal_status(sym, universe=None):
    """Status for one symbol, with user overrides applied last.
    -> {"status", "reasons", "source", ...} (status 'unknown' if not listed)."""
    sym = normalize_symbol(sym)
    uni = universe if universe is not None else load_universe()
    rec = dict((uni.get("stocks") or {}).get(sym) or {"status": "unknown",
                                                       "reasons": ["not in the halal universe"]})
    ov = (read_json("halal_overrides.json", {}) or {}).get(sym)
    if ov and ov.get("status") in STATUSES:
        rec["status"] = ov["status"]
        rec["reasons"] = ["user override: %s" % ov.get("note", "no note")] + list(rec.get("reasons", []))
        rec["source"] = "override"
    if sym in KNOWN_EXCLUDED and rec.get("source") != "override":
        rec["status"] = "excluded"
        rec["reasons"] = ["core business: %s" % KNOWN_EXCLUDED[sym]]
    rec["symbol"] = sym
    return rec


def universe_age_days(universe=None):
    uni = universe if universe is not None else load_universe()
    u = uni.get("updated")
    if not u:
        return None
    return (today_ist() - parse_date(u)).days


def read_index_csv(text):
    """NSE index constituent CSV (Company Name, Industry, Symbol, Series, ISIN)
    or any CSV with a Symbol column -> list of dicts."""
    rows = []
    rdr = csv.DictReader(io.StringIO(text))
    for r in rdr:
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        sym = r.get("symbol") or r.get("nse symbol") or r.get("ticker") or r.get("nse code")
        if not sym or sym.upper().startswith("DUMMY"):    # NSE placeholder rows
            continue
        rows.append({"symbol": normalize_symbol(sym),
                     "name": r.get("company name") or r.get("name") or r.get("company") or "",
                     "industry": r.get("industry") or r.get("sector") or "",
                     "isin": r.get("isin code") or r.get("isin") or ""})
    return rows


# ---------------------------------------------------------------------------
# News feeds (RSS 2.0 and Atom)
# ---------------------------------------------------------------------------


def _strip_tags(s):
    import html
    s = html.unescape(html.unescape(s or ""))          # twice: some feeds double-encode (&amp;amp;)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def _parse_when(s):
    if not s:
        return None
    s = s.strip()
    from email.utils import parsedate_to_datetime
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        d = None
    if d is None:
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=IST)
    return d.astimezone(IST)


def parse_feed(body, source=""):
    """RSS/Atom bytes -> [{title, link, published (IST ISO), source, summary}]."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    items = []
    atom = "{http://www.w3.org/2005/Atom}"
    nodes = root.findall(".//item") or root.findall(".//%sentry" % atom)
    for it in nodes:
        def t(tag):
            e = it.find(tag)
            if e is None:
                e = it.find(atom + tag)
            return (e.text or "") if e is not None else ""
        link = t("link")
        if not link:
            le = it.find(atom + "link")
            link = le.get("href", "") if le is not None else ""
        when = _parse_when(t("pubDate") or t("published") or t("updated"))
        src = it.find("source")
        items.append({
            "title": _strip_tags(t("title")), "link": link.strip(),
            "published": when.isoformat() if when else None,
            "source": (src.text.strip() if src is not None and src.text else source),
            "summary": _strip_tags(t("description") or t("summary"))[:300],
        })
    return items


# ---------------------------------------------------------------------------
# Hard rules: these cannot be switched off from config
# ---------------------------------------------------------------------------

HARD_RULES = (
    "product must be CNC (delivery): no MIS/intraday, no NRML, no margin (MTF)",
    "BUY to open only: no short selling; SELL only shares you already hold",
    "cash equities only: no futures, options or other derivatives",
    "every order needs the user's explicit yes; nothing here places orders",
)


def guard_order(order, holdings=None):
    """-> list of hard-rule violations (empty means the order may go on to risk checks)."""
    v = []
    prod = (order.get("product") or "").upper()
    if prod != "CNC":
        v.append("product %r is not CNC: only delivery is allowed" % (order.get("product"),))
    side = (order.get("side") or "").upper()
    sym = normalize_symbol(order.get("symbol"))
    if side not in ("BUY", "SELL"):
        v.append("side %r must be BUY or SELL" % (order.get("side"),))
    if side == "SELL":
        held = (holdings or {}).get(sym, 0)
        if order.get("qty", 0) > held:
            v.append("SELL %s of %s but only %s held: short selling is not allowed"
                     % (order.get("qty"), sym, held))
    if is_derivative(sym) or order.get("instrument", "EQ") not in ("EQ", "BE", None):
        v.append("%s looks like a derivative: cash equities only" % sym)
    if order.get("margin") or order.get("leverage") or order.get("mtf"):
        v.append("margin / leverage / MTF is not allowed")
    q = order.get("qty")
    if not isinstance(q, int) or q <= 0:
        v.append("quantity must be a positive whole number")
    return v


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def fmt_rs(x, dec=2):
    """Indian digit grouping: 1234567.8 -> 'Rs 12,34,567.80'."""
    if x is None:
        return "-"
    neg = x < 0
    s = ("%." + str(dec) + "f") % abs(x)
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        whole = head + "," + tail
    out = "Rs " + whole + ("." + frac if frac else "")
    return "-" + out if neg else out


def print_json(obj):
    sys.stdout.write(json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n")


def die(msg, code=1):
    sys.stderr.write("error: %s\n" % msg)
    sys.exit(code)


DISCLAIMER = ("Not financial advice. Not a fatwa. Software that reads public data and does "
              "arithmetic; check everything with your broker and your scholar.")
