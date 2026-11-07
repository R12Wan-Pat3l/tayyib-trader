#!/usr/bin/env python3
"""tayyib-halal: build and query the halal (Shariah-screened) stock universe.

Every other skill reads trader/halal_universe.json and refuses anything
that is not 'compliant'. Two ways to build it:

  1. --official FILE|URL  an official Shariah list (e.g. Nifty 500 Shariah
     constituents, or an export from a TASIS / Islamicly / Musaffa screener).
     Trusted as compliant, minus the known-excluded businesses.
  2. self-screen (default) the Nifty 500 list -> business screen (industry,
     name, known exclusions) -> TASIS-style financial ratios from Yahoo.

held (v0.2.4): re-checks the stocks you HOLD (open positions in positions.json) with the same screen when
their screen is older than halal.held_recheck_days (default 7), and alerts you once per status change:
"No longer compliant" (now excluded or review, and compliant when you bought it), "Not compliant now (status
at purchase unknown)" (v0.2.5: a backfilled position or an imported holding), "Near a limit" or "Could not
verify" (the screen failed). Imported holdings (ticket.py import, v0.2.5) are re-checked like trades.
It offers a SELL ticket to place yourself and a purification estimate. It never sells anything.
--write saves trader/held_halal.json, the alerts in alerts.json and the status at buy time on each position.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tayyib_core as tc  # noqa: E402


def load_rows(src, fixture):
    if src and os.path.exists(src):
        with open(src, "r", encoding="utf-8-sig") as f:
            return tc.read_index_csv(f.read())
    body = tc.fetch(src, fixture=fixture, headers=tc.INDEX_HEADERS)   # honest name, no link (v0.2.7)
    return tc.read_index_csv(body.decode("utf-8-sig", "replace"))


PARENT_CACHE = os.path.join("cache", "parent_list.csv")      # the last good download, kept after each one
PARENT_META = os.path.join("cache", "parent_list.json")
USER_FILE = "ind_nifty500list.csv"                           # downloaded by the user into the data folder


class NoParentList(Exception):
    pass


def _rows_or_none(text):
    """A usable constituents list, or None. Never a partial one: every row needs a symbol."""
    try:
        rows = tc.read_index_csv(text)
    except Exception:                                         # a broken file is not a list
        return None
    return rows if rows and all(r["symbol"] for r in rows) else None


def _age(date_iso):
    try:
        return (tc.today_ist() - tc.parse_date(date_iso)).days
    except (TypeError, ValueError):
        return None


def load_parent(src, fixture):
    """The list to self-screen -> (rows, info). Order: download (honest user agent) and keep a copy in
    trader/cache/; if refused, (a) that last good copy, (b) the user's own ind_nifty500list.csv in the data
    folder; otherwise NoParentList. info = {kind, url, date, age_days, note}."""
    if src and os.path.exists(src):                           # an explicit local file (--parent FILE)
        rows = _rows_or_none(open(src, encoding="utf-8-sig").read())
        if rows is None:
            raise NoParentList("%s has no Symbol column or no rows: not a constituents list" % src)
        return rows, {"kind": "file", "url": src, "date": None, "age_days": None,
                      "note": "Nifty 500 list from your file %s" % os.path.basename(src)}
    why = None
    try:
        body = tc.fetch(src, fixture=fixture, headers=tc.INDEX_HEADERS)   # honest name, no link (v0.2.7)
        text = body.decode("utf-8-sig", "replace")
        rows = _rows_or_none(text)
        if rows is not None:
            today = tc.today_ist().isoformat()
            os.makedirs(os.path.join(tc.data_dir(), "cache"), exist_ok=True)
            tmp = os.path.join(tc.data_dir(), PARENT_CACHE + ".tmp")
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            os.replace(tmp, os.path.join(tc.data_dir(), PARENT_CACHE))
            tc.write_json(PARENT_META, {"url": src, "downloaded": today, "rows": len(rows)})
            return rows, {"kind": "download", "url": src, "date": today, "age_days": 0,
                          "note": "Nifty 500 list downloaded today from %s" % _host(src)}
        why = "%s did not send a constituents list" % _host(src)
    except tc.FetchError as e:
        why = tc.fetch_reason(e, _host(src))
    cache = os.path.join(tc.data_dir(), PARENT_CACHE)
    if os.path.exists(cache):
        rows = _rows_or_none(open(cache, encoding="utf-8").read())
        meta = tc.read_json(PARENT_META, {}) or {}
        if rows is not None and meta.get("downloaded"):
            age = _age(meta["downloaded"])
            return rows, {"kind": "cache", "url": meta.get("url"), "date": meta["downloaded"], "age_days": age,
                          "note": "%s: using the copy downloaded on %s (%s old)" % (
                              why, meta["downloaded"], tc.plural(age, "day"))}
    mine = os.path.join(tc.data_dir(), USER_FILE)
    if os.path.exists(mine):
        rows = _rows_or_none(open(mine, encoding="utf-8-sig").read())
        if rows is not None:
            date = tc.dt.datetime.fromtimestamp(os.path.getmtime(mine), tc.IST).date().isoformat()
            age = _age(date)
            return rows, {"kind": "user_file", "url": mine, "date": date, "age_days": age,
                          "note": "%s: using your %s (saved %s, %s old)" % (why, USER_FILE, date,
                                                                             tc.plural(age, "day"))}
        why += "; your %s is not a constituents list (no Symbol column or no rows)" % USER_FILE
    raise NoParentList(
        "Could not get the Nifty 500 list (%s) and there is no saved copy. Download it yourself: on "
        "niftyindices.com open Nifty 500 and download the index constituents CSV (ind_nifty500list.csv), save it "
        "as %s, then run the build again. Nothing was changed." % (why, os.path.join(tc.data_dir(), USER_FILE)))


def _host(url):
    m = tc.re.match(r"https?://(?:www\.)?([^/]+)", url or "")
    return m.group(1) if m else (url or "the source")


def cmd_build(a, cfg):
    stocks, errors = {}, []
    if a.official:
        rows = load_rows(a.official, "index/official.csv")
        source = "official list: %s" % os.path.basename(a.official)
        for r in rows[: a.limit or None]:
            st, why = tc.business_screen(r["symbol"], r["name"], r["industry"])
            status = "excluded" if st == "excluded" else "compliant"
            reasons = why if st == "excluded" else ["on the official Shariah list"] + (why if st == "review" else [])
            stocks[r["symbol"]] = dict(r, status=status, reasons=reasons, source=source)
    else:
        src = a.parent or cfg["halal"]["parent_list_url"]
        try:
            rows, parent = load_parent(src, "index/nifty500.csv")
        except NoParentList as e:
            tc.die(str(e))                                    # never a made-up or partial list
        source = "self-screened (TASIS-style) from %s" % os.path.basename(src)
        for n, r in enumerate(rows[: a.limit or None]):
            st, why = tc.business_screen(r["symbol"], r["name"], r["industry"])
            rec = dict(r, source=source, reasons=list(why))
            if st == "excluded":
                rec["status"] = "excluded"
            elif a.no_financials:
                rec["status"] = "review" if st == "review" else "unknown"
                rec["reasons"].append("financial ratios not checked (--no-financials)")
            else:
                try:
                    fs = tc.financial_screen(tc.fetch_fundamentals(r["symbol"]), cfg)
                    rec["ratios"], rec["as_of"], rec["why"] = fs["ratios"], fs["as_of"], fs["why"]
                    rec["near_limit"] = fs["near_limit"]          # display only: ratios close under a limit
                    rec["over_limit"] = fs["over_limit"]          # display only: ratios at or over a limit
                    rec["reasons"] += fs["reasons"]
                    rec["status"] = fs["status"] if fs["status"] != "compliant" or st == "pass" else "review"
                except tc.FetchError as e:
                    rec["status"] = "unknown"
                    rec["reasons"].append("financials unavailable: %s" % e)
                    errors.append(r["symbol"])
                if not tc.fixtures_dir():
                    time.sleep(a.sleep)
            stocks[r["symbol"]] = rec
            if not a.json and (n + 1) % 50 == 0:
                sys.stderr.write("  screened %d/%d\n" % (n + 1, len(rows)))
    h = cfg["halal"]
    uni = {"updated": tc.today_ist().isoformat(), "source": source, "method": "TASIS-style",
           "thresholds": {k: h[k] for k in tc.TASIS_HALAL}, "stocks": stocks}
    if not a.official:
        uni["parent_list"] = parent
    tc.write_json("halal_universe.json", uni)
    counts = {s: sum(1 for x in stocks.values() if x["status"] == s) for s in tc.STATUSES}
    out = {"written": "trader/halal_universe.json", "source": source, "counts": counts, "fetch_errors": errors,
           "notes": ([parent["note"]] if not a.official else []) + [n for n in [tc.old_overrides_note()] if n]}
    banner = tc.halal_banner(cfg, uni)
    if banner:
        out = dict({"banner": banner}, **out)
    if cfg.get("_notes"):
        out["config_notes"] = tc.config_notes(cfg)
    if a.json:
        return tc.print_json(out)
    if banner:
        print(banner)
    print("Halal universe built: %d stocks from %s" % (len(stocks), source))
    for n in out["notes"]:
        print("  " + n)
    for s in tc.STATUSES:
        print("  %-10s %8d" % (s, counts[s]))
    if errors:
        print("  financials unavailable for %d (marked unknown): %s" % (len(errors), ", ".join(errors[:15])))
    print("Only 'compliant' stocks reach the scanner. " + tc.DISCLAIMER)


LABELS = (("debt_to_assets_pct", "debt / total assets", "max_debt_to_assets_pct"),
          ("interest_income_pct", "reported interest / total income", "max_noncompliant_income_pct"),
          ("noncompliant_income_pct", "  + assumed 8% on short-term investments", "max_noncompliant_income_pct"),
          ("cash_receivables_to_assets_pct", "cash + receivables / total assets", "max_cash_receivables_to_assets_pct"))


def show(rec, cfg=None):
    cfg = cfg or tc.load_config()
    print("%-12s %-10s %s" % (rec["symbol"], rec["status"].upper(), rec.get("name", "")))
    for r in rec.get("reasons", []):
        print("    - %s" % r)
    ratios = rec.get("ratios") or {}
    for key, label, lim in LABELS:
        if key in ratios:
            v, L = ratios[key], cfg["halal"][lim]
            print("    %-44s %6.2f%%  (limit %.0f%%) %s" % (label, v, L, "ok" if v < L else "OVER"))
    if ratios.get("total_income_basis"):
        print("    (total income = %s)" % ratios["total_income_basis"])


def cmd_check(a, cfg):
    uni = tc.load_universe()
    out = []
    for sym in tc.parse_symbols(a.symbols):
        rec = tc.halal_status(sym, uni)
        if rec["status"] == "unknown" and a.live:
            st, why = tc.business_screen(sym, rec.get("name", ""), rec.get("industry", ""))
            rec["reasons"] = why
            if st != "excluded":
                try:
                    fs = tc.financial_screen(tc.fetch_fundamentals(sym), cfg)
                    rec.update(ratios=fs["ratios"], as_of=fs["as_of"], near_limit=fs["near_limit"], over_limit=fs["over_limit"])
                    rec["reasons"] += fs["reasons"]
                    rec["status"] = fs["status"] if st == "pass" or fs["status"] != "compliant" else "review"
                except tc.FetchError as e:
                    rec["reasons"].append("financials unavailable: %s" % e)
            else:
                rec["status"] = "excluded"
            rec["source"] = "live check (not saved)"
        out.append(rec)
    banner = tc.halal_banner(cfg, uni)
    if a.json:
        return tc.print_json({"banner": banner, "stocks": out})          # banner is null unless loosened
    if banner:
        print(banner)
    for rec in out:
        show(rec, cfg)
    age = tc.universe_age_days(uni)
    if age is not None and age > cfg["halal"]["list_max_age_days"]:
        print("warning: the halal universe is %s old; rebuild it" % tc.plural(age, "day"))


def cmd_list(a, cfg):
    uni = tc.load_universe()
    rows = [tc.halal_status(s, uni) for s in sorted(uni.get("stocks", {}))]
    if a.status:
        rows = [r for r in rows if r["status"] == a.status]
    banner = tc.halal_banner(cfg, uni)
    if a.json:
        return tc.print_json({"banner": banner, "stocks": rows})         # banner is null unless loosened
    if banner:
        print(banner)
    print("%d stocks (%s), updated %s, source: %s" % (len(rows), a.status or "all",
                                                     uni.get("updated"), uni.get("source")))
    for r in rows:
        print("  %-12s %-10s %s" % (r["symbol"], r["status"], r.get("name", "")))


def cmd_compare(a, cfg):
    """Compare our universe with a trusted Shariah list (CSV with a Symbol column).

    If the CSV has a Status/Compliance/Shariah column, its values are used
    (compliant / halal / yes / pass vs anything else); otherwise every symbol in
    the file is taken as compliant by that source."""
    with open(a.file, "r", encoding="utf-8-sig") as f:
        text = f.read()
    import csv as _csv
    import io as _io
    theirs = {}
    for r in _csv.DictReader(_io.StringIO(text)):
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        sym = tc.normalize_symbol(r.get("symbol") or r.get("nse symbol") or r.get("ticker") or r.get("nse code") or "")
        if not sym or sym.startswith("DUMMY"):
            continue
        st = (r.get("status") or r.get("compliance") or r.get("shariah") or r.get("halal") or "compliant").lower()
        theirs[sym] = "compliant" if st in ("compliant", "halal", "yes", "pass", "passed", "shariah compliant", "y") else "not compliant"
    uni = tc.load_universe()
    if not uni.get("stocks"):
        tc.die("no halal universe yet: run halal.py build first")
    ours = {s: tc.halal_status(s, uni) for s in uni["stocks"]}
    agree, we_stricter, we_looser, not_in_ours = [], [], [], []
    for sym, t in sorted(theirs.items()):
        o = ours.get(sym)
        if o is None:
            not_in_ours.append({"symbol": sym, "theirs": t})
            continue
        row = {"symbol": sym, "theirs": t, "ours": o["status"], "name": o.get("name", ""),
               "reasons": o.get("reasons", [])[:3], "ratios": o.get("ratios", {})}
        if (t == "compliant") == (o["status"] == "compliant"):
            agree.append(row)
        elif t == "compliant":
            we_stricter.append(row)      # they say halal, we block: safe side, worth checking
        else:
            we_looser.append(row)        # we say halal, they don't: fix this first
    covered = len(agree) + len(we_stricter) + len(we_looser)
    out = {"file": a.file, "their_symbols": len(theirs), "overlap": covered,
           "agreement_pct": round(len(agree) / covered * 100, 1) if covered else None,
           "we_say_compliant_they_do_not": we_looser, "they_say_compliant_we_block": we_stricter,
           "not_in_our_universe": not_in_ours, "agree": len(agree)}
    banner = tc.halal_banner(cfg, uni)
    if banner:
        out = dict({"banner": banner}, **out)
    if getattr(a, "json", False):
        return tc.print_json(out)
    if banner:
        print(banner)
    print("Compared with %s: %d symbols, %d also in our universe, agreement %s%%"
          % (os.path.basename(a.file), len(theirs), covered, out["agreement_pct"]))
    print("\n1. WE SAY COMPLIANT, THEY DO NOT (%d): check these first; they could let a non-halal trade through"
          % len(we_looser))
    for r in we_looser:
        print("   %-12s %-30s ours %-9s %s" % (r["symbol"], r["name"][:30], r["ours"], r["ratios"]))
    print("\n2. THEY SAY COMPLIANT, WE BLOCK (%d): the safe side; often missing data or the income test" % len(we_stricter))
    if we_stricter:
        print("   %-12s %-9s %8s %9s %9s %8s  %s" % ("symbol", "ours", "debt%", "reported%", "+assumed%", "cash%", "why"))
    for r in we_stricter:
        q = r["ratios"] or {}
        f = lambda k: "-" if q.get(k) is None else "%.2f" % q[k]
        why = "assumed 8% return only" if any("only the assumed 8%" in x for x in r["reasons"]) else \
              "; ".join(r["reasons"])[:60]
        print("   %-12s %-9s %8s %9s %9s %8s  %s" % (r["symbol"], r["ours"], f("debt_to_assets_pct"),
              f("interest_income_pct"), f("noncompliant_income_pct"), f("cash_receivables_to_assets_pct"), why))
    if not_in_ours:
        print("\n3. ON THEIR LIST, NOT IN OUR UNIVERSE (%d): outside the Nifty 500 or not built yet: %s"
              % (len(not_in_ours), ", ".join(x["symbol"] for x in not_in_ours[:30])))
    print("\nRead only: nothing is changed. The automatic TASIS screen decides (v0.2.7: no per-stock overrides); "
          "group 2 is the strict side by design.")


HELD_FILE = "held_halal.json"


def screen_live(sym, rec, cfg):
    """The tayyib-halal screen for one held stock, now -> screen dict. A failure is status "unknown" with the
    error: never read as compliant or as non-compliant."""
    today = tc.today_ist().isoformat()
    st, why = tc.business_screen(sym, rec.get("name", ""), rec.get("industry", ""))
    out = {"status": None, "ratios": {}, "as_of": None, "near_limit": [], "over_limit": [], "reasons": list(why),
           "screened": today, "source": "re-screened %s (held stock): Yahoo annual figures, TASIS-style" % today,
           "error": None}
    if st == "excluded":
        out["status"] = "excluded"
        out["source"] = "re-screened %s (held stock): business screen" % today
        return out
    try:
        fs = tc.financial_screen(tc.fetch_fundamentals(sym), cfg)
    except tc.FetchError as e:
        out.update(status="unknown", error="financials unavailable: %s" % str(e)[:200], screened=None)
        out["reasons"].append(out["error"])
        return out
    out.update(ratios=fs["ratios"], as_of=fs["as_of"], near_limit=fs["near_limit"], over_limit=fs["over_limit"])
    out["reasons"] += fs["reasons"]
    out["status"] = fs["status"] if fs["status"] != "compliant" or st == "pass" else "review"
    if out["status"] == "unknown":
        out["error"] = "; ".join(fs["reasons"][:1]) or "missing data"
    return out


def _screen_age(screen, uni):
    d = (screen or {}).get("screened") or uni.get("updated")
    try:
        return (tc.today_ist() - tc.parse_date(d)).days
    except (TypeError, ValueError):
        return None


def _last_close(sym, save):
    try:
        bars, _ = tc.get_daily_bars(sym, save=save)
        return bars[-1]["close"], bars[-1]["date"]
    except (tc.FetchError, IndexError, KeyError):
        return None, None


def held_view(cfg, write=False):
    """The held-stock re-check (pure of side effects unless write). -> (out, files) where files are the new
    contents of positions.json, alerts.json and held_halal.json (written by the caller when write)."""
    today = tc.today_ist().isoformat()
    h = cfg["halal"]
    uni = tc.load_universe()
    pos = tc.read_json("positions.json", {"positions": []}) or {"positions": []}
    al = tc.read_json("alerts.json", {"alerts": []}) or {"alerts": []}
    store = tc.read_json(HELD_FILE, {"symbols": {}}) or {"symbols": {}}
    store.setdefault("symbols", {})
    open_pos = [x for x in pos.get("positions", []) if x.get("status") == "open"]
    backfilled = []
    for x in open_pos:                                  # the status at buy time (v0.2.4); older positions backfilled
        if not x.get("halal_at_buy"):
            rec = dict((uni.get("stocks") or {}).get(x["symbol"]) or {"status": "unknown", "source": "not in the halal list"})
            x["halal_at_buy"] = {"status": rec.get("status"), "ratios": rec.get("ratios") or {},
                                 "as_of": rec.get("as_of"), "date": today, "source": rec.get("source") or "halal list built %s" % uni.get("updated"),
                                 "backfilled": True}
            backfilled.append(x["symbol"])
    syms = sorted({x["symbol"] for x in open_pos})
    items, errors, n_next = [], [], 1 + max([x.get("n", 0) for x in al["alerts"]] or [0])
    for sym in syms:
        mine = [x for x in open_pos if x["symbol"] == sym]
        qty = sum(int(x["qty"]) for x in mine)
        first = min(mine, key=lambda x: x.get("opened") or x.get("imported") or "")
        since_held = first.get("opened") or first.get("imported")     # an imported holding: held since at least then
        at_buy = first.get("halal_at_buy") or {}
        rec = tc.halal_status(sym, uni)                 # the list record
        mem = store["symbols"].get(sym) or {}
        screen = mem.get("screen")
        rechecked = False
        if sym in tc.KNOWN_EXCLUDED:
            screen = {"status": "excluded", "ratios": {}, "as_of": None, "near_limit": [], "over_limit": [],
                      "reasons": ["core business: %s" % tc.KNOWN_EXCLUDED[sym]], "screened": today,
                      "source": "known exclusion", "error": None}
        else:
            base = screen or ({"status": rec.get("status"), "ratios": rec.get("ratios") or {}, "as_of": rec.get("as_of"),
                               "near_limit": rec.get("near_limit") or [], "over_limit": rec.get("over_limit") or [],
                               "reasons": rec.get("reasons") or [], "screened": uni.get("updated"),
                               "source": "halal list built %s" % (uni.get("updated") or "UNKNOWN"), "error": None}
                              if (uni.get("stocks") or {}).get(sym) else None)
            age = _screen_age(base, uni) if base else None
            if base is None or age is None or age >= h["held_recheck_days"]:
                screen = screen_live(sym, rec, cfg)
                rechecked = True
                if screen["error"] and base:
                    screen["last_good"] = {k: base.get(k) for k in ("status", "ratios", "as_of", "screened", "source")}
            else:
                screen = base
        screen = dict(screen)
        screen["near_limit"] = tc.near_limits(screen.get("ratios"), h) if screen.get("status") == "compliant" else []
        level = tc.held_level(screen)
        status_now = "UNKNOWN" if level == "UNKNOWN" else screen["status"]
        last_status = mem.get("last_status")
        last, last_date = _last_close(sym, save=write)
        key = "%s:%s" % (level, status_now)
        opened = [z for z in al["alerts"] if z.get("kind") == "halal" and z["symbol"] == sym and z.get("status") == "open"]
        same = [z for z in opened if z.get("key") == key]
        new = False
        if level in ("BLOCK", "WARN") or (level == "UNKNOWN" and not opened):
            if not same:
                for z in opened:
                    z.update(status="resolved", resolved=today, resolution="superseded: now %s" % key)
                z = {"n": n_next, "symbol": sym, "kind": "halal", "level": level, "key": key,
                     "note": "%s: %s" % (tc.held_title(level, at_buy), sym), "status": "open",
                     "fired": tc.now_ist().isoformat(timespec="minutes"), "created": today, "since": today,
                     "since_price": last, "from_status": last_status or at_buy.get("status"), "to_status": status_now}
                n_next += 1
                al["alerts"].append(z)
                same, new = [z], True
        elif level is None:
            for z in opened:
                z.update(status="resolved", resolved=today, resolution="status now %s, nothing near a limit" % status_now)
        alert = (same or [z for z in opened if z.get("status") == "open"] or [None])[0]
        if level == "UNKNOWN":
            errors.append("%s: %s" % (sym, screen.get("error") or "no data"))
        item = {"symbol": sym, "name": rec.get("name", ""), "qty": qty, "opened": since_held,
                "position_id": first.get("id"), "level": level, "title": tc.held_title(level, at_buy),
                "holding": any(tc.is_holding(x) for x in mine), "status_at_buy_known": tc.buy_status_known(at_buy),
                "status_at_buy": at_buy.get("status") or "UNKNOWN", "backfilled": bool(at_buy.get("backfilled")),
                "last_status": last_status, "status_now": status_now, "rechecked": rechecked,
                "ratios": tc.ratio_changes(at_buy.get("ratios") or (mem.get("screen") or {}).get("ratios"),
                                           screen.get("ratios"), h, h.get("near_limit_pct")),
                "failed": [r for r in screen.get("reasons", [])
                           if not r.startswith(("all three", "business screen passed"))][:3]
                if level == "BLOCK" else [],
                "near": screen.get("near_limit") or [], "data_date": screen.get("as_of"),
                "source": screen.get("source"), "screened": screen.get("screened"),
                "reason": screen.get("error"), "last_good": screen.get("last_good"),
                "last_price": last, "last_price_date": last_date,
                "alert": None if alert is None else {"n": alert["n"], "since": alert.get("since"), "new": new,
                                                     "open": alert.get("status") == "open"}}
        if level == "BLOCK":
            since = (alert or {}).get("since") or today
            item["wording"] = tc.held_wording(at_buy)
            item["sell_by"] = tc.grace_text(since, h.get("exit_grace_days") or 0)
            item["sell_ticket"] = tc.sell_ticket(sym, qty, first.get("id"), cfg.get("broker", "zerodha"), last, today,
                                                 cfg.get("exchange", "NSE"))
            ratio = (screen.get("ratios") or {}).get("noncompliant_income_pct")
            divs = (tc.read_json("purification.json", {"dividends": []}) or {}).get("dividends", [])
            item["purify"] = tc.purify_estimate(sym, qty, since_held, since, (alert or {}).get("since_price"),
                                                last, ratio, divs)
        items.append(item)
        mem = dict(mem, screen=screen if rechecked or not mem.get("screen") else mem.get("screen"),
                   last_checked=today)
        if level != "UNKNOWN":
            mem["last_status"] = status_now
        store["symbols"][sym] = mem
    for z in al["alerts"]:                             # held no more (sold): resolve
        if z.get("kind") == "halal" and z.get("status") == "open" and z["symbol"] not in syms:
            z.update(status="resolved", resolved=today, resolution="no longer held")
    alerts = [x for x in items if x["level"]]
    order = {"BLOCK": 0, "UNKNOWN": 1, "WARN": 2}
    alerts.sort(key=lambda x: (order[x["level"]], x["symbol"]))
    out = {"checked": today, "held": items, "alerts": alerts, "errors": errors, "backfilled": backfilled,
           "recheck_days": h["held_recheck_days"], "written": bool(write),
           "note": None if syms else "no open positions or imported holdings in positions.json: nothing to re-check"}
    store.update(updated=today, view=out)
    return out, {"positions.json": pos if backfilled else None, "alerts.json": al, HELD_FILE: store}


def cmd_held(a, cfg):
    out, files = held_view(cfg, write=a.write)
    if a.write:
        for name, obj in files.items():
            if obj is not None and (name != "alerts.json" or obj["alerts"] or os.path.exists(tc.path(name))):
                tc.write_json(name, obj)
    if a.json:
        return tc.print_json(out)
    if out["note"]:
        print(out["note"])
    if out["held"]:
        print("%-12s %5s  %-12s %-12s %-22s %s" % ("stock", "qty", "at buy", "now", "alert", "data"))
    for x in out["held"]:
        print("%-12s %5d  %-12s %-12s %-22s %s (%s)" % (
            x["symbol"], x["qty"], x["status_at_buy"] + ("*" if x["backfilled"] else ""), x["status_now"],
            "%s %s" % (x["level"], x["title"]) if x["level"] else "-", x["data_date"] or "UNKNOWN", x["source"]))
        for r in x["ratios"]:
            print("    %-48s %s -> %s (limit %s)%s" % (r["check"], "-" if r["old"] is None else "%.2f%%" % r["old"],
                                                      "UNKNOWN" if r["new"] is None else "%.2f%%" % r["new"],
                                                      "-" if r["limit"] is None else "%.0f%%" % r["limit"],
                                                      " OVER" if r["over"] else " near" if r["near"] else ""))
        if x["level"] == "UNKNOWN":
            print("    could not verify: %s" % (x["reason"] or "no data"))
        if x["level"] == "BLOCK":
            print("    " + x["wording"])
            print("    sell %s; SELL ticket %s (CNC, %d shares, you place it)" % (x["sell_by"], x["sell_ticket"]["id"],
                                                                               x["qty"]))
    if any(x["backfilled"] for x in out["held"]):
        print("* status at buy backfilled from the current list (not recorded when you bought)")
    if not a.write:
        print("(nothing saved: run with --write to save the alerts)")
    print(tc.DISCLAIMER)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build trader/halal_universe.json")
    b.add_argument("--official", help="CSV file or URL of an official Shariah list (Symbol column)")
    b.add_argument("--parent", help="CSV file or URL of the list to self-screen (default Nifty 500)")
    b.add_argument("--no-financials", action="store_true", help="business screen only (fast)")
    b.add_argument("--limit", type=int, default=0)
    b.add_argument("--sleep", type=float, default=0.4, help="seconds between Yahoo requests")
    c = sub.add_parser("check", help="halal status of symbols")
    c.add_argument("symbols")
    c.add_argument("--live", action="store_true", help="screen symbols not in the universe now")
    l_ = sub.add_parser("list")
    l_.add_argument("--status", choices=tc.STATUSES)
    cp = sub.add_parser("compare", help="compare with a trusted Shariah list (CSV with a Symbol column): read only")
    cp.add_argument("file")
    hd = sub.add_parser("held", help="re-check the stocks you hold (v0.2.4); alerts once per status change")
    hd.add_argument("--write", action="store_true", help="save held_halal.json, alerts.json and positions' status at buy")
    for sp in (b, c, l_, cp, hd):
        sp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    a = p.parse_args(argv)
    cfg = tc.load_config()
    tc.report_config(cfg)
    {"build": cmd_build, "check": cmd_check, "list": cmd_list,
     "compare": cmd_compare, "held": cmd_held}[a.cmd](a, cfg)


if __name__ == "__main__":
    main()
