"""tayyib_core: the shared library behind every tayyib-trader skill.

Standard library only, Python 3.8+. The canonical copy lives in
core/tayyib_core.py; `python3 tools/sync_core.py` copies it into every skill
folder so each skill still works when its folder is copied on its own.
Do not edit the copies inside the skill folders: edit this file and sync.

What lives here:
  config + the trader/ folder   load_config, validate_config, settings_snapshot, risk_preview
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

import copy
import csv
import datetime as dt
import gzip
import hashlib
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

VERSION = "0.1.5"
# Bump DEFAULTS_VERSION only when a default value changes behaviour (tests/fixtures/defaults_versions.json
# records the defaults of every version, and a test fails if one changes without a bump). Adding a
# key whose default keeps the old behaviour needs no bump.
DEFAULTS_VERSION = 1
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
    # setup detection, liquidity window and ranking (v0.1.5: moved here from the code, same values)
    "scanner": {
        "warmup_bars": 200,             # no signal before this many bars of history
        "min_history_bars": 210,        # the scanner skips stocks with less history
        "liquidity_days": 20,           # window for the average traded value
        "setups": {
            "breakout": {"enabled": True, "trend_fast_ma": 50, "trend_slow_ma": 200, "trend_slope_days": 10,
                         "high_lookback_days": 20, "max_distance_to_high_pct": 3.0,
                         "volume_fast_days": 5, "volume_slow_days": 20, "volume_dry_ratio": 0.9,
                         "trigger_buffer_pct": 0.2, "invalidation_lookback_days": 5, "valid_days": 3,
                         "min_score": 0},
            "pullback": {"enabled": True, "trend_fast_ma": 50, "trend_slow_ma": 200, "trend_slope_days": 10,
                         "ema_length": 20, "touch_band_pct": 1.0, "max_close_below_ema_pct": 1.5,
                         "rsi_length": 14, "rsi_min": 35, "rsi_max": 58,
                         "trigger_buffer_pct": 0.2, "invalidation_lookback_days": 3,
                         "invalidation_buffer_pct": 0.2, "valid_days": 3, "min_score": 0},
            "oversold": {"enabled": True, "trend_slow_ma": 200, "rsi_length": 14, "rsi_below": 35,
                         "rsi_lookback_days": 4, "require_green_day": True,
                         "trigger_buffer_pct": 0.2, "invalidation_lookback_days": 6, "valid_days": 3,
                         "min_score": 0},
            "squeeze": {"enabled": True, "trend_fast_ma": 50, "trend_slow_ma": 200, "trend_slope_days": 10,
                        "recent_days": 10, "prior_days": 30, "max_range_ratio": 0.5,
                        "max_recent_range_pct": 8.0, "trigger_buffer_pct": 0.2, "valid_days": 3,
                        "min_score": 0},
            "trend": {"enabled": True, "fast_ma": 50, "slow_ma": 200, "slope_days": 20,
                      "high_lookback_days": 252, "min_pct_of_high": 85.0, "return_lookback_days": 126,
                      "min_return_pct": 0.0, "invalidation_lookback_days": 20, "ma_buffer_pct": 3.0,
                      "trigger_buffer_pct": 0.2, "valid_days": 5, "min_score": 0},
        },
    },
    # tayyib-daily (its --top / --picks flags still override these)
    "daily": {
        "top": 10,                      # plan at most N stocks
        "picks": 3,                     # highlight the best N PASS stocks
        "min_expectancy_r": None,       # skip stocks whose time-machine expectancy is lower (null = no filter)
    },
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
        "method": "tasis",              # "tasis" or "custom" (thresholds that differ from TASIS)
        "loosen_note": "",              # REQUIRED to loosen any threshold: your source or scholar
        "require_compliant": True,      # locked: a hard rule, cannot be switched off
        "allow_review": False,          # treat 'review' as BLOCK unless true (loosening: needs loosen_note)
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


# ---------------------------------------------------------------------------
# Config documentation and validation. DEFAULT_CONFIG_DOCS is what a settings UI renders:
# key (dotted) -> {description, min, max, unit, type, ...}. Every user value is checked
# against it; an invalid value falls back to its default for that key only and is reported.
# Hard rules (CNC only, no shorting, no F&O, no margin, compliant stocks only) have no key.
# ---------------------------------------------------------------------------

def _doc(description, min=None, max=None, unit=None, type="number", **kw):
    d = {"description": description, "min": min, "max": max, "unit": unit, "type": type}
    d.update(kw)
    return d


TASIS_HALAL = {"max_debt_to_assets_pct": 25.0, "max_noncompliant_income_pct": 3.0,
               "max_cash_receivables_to_assets_pct": 90.0, "noncompliant_investment_return_pct": 8.0}

DEFAULT_CONFIG_DOCS = {
    "capital": _doc("Your trading capital in rupees: sizing and every % limit use it", 1000, 1e10, "Rs"),
    "max_risk_per_trade_pct": _doc("Most you lose on one trade if its stop is hit, incl. charges, as % of "
                                   "capital. Not the stop distance", 0.25, 3, "%"),
    "max_risk_per_trade_rs": _doc("Optional rupee cap on the loss per trade (null = none)", 1, 1e8, "Rs",
                                  nullable=True),
    "max_position_pct": _doc("Most of your capital in any one stock", 5, 40, "%"),
    "max_open_positions": _doc("Most open positions plus approved tickets at once", 1, 20, "positions",
                               type="int"),
    "max_portfolio_heat_pct": _doc("Most total loss if every open stop were hit at once, as % of capital",
                                   1, 15, "%"),
    "max_positions_per_industry": _doc("Most positions in one industry", 1, 20, "positions", type="int"),
    "min_reward_risk": _doc("Least net reward:risk a plan must offer after charges", 1, 5, "R"),
    "cash_available": _doc("Cash you can use (null = capital minus open positions)", 0, 1e10, "Rs",
                           nullable=True),
    "exchange": _doc("Exchange for tickets", type="enum", choices=["NSE", "BSE"]),
    "tick_size": _doc("Price step for rounding entries, stops and targets", 0.01, 1, "Rs"),
    "min_price": _doc("Skip stocks priced under this", 1, 100000, "Rs"),
    "min_turnover_rs": _doc("Skip stocks whose average daily traded value is under this (at least Rs 50 lakh)",
                            5000000, 1e11, "Rs"),
    "holidays": _doc("NSE trading holidays, YYYY-MM-DD (used for plan dates)", type="dates"),
    "scanner.warmup_bars": _doc("No setup is armed before this many bars of history", 60, 400, "bars",
                                type="int"),
    "scanner.min_history_bars": _doc("The scanner skips stocks with less history than this", 60, 500, "bars",
                                     type="int"),
    "scanner.liquidity_days": _doc("Days averaged for the traded-value (liquidity) filter", 5, 60, "days",
                                   type="int"),
    "modes.swing.atr_mult_cap": _doc("Swing: a structure stop wider than this many ATR is replaced", 1, 6, "ATR"),
    "modes.swing.atr_fallback": _doc("Swing: the ATR stop used when the structure stop is too wide", 0.5, 5,
                                     "ATR"),
    "modes.swing.min_stop_atr": _doc("Swing: the stop is never closer than this many ATR", 0.25, 3, "ATR"),
    "modes.swing.max_stop_pct": _doc("Swing: the stop is never further below the entry than this", 2, 10, "%"),
    "modes.swing.target_r": _doc("Swing: target as a multiple of the risk", 1, 6, "R"),
    "modes.swing.max_hold_days": _doc("Swing: time stop, in trading sessions", 1, 60, "sessions", type="int"),
    "modes.delivery.max_stop_pct": _doc("Delivery: the stop is never further below the entry than this", 3, 15,
                                        "%"),
    "modes.delivery.min_stop_atr": _doc("Delivery: the stop is never closer than this many ATR", 0.5, 5, "ATR"),
    "modes.delivery.target_r": _doc("Delivery: review level as a multiple of the risk", 1, 10, "R"),
    "modes.delivery.max_hold_days": _doc("Delivery: time stop, in trading sessions", 20, 750, "sessions",
                                         type="int"),
    "broker": _doc("Broker whose charges are used", type="enum", choices=["zerodha", "groww", "custom"]),
    "charges.stt_pct": _doc("STT on delivery, each side", 0, 1, "%"),
    "charges.exchange_txn_pct": _doc("Exchange transaction charge", 0, 0.1, "%"),
    "charges.sebi_fee_pct": _doc("SEBI turnover fee", 0, 0.01, "%"),
    "charges.ipft_pct": _doc("NSE investor protection fund charge", 0, 0.01, "%"),
    "charges.stamp_duty_buy_pct": _doc("Stamp duty on the buy", 0, 0.1, "%"),
    "charges.gst_pct": _doc("GST on brokerage + exchange + SEBI charges", 0, 30, "%"),
    "halal.method": _doc("'tasis' (the NSE Shariah index method) or 'custom' (your own thresholds)",
                         type="enum", choices=["tasis", "custom"]),
    "halal.loosen_note": _doc("Your source or scholar. Required for any threshold looser than TASIS",
                              type="string"),
    "halal.require_compliant": _doc("Locked: only compliant stocks can pass (a hard rule)", type="locked",
                                    choices=[True]),
    "halal.allow_review": _doc("Let 'review' stocks through with a WARN. Loosening: needs halal.loosen_note",
                               type="bool"),
    "halal.list_max_age_days": _doc("Warn when the halal list is older than this", 7, 365, "days", type="int"),
    "halal.auto_rebuild_days": _doc("tayyib-daily rebuilds the halal list when older (0 = never)", 0, 365, "days",
                                    type="int"),
    "halal.max_debt_to_assets_pct": _doc("Debt / total assets must be under this (TASIS 25; higher needs "
                                         "loosen_note)", 1, 50, "%"),
    "halal.max_noncompliant_income_pct": _doc("Non-compliant income / total income must be under this (TASIS 3; "
                                              "higher needs loosen_note)", 0.1, 10, "%"),
    "halal.max_cash_receivables_to_assets_pct": _doc("(Cash + receivables) / total assets must be under this "
                                                     "(TASIS 90; higher needs loosen_note)", 10, 100, "%"),
    "halal.noncompliant_investment_return_pct": _doc("Return assumed on short-term investments for the income "
                                                     "test (TASIS 8; lower needs loosen_note)", 0, 20, "%"),
    "halal.list_url": _doc("Optional CSV URL of an official Shariah list", type="string", nullable=True),
    "halal.parent_list_url": _doc("The index list that is self-screened", type="string"),
    "news.feeds": _doc("RSS feeds read for market news: name -> URL", type="map"),
    "news.google_news": _doc("Search Google News India per stock", type="bool"),
    "news.nse_announcements": _doc("Read NSE corporate announcements per stock", type="bool"),
    "user_agent": _doc("User agent for data requests", type="string"),
    "daily.top": _doc("tayyib-daily plans at most this many stocks (--top overrides)", 1, 50, "stocks",
                      type="int"),
    "daily.picks": _doc("tayyib-daily highlights this many PASS stocks (--picks overrides)", 0, 20, "stocks",
                        type="int"),
    "daily.min_expectancy_r": _doc("Skip stocks whose time-machine expectancy is under this (null = no filter)",
                                   -2, 2, "R", nullable=True),
}
for _b in ("zerodha", "groww", "custom"):
    DEFAULT_CONFIG_DOCS.update({
        "brokers.%s.brokerage_pct" % _b: _doc("%s: brokerage as %% of each order" % _b, 0, 2, "%"),
        "brokers.%s.brokerage_min" % _b: _doc("%s: minimum brokerage per order" % _b, 0, 100, "Rs"),
        "brokers.%s.brokerage_cap" % _b: _doc("%s: maximum brokerage per order (0 = none)" % _b, 0, 1000, "Rs"),
        "brokers.%s.dp_charge_per_sell" % _b: _doc("%s: depository charge per sell" % _b, 0, 100, "Rs"),
    })
_TREND_DOCS = (("trend_fast_ma", "uptrend: fast moving average length", 5, 150, "days"),
               ("trend_slow_ma", "uptrend: slow moving average length", 50, 300, "days"),
               ("trend_slope_days", "uptrend: the fast average must be higher than this many days ago", 1, 60,
                "days"))
_SETUP_DOCS = {
    "breakout": _TREND_DOCS + (
        ("high_lookback_days", "the recent high is the highest high of this many days", 5, 120, "days"),
        ("max_distance_to_high_pct", "the close must be within this % under that high", 0.5, 10, "%"),
        ("volume_fast_days", "volume dry-up: short average length", 2, 20, "days"),
        ("volume_slow_days", "volume dry-up: long average length", 5, 60, "days"),
        ("volume_dry_ratio", "score bonus when short / long volume average is under this", 0.3, 1.5, "ratio"),
        ("invalidation_lookback_days", "stop structure: lowest low of this many days", 2, 30, "days")),
    "pullback": _TREND_DOCS + (
        ("ema_length", "the pullback average (EMA) length", 5, 100, "days"),
        ("touch_band_pct", "the day's low must come within this % above the EMA", 0, 5, "%"),
        ("max_close_below_ema_pct", "the close may be at most this % under the EMA", 0, 5, "%"),
        ("rsi_length", "RSI length", 2, 50, "days"),
        ("rsi_min", "RSI must be at least this", 0, 100, "RSI"),
        ("rsi_max", "RSI must be at most this", 0, 100, "RSI"),
        ("invalidation_lookback_days", "stop structure: lowest low of this many days", 2, 30, "days"),
        ("invalidation_buffer_pct", "stop structure sits this % under that low", 0, 5, "%")),
    "oversold": (
        ("trend_slow_ma", "the close must be above this moving average", 50, 300, "days"),
        ("rsi_length", "RSI length", 2, 50, "days"),
        ("rsi_below", "RSI must have dipped under this", 5, 50, "RSI"),
        ("rsi_lookback_days", "the RSI dip counts within this many days", 1, 20, "days"),
        ("require_green_day", "the signal day must close above its open", None, None, None, "bool"),
        ("invalidation_lookback_days", "stop structure: lowest low of this many days", 2, 30, "days")),
    "squeeze": _TREND_DOCS + (
        ("recent_days", "the recent (tight) range: this many days", 3, 40, "days"),
        ("prior_days", "the earlier range it is compared with: this many days", 10, 120, "days"),
        ("max_range_ratio", "the recent range must be under this fraction of the earlier range", 0.1, 0.9,
         "ratio"),
        ("max_recent_range_pct", "the recent range must be under this % of the price", 1, 30, "%")),
    "trend": (
        ("fast_ma", "fast moving average length", 5, 150, "days"),
        ("slow_ma", "slow (long-term) moving average length", 50, 300, "days"),
        ("slope_days", "the slow average must be higher than this many days ago", 1, 120, "days"),
        ("high_lookback_days", "the 52-week high: highest high of this many days", 60, 400, "days"),
        ("min_pct_of_high", "the close must be at least this % of that high", 50, 100, "%"),
        ("return_lookback_days", "return measured over this many days", 20, 260, "days"),
        ("min_return_pct", "that return must be above this", -50, 200, "%"),
        ("invalidation_lookback_days", "stop structure: lowest low of this many days", 5, 60, "days"),
        ("ma_buffer_pct", "or this % under the slow average, whichever is higher", 0, 10, "%")),
}
for _s, _rows in _SETUP_DOCS.items():
    _pre = "scanner.setups.%s." % _s
    DEFAULT_CONFIG_DOCS[_pre + "enabled"] = _doc("%s setup on (true) or off (false)" % _s, type="bool")
    for _r in _rows:
        _k, _desc, _mn, _mx, _u = _r[:5]
        _t = _r[5] if len(_r) > 5 else ("int" if _u == "days" else "number")
        DEFAULT_CONFIG_DOCS[_pre + _k] = _doc(_desc, _mn, _mx, _u, type=_t)
    DEFAULT_CONFIG_DOCS[_pre + "trigger_buffer_pct"] = _doc("the buy-stop trigger sits this % above the level",
                                                            0, 2, "%")
    DEFAULT_CONFIG_DOCS[_pre + "valid_days"] = _doc("the trigger stays valid this many sessions", 1, 20,
                                                    "sessions", type="int")
    DEFAULT_CONFIG_DOCS[_pre + "min_score"] = _doc("ignore signals scoring under this", 0, 200, "score")

# words in an unknown key that ask for something the hard rules forbid: the warning says so
_HARD_RULE_WORDS = {"intraday", "mis", "nrml", "short", "shorting", "shorts", "fno", "f&o", "futures", "future",
                    "options", "option", "derivative", "derivatives", "margin", "mtf", "leverage", "product",
                    "excluded", "unknown", "noncompliant", "non", "orders", "order", "autotrade", "auto"}


def _fmt_val(v):
    if isinstance(v, float) and v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return json.dumps(v, ensure_ascii=False, default=str)


def _expect(doc):
    t = doc["type"]
    if t in ("number", "int"):
        return "range %s–%s" % (_fmt_val(doc["min"]), _fmt_val(doc["max"]))
    if t in ("enum", "locked"):
        return "one of %s" % ", ".join(_fmt_val(c) for c in doc["choices"])
    return {"bool": "true or false", "string": "text", "dates": "a list of YYYY-MM-DD dates",
            "map": "an object of name: URL text"}.get(t, t)


def _check_value(doc, v):
    """-> (ok, cleaned value)."""
    t = doc["type"]
    if v is None:
        return bool(doc.get("nullable")), v
    if t in ("number", "int"):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            return False, v
        if t == "int":
            if v != int(v):
                return False, v
            v = int(v)
        lo, hi = doc.get("min"), doc.get("max")
        return (lo is None or v >= lo) and (hi is None or v <= hi), v
    if t == "bool":
        return isinstance(v, bool), v
    if t in ("enum", "locked"):
        return any(v == c and type(v) == type(c) for c in doc["choices"]), v
    if t == "string":
        return isinstance(v, str), v
    if t == "dates":
        if not isinstance(v, list):
            return False, v
        for x in v:
            try:
                dt.datetime.strptime(x, "%Y-%m-%d")
            except (TypeError, ValueError):
                return False, v
        return True, v
    if t == "map":
        return isinstance(v, dict) and all(isinstance(x, str) for x in v.values()), v
    return False, v


def _clean_user(user, defaults, prefix, notes):
    """Walk the user's config against the defaults and the docs -> a cleaned overlay."""
    out = {}
    for k, v in user.items():
        key = prefix + str(k)
        doc = DEFAULT_CONFIG_DOCS.get(key)
        dflt = defaults.get(k) if isinstance(defaults, dict) else None
        if doc is None and isinstance(dflt, dict):
            if not isinstance(v, dict):
                notes.append("CONFIG: %s = %s invalid (expected an object of settings), using the defaults"
                             % (key, _fmt_val(v)))
                continue
            out[k] = _clean_user(v, dflt, key + ".", notes)
            continue
        if doc is None:
            words = set(re.split(r"[._\- ]+", key.lower()))
            if words & _HARD_RULE_WORDS:
                notes.append("CONFIG: unknown key %s ignored: delivery (CNC) only, no intraday, F&O, short "
                             "selling or margin, compliant stocks only, and no order placement are hard rules, "
                             "not settings" % key)
            else:
                notes.append("CONFIG: unknown key %s ignored" % key)
            continue
        ok, cv = _check_value(doc, v)
        if ok:
            out[k] = cv
        elif doc["type"] == "locked":
            notes.append("CONFIG: %s = %s ignored: it is a hard rule and stays %s"
                         % (key, _fmt_val(v), _fmt_val(dflt)))
        else:
            notes.append("CONFIG: %s = %s invalid (%s), using default %s"
                         % (key, _fmt_val(v), _expect(doc), _fmt_val(dflt)))
    return out


