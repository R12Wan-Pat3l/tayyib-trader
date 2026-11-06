"""Capture the decision outputs of the pipeline on the fixtures, for the v0.1.4 baseline test.

capture() uses only APIs that existed in v0.1.4 (tc.detect, tc.liquidity_ok, tc.plan_trade,
size.size, check.check_order, timemachine.history) plus full daily.py runs, and keeps only the
fields v0.1.4 produced. tests/fixtures/baseline_v0.1.4.json.gz was written by
`python3 tests/baseline.py --write` BEFORE any v0.1.5 change; test_baseline.py compares the
current code against it. Never regenerate it to make a failing test pass: a difference means a
default-config decision changed.
"""
import copy
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")
NOW = "2026-10-30 18:00"
BASELINE = os.path.join(FIX, "baseline_v0.1.4.json.gz")
os.environ.setdefault("TAYYIB_FIXTURES", FIX)
os.environ.setdefault("TAYYIB_NOW", NOW)
sys.path.insert(0, os.path.join(ROOT, "core"))
for d in ("tayyib-budget", "tayyib-risk", "tayyib-timemachine"):
    sys.path.insert(0, os.path.join(ROOT, d))
import tayyib_core as tc  # noqa: E402
import size as size_mod  # noqa: E402
import check as check_mod  # noqa: E402
import timemachine as tm_mod  # noqa: E402

SYMS = ("ALFA", "BRVO", "CHRL", "DLTA", "ECHO", "ITC", "THIN")
SETUPS = ("breakout", "pullback", "oversold", "squeeze", "trend")
# every field a v0.1.4 daily row had; new fields (why, settings_hash, ...) are ignored here
ROW_KEYS = ("symbol", "name", "mode", "setup", "score", "entry", "stop", "stop_pct", "target", "valid_until",
            "max_hold_days", "qty", "position_rs", "loss_at_stop_rs", "gain_at_target_rs", "rr_net",
            "expectancy_r", "past_trades", "verdict", "risk", "reason", "reasons", "order_id")
TOP_KEYS = ("date", "mode", "capital", "risk_per_trade_pct", "broker", "universe_updated", "scanned",
            "top_picks", "notes")
VOLATILE = ("created", "risk_checked", "asof")


def _strip(obj):
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items() if k not in VOLATILE}
    if isinstance(obj, list):
        return [_strip(x) for x in obj]
    return obj


def sweep():
    """Every setup at every bar index of every fixture chart, with the plan, size, risk check and
    the time machine's history replay of each signal: far more cases than the daily list shows."""
    cfg = copy.deepcopy(tc.DEFAULT_CONFIG)
    out = {}
    uni = {"updated": "2026-10-30", "stocks": {s: {"status": "compliant", "industry": "X"} for s in SYMS}}
    for s in SYMS:
        bars, _ = tc.get_daily_bars(s)
        ind = tc.indicators(bars)
        rec = {"liquidity": [], "signals": [], "history": {}}
        for k in range(30, len(bars) + 1, 7):
            ok, why = tc.liquidity_ok(bars[:k], cfg)
            rec["liquidity"].append([k, ok, why])
        for i in range(200, len(bars)):
            for setup in SETUPS:
                sig = tc.detect(setup, bars, ind, i, cfg["tick_size"])
                if not sig:
                    continue
                sig = dict(sig, symbol=s)
                item = {"i": i, "signal": sig}
                try:
                    pl = tc.plan_trade(sig, cfg)
                except ValueError as e:
                    item["plan_error"] = str(e)
                    rec["signals"].append(item)
                    continue
                item["plan"] = pl
                sz = size_mod.size(pl, cfg, cfg["capital"])
                item["size"] = sz
                if sz.get("qty"):
                    o = {"id": "%s-%s-%s" % (s, pl["signal_date"], setup), "symbol": s, "side": "BUY",
                         "product": "CNC", "instrument": "EQ", "qty": sz["qty"], "trigger_price": pl["entry"],
                         "stop": pl["stop"], "target": pl["target"], "setup": setup, "mode": pl["mode"],
                         "valid_until": None}
                    o.update({k: v for k, v in sz.items() if k not in ("qty", "limit_price")})
                    item["risk"] = check_mod.check_order(o, cfg, [], uni, {})
                rec["signals"].append(item)
        for setup in SETUPS:
            mode = "delivery" if setup == "trend" else "swing"
            summ, trades = tm_mod.history(bars, {"setup": setup, "mode": mode}, cfg)
            rec["history"][setup] = {"summary": summ, "trades": trades}
        out[s] = rec
    return out


