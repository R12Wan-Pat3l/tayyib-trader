#!/usr/bin/env python3
"""tayyib-news: Indian market news for the stocks you watch.

Sources (all free, public): Google News India RSS per stock, NSE corporate
announcements, and Moneycontrol / ET Markets / Livemint RSS. Headlines are
tagged (results, dividend, order win, deal, regulatory, fund-raise...) and
anything that could change a stock's halal status is flagged HALAL-WATCH.
Writes trader/news.json.
"""
import argparse
import datetime as dt
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tayyib_core as tc  # noqa: E402

TAGS = {
    "results": ("results", "q1 ", "q2 ", "q3 ", "q4 ", "quarterly", "net profit", "earnings", "ebitda"),
    "dividend": ("dividend", "record date", "bonus", "split", "buyback"),
    "order-win": ("order", "contract", "bags", "wins", "secures"),
    "deal": ("acqui", "merger", "stake", "demerger", "takeover", "joint venture"),
    "bulk-block": ("block deal", "bulk deal"),
    "rating": ("upgrade", "downgrade", "target price", "rating", "buy call", "sell call"),
    "regulatory": ("sebi", "penalty", "probe", "raid", "notice", "show cause", "court", "nclt"),
    "pledge": ("pledge",),
    "management": ("resign", "ceo", "cfo", "appoint", "managing director", "auditor"),
}
HALAL_WATCH = {
    "new debt": ("qip", "ncd", "bond", "debenture", "borrow", "loan", "term loan", "commercial paper"),
    "impermissible business": ("liquor", "alcohol", "brewery", "casino", "gambling", "betting",
                               "nbfc", "lending business", "insurance arm", "banking licence"),
}


# Phrases that only describe a LIST of stocks (plural). Words that can describe one company
# ("multibagger", "dhamaka") are not here: a pick-list tag drops every flag from the headline.
PICK_LISTS = ("stocks to buy", "stock picks", "top picks", "stocks to watch", "buzzing stocks",
              "stocks in news", "shares to buy", "stock recommendations", "stocks that",
              "dhamaka stocks", "dhamaka picks", "promising stocks", "multibagger stocks",
              "top stocks", "stocks for", "best stocks", "stocks under", "picks for",
              "stocks recommended", "stocks in focus", "shares in focus", "stocks to bet")


def tag(text):
    t = (text or "").lower() + " "
    if any(w in t for w in PICK_LISTS):
        return ["pick-list"], []            # a list of many stocks says little about this one
    tags = [k for k, words in TAGS.items() if any(w in t for w in words)]
    watch = [k for k, words in HALAL_WATCH.items() if any(w in t for w in words)]
    return tags, watch


def nse_announcements(sess, sym):
    obj = sess.get_json("/api/corporate-announcements", {"index": "equities", "symbol": sym},
                        fixture="nse/announcements_%s.json" % sym)
    rows = obj if isinstance(obj, list) else obj.get("data", [])
    out = []
    for r in rows:
        when = r.get("an_dt") or r.get("sort_date") or ""
        iso = None
        for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                iso = dt.datetime.strptime(when, fmt).replace(tzinfo=tc.IST).isoformat()
                break
            except ValueError:
                pass
        title = r.get("desc") or r.get("subject") or ""
        detail = r.get("attchmntText") or ""
        out.append({"title": (title + (": " + detail if detail else ""))[:300],
                    "link": r.get("attchmntFile") or "", "published": iso,
                    "source": "NSE announcement", "summary": ""})
    return out


def google_news(name, sym):
    q = '"%s" share OR stock' % (name or sym)
    url = "https://news.google.com/rss/search?q=%s&hl=en-IN&gl=IN&ceid=IN:en" % urllib.parse.quote(q)
    return tc.parse_feed(tc.fetch(url, fixture="rss/google_%s.xml" % sym), "Google News")


def title_key(title):
    """Headline without the ' - Source' suffix, punctuation or case."""
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"\s+-\s+[^-]+$", "", (title or "").lower())).strip()


def near_same(a, b, ta=None, tb=None):
    """Same story reworded slightly ('Amid' vs 'Amidst'). Never merges headlines whose
    numbers differ (a new high of Rs 2,086 vs Rs 2,125 is a new event) or that were
    published more than 12 hours apart (template sites repeat a story shape daily)."""
    import difflib
    if a == b:
        return True
    if re.findall(r"\d+", a) != re.findall(r"\d+", b):
        return False
    if ta and tb:
        try:
            gap = abs((dt.datetime.fromisoformat(ta) - dt.datetime.fromisoformat(tb)).total_seconds())
        except ValueError:
            gap = 0
        if gap > 12 * 3600:
            return False
    return len(a) > 25 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.9


