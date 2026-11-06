#!/usr/bin/env python3
"""tayyib-broker: the order ticket you place yourself, and your trade journal.

This version connects to no broker and can place no order. It prints each
risk-approved order in plain words with the exact steps for Zerodha Kite
and Groww, then records what you actually did:

  show                         tickets for PASS/WARN orders
  placed ID --price P          you bought: opens a position in trader/positions.json
  stop ID --stop P             raise a stop (trailing); a stop can never be lowered
  close ID --price P           you sold: closes it, P&L after charges and in R (a held-stock halal
                               alert for it is resolved when the whole position is sold)
  positions                    open and closed trades with totals (imported holdings listed apart)
  import FILE [--broker zerodha|groww|auto] [--yes] [--map ISIN=SYMBOL]
                               (v0.2.5) your real holdings from a Zerodha Console / Kite or Groww holdings export
                               (.csv or .xlsx). Without --yes: a preview, nothing written. With --yes:
                               positions.json is backed up, then holdings are added as kind "holding" (not
                               trades: no stop, target or tracker row). Read only towards your broker.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tayyib_core as tc  # noqa: E402

# The Kite / Groww steps live in the core (tc.BROKER_STEPS) so the dashboard shows the same text.
STEPS = tc.BROKER_STEPS


def load():
    orders = tc.read_json("orders.json", {"orders": []}) or {"orders": []}
    pos = tc.read_json("positions.json", {"positions": []}) or {"positions": []}
    return orders, pos


def find(items, key):
    key = key.upper()
    hits = [x for x in items if x["id"].upper() == key] or \
           [x for x in items if x["symbol"] == tc.normalize_symbol(key)]
    if not hits:
        tc.die("no order/position %s" % key)
    return hits[-1]


def ticket_text(o):
    s = ["TICKET %s  [%s]" % (o["id"], o["status"]),
         "  BUY %d %s on %s, product CNC (delivery), %s %s" % (o["qty"], o["symbol"], o["exchange"],
                                                             o["mode"], o["setup"]),
         "  buy only if price trades at or above %.2f (stop-limit, limit %.2f), valid until %s"
         % (o["trigger_price"], o["limit_price"], o["valid_until"]),
         "  costs about %s + %s charges" % (tc.fmt_rs(o["position_value_rs"]), tc.fmt_rs(o["buy_charges_rs"])),
         "  stop %.2f -> you lose about %s;  target %.2f -> you gain about %s"
         % (o["stop"], tc.fmt_rs(o["loss_at_stop_rs"]), o["target"], tc.fmt_rs(o["gain_at_target_rs"])),
         "  time stop: sell by %s if neither hits" % (o.get("time_stop_date") or "-"),
         "  How to place it yourself (%s):" % o.get("broker", "zerodha")]
    for k, step in enumerate(tc.broker_steps(o), 1):
        s.append("    %d. %s" % (k, step))
    s.append("  Then tell me: ticket.py placed %s --price <your fill>" % o["id"])
    return "\n".join(s)


# --- import (v0.2.5): your real holdings from a Zerodha / Groww export. Read only: it places nothing ----------

IMPORT_BROKERS = ("zerodha", "groww", "auto")
SME_RE = re.compile(r"-(SM|ST|BZ|IT|BT|IL|SZ)$")
SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9&_.-]{0,19}$")


def parse_maps(items):
    out = {}
    for m in items or []:
        isin, _, sym = (m or "").partition("=")
        isin, sym = isin.strip().upper(), tc.normalize_symbol(sym)
        if not tc.ISIN_RE.match(isin) or not SYMBOL_RE.match(sym or ""):
            tc.die("--map takes ISIN=SYMBOL, e.g. --map INE002A01018=RELIANCE (got %r)" % m)
        out[isin] = sym
    return out


def match_row(row, uni, by_isin, maps, price_check):
    """One export row -> (NSE symbol or None, how it matched, why not). Never guesses from a company name."""
    isin, raw = row["isin"], (row["symbol"] or "").strip().upper()
    if row.get("problem"):
        return None, None, row["problem"]
    if row.get("exchange") and row["exchange"] not in ("NSE", "NSE/BSE", "BSE/NSE", ""):
        if row["exchange"] == "BSE":
            return None, None, "listed on BSE only in your export: the screen covers NSE stocks"
    if isin and isin in maps:
        return maps[isin], "your --map", None
    if isin and isin in by_isin:
        return by_isin[isin], "ISIN", None
    if raw:
        if SME_RE.search(raw):
            return None, None, "%s is an SME / special series: not covered" % raw
        sym = tc.normalize_symbol(re.sub(r"-(EQ|BE|BL)$", "", raw))
        if not SYMBOL_RE.match(sym or ""):
            return None, None, "%r is not an NSE trading symbol" % row["symbol"]
        listed = (uni.get("stocks") or {}).get(sym)
        if isin and listed and listed.get("isin") and listed["isin"].upper() != isin:
            return None, None, "symbol %s and ISIN %s disagree (the list has %s): check the export" % (
                sym, isin, listed["isin"])
        if listed:
            return sym, "symbol", None
        ok, why = price_check(sym)
        if ok:
            return sym, "symbol (NSE price found)", None
        return None, None, "no NSE price data for %s (%s): BSE-only, SME or delisted?" % (sym, why)
    if isin and not tc.ISIN_RE.match(isin):
        return None, None, "%r is not a valid Indian ISIN" % isin
    return None, None, ("ISIN %s is not in your halal list (Nifty 500): if you know its NSE symbol, add "
                        "--map %s=SYMBOL" % (isin, isin))


def _price_check(sym):
    try:
        bars, _ = tc.get_daily_bars(sym)
    except tc.FetchError as e:
        return False, str(e)[:120]
    return (True, None) if bars else (False, "no bars")


def alert_preview(sym, uni, cfg):
    """Halal status now (overrides applied) and the alert level the held-stock check would give an imported
    holding (status at purchase unknown). Not in the list -> UNKNOWN until the held check screens it."""
    rec = tc.halal_status(sym, uni)
    st = rec.get("status")
    if st not in ("compliant", "review", "excluded"):
        return "UNKNOWN (not in your halal list)", "UNKNOWN", "Could not verify yet: the held check screens it"
    near = tc.near_limits(rec.get("ratios"), cfg["halal"]) if st == "compliant" else []
    level = tc.held_level({"status": st, "near_limit": near})
    at_buy = {"status": tc.IMPORTED_AT_BUY, "imported": True}
    return st, level, tc.held_title(level, at_buy) or "none"


def plan_import(fn, broker, cfg, maps=None, price_check=_price_check, today=None):
    """Read and match an export, then compare with positions.json -> the preview (nothing written)."""
    today = today or tc.today_ist().isoformat()
    try:
        rows = tc.read_table(fn)
    except (OSError, ValueError, KeyError) as e:
        tc.die("could not read %s: %s" % (os.path.basename(fn), e))
    except Exception as e:                                          # a damaged zip / xml
        tc.die("could not read %s: %s: %s" % (os.path.basename(fn), type(e).__name__, e))
    start, cols, heads = tc.find_holding_columns(rows)
    if start is None:
        shown = "; ".join(" | ".join(h) for h in heads[:8]) or "(no text in the first rows)"
        tc.die("could not find the columns: an import needs a symbol / instrument / trading symbol or ISIN column "
               "and a quantity / qty column (average price if present). Headers found: " + shown)
    found = tc.detect_broker(heads)
    if broker == "auto":
        broker = found or "unknown"
    elif found and found != broker:
        tc.die("this looks like a %s export, not %s: run with --broker %s (or auto)" % (found, broker, found))
    src = "import:%s:%s" % (broker, today)
    uni = tc.load_universe()
    by_isin = {(r.get("isin") or "").upper(): s for s, r in (uni.get("stocks") or {}).items() if r.get("isin")}
    pos = tc.read_json("positions.json", {"positions": []}) or {"positions": []}
    plist = pos.get("positions") or []
    journal = {}
    for x in plist:
        if not tc.is_holding(x) and x.get("status") == "open":
            journal.setdefault(x["symbol"], []).append(x)
    holdings = {x["symbol"]: x for x in plist if tc.is_holding(x)}
    merged, unmatched, lines = {}, [], []
    for r in tc.holding_rows(rows, cols, start):
        sym, how, why = match_row(r, uni, by_isin, maps or {}, price_check)
        label = r["symbol"] or r["name"] or r["isin"]
        if not sym:
            unmatched.append({"line": r["line"], "label": label, "isin": r["isin"] or None, "qty": r["qty"],
                              "avg_price": r["avg_price"], "reason": why})
            continue
        if r["qty"] == 0:
            unmatched.append({"line": r["line"], "label": label, "isin": r["isin"] or None, "qty": 0,
                              "avg_price": r["avg_price"], "reason": "quantity 0: nothing held"})
            continue
        m = merged.setdefault(sym, {"symbol": sym, "label": label, "isin": r["isin"] or None, "name": r["name"],
                                    "qty": 0, "cost": 0.0, "avg_known": True, "matched_by": how, "lines": []})
        m["qty"] += r["qty"]
        m["lines"].append(r["line"])
        if r["avg_price"] is None:
            m["avg_known"] = False
        else:
            m["cost"] += r["avg_price"] * r["qty"]
    for sym, m in sorted(merged.items()):
        avg = round(m["cost"] / m["qty"], 4) if m["avg_known"] and m["qty"] else None
        jq = sum(int(x["qty"]) for x in journal.get(sym, []))
        own = m["qty"] - jq
        st, level, title = alert_preview(sym, uni, cfg)
        old = holdings.get(sym)
        note = None
        if jq:
            note = "%d of these shares are your journal trade%s %s: not imported again" % (
                min(jq, m["qty"]), "s" if len(journal[sym]) > 1 else "", ", ".join(x["id"] for x in journal[sym]))
        if own <= 0:
            action = "leave"
            if own < 0:
                note = "the export has %d, your journal has %d open: check the journal" % (m["qty"], jq)
        elif old is None:
            action = "add"
        elif old.get("qty") == own and old.get("avg_price") == avg and old.get("status") == "open":
            action = "leave"
        else:
            action = "update"
        lines.append({"symbol": sym, "label": m["label"], "isin": m["isin"], "name": m["name"], "qty": own,
                      "export_qty": m["qty"], "journal_qty": jq, "avg_price": avg, "matched_by": m["matched_by"],
                      "halal_now": st, "alert_level": level, "alert": title, "action": action, "note": note,
                      "old_qty": (old or {}).get("qty")})
    in_file = {x["symbol"] for x in lines if x["qty"] > 0}
    gone = [{"symbol": s, "qty": x.get("qty"), "action": "mark not in latest import"}
            for s, x in sorted(holdings.items()) if s not in in_file and x.get("status") == "open"]
    counts = {"add": sum(x["action"] == "add" for x in lines), "update": sum(x["action"] == "update" for x in lines),
              "leave": sum(x["action"] == "leave" for x in lines), "not_in_latest_import": len(gone),
              "could_not_match": len(unmatched)}
    return {"file": os.path.basename(fn), "broker": broker, "detected": found, "source": src, "date": today,
            "header_line": start + 1, "columns": {k: heads[v] for k, v in cols.items() if isinstance(v, int)},
            "qty_extra": [heads[c] for c in cols.get("qty_extra") or []],
            "holdings": lines, "not_in_latest_import": gone, "could_not_match": unmatched, "counts": counts}


def apply_import(plan):
    """Write the plan: back up positions.json, then add / update holdings (kind "holding"), mark holdings missing
    from this export "not in latest import" (never deleted) and keep the unmatched rows. Journal trades are never
    touched. -> the backup's file name (None if there was no positions.json)."""
    pos = tc.read_json("positions.json", None)
    backup = None
    if pos is not None:
        stamp = tc.now_ist().strftime("%Y%m%d-%H%M%S")
        backup = "positions.backup-%s.json" % stamp
        k = 1
        while os.path.exists(tc.path(backup)):
            backup, k = "positions.backup-%s-%d.json" % (stamp, k), k + 1
        with open(tc.path("positions.json"), "rb") as f, open(tc.path(backup), "wb") as g:
            g.write(f.read())
    pos = pos or {"positions": []}
    plist = pos.setdefault("positions", [])
    by = {x["symbol"]: x for x in plist if tc.is_holding(x)}
    for h in plan["holdings"]:
        if h["action"] == "leave" and h["qty"] > 0:
            by[h["symbol"]]["last_import"] = plan["date"]
            continue
        if h["qty"] <= 0:
            continue
        x = by.get(h["symbol"])
        if x is None:
            x = {"id": "HOLD-%s" % h["symbol"], "kind": tc.HOLDING, "symbol": h["symbol"], "product": "CNC",
                 "imported": plan["date"], "opened": None,
                 "halal_at_buy": {"status": tc.IMPORTED_AT_BUY, "ratios": {}, "as_of": None, "date": plan["date"],
                                  "source": plan["source"], "backfilled": False, "imported": True}}
            plist.append(x)
            by[h["symbol"]] = x
        x.update(qty=h["qty"], avg_price=h["avg_price"], isin=h["isin"], name=h["name"] or x.get("name"),
                 status="open", source=plan["source"], last_import=plan["date"], file=plan["file"],
                 matched_by=h["matched_by"], journal_qty=h["journal_qty"] or None)
        x.pop("not_in_latest_import", None)
    for g in plan["not_in_latest_import"]:
        x = by[g["symbol"]]
        x.update(status="not_in_latest_import", not_in_latest_import=plan["date"])
    pos["unmatched_holdings"] = {"date": plan["date"], "file": plan["file"], "source": plan["source"],
                                 "rows": plan["could_not_match"]}
    tc.write_json("positions.json", pos)
    return backup