def _halal_policy(cfg, notes):
    """TASIS thresholds unless the user sets their own. Stricter: free. Looser (or allow_review):
    only with a non-empty halal.loosen_note, otherwise an error and the TASIS value."""
    h = cfg["halal"]
    note = (h.get("loosen_note") or "").strip()
    looser = [k for k, tv in TASIS_HALAL.items()
              if (h[k] < tv if k == "noncompliant_investment_return_pct" else h[k] > tv)]
    if h.get("allow_review"):
        looser.append("allow_review")
    if looser and not note:
        for k in looser:
            dv = DEFAULT_CONFIG["halal"][k]
            notes.append("CONFIG ERROR: halal.%s = %s is looser than TASIS (%s) and needs halal.loosen_note "
                         "(your source or scholar), using %s" % (k, _fmt_val(h[k]), _fmt_val(dv), _fmt_val(dv)))
            h[k] = dv
        looser = []
    differs = [k for k in TASIS_HALAL if h[k] != TASIS_HALAL[k]]
    if differs and h.get("method") == "tasis":
        notes.append("CONFIG: halal thresholds differ from TASIS (%s): halal.method is custom"
                     % ", ".join("%s %s" % (k, _fmt_val(h[k])) for k in differs))
        h["method"] = "custom"
    cfg["_halal_loosened"] = note if looser else None
    cfg["_halal_looser_keys"] = looser