def _run(d, script, *args):
    argv = [sys.executable, os.path.join(ROOT, script)] + [str(a) for a in args] + ["--json"]
    env = dict(os.environ, TAYYIB_DIR=d, TAYYIB_FIXTURES=FIX, TAYYIB_NOW=NOW)
    p = subprocess.run(argv, capture_output=True, encoding="utf-8", env=env, cwd=d)
    if p.returncode != 0:
        raise RuntimeError("%s %s: %s" % (script, args, p.stderr))
    return json.loads(p.stdout)


def _read(d, name):
    p = os.path.join(d, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


PIPELINE_RUNS = (("all-news", ()), ("all-nonews", ("--no-news",)), ("swing", ("--mode", "swing", "--no-news")),
                 ("delivery", ("--mode", "delivery", "--no-news")), ("top2", ("--top", "2", "--no-news")))


# v0.1.7 (default@2) ranks rows with fewer than daily.min_past_trades_for_rank past trades by setup score.
# With the key at 0 every decision must be the v0.1.4 one: that proves the ranking rule is the only change.
V014_ORDER = {"daily": {"min_past_trades_for_rank": 0}}


def pipeline(config=V014_ORDER):
    out = {}
    for name, args in PIPELINE_RUNS:
        d = tempfile.mkdtemp(prefix="tayyib-baseline-")
        try:
            if config:
                with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as f:
                    json.dump(config, f)
            b = _run(d, "tayyib-halal/halal.py", "build")
            daily = _run(d, "tayyib-daily/daily.py", *args)
            rec = {"halal_counts": b["counts"],
                   "universe": _strip((_read(d, "halal_universe.json") or {}).get("stocks")),
                   "daily": {k: daily.get(k) for k in TOP_KEYS},
                   "rows": [{k: r.get(k) for k in ROW_KEYS} for r in daily["rows"]],
                   "scan": _strip((_read(d, "scan.json") or {}).get("candidates")),
                   "plans": _strip((_read(d, "plan.json") or {}).get("plans")),
                   "orders": _strip((_read(d, "orders.json") or {}).get("orders")),
                   "risk": _strip((_read(d, "risk.json") or {}).get("results"))}
            # tracker rows: only the v0.1.4 fields (settings_hash is new)
            tr = (_read(d, "tracker.json") or {}).get("rows") or []
            rec["tracker"] = [{k: v for k, v in r.items() if k != "settings_hash"} for r in tr]
            out[name] = rec
        finally:
            shutil.rmtree(d, ignore_errors=True)
    return out


def capture():
    return {"sweep": sweep(), "pipeline": pipeline()}


# Snapshots of the full daily pipeline on the TRUE defaults (no config.json), one per DEFAULTS_VERSION
# (v0.2.5). default@2 was written by `py tests/baseline.py --write-default 2` with the v0.2.4 code, before
# any v0.2.5 change; default@3 by `--write-default 3` after it. v0.2.5's only decision change is pullback
# off: with PULLBACK_ON the v0.2.5 code must reproduce default@2 exactly. Never rewrite a snapshot to make
# a failing test pass (the writer refuses an existing file).
PULLBACK_ON = {"scanner": {"setups": {"pullback": {"enabled": True}}}}
# v0.2.6: pullback is on by default again (default@4 = default@2 in every value); with it switched off the code must
# reproduce the historic default@3 snapshot exactly.
PULLBACK_OFF = {"scanner": {"setups": {"pullback": {"enabled": False}}}}


def snapshot_path(version):
    return os.path.join(FIX, "baseline_default%d.json.gz" % int(version))


def write_default_snapshot(version):
    version = int(version)
    if version != tc.DEFAULTS_VERSION:
        sys.exit("refused: the code's DEFAULTS_VERSION is %d, not %d" % (tc.DEFAULTS_VERSION, version))
    path = snapshot_path(version)
    if os.path.exists(path):
        sys.exit("refused: %s exists (never rewrite a snapshot)" % path)
    data = {"defaults_version": version, "written_by": tc.VERSION, "pipeline": pipeline(config=None)}
    with open(path, "wb") as f:
        f.write(gzip.compress((canonical(data) + "\n").encode("utf-8"), mtime=0))
    print("wrote %s (pipeline sha256 %s)" % (path, digest(data["pipeline"])))


def load_default_snapshot(version):
    with open(snapshot_path(version), "rb") as f:
        return json.loads(gzip.decompress(f.read()).decode("utf-8"))


# keys added to v0.1.4 records since (display only); nothing else may appear, and nothing may change or
# go missing. v0.1.5: why, override. v0.1.7: near_limit, over_limit (halal list: ratios near / over a limit).
NEW_KEYS = frozenset(("why", "override", "near_limit", "over_limit"))


def diff(base, cur, path="", out=None, new_keys=NEW_KEYS):
    """Every place `cur` differs from `base`: a changed or missing value, or a key that is not an
    allowed v0.1.5 addition. -> list of 'path: what' strings (empty means identical)."""
    out = [] if out is None else out
    if isinstance(base, dict) and isinstance(cur, dict):
        for k in base:
            if k not in cur:
                out.append("%s.%s: missing" % (path, k))
            else:
                diff(base[k], cur[k], "%s.%s" % (path, k), out, new_keys)
        for k in cur:
            if k not in base and k not in new_keys:
                out.append("%s.%s: unexpected new key" % (path, k))
    elif isinstance(base, list) and isinstance(cur, list):
        if len(base) != len(cur):
            out.append("%s: %d items, was %d" % (path, len(cur), len(base)))
        for k, (x, y) in enumerate(zip(base, cur)):
            diff(x, y, "%s[%d]" % (path, k), out, new_keys)
    elif base != cur or type(base) != type(cur):
        out.append("%s: %r, was %r" % (path, cur, base))
    return out


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def load_baseline():
    with open(BASELINE, "rb") as f:
        return json.loads(gzip.decompress(f.read()).decode("utf-8"))


def digest(obj):
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


DEFAULTS = os.path.join(FIX, "defaults_versions.json")


def load_defaults():
    with open(DEFAULTS, encoding="utf-8") as f:
        return json.load(f)


def record_defaults():
    """Add the current defaults to tests/fixtures/defaults_versions.json under DEFAULTS_VERSION.
    New keys are added to the current version; a changed value is refused unless DEFAULTS_VERSION
    was bumped first (that is what the version means)."""
    hist = load_defaults() if os.path.exists(DEFAULTS) else {}
    v, cur = str(tc.DEFAULTS_VERSION), tc.default_values()
    old = hist.get(v, {})
    changed = sorted(k for k in old if k in cur and cur[k] != old[k] or k not in cur)
    if changed:
        sys.exit("refused: defaults changed without a DEFAULTS_VERSION bump: %s" % ", ".join(changed))
    hist[v] = dict(old, **{k: x for k, x in cur.items() if k not in old})
    with open(DEFAULTS, "w", encoding="utf-8") as f:
        json.dump(hist, f, indent=1, sort_keys=True)
        f.write("\n")
    print("defaults v%s: %d keys -> %s" % (v, len(hist[v]), DEFAULTS))


if __name__ == "__main__":
    if "--defaults" in sys.argv:
        record_defaults()
        sys.exit(0)
    if "--write-default" in sys.argv:
        write_default_snapshot(sys.argv[sys.argv.index("--write-default") + 1])
        sys.exit(0)
    data = capture()
    n_sig = sum(len(v["signals"]) for v in data["sweep"].values())
    print("signals in sweep: %d; pipeline runs: %d" % (n_sig, len(data["pipeline"])))
    print("sha256 sweep    %s" % digest(data["sweep"]))
    print("sha256 pipeline %s" % digest(data["pipeline"]))
    if "--write" in sys.argv:
        with open(BASELINE, "w", encoding="utf-8") as f:
            f.write(canonical(data) + "\n")
        print("wrote %s" % BASELINE)