def short_name(name):
    n = re.sub(r"[.,]", " ", (name or "").lower())
    n = re.sub(r"\b(limited|ltd|the|india|co|company|corporation|corp|inc|plc)\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def mentions(item, sym, name):
    """The headline itself must name the company (or its NSE symbol) as a whole phrase."""
    t = " " + re.sub(r"[^a-z0-9&]+", " ", (item["title"] or "").lower()) + " "
    short = short_name(name)
    if (" %s " % sym.lower()) in t:
        return True
    return bool(short) and len(short) >= 3 and (" %s " % short) in t


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--symbols", help="default: scan candidates + open positions")
    p.add_argument("--hours", type=float, default=72)
    p.add_argument("--market", action="store_true", help="also list general market headlines")
    p.add_argument("--show", type=int, default=8, help="headlines printed per stock (all are saved)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    cfg = tc.load_config()
    uni = tc.load_universe()

    if a.symbols:
        syms = tc.parse_symbols(a.symbols)
    else:
        syms = [c["symbol"] for c in (tc.read_json("scan.json", {}) or {}).get("candidates", [])[:10]]
        syms += [p_["symbol"] for p_ in (tc.read_json("positions.json", {}) or {}).get("positions", [])
                 if p_.get("status") == "open"]
        syms = list(dict.fromkeys(syms))
    if not syms and not a.market:
        tc.die("no symbols: pass --symbols or run tayyib-scanner first")

    cutoff = tc.now_ist() - dt.timedelta(hours=a.hours)
    errors, general = [], []
    for name, url in (cfg["news"]["feeds"] or {}).items():
        try:
            general += tc.parse_feed(tc.fetch(url, fixture="rss/%s.xml" % name), name)
        except tc.FetchError as e:
            errors.append("%s: %s" % (name, e))
    sess = tc.NSESession()
    result = {}
    for s in syms:
        rec = tc.halal_status(s, uni)
        name = rec.get("name", "")
        items = []
        if cfg["news"]["google_news"]:
            try:
                items += [g for g in google_news(name, s) if mentions(g, s, name)]
            except tc.FetchError as e:
                errors.append("google %s: %s" % (s, e))
        if cfg["news"]["nse_announcements"]:
            try:
                items += nse_announcements(sess, s)
            except (tc.FetchError, ValueError) as e:
                errors.append("nse %s: %s" % (s, e))
        items += [g for g in general if mentions(g, s, name)]
        seen, kept = [], []
        for it in items:
            if it["published"] and dt.datetime.fromisoformat(it["published"]) < cutoff:
                continue
            key = title_key(it["title"])
            if any(near_same(key, k, it["published"], t) for k, t in seen):
                continue
            seen.append((key, it["published"]))
            it["tags"], it["halal_watch"] = tag(it["title"])
            kept.append(it)
        kept.sort(key=lambda x: x["published"] or "", reverse=True)
        result[s] = kept
    market = []
    if a.market:
        for g in general:
            if not g["published"] or dt.datetime.fromisoformat(g["published"]) >= cutoff:
                g["tags"], g["halal_watch"] = tag(g["title"])
                market.append(g)
        market.sort(key=lambda x: x["published"] or "", reverse=True)
        market = market[:30]
    out = {"asof": tc.now_ist().isoformat(timespec="minutes"), "hours": a.hours,
           "symbols": result, "market": market, "errors": errors}
    tc.write_json("news.json", out)
    if a.json:
        return tc.print_json(out)
    for s, items in result.items():
        print("%s: %d headlines in the last %.0fh" % (s, len(items), a.hours))
        for it in items[:a.show]:
            when = (it["published"] or "")[:16].replace("T", " ")
            flags = (" [" + ", ".join(it["tags"]) + "]") if it["tags"] else ""
            watch = ("  HALAL-WATCH: " + ", ".join(it["halal_watch"])) if it["halal_watch"] else ""
            print("  %s IST  %s%s%s" % (when, it["title"][:110], flags, watch))
            print("      %s" % it["source"])
        if len(items) > a.show:
            print("  ... +%d more (use --show %d, or --json for all)" % (len(items) - a.show, len(items)))
    if market:
        print("Market headlines:")
        for it in market[:10]:
            flags = (" [" + ", ".join(it["tags"]) + "]") if it.get("tags") else ""
            watch = ("  HALAL-WATCH: " + ", ".join(it["halal_watch"])) if it.get("halal_watch") else ""
            print("  %s  %s%s%s" % ((it["published"] or "")[:16].replace("T", " "), it["title"][:110], flags, watch))
    if errors:
        print("(%d sources failed; first: %s)" % (len(errors), errors[0]))


if __name__ == "__main__":
    main()