def validate_config(user, defaults=None):
    """Validate a user config (the contents of config.json) -> (cfg, notes).

    cfg is the defaults overlaid with every valid user value; an invalid value falls back to its
    default for that key only. notes lists every fallback, unknown key and halal-policy error as
    "CONFIG: ..." text; cfg["_notes"] carries the same list for scripts to report."""
    defaults = copy.deepcopy(defaults or DEFAULT_CONFIG)
    notes = []
    if not isinstance(user, dict):
        notes.append("CONFIG: config.json is not an object of settings: using the defaults")
        user = {}
    cfg = deep_merge(defaults, _clean_user(user, defaults, "", notes))
    _halal_policy(cfg, notes)
    cfg["_notes"] = notes
    return cfg, notes


def load_config():
    """Defaults, overlaid with the valid values of trader/config.json (see validate_config)."""
    try:
        user = read_json("config.json", {})
    except ValueError as e:
        cfg, _ = validate_config({})
        cfg["_notes"].append("CONFIG: config.json could not be read (%s): using the defaults" % e)
        return cfg
    return validate_config({} if user is None else user)[0]


def config_notes(cfg):
    return list((cfg or {}).get("_notes") or [])


def report_config(cfg):
    """Print each config note to stderr (never stdout, so --json output stays clean)."""
    for n in config_notes(cfg):
        sys.stderr.write(n + "\n")


