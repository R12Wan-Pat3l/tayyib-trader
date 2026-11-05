#!/usr/bin/env python3
"""tayyib-trader MCP server: every tool, for any MCP client (Claude Desktop,
Claude Code, Cursor, ChatGPT and others that speak the Model Context Protocol).

Standard library only. Speaks JSON-RPC 2.0 over stdio, one message per line.
Each tool runs the matching skill script with --json and returns its output.

There is deliberately no tool that places, modifies or records an order:
this server can analyse, plan and check, never trade. Recording a fill
(ticket.py placed / close) stays a manual command the user runs.

  python3 mcp/server.py                  # the client starts it; see README
  TAYYIB_DIR=/path/to/trader             # where trader/ files live (default ./trader)
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = "0.1.8"
PROTOCOL = "2025-06-18"


def S(props=None, required=None):
    return {"type": "object", "properties": props or {}, "required": required or []}


SYM = {"type": "string", "description": "NSE symbol(s), comma separated, e.g. 'TCS' or 'TCS,INFY'"}
SYM1 = {"type": "string", "description": "one NSE symbol, e.g. 'TCS'"}

# name: (description, schema, script, argv builder)
TOOLS = {
    "daily": ("Today's halal trade list in one call: scan, news, plan, time machine, size and risk check for the "
              "best candidates. Returns entry, stop, target, quantity, rupee risk, verdict and PASS/WARN/BLOCK. "
              "Run after 3:30 PM IST. Places nothing.",
              S({"mode": {"type": "string", "enum": ["swing", "delivery", "all"]}, "top": {"type": "integer"},
                 "no_news": {"type": "boolean"}}), "tayyib-daily/daily.py",
              lambda a: (["--mode", a["mode"]] if a.get("mode") else []) + (["--top", str(a["top"])] if a.get("top") else [])
              + (["--no-news"] if a.get("no_news") else [])),
    "tracker_report": ("Paper record of every earlier daily list: did each stock reach its buy price, then the "
                       "target or the stop? Win rate, average R and P&L by check, mode and setup.",
                       S(), "tayyib-tracker/tracker.py", lambda a: ["report"]),
    "halal_check": ("Halal (Shariah) status of NSE stocks from the screened universe, with reasons and "
                    "TASIS-style ratios. live=true screens symbols not in the universe. Returns "
                    "{banner, stocks[]}: banner is null, or the 'looser than TASIS' line to show first.",
                    S({"symbols": SYM, "live": {"type": "boolean"}}, ["symbols"]), "tayyib-halal/halal.py",
                    lambda a: ["check", a["symbols"]] + (["--live"] if a.get("live") else [])),
    "halal_list": ("List the halal universe, optionally by status (compliant, review, excluded, unknown). "
                   "Returns {banner, stocks[]}: banner is null, or the 'looser than TASIS' line to show first.",
                   S({"status": {"type": "string", "enum": ["compliant", "review", "excluded", "unknown"]}}),
                   "tayyib-halal/halal.py", lambda a: ["list"] + (["--status", a["status"]] if a.get("status") else [])),
    "halal_build": ("Rebuild the halal universe. Default: self-screen the Nifty 500 (slow: one request per "
                    "stock). official: path/URL of an official Shariah list CSV instead. limit: first N only.",
                    S({"official": {"type": "string"}, "no_financials": {"type": "boolean"},
                       "limit": {"type": "integer"}}), "tayyib-halal/halal.py",
                    lambda a: ["build"] + (["--official", a["official"]] if a.get("official") else [])
                    + (["--no-financials"] if a.get("no_financials") else [])
                    + (["--limit", str(a["limit"])] if a.get("limit") else [])),
    "scan": ("Scan halal-compliant NSE stocks for swing (breakout, pullback, oversold, squeeze) and "
             "delivery (trend) setups. Writes trader/scan.json.",
             S({"mode": {"type": "string", "enum": ["swing", "delivery", "all"]}, "symbols": SYM,
                "limit": {"type": "integer"}, "top": {"type": "integer"}}), "tayyib-scanner/scan.py",
             lambda a: (["--mode", a["mode"]] if a.get("mode") else []) + (["--symbols", a["symbols"]] if a.get("symbols") else [])
             + (["--limit", str(a["limit"])] if a.get("limit") else []) + (["--top", str(a["top"])] if a.get("top") else [])),
    "news": ("Recent Indian market news per stock (Google News India, NSE announcements, Moneycontrol, ET, "
             "Mint), tagged, with HALAL-WATCH flags.",
             S({"symbols": SYM, "hours": {"type": "number"}, "market": {"type": "boolean"}}), "tayyib-news/news.py",
             lambda a: (["--symbols", a["symbols"]] if a.get("symbols") else []) + (["--hours", str(a["hours"])] if a.get("hours") else [])
             + (["--market"] if a.get("market") else [])),
    "entry_check": ("Has the armed setup triggered? WAITING / TRIGGERED / EXTENDED / INVALIDATED / EXPIRED.",
                    S({"symbols": SYM, "setup": {"type": "string"}}, ["symbols"]), "tayyib-entry/entry.py",
                    lambda a: ["check", a["symbols"]] + (["--setup", a["setup"]] if a.get("setup") else [])),
    "exit_plan": ("Stop, target, time stop and trailing rules for a setup, set before entry. write=true saves "
                  "to trader/plan.json.",
                  S({"symbols": SYM, "setup": {"type": "string"}, "entry": {"type": "number"},
                     "stop": {"type": "number"}, "target": {"type": "number"}, "write": {"type": "boolean"}}, ["symbols"]),
                  "tayyib-exit/exit.py",
                  lambda a: ["plan", a["symbols"]] + sum([["--" + k, str(a[k])] for k in ("setup", "entry", "stop", "target") if a.get(k)], [])
                  + (["--write"] if a.get("write") else [])),
    "timemachine": ("Monte Carlo (resampled own history) + historical replay of each plan, in R after charges.",
                    S({"symbols": SYM, "runs": {"type": "integer"}, "seed": {"type": "integer"}}),
                    "tayyib-timemachine/timemachine.py",
                    lambda a: ["run"] + ([a["symbols"]] if a.get("symbols") else []) + ["--write"]
                    + (["--runs", str(a["runs"])] if a.get("runs") else []) + (["--seed", str(a["seed"])] if a.get("seed") else [])),
    "size": ("Size planned trades to capital and max loss, with Indian delivery charges. Writes trader/orders.json.",
             S({"symbols": SYM, "capital": {"type": "number"}, "risk_pct": {"type": "number"}}), "tayyib-budget/size.py",
             lambda a: ([a["symbols"]] if a.get("symbols") else []) + ["--write"]
             + (["--capital", str(a["capital"])] if a.get("capital") else []) + (["--risk-pct", str(a["risk_pct"])] if a.get("risk_pct") else [])),
    "risk_check": ("PASS / WARN / BLOCK each sized order: hard rules (CNC only, no shorts, no F&O, halal only) "
                   "and limits.", S({"ids": {"type": "string"}}), "tayyib-risk/check.py",
                   lambda a: ([a["ids"]] if a.get("ids") else [])),
    "ticket_show": ("Plain-words order tickets for approved orders, with Zerodha/Groww steps. Does not place anything.",
                    S({"id": {"type": "string"}}), "tayyib-broker/ticket.py",
                    lambda a: ["show"] + ([a["id"]] if a.get("id") else [])),
    "positions": ("Open and closed trades from the journal, with P&L after charges.", S(), "tayyib-broker/ticket.py",
                  lambda a: ["positions"]),
    "alerts_check": ("Check price/date alerts; each rings once.", S(), "tayyib-alerts/alerts.py", lambda a: ["check"]),
    "results": ("Quarterly results (revenue, operating profit, net profit, EPS, growth) and halal-ratio drift.",
                S({"symbol": SYM1, "quarters": {"type": "integer"}}, ["symbol"]), "tayyib-results/results.py",
                lambda a: [a["symbol"]] + (["--quarters", str(a["quarters"])] if a.get("quarters") else [])),
    "insider": ("NSE insider-trading (SEBI PIT) disclosures and bulk/block deals.",
                S({"symbols": SYM, "days": {"type": "integer"}}, ["symbols"]), "tayyib-insider/insider.py",
                lambda a: [a["symbols"]] + (["--days", str(a["days"])] if a.get("days") else [])),
    "purify_report": ("Purification (charity) amount for dividends, optionally gains, from non-compliant income.",
                      S({"year": {"type": "integer"}, "include_gains": {"type": "boolean"}}), "tayyib-purify/purify.py",
                      lambda a: ["report"] + (["--year", str(a["year"])] if a.get("year") else [])
                      + (["--include-gains"] if a.get("include_gains") else [])),
}


def run_tool(name, args):
    desc, schema, script, build = TOOLS[name]
    for k in schema.get("required", []):
        if k not in args:
            return True, "missing required argument: %s" % k
    argv = [sys.executable, os.path.join(ROOT, script)] + build(args) + ["--json"]
    p = subprocess.run(argv, capture_output=True, encoding="utf-8", errors="replace", timeout=1800,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))   # child scripts print UTF-8
    text = p.stdout.strip() or p.stderr.strip() or "(no output)"
    if p.returncode != 0 and p.stderr.strip():
        text = (p.stdout.strip() + "\n" + p.stderr.strip()).strip()
    return p.returncode != 0, text


def handle(msg):
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None                       # notification
    if method == "initialize":
        client = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL
        return {"protocolVersion": client, "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "tayyib-trader", "version": VERSION},
                "instructions": ("Halal swing/delivery trading tools for NSE/BSE. Only Shariah-screened stocks; "
                                 "CNC delivery only; no shorts, F&O or margin. No tool places orders: show the "
                                 "ticket and let the user place it after an explicit yes. Not financial advice, "
                                 "not a fatwa.")}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [{"name": n, "description": t[0], "inputSchema": t[1]} for n, t in TOOLS.items()]}
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        if name not in TOOLS:
            raise LookupError("unknown tool %s" % name)
        is_err, text = run_tool(name, params.get("arguments") or {})
        return {"content": [{"type": "text", "text": text}], "isError": is_err}
    raise NotImplementedError(method)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()
            continue
        try:
            res = handle(msg)
            if res is None:
                continue
            out = {"jsonrpc": "2.0", "id": msg.get("id"), "result": res}
        except NotImplementedError as e:
            out = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32601, "message": "method not found: %s" % e}}
        except Exception as e:  # noqa: BLE001
            out = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32602, "message": str(e)}}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