def print_import(plan, written, backup):
    rs = lambda v: "UNKNOWN" if v is None else "%.2f" % v
    print("Holdings in %s (%s export, header on line %d)" % (plan["file"], plan["broker"], plan["header_line"]))
    if plan["qty_extra"]:
        print("  quantity = %s + %s" % (plan["columns"].get("qty"), " + ".join(plan["qty_extra"])))
    print("%-14s %7s %11s  %-12s %-24s %-12s %-46s %s" % ("in the file", "qty", "avg price", "NSE symbol", "matched by",
                                                         "halal now", "alert", "action"))
    for h in plan["holdings"]:
        print("%-14s %7d %11s  %-12s %-24s %-12s %-46s %s" % (h["label"][:14], h["qty"], rs(h["avg_price"]), h["symbol"],
                                                             h["matched_by"], h["halal_now"][:12], h["alert"],
                                                             h["action"]))
        if h["note"]:
            print("    " + h["note"])
    for g in plan["not_in_latest_import"]:
        print("%-14s %7s %11s  %-12s %-24s %-12s %-46s %s" % (g["symbol"], g["qty"], "", g["symbol"], "", "", "",
                                                             "not in latest import (kept, marked)"))
    if plan["could_not_match"]:
        print("Could not match (kept in positions.json, never shown as compliant):")
        for u in plan["could_not_match"]:
            print("  line %d  %-20s qty %s: %s" % (u["line"], u["label"][:20], u["qty"], u["reason"]))
    c = plan["counts"]
    print("will add %d / update %d / leave %d; %d not in this export (marked, not deleted); %d could not match"
          % (c["add"], c["update"], c["leave"], c["not_in_latest_import"], c["could_not_match"]))
    if written:
        print("written to positions.json%s. Holdings are not trades: no stop, no target, no tracker row."
              % (" (old file backed up to %s)" % backup if backup else ""))
        print("Next: halal.py held --write re-checks them with the halal screen.")
    else:
        print("Preview only: nothing written. Run again with --yes to import.")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    sh = sub.add_parser("show")
    sh.add_argument("id", nargs="?")
    pl = sub.add_parser("placed")
    pl.add_argument("id", help="order id from 'show', or the symbol")
    pl.add_argument("--price", type=float, required=True)
    pl.add_argument("--qty", type=int)
    pl.add_argument("--date")
    st = sub.add_parser("stop")
    st.add_argument("id", help="position id, or the symbol")
    st.add_argument("--stop", type=float, required=True)
    cl = sub.add_parser("close")
    cl.add_argument("id", help="position id, or the symbol")
    cl.add_argument("--price", type=float, required=True)
    cl.add_argument("--qty", type=int, help="partial sell")
    cl.add_argument("--date")
    cl.add_argument("--reason", choices=("stop", "target", "time", "trail", "manual", "halal"), default="manual")
    ps = sub.add_parser("positions")
    im = sub.add_parser("import", help="your holdings from a Zerodha / Groww export (preview unless --yes)")
    im.add_argument("file")
    im.add_argument("--broker", choices=IMPORT_BROKERS, default="auto")
    im.add_argument("--yes", action="store_true", help="write positions.json (backed up first)")
    im.add_argument("--map", action="append", metavar="ISIN=SYMBOL", help="your own ISIN -> NSE symbol match")
    for sp in (sh, pl, st, cl, ps, im):
        sp.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    a = p.parse_args(argv)
    cfg = tc.load_config()
    tc.report_config(cfg)
    orders, pos = load()

    if a.cmd == "import":
        fn = os.path.abspath(a.file)
        if not os.path.isfile(fn):
            tc.die("no such file: %s" % a.file)
        plan = plan_import(fn, a.broker, cfg, parse_maps(a.map))
        backup = apply_import(plan) if a.yes else None
        plan.update(written=bool(a.yes), backup=backup)
        if a.json:
            return tc.print_json(plan)
        print_import(plan, a.yes, backup)
        return

    if a.cmd == "show":
        ready = [o for o in orders["orders"] if o.get("status") in ("PASS", "WARN")]
        if a.id:
            ready = [find(orders["orders"], a.id)]
        if a.json:
            return tc.print_json(ready)
        if not ready:
            print("no approved orders: run tayyib-risk check first (only PASS/WARN become tickets)")
        for o in ready:
            if o["status"] not in ("PASS", "WARN"):
                print("%s is %s: not a ticket" % (o["id"], o["status"]))
                continue
            print(ticket_text(o))
            print()
        print("Nothing here places an order. You place it in your broker app, after you have said yes.")
        return

    if a.cmd == "placed":
        o = find(orders["orders"], a.id)
        if o["status"] not in ("PASS", "WARN"):
            tc.die("%s is %s: only risk-approved orders can be recorded as placed" % (o["id"], o["status"]))
        v = tc.guard_order(dict(o, qty=a.qty or o["qty"]))
        if v:
            tc.die("; ".join(v))
        qty = a.qty or o["qty"]
        fill = a.price
        if fill <= o["stop"]:
            tc.die("fill %.2f is at or under the stop %.2f: do not take this trade" % (fill, o["stop"]))
        position = {"id": o["id"], "symbol": o["symbol"], "mode": o["mode"], "setup": o["setup"],
                    "qty": qty, "entry": fill, "stop": o["stop"], "initial_stop": o["stop"],
                    "target": o["target"], "time_stop_date": o.get("time_stop_date"),
                    "opened": a.date or tc.today_ist().isoformat(), "status": "open",
                    "buy_charges_rs": tc.order_charges("BUY", fill, qty, cfg)["total"], "product": "CNC"}
        rec = tc.halal_status(o["symbol"])              # v0.2.4: the status at buy time, for the held-stock re-check
        position["halal_at_buy"] = {"status": rec.get("status"), "ratios": rec.get("ratios") or {},
                                    "as_of": rec.get("as_of"), "date": position["opened"],
                                    "source": rec.get("source"), "backfilled": False}
        pos["positions"].append(position)
        o["status"] = "PLACED"
        tc.write_json("positions.json", pos)
        tc.write_json("orders.json", orders)
        if a.json:
            return tc.print_json(position)
        print("opened %s: %d @ %.2f, stop %.2f, target %.2f. Set the stop/target GTT in your app now."
              % (o["symbol"], qty, fill, o["stop"], o["target"]))
        return

    open_pos = [x for x in pos["positions"] if x["status"] == "open"]
    trades_open = tc.trade_positions(open_pos)
    if a.cmd == "stop":
        x = find(trades_open, a.id)
        if a.stop < x["stop"]:
            tc.die("a stop can only move up (%.2f -> %.2f refused)" % (x["stop"], a.stop))
        x["stop"] = round(a.stop, 2)
        tc.write_json("positions.json", pos)
        print("%s stop raised to %.2f. Update the GTT in your app." % (x["symbol"], x["stop"]))
        return

    if a.cmd == "close":
        x = find(open_pos, a.id)
        qty = a.qty or x["qty"]
        if qty > x["qty"]:
            tc.die("you hold %d; selling %d would be a short sale" % (x["qty"], qty))
        sell = tc.order_charges("SELL", a.price, qty, cfg)["total"]
        buy = (x.get("buy_charges_rs") or 0) * qty / x["qty"]
        entry = x.get("entry", x.get("avg_price"))          # an imported holding: its average price (may be UNKNOWN)
        pnl = None if entry is None else (a.price - entry) * qty - sell - buy
        risk = (x["entry"] - x["initial_stop"]) * qty if not tc.is_holding(x) else 0
        closed = dict(x, qty=qty, exit=a.price, closed=a.date or tc.today_ist().isoformat(),
                      reason=a.reason, status="closed", pnl_rs=None if pnl is None else round(pnl, 2),
                      r=round(pnl / risk, 2) if risk > 0 and pnl is not None else None, sell_charges_rs=sell,
                      buy_charges_rs=round(buy, 2))
        full = qty == x["qty"]
        if full:
            pos["positions"].remove(x)
        else:
            if x.get("buy_charges_rs") is not None:
                x["buy_charges_rs"] = round(x["buy_charges_rs"] - buy, 2)
            x["qty"] -= qty
            closed["id"] = x["id"] + "-part"
        pos["positions"].append(closed)
        tc.write_json("positions.json", pos)
        if full:
            al = tc.read_json("alerts.json", {"alerts": []}) or {"alerts": []}
            still = any(y["symbol"] == x["symbol"] and y["status"] == "open" for y in pos["positions"])
            for z in al["alerts"]:
                if z["symbol"] == x["symbol"] and not z["fired"] and z["note"].split(":")[0] in ("STOP", "TARGET", "TIME STOP"):
                    z["fired"] = "cancelled: position closed"
                if z.get("kind") == "halal" and z["symbol"] == x["symbol"] and z.get("status") == "open" and not still:
                    z.update(status="resolved", resolved=closed["closed"],
                             resolution="you sold it on %s at %.2f" % (closed["closed"], a.price))
            tc.write_json("alerts.json", al)
            hh = tc.read_json("held_halal.json", None)
            if hh and not still:                        # the dashboard's held-stock view drops it too
                view = hh.get("view") or {}
                for k in ("held", "alerts"):
                    view[k] = [y for y in view.get(k) or [] if y.get("symbol") != x["symbol"]]
                tc.write_json("held_halal.json", hh)
        if a.json:
            return tc.print_json(closed)
        if tc.is_holding(x):
            print("sold %d %s @ %.2f (%s), an imported holding: %s against the average price (not a trade: no R, "
                  "not in the trade totals)" % (qty, x["symbol"], a.price, a.reason,
                                                "UNKNOWN" if pnl is None else tc.fmt_rs(pnl)))
            return
        print("closed %d %s @ %.2f (%s): %s after charges, %+.2fR"
              % (qty, x["symbol"], a.price, a.reason, tc.fmt_rs(pnl), closed["r"] or 0))
        return

    if a.cmd == "positions":
        if a.json:
            return tc.print_json(pos)
        print("Open:")
        for x in trades_open:
            print("  %-12s %4d @ %9.2f  stop %9.2f  target %9.2f  since %s  out by %s"
                  % (x["symbol"], x["qty"], x["entry"], x["stop"], x["target"], x["opened"], x.get("time_stop_date") or "-"))
        done = [x for x in tc.trade_positions(pos["positions"]) if x["status"] == "closed"]
        print("Closed: %d" % len(done))
        for x in done:
            print("  %-12s %4d  %9.2f -> %9.2f  %-7s %s  %+.2fR" % (x["symbol"], x["qty"], x["entry"], x["exit"],
                                                               x["reason"], tc.fmt_rs(x["pnl_rs"]), x["r"] or 0))
        if done:
            tot = sum(x["pnl_rs"] for x in done)
            wins = sum(1 for x in done if x["pnl_rs"] > 0)
            print("  total %s, %d of %d winners, avg %+.2fR" % (tc.fmt_rs(tot), wins, len(done),
                                                              sum((x["r"] or 0) for x in done) / len(done)))
        hold = [x for x in pos["positions"] if tc.is_holding(x)]
        if hold:
            print("Holdings (imported, not trades; left out of the totals above):")
            for x in hold:
                print("  %-12s %6s @ %9s  %-22s %s" % (x["symbol"], x.get("qty"), "UNKNOWN" if x.get("avg_price") is None
                                                        else "%.2f" % x["avg_price"],
                                                        {"open": "held"}.get(x["status"], x["status"].replace("_", " ")),
                                                        x.get("source") or ""))


if __name__ == "__main__":
    main()