def halal_banner(cfg, universe=None):
    """The line every daily list and halal list output starts with when thresholds are looser than
    TASIS, in the config now or in the halal list as it was built. None otherwise."""
    note = (cfg or {}).get("_halal_loosened")
    if note:
        return "Halal thresholds are looser than TASIS (your setting): %s" % note
    built = (universe or {}).get("loosened")
    if built:
        return ("Halal thresholds are looser than TASIS (your setting): %s (the halal list was built with "
                "them; rebuild it to drop them)" % built)
    return None


# Keys that change no decision; every other key is part of the settings snapshot.
# display or transport only: user_agent (HTTP header), halal.loosen_note (banner text; the thresholds it
# allows are recorded as values), halal.list_url (documented but read by no script yet)
SETTINGS_EXCLUDE = ("user_agent", "halal.list_url", "halal.loosen_note")


def _decision_values(cfg):
    vals = copy.deepcopy({k: v for k, v in cfg.items() if not str(k).startswith("_")})
    for dotted in SETTINGS_EXCLUDE:
        ks = dotted.split(".")
        d = vals
        for k in ks[:-1]:
            d = d.get(k) if isinstance(d, dict) else None
        if isinstance(d, dict):
            d.pop(ks[-1], None)
    return vals


def _leaves(d, prefix=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict) and v:
            out.update(_leaves(v, prefix + str(k) + "."))
        else:
            out[prefix + str(k)] = v
    return out


def default_values():
    """Every decision-affecting default as flat dotted keys (what DEFAULTS_VERSION stands for)."""
    return _leaves(_decision_values(validate_config({})[0]))


def settings_snapshot(cfg):
    """-> {hash, label, defaults_version, values, differs_from_default[]}.

    hash: the first 8 hex characters of the sha1 of the canonical JSON (sorted keys, no spaces) of
    {"defaults_version": DEFAULTS_VERSION, "differs": [[key, value], ...]}, so it depends only on
    what you changed and on which set of defaults you changed it from. A new key whose default keeps
    the old behaviour does not change it. label: "default@<DEFAULTS_VERSION>" when nothing differs,
    otherwise the hash."""
    vals = _decision_values(cfg)
    base, mine = default_values(), _leaves(vals)
    differs = [{"key": k, "value": mine.get(k), "default": base.get(k)}
               for k in sorted(set(base) | set(mine)) if mine.get(k) != base.get(k)]
    canon = json.dumps({"defaults_version": DEFAULTS_VERSION, "differs": [[d["key"], d["value"]] for d in differs]},
                       sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    h = hashlib.sha1(canon.encode("utf-8")).hexdigest()[:8]
    return {"hash": h, "label": "default@%d" % DEFAULTS_VERSION if not differs else h,
            "defaults_version": DEFAULTS_VERSION, "values": vals, "differs_from_default": differs}


def risk_preview(cfg, stops_pct=(2, 3, 5, 8, 10, 15), entry=1000.0):
    """What the risk settings mean in rupees: the drawdown after 3, 5 and 10 losses in a row (each
    loss is the risk % of what is left), the rupee loss per trade, and which limit sets the quantity
    for sample stop distances: risk % or max position %. Charges are left out."""
    cap = float(cfg["capital"])
    budget = cap * cfg["max_risk_per_trade_pct"] / 100.0
    if cfg.get("max_risk_per_trade_rs"):
        budget = min(budget, float(cfg["max_risk_per_trade_rs"]))
    r = budget / cap
    max_pos = cap * cfg["max_position_pct"] / 100.0
    streaks = []
    for n in (3, 5, 10):
        left = cap * (1 - r) ** n
        streaks.append({"losses": n, "drawdown_pct": round((1 - (1 - r) ** n) * 100, 2),
                        "capital_left_rs": round(left, 2), "lost_rs": round(cap - left, 2),
                        "simple_sum_pct": round(n * r * 100, 2)})
    samples = []
    for sp in stops_pct:
        sp = float(sp)
        per_share = entry * sp / 100.0
        q_risk = int(budget // per_share) if per_share > 0 else 0
        q_pos = int(max_pos // entry)
        q = min(q_risk, q_pos)
        samples.append({"stop_pct": sp, "entry": entry, "qty_by_risk": q_risk, "qty_by_position": q_pos,
                        "qty": q, "binding": "risk" if q_risk < q_pos else "position" if q_pos < q_risk else "both",
                        "position_rs": round(q * entry, 2), "position_pct": round(q * entry / cap * 100, 2),
                        "loss_at_stop_rs": round(q * per_share, 2)})
    cross = budget / max_pos * 100 if max_pos else None
    return {"capital": cap, "risk_per_trade_pct": cfg["max_risk_per_trade_pct"],
            "risk_per_trade_rs": round(budget, 2), "effective_risk_pct": round(r * 100, 4),
            "max_position_pct": cfg["max_position_pct"], "max_position_rs": round(max_pos, 2),
            "losing_streaks": streaks, "binding_stop_pct": None if cross is None else round(cross, 2),
            "samples": samples,
            "explain": ("Risk per trade is what you lose when a stop is hit, not how far away the stop is. "
                        "Stops wider than %.2f%% are sized by the risk (%s at the stop); stops tighter than that "
                        "hit the %s%% max position first, so the loss at the stop is smaller."
                        % (cross or 0, fmt_rs(budget, 0), _fmt_val(cfg["max_position_pct"]))),
            "note": "Before charges (STT, stamp duty, GST, DP charge). tayyib-budget includes them, so its "
                    "quantities can be a share or two lower."}


# ---------------------------------------------------------------------------
# why[]: the checks behind each decision, recorded when the decision is made
# ---------------------------------------------------------------------------

WHY_GROUPS = ("HALAL", "LIQUIDITY", "SETUP", "NEWS", "PLAN", "HISTORY", "RISK")


def why_item(group, check, value=None, limit=None, op=None, ok=None, unit=None, note=None):
    """One reason. ok is True / False, or None when the input was missing (never a made-up 0)."""
    return {"group": group, "check": check, "value": value, "limit": limit, "op": op, "ok": ok,
            "unit": unit, "note": note}


def cmp_op(value, op, limit):
    """value op limit -> True / False, or None when either side is missing."""
    if value is None or limit is None:
        return None
    return {"<": value < limit, "<=": value <= limit, ">": value > limit, ">=": value >= limit,
            "==": value == limit}[op]


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
        "close": closes, "volume": vols,
        "sma20": sma(closes, 20), "sma50": sma(closes, 50), "sma200": sma(closes, 200),
        "ema20": ema(closes, 20), "rsi14": rsi(closes, 14), "atr14": atr(bars, 14),
        "vol20": sma(vols, 20), "vol5": sma(vols, 5),
    }


def series(ind, kind, n):
    """A moving average ('sma', 'ema', 'vol' = volume SMA) or 'rsi' series of any length,
    computed once and kept in `ind` (the default lengths are already there)."""
    key = "%s%d" % (kind, n)
    if key not in ind:
        fn = {"sma": sma, "ema": ema, "rsi": rsi, "vol": sma}[kind]
        ind[key] = fn(ind["volume"] if kind == "vol" else ind["close"], n)
    return ind[key]


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


def setup_params(cfg, setup):
    """The thresholds for one setup: cfg["scanner"]["setups"][setup] over the defaults."""
    base = DEFAULT_CONFIG["scanner"]["setups"].get(setup) or {}
    mine = (((cfg or {}).get("scanner") or {}).get("setups") or {}).get(setup) or {}
    return deep_merge(base, mine)


def _factor(pct, sign=1):
    """1 + pct/100 (or 1 - pct/100), rounded to 12 places so 0.2 gives exactly 1.002, the literal
    the code used before v0.1.5."""
    return round(1 + sign * pct / 100.0, 12)


def _uptrend(p, ind, i, c, S):
    """close > fast MA > slow MA, and the fast MA higher than slope_days ago -> (ok, why[])."""
    f, sl, d = p["trend_fast_ma"], p["trend_slow_ma"], p["trend_slope_days"]
    fv, sv = S("sma", f), S("sma", sl)
    if fv is None or sv is None:
        return None, []
    prev = S("sma", f, i - d) or fv
    ok = c > fv > sv and fv > prev
    return ok, [why_item("SETUP", "close above the %d-day average" % f, c, fv, ">", c > fv, "Rs"),
                why_item("SETUP", "%d-day average above the %d-day" % (f, sl), fv, sv, ">", fv > sv, "Rs"),
                why_item("SETUP", "%d-day average rising (vs %d days ago)" % (f, d), fv, prev, ">", fv > prev,
                         "Rs")]


def detect(setup, bars, ind, i, tick=0.05, cfg=None):
    """Return a signal dict if `setup` is armed at the close of bar i.

    Thresholds come from cfg["scanner"]["setups"][setup] (the defaults when cfg is None). The
    signal's why[] lists every condition the setup tested, with the value measured and the
    threshold used, recorded here when the decision is made."""
    sc = (cfg or DEFAULT_CONFIG).get("scanner") or DEFAULT_CONFIG["scanner"]
    if i < sc.get("warmup_bars", 200) or i >= len(bars):
        return None
    p = setup_params(cfg, setup)
    c = ind["close"][i]
    a = ind["atr14"][i]
    if a is None or not p:
        return None
    hi = lambda k0, k1: max(b["high"] for b in bars[k0:k1 + 1])
    lo = lambda k0, k1: min(b["low"] for b in bars[k0:k1 + 1])
    S = lambda kind, n, k=i: series(ind, kind, n)[k]
    sig, w = None, []
    if setup in ("breakout", "pullback", "squeeze"):
        up, w = _uptrend(p, ind, i, c, S)
        if not up:
            return None
        slow = S("sma", p["trend_slow_ma"])
    if setup == "breakout":
        H, maxd = p["high_lookback_days"], p["max_distance_to_high_pct"]
        h20 = hi(i - H + 1, i)
        dist = (h20 - c) / c
        if 0 <= dist <= maxd / 100.0:
            vf, vs = S("vol", p["volume_fast_days"]), S("vol", p["volume_slow_days"])
            dry = (vf or 1) / (vs or 1)
            bonus = dry < p["volume_dry_ratio"]
            score = 50 + (maxd - dist * 100) * 6 + min(20, (c / slow - 1) * 60) + (10 if bonus else 0)
            L = p["invalidation_lookback_days"]
            sig = {"trigger": h20 * _factor(p["trigger_buffer_pct"]), "invalidation": lo(i - L + 1, i),
                   "score": score, "notes": "%d-day high %.2f, %.1f%% away, volume %s"
                   % (H, h20, dist * 100, "drying up" if bonus else "normal")}
            w += [why_item("SETUP", "distance under the %d-day high" % H, dist * 100, maxd, "<=", True, "%",
                           "%d-day high %.2f" % (H, h20)),
                  why_item("SETUP", "volume %d-day / %d-day average" % (p["volume_fast_days"], p["volume_slow_days"]),
                           dry, p["volume_dry_ratio"], "<", bonus, "ratio",
                           "score bonus only (+10), not required")]
    elif setup == "pullback":
        e20, r = S("ema", p["ema_length"]), S("rsi", p["rsi_length"])
        if e20 is None or r is None:
            return None
        b = bars[i]
        touch, below = e20 * _factor(p["touch_band_pct"]), e20 * _factor(p["max_close_below_ema_pct"], -1)
        if b["low"] <= touch and c >= below and p["rsi_min"] <= r <= p["rsi_max"]:
            score = 55 + (p["rsi_max"] - r) + min(20, (c / slow - 1) * 60)
            L = p["invalidation_lookback_days"]
            sig = {"trigger": b["high"] * _factor(p["trigger_buffer_pct"]),
                   "invalidation": lo(i - L + 1, i) * _factor(p["invalidation_buffer_pct"], -1),
                   "score": score, "notes": "touched the %d EMA %.2f, RSI %.0f" % (p["ema_length"], e20, r)}
            w += [why_item("SETUP", "day's low within %s%% of the %d EMA" % (_fmt_val(p["touch_band_pct"]),
                                                                            p["ema_length"]),
                           b["low"], touch, "<=", True, "Rs", "%d EMA %.2f" % (p["ema_length"], e20)),
                  why_item("SETUP", "close at most %s%% under the %d EMA" % (_fmt_val(p["max_close_below_ema_pct"]),
                                                                            p["ema_length"]),
                           c, below, ">=", True, "Rs"),
                  why_item("SETUP", "RSI(%d) at least" % p["rsi_length"], r, p["rsi_min"], ">=", True, "RSI"),
                  why_item("SETUP", "RSI(%d) at most" % p["rsi_length"], r, p["rsi_max"], "<=", True, "RSI")]
    elif setup == "oversold":
        slow = S("sma", p["trend_slow_ma"])
        if slow is None or not c > slow:
            return None
        N = p["rsi_lookback_days"]
        vals = [x for x in series(ind, "rsi", p["rsi_length"])[i - N + 1:i + 1] if x is not None]
        if not vals:
            return None
        rmin = min(vals)
        green = bars[i]["close"] > bars[i]["open"]
        if rmin < p["rsi_below"] and (green or not p["require_green_day"]):
            score = 45 + (p["rsi_below"] - rmin) * 2 + min(15, (c / slow - 1) * 40)
            L = p["invalidation_lookback_days"]
            sig = {"trigger": bars[i]["high"] * _factor(p["trigger_buffer_pct"]), "invalidation": lo(i - L + 1, i),
                   "score": score, "notes": "RSI low %.0f, green close above the 200-day" % rmin}
            w = [why_item("SETUP", "close above the %d-day average" % p["trend_slow_ma"], c, slow, ">", True, "Rs"),
                 why_item("SETUP", "lowest RSI(%d) of the last %d days" % (p["rsi_length"], N), rmin, p["rsi_below"],
                          "<", True, "RSI"),
                 why_item("SETUP", "green day (close above open)", bars[i]["close"], bars[i]["open"], ">", green, "Rs",
                          None if p["require_green_day"] else "not required (require_green_day is false)")]
    elif setup == "squeeze":
        R, P = p["recent_days"], p["prior_days"]
        r10 = hi(i - R + 1, i) - lo(i - R + 1, i)
        rp = hi(i - R - P + 1, i - R) - lo(i - R - P + 1, i - R)
        ratio, maxr = p["max_range_ratio"], p["max_recent_range_pct"]
        if rp > 0 and r10 < ratio * rp and r10 / c < maxr / 100.0:
            score = 50 + (ratio - r10 / rp) * 80 + min(15, (c / slow - 1) * 40)
            sig = {"trigger": hi(i - R + 1, i) * _factor(p["trigger_buffer_pct"]), "invalidation": lo(i - R + 1, i),
                   "score": score, "notes": "%d-day range %.1f%% vs prior %.1f%%"
                   % (R, r10 / c * 100, rp / c * 100)}
            w += [why_item("SETUP", "%d-day range / prior %d-day range" % (R, P), r10 / rp, ratio, "<", True, "ratio"),
                  why_item("SETUP", "%d-day range as %% of price" % R, r10 / c * 100, maxr, "<", True, "%")]
    elif setup == "trend":
        sl, f, d = p["slow_ma"], p["fast_ma"], p["slope_days"]
        s200, s50 = S("sma", sl), S("sma", f)
        if s200 is None or s50 is None:
            return None
        s200_prev = S("sma", sl, i - d)
        L = p["high_lookback_days"]
        if i >= L - 1 and s200_prev and c > s200 and s50 > s200 and s200 > s200_prev:
            h52 = hi(i - L + 1, i)
            RL = p["return_lookback_days"]
            ret6 = c / ind["close"][i - RL] - 1
            mp = p["min_pct_of_high"] / 100.0
            if c >= mp * h52 and ret6 > p["min_return_pct"] / 100.0:
                score = 50 + (c / h52 - mp) * 200 + min(20, ret6 * 50)
                IL = p["invalidation_lookback_days"]
                sig = {"trigger": bars[i]["high"] * _factor(p["trigger_buffer_pct"]),
                       "invalidation": max(lo(i - IL + 1, i), s200 * _factor(p["ma_buffer_pct"], -1)),
                       "score": score, "notes": "%.1f%% below the 52-week high, 6-month return %.1f%%"
                       % ((1 - c / h52) * 100, ret6 * 100)}
                w = [why_item("SETUP", "close above the %d-day average" % sl, c, s200, ">", True, "Rs"),
                     why_item("SETUP", "%d-day average above the %d-day" % (f, sl), s50, s200, ">", True, "Rs"),
                     why_item("SETUP", "%d-day average rising (vs %d days ago)" % (sl, d), s200, s200_prev, ">", True,
                              "Rs"),
                     why_item("SETUP", "close as %% of the %d-day high" % L, c / h52 * 100, p["min_pct_of_high"], ">=",
                              True, "%", "%d-day high %.2f" % (L, h52)),
                     why_item("SETUP", "%d-day return" % RL, ret6 * 100, p["min_return_pct"], ">", True, "%")]
    if not sig:
        return None
    sig.update({
        "setup": setup, "date": bars[i]["date"], "close": round(c, 2),
        "trigger": round_tick(sig["trigger"], tick, "up"),
        "invalidation": round_tick(sig["invalidation"], tick, "down"),
        "atr": round(a, 2), "score": round(sig["score"], 1),
        "valid_days": p["valid_days"],
        "mode": "delivery" if setup in DELIVERY_SETUPS else "swing",
    })
    if sig["invalidation"] >= sig["trigger"]:
        return None
    if sig["score"] < p["min_score"]:
        return None
    sig["why"] = w + [
        why_item("SETUP", "score", sig["score"], p["min_score"], ">=", True, "score"),
        why_item("SETUP", "stop structure (invalidation) under the trigger", sig["invalidation"], sig["trigger"], "<",
                 True, "Rs", "buy-stop trigger %.2f, valid %d sessions" % (sig["trigger"], sig["valid_days"]))]
    return sig


def enabled_setups(cfg, names):
    return [n for n in names if setup_params(cfg, n).get("enabled", True)]


def detect_all(bars, mode="swing", i=None, setups=None, tick=0.05, cfg=None):
    ind = indicators(bars)
    i = len(bars) - 1 if i is None else i
    names = setups or (SWING_SETUPS if mode == "swing" else DELIVERY_SETUPS if mode == "delivery"
                       else SWING_SETUPS + DELIVERY_SETUPS)
    names = enabled_setups(cfg, names)
    out = [s for s in (detect(n, bars, ind, i, tick, cfg) for n in names) if s]
    return sorted(out, key=lambda s: -s["score"])


def liquidity_check(bars, cfg):
    """Price and average traded value -> (ok, text, why[])."""
    n = ((cfg.get("scanner") or {}).get("liquidity_days") or 20)
    ind_v = sma([float(b["volume"]) for b in bars], n)[-1] if bars else None
    if ind_v is None:
        return False, "less than %d days of data" % n, [
            why_item("LIQUIDITY", "days of price data", len(bars), n, ">=", False, "days")]
    c = bars[-1]["close"]
    turnover = ind_v * c
    w = [why_item("LIQUIDITY", "price (last close)", c, cfg["min_price"], ">=", not c < cfg["min_price"], "Rs"),
         why_item("LIQUIDITY", "%d-day average traded value" % n, turnover, cfg["min_turnover_rs"], ">=",
                  not turnover < cfg["min_turnover_rs"], "Rs")]
    if c < cfg["min_price"]:
        return False, "price %.2f under min_price %s" % (c, cfg["min_price"]), w
    if turnover < cfg["min_turnover_rs"]:
        return False, "%d-day avg turnover %s under %s" % (n, fmt_rs(turnover, 0), fmt_rs(cfg["min_turnover_rs"], 0)), w
    return True, "avg turnover %s" % fmt_rs(turnover, 0), w


def liquidity_ok(bars, cfg):
    ok, why, _ = liquidity_check(bars, cfg)
    return ok, why


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
    stop_pct = (entry - stop) / entry * 100
    cap = m.get("max_stop_pct")
    in_atr = risk / a if a else None
    plan["why"] = [
        why_item("PLAN", "stop distance under the entry", stop_pct, cap, "<=",
                 cmp_op(round(stop_pct, 6), "<=", cap), "%", "stop %.2f: %s" % (stop, method)),
        why_item("PLAN", "stop distance in ATR", in_atr, m["min_stop_atr"], ">=",
                 cmp_op(None if in_atr is None else round(in_atr, 6), ">=", m["min_stop_atr"]), "ATR",
                 "ATR %.2f; the %% cap wins when both apply" % a),
        why_item("PLAN", "target", m["target_r"], None, None, True, "R",
                 "target %.2f = entry %.2f + %sR x risk %.2f" % (target, entry, _fmt_val(m["target_r"]), risk)),
        why_item("PLAN", "time stop", m["max_hold_days"], None, None, True, "sessions"),
    ]
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
    return {"status": status, "ratios": ratios, "reasons": reasons, "as_of": as_of,
            "why": _ratio_why(ratios, h, "the screen")}


_RATIO_CHECKS = (("debt / total assets", "debt_to_assets_pct", "max_debt_to_assets_pct", None),
                 ("reported interest / total income", "interest_income_pct", "max_noncompliant_income_pct",
                  "interest the company reported"),
                 ("non-compliant income (reported + assumed return)", "noncompliant_income_pct",
                  "max_noncompliant_income_pct", "the TASIS income test"),
                 ("cash + receivables / total assets", "cash_receivables_to_assets_pct",
                  "max_cash_receivables_to_assets_pct", None))


def _ratio_why(ratios, limits, when):
    """The halal ratios against the limits they were tested with. A missing ratio is ok=None."""
    w = []
    for label, key, lim, note in _RATIO_CHECKS:
        v, L = ratios.get(key), (limits or {}).get(lim)
        w.append(why_item("HALAL", label, v, L, "<", None if v is None or L is None else not v >= L, "%",
                          note if v is not None else "UNKNOWN: not in the data (%s)" % when))
        if key == "noncompliant_income_pct":
            rate = (limits or {}).get("noncompliant_investment_return_pct")
            av = ratios.get("assumed_return_pct")
            w.append(why_item("HALAL", "of which assumed return on short-term investments", av, None, None,
                              None if av is None else True, "%",
                              "assumed %s%% a year" % _fmt_val(rate) if rate is not None
                              else "assumed rate not recorded in this list (TASIS uses 8%)"))
    return w


def halal_why(rec, universe=None):
    """HALAL items for one stock, from its halal-list record: status, your override, the ratios
    and the limits they were tested with when the list was built, and the date of the figures."""
    uni = universe or {}
    st = rec.get("status")
    w = [why_item("HALAL", "halal status", st, "compliant", "==", None if st is None else st == "compliant",
                  None, "; ".join((rec.get("reasons") or [])[:2]) or None)]
    ov = rec.get("override")
    if ov:
        w.append(why_item("HALAL", "your override", ov.get("status"), None, None, True, None,
                          "%s (set %s)" % (ov.get("note") or "no note", ov.get("date") or "UNKNOWN")))
    if rec.get("why"):
        w += [dict(x) for x in rec["why"]]
    elif rec.get("ratios"):
        w += [dict(x, note=(x["note"] or "") + (" " if x["note"] else "") + "(from the ratios and limits stored "
                     "when the list was built)") for x in _ratio_why(rec["ratios"], uni.get("thresholds"), "list")]
    else:
        w.append(why_item("HALAL", "financial ratios", None, None, None, None, "%",
                          "UNKNOWN: not computed for this stock (%s)" % (rec.get("source") or uni.get("source")
                                                                         or "no source")))
    w.append(why_item("HALAL", "figures as of", rec.get("as_of"), None, None, True if rec.get("as_of") else None,
                      "date", "halal list built %s (%s)" % (uni.get("updated") or "UNKNOWN",
                                                           uni.get("method") or "TASIS-style")))
    return w


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
        rec["override"] = dict(ov)
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
