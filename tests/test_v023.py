"""v0.2.3: today's list by email (tayyib-email), tayyib-daily --email, the Windows scheduled task, start.bat and the
first-run setup, the Settings Email section with "Send test email", and the drawdown labels. Offline: smtplib is
mocked, the clock is fixed (2026-10-30 18:00 IST, a Friday) and nothing is sent anywhere."""
import email
import email.policy
import io
import json
import os
import smtplib
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from _util import FIX, NOW, ROOT, OfflineCase, tc
from test_v018 import ServerCase, D, A, script

sys.path.insert(0, os.path.join(ROOT, "tayyib-email"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import email_report as ER  # noqa: E402
import schedule_windows as SW  # noqa: E402

DAY = tc.parse_date("2026-10-30")
SECRET = "pw-s3cr3t-0123456789"
PAGE = open(os.path.join(ROOT, "tayyib-dashboard", "index.html"), encoding="utf-8").read()


def why(ok=True):
    return [{"group": "HALAL", "check": "halal status", "value": "compliant", "limit": "compliant", "op": "==", "ok": True},
            {"group": "SETUP", "check": "close above the 200-day average", "value": 120.5, "limit": 100.0, "op": ">",
             "ok": True, "unit": "Rs"},
            {"group": "NEWS", "check": "Exchange filings (NSE)", "value": None, "ok": None,
             "note": "UNKNOWN: NSE did not answer"},
            {"group": "HISTORY", "check": "time-machine expectancy after charges", "value": 0.4, "limit": 0, "op": ">=",
             "ok": ok, "unit": "R"}]


def row(sym, risk, setup="breakout", mode="swing", reason=""):
    return {"symbol": sym, "name": sym.title() + " Ltd", "mode": mode, "setup": setup, "score": 80, "entry": 100.5,
            "stop": 95.25, "stop_pct": 5.2, "target": 111.0, "valid_until": "2026-11-06", "qty": 40,
            "position_rs": 4020.0, "loss_at_stop_rs": 228.4, "expectancy_r": 0.41, "past_trades": 9, "risk": risk,
            "reason": reason, "reasons": [reason] if reason else [], "why": why()}


def daily(picks=("ALFA", "BRAV", "CHRL"), asof="2026-10-30T16:25+05:30", date="2026-10-30", banners=None):
    rows = [row(s, "PASS") for s in picks] + [
        row("DELT", "WARN", reason="WARN: results news in the window: gaps are likely"),
        row("ECHO", "WARN", reason="WARN: HALAL-WATCH: new borrowing"),
        row("FOXT", "BLOCK", reason="BLOCK: open positions 6 (max 6)")]
    return {"banners": ["Exchange filings unavailable today (NSE did not answer)."] if banners is None else banners,
            "date": date, "asof": asof, "mode": "all", "capital": 100000, "risk_per_trade_pct": 1.0,
            "broker": "zerodha", "rows": rows, "notes": ["replaced X with Y"], "top_picks": list(picks),
            "settings": {"label": "default@2"}}


class FakeSMTP(object):
    """Stands in for smtplib.SMTP_SSL / SMTP: records what would have been sent."""
    sent = []
    calls = []

    def __init__(self, host, port, timeout=None, context=None):
        FakeSMTP.calls.append(("connect", host, port))

    def ehlo(self):
        FakeSMTP.calls.append(("ehlo",))

    def starttls(self, context=None):
        FakeSMTP.calls.append(("starttls",))

    def login(self, user, pw):
        FakeSMTP.calls.append(("login", user, pw))

    def send_message(self, msg, from_addr=None, to_addrs=None):
        FakeSMTP.sent.append((msg, from_addr, list(to_addrs)))

    def quit(self):
        FakeSMTP.calls.append(("quit",))


class RefusingSMTP(FakeSMTP):
    def login(self, user, pw):
        raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted for " + user.encode())


def never(*a, **k):
    raise AssertionError("smtplib must not be used here")


class EmailCase(OfflineCase):
    def setUp(self):
        super().setUp()
        self.env = mock.patch.dict(os.environ, {})
        self.env.start()
        os.environ.pop(ER.PW_ENV, None)
        FakeSMTP.sent, FakeSMTP.calls = [], []
        os.makedirs(os.path.join(self.dir, "daily"), exist_ok=True)

    def tearDown(self):
        self.env.stop()
        super().tearDown()

    def cfg(self, **email_over):
        e = {"from": "me@example.com"}
        e.update(email_over)
        self.write("config.json", {"email": e})
        return tc.load_config()

    def put_daily(self, d=None, date="2026-10-30"):
        self.write("daily/%s.json" % date, d or daily())
        with open(os.path.join(self.dir, "daily", date + ".md"), "w", encoding="utf-8") as f:
            f.write("# list\n")

    def logged(self):
        return self.read("email/log.json")["entries"]


# --- F1. the email from a fixture daily file ------------------------------------------------------------

class Build(EmailCase):
    def test_subject_variants(self):
        cfg = self.cfg()
        self.put_daily()
        self.assertEqual(ER.build(DAY, cfg)["subject"], "tayyib: 3 picks for 30 Oct 2026 (PASS 3 · WARN 2)")
        self.put_daily(daily(picks=("ALFA",)))
        self.assertEqual(ER.build(DAY, cfg)["subject"], "tayyib: 1 pick for 30 Oct 2026 (PASS 1 · WARN 2)")
        self.put_daily(daily(picks=()))
        rep = ER.build(DAY, cfg)
        self.assertEqual((rep["kind"], rep["subject"]), ("none", "tayyib: no picks today"))
        os.remove(os.path.join(self.dir, "daily", "2026-10-30.json"))
        self.assertEqual(ER.build(DAY, cfg)["subject"], "tayyib: run FAILED / data stale")

    def test_sections_in_order(self):
        cfg = self.cfg()
        d = daily()          # v0.2.4: the held section is the re-check's held_alerts[] (it replaced the simple list)
        d["held_alerts"] = [{"symbol": "BETA", "level": "BLOCK", "title": tc.HELD_TITLES["BLOCK"], "qty": 5,
                             "status_at_buy": "compliant", "status_now": "excluded", "data_date": "2026-03-31",
                             "source": "re-screened", "ratios": [], "failed": ["debt 41% of assets, over 25%"],
                             "alert": {"new": True, "since": "2026-10-30"}, "wording": tc.HELD_WORDING,
                             "sell_by": "as soon as reasonable",
                             "sell_ticket": tc.sell_ticket("BETA", 5, "BETA-1", last=50.0, date="2026-10-30"),
                             "purify": tc.purify_estimate("BETA", 5, "2026-10-01", "2026-10-30", 50.0, 50.0, 1.0, [])}]
        self.put_daily(d)
        self.write("halal_universe.json", {"updated": "2026-10-01", "stocks": {
            "ALFA": {"status": "compliant"}, "BETA": {"status": "excluded", "reasons": ["debt 41% of assets, over 25%"]}}})
        self.write("positions.json", {"positions": [{"symbol": "BETA", "status": "open"},
                                                    {"symbol": "ALFA", "status": "open"},
                                                    {"symbol": "GAMA", "status": "closed"}]})
        rep = ER.build(DAY, cfg)
        self.assertEqual([h["symbol"] for h in rep["held_alerts"]], ["BETA"])          # ALFA, GAMA: no alert
        self.assertEqual([c["symbol"] for c in rep["picks"]], ["ALFA", "BRAV", "CHRL"])
        self.assertEqual([o["symbol"] for o in rep["others"]], ["DELT", "ECHO", "FOXT"])
        c = rep["picks"][0]
        for k in ("entry", "stop", "target", "qty", "position", "loss_at_stop", "expectancy", "why", "setup", "mode"):
            self.assertIn(k, c)
        self.assertEqual((c["entry"], c["qty"], c["position"], c["expectancy"]), ("100.50", "40", "₹4,020", "+0.41R"))
        self.assertEqual((c["why"][0]["mark"], c["why"][-1]["mark"]), ("✓", "?"))  # v0.2.4 (C1): UNKNOWN comes last
        for out in (ER.render_html(rep), ER.render_text(rep)):
            low = out.lower()
            pos = [low.index(x) for x in ("no longer compliant", "exchange filings unavailable", "alfa", "delt",
                                          "paper tracker", "own inbox", "generated on your computer")]
            self.assertEqual(pos, sorted(pos), out[:400])
            self.assertIn("BETA", out[:out.index("Exchange filings unavailable")])
            self.assertIn(ER.FOOTER % tc.VERSION, out)
            self.assertIn("Not financial advice, not a fatwa.", out)
            self.assertIn("SEBI Research Analyst registration", out)
        h = ER.render_html(rep)
        self.assertNotIn("<style", h)
        self.assertNotIn("<img", h)
        self.assertNotIn("http", h.replace("http-equiv", ""))           # nothing loaded from the web

    def test_tracker_summary(self):
        cfg = self.cfg()
        self.put_daily()
        rows = [{"date": "2026-10-01", "check": "PASS", "status": "TARGET", "exited": "2026-10-20", "r": 2.0, "pnl_rs": 1900},
                {"date": "2026-10-02", "check": "WARN", "status": "STOP", "exited": "2026-10-21", "r": -1.0, "pnl_rs": -1010},
                {"date": "2026-09-02", "check": "PASS", "status": "STOP", "exited": "2026-09-21", "r": -1.0, "pnl_rs": -990},
                {"date": "2026-10-25", "check": "PASS", "status": "OPEN"},
                {"date": "2026-10-26", "check": "BLOCK", "status": "WAITING"},
                {"date": "2026-10-26", "check": "PASS", "status": "REPLACED"}]
        self.write("tracker.json", {"rows": rows, "summary": {
            "check: PASS": {"closed": 2, "win_rate_pct": 50.0, "avg_r": 0.5},
            "check: WARN": {"closed": 1, "win_rate_pct": 0.0, "avg_r": -1.0}, "check: BLOCK": {"closed": 0}}})
        t = ER.build(DAY, cfg)["tracker"]
        self.assertEqual((t["open"], t["waiting"], t["month_closed"], t["month_wins"]), (1, 1, 2, 1))
        self.assertEqual(t["month_text"], "2 (1 won) · +1.00R · ₹890.00")
        self.assertEqual([b["win_rate"] for b in t["by_check"]],
                         ["50.0% of 2 closed trades", "0.0% of 1 closed trade", "no closed trades yet"])


# --- F2. stale, missing, failed: the FAILED email, never older picks ------------------------------------

class Failed(EmailCase):
    def check_failed(self, rep, why):
        self.assertEqual((rep["kind"], rep["subject"]), ("failed", "tayyib: run FAILED / data stale"))
        self.assertIn(why, rep["problem"])
        self.assertEqual((rep["picks"], rep["others"], rep["banners"]), ([], [], []))
        for out in (ER.render_html(rep), ER.render_text(rep)):
            for sym in ("ALFA", "BRAV", "CHRL", "DELT", "FOXT"):
                self.assertNotIn(sym, out)
            self.assertIn("never presented as today", out)

    def test_missing_with_an_older_file_present(self):
        cfg = self.cfg()
        self.put_daily(daily(date="2026-10-29", asof="2026-10-29T16:25+05:30"), date="2026-10-29")
        self.check_failed(ER.build(DAY, cfg), "is missing")

    def test_stale(self):
        cfg = self.cfg()
        self.put_daily(daily(asof="2026-10-30T11:05+05:30"))               # made in market hours
        self.check_failed(ER.build(DAY, cfg), "before that session closed")
        self.put_daily(daily(date="2026-10-29", asof="2026-10-29T16:25+05:30"))   # yesterday's list under today's name
        self.check_failed(ER.build(DAY, cfg), "is not the list of 2026-10-30")

    def test_run_failed_and_sent(self):
        cfg = self.cfg(enabled=True)
        self.put_daily()                                                   # even a good-looking file is not shown
        self.check_failed(ER.build(DAY, cfg, run_failed="exit code 1: no halal universe yet"), "tayyib-daily failed")
        os.environ[ER.PW_ENV] = SECRET
        with mock.patch.object(ER.smtplib, "SMTP_SSL", FakeSMTP):
            out = ER.do_send(cfg, DAY, scheduled=True, run_failed="exit code 1: boom")
        self.assertEqual(out["status"], "sent")
        msg = FakeSMTP.sent[0][0]
        self.assertEqual(msg["Subject"], "tayyib: run FAILED / data stale")
        self.assertEqual(len(list(msg.iter_attachments())), 0)             # no attached older list
        self.assertEqual(self.logged()[-1]["kind"], "failed")


class MarketClosed(EmailCase):
    def test_weekend_and_holiday_send_nothing(self):
        cfg = self.cfg(enabled=True)
        os.environ[ER.PW_ENV] = SECRET
        with mock.patch.object(ER.smtplib, "SMTP_SSL", never), mock.patch.object(ER.smtplib, "SMTP", never):
            for date in ("2026-10-31", "2026-11-01"):
                out = ER.do_send(cfg, tc.parse_date(date), scheduled=True)
                self.assertEqual(out["status"], "market_closed")
            self.write("config.json", {"email": {"from": "me@example.com", "enabled": True}, "holidays": ["2026-10-30"]})
            out = ER.do_send(tc.load_config(), DAY)
            self.assertEqual(out["status"], "market_closed")
            out = ER.do_send(tc.load_config(), DAY, dry_run=True)
            self.assertEqual(out["status"], "market_closed")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "email", "2026-10-30.eml")))
        self.assertEqual([e["status"] for e in self.logged()], ["market_closed"] * 4)


# --- F3. the password: only from the environment, never written or shown --------------------------------

class Password(EmailCase):
    def test_only_from_env_never_in_config_log_eml(self):
        self.write("config.json", {"email": {"from": "me@example.com", "password": SECRET, "smtp_password": SECRET}})
        cfg = tc.load_config()
        self.assertNotIn("password", cfg["email"])
        notes = [n for n in tc.config_notes(cfg) if "refused" in n]
        self.assertEqual(len(notes), 2)
        self.assertNotIn(SECRET, json.dumps(tc.config_notes(cfg)))
        self.assertIn("TAYYIB_SMTP_PASSWORD", notes[0])
        self.assertIsNone(ER.password())                                   # config.json is never read for it
        self.assertTrue(tc.config_errors(tc.config_notes(cfg)))           # a settings editor refuses to save it
        os.environ[ER.PW_ENV] = SECRET
        self.assertEqual(ER.password(), SECRET)
        self.put_daily()
        with mock.patch.object(ER.smtplib, "SMTP_SSL", FakeSMTP):
            ER.do_send(cfg, DAY)
        self.assertIn(("login", "me@example.com", SECRET), FakeSMTP.calls)
        ER.do_send(cfg, DAY, dry_run=True)
        with mock.patch.object(ER.smtplib, "SMTP_SSL", RefusingSMTP):
            with self.assertRaises(ER.Problem) as e:
                ER.do_send(cfg, DAY)
        self.assertIn("SMTPAuthenticationError 535", str(e.exception))
        self.assertIn("App Password", str(e.exception))
        self.assertNotIn("me@example.com", str(e.exception))               # the server echoed the address: scrubbed
        for name in ("email/log.json", "email/2026-10-30.eml", "email/2026-10-30.html"):
            raw = open(os.path.join(self.dir, name), "rb").read()
            self.assertNotIn(SECRET.encode(), raw, name)
        log = open(os.path.join(self.dir, "email", "log.json"), encoding="utf-8").read()
        self.assertNotIn("me@example.com", log)
        self.assertNotIn("@", log)

    def test_password_like_keys_rejected_by_config_writes(self):
        self.write("config.json", {})
        for k in ("email.password", "email.smtp_password", "email.app_password", "smtp_pass", "email.token",
                  "email.secret"):
            with self.assertRaises(A.Refused) as e:
                A.save_config({"set": {k: SECRET}, "reset": [], "version": A.config_version()})
            self.assertEqual(e.exception.code, 400, k)
            self.assertNotIn(SECRET, str(e.exception))
        self.assertEqual(self.read("config.json"), {})
        for k in ("email.password", "smtp_password", "email.app_password", "api_token", "email.secret"):
            self.assertTrue(tc.is_secret_key(k), k)
        for k in ("email.from", "email.to", "email.smtp_host", "email.send_when", "email.attach_md", "email.enabled"):
            self.assertFalse(tc.is_secret_key(k), k)

    def test_email_is_not_part_of_the_settings(self):
        base = tc.settings_snapshot(tc.validate_config({})[0])
        mine = tc.settings_snapshot(tc.validate_config({"email": {"enabled": True, "from": "me@example.com",
                                                                   "to": ["a@example.com"], "smtp_port": 587}})[0])
        self.assertEqual((mine["hash"], mine["label"]), (base["hash"], ("default@%d" % tc.DEFAULTS_VERSION)))
        self.assertNotIn("email", mine["values"])
        self.assertNotIn("me@example.com", json.dumps(mine))


class MissingPassword(EmailCase):
    def test_test_and_send_give_the_message(self):
        self.cfg()
        self.put_daily()
        for args in (["test"], ["send"]):
            p = self.run_script("tayyib-email/email_report.py", *args, ok=False, as_json=False)
            self.assertEqual(p.returncode, 2, args)
            self.assertEqual(p.stderr.strip(), "error: TAYYIB_SMTP_PASSWORD is not set: see User guide, Get the list by email")
            self.assertNotIn("Traceback", p.stderr)
        self.cfg(enabled=True)
        out = ER.do_send(tc.load_config(), DAY, scheduled=True)
        self.assertEqual((out["status"], out["message"]), ("skipped", "email skipped: password not set"))
        self.assertEqual(self.logged()[-1]["error"], "password not set")

    def test_more_than_three_recipients_refused(self):
        self.write("config.json", {"email": {"from": "me@example.com", "to": ["a@x.com", "b@x.com", "c@x.com", "d@x.com"]}})
        cfg = tc.load_config()
        with self.assertRaises(ER.Problem) as e:
            ER.recipients(cfg)
        self.assertIn("at most 3", str(e.exception))
        self.write("config.json", {})
        with self.assertRaises(A.Refused) as e:
            A.save_config({"set": {"email.to": ["a@x.com", "b@x.com", "c@x.com", "d@x.com"]}, "reset": [],
                           "version": A.config_version()})
        self.assertEqual(e.exception.code, 400)
        for bad in (["not-an-address"], "me@example.com", ["a@x.com\r\nBcc: z@x.com"], [3]):
            self.assertFalse(tc._check_value(tc.DEFAULT_CONFIG_DOCS["email.to"], bad)[0], bad)
        self.assertFalse(tc._check_value(tc.DEFAULT_CONFIG_DOCS["email.from"], "me@x.com\nBcc: y@x.com")[0])
        self.assertEqual(ER.recipients(tc.validate_config({"email": {"from": "me@x.com"}})[0]), ("me@x.com", ["me@x.com"]))
        self.assertEqual(ER.recipients(tc.validate_config({"email": {"from": "me@x.com", "to": ["a@x.com", "b@x.com",
                                                                                               "c@x.com"]}})[0])[1],
                         ["a@x.com", "b@x.com", "c@x.com"])

    def test_dry_run(self):
        self.cfg()
        self.put_daily()
        out = self.run_script("tayyib-email/email_report.py", "send", "--dry-run")      # no password in the env
        self.assertEqual(out["status"], "dry_run")
        msg = email.message_from_bytes(open(out["eml"], "rb").read(), policy=email.policy.default)
        self.assertEqual(msg["Subject"], "tayyib: 3 picks for 30 Oct 2026 (PASS 3 · WARN 2)")
        self.assertEqual(msg["To"], "me@example.com")
        self.assertIn("ALFA", msg.get_body(preferencelist=("plain",)).get_content())
        self.assertIn("ALFA", msg.get_body(preferencelist=("html",)).get_content())
        self.assertEqual([a.get_filename() for a in msg.iter_attachments()], ["2026-10-30.md"])
        self.assertEqual(self.logged()[-1]["status"], "dry_run")
        with mock.patch.object(ER.smtplib, "SMTP_SSL", never), mock.patch.object(ER.smtplib, "SMTP", never):
            self.assertEqual(ER.do_send(tc.load_config(), DAY, dry_run=True)["status"], "dry_run")

    def test_starttls_on_587(self):
        cfg = self.cfg(smtp_port=587)
        self.put_daily()
        os.environ[ER.PW_ENV] = SECRET
        with mock.patch.object(ER.smtplib, "SMTP", FakeSMTP), mock.patch.object(ER.smtplib, "SMTP_SSL", never):
            ER.do_send(cfg, DAY)
        self.assertEqual([c[0] for c in FakeSMTP.calls], ["connect", "ehlo", "starttls", "ehlo", "login", "quit"])

    def test_picks_only(self):
        cfg = self.cfg(enabled=True, send_when="picks_only")
        self.put_daily(daily(picks=()))
        os.environ[ER.PW_ENV] = SECRET
        with mock.patch.object(ER.smtplib, "SMTP_SSL", never):
            self.assertEqual(ER.do_send(cfg, DAY, scheduled=True)["status"], "skipped")


class ScheduledRun(EmailCase):
    def test_daily_email_without_password_still_makes_the_list(self):
        self.build_universe()
        self.cfg(enabled=True)
        p = self.run_script("tayyib-daily/daily.py", "--email", "--no-news", "--runs", "300", ok=False, as_json=False)
        self.assertEqual(p.returncode, 0, p.stderr[-800:])
        self.assertTrue(os.path.exists(os.path.join(self.dir, "daily", "2026-10-30.json")))
        self.assertIn("email skipped: password not set", p.stdout)
        e = self.logged()[-1]
        self.assertEqual((e["command"], e["status"], e["error"]), ("scheduled", "skipped", "password not set"))

    def test_daily_email_when_the_list_fails(self):
        self.cfg(enabled=True)                                            # no halal universe: the list fails
        p = self.run_script("tayyib-daily/daily.py", "--email", "--no-rebuild", ok=False, as_json=False)
        self.assertNotEqual(p.returncode, 0)
        e = self.logged()[-1]
        self.assertEqual((e["kind"], e["status"]), ("failed", "skipped"))

    def test_without_email_args(self):
        sys.path.insert(0, os.path.join(ROOT, "tayyib-daily"))
        import daily
        self.assertEqual(daily.without_email_args(["--email", "--dir", "C:\\t", "--no-news", "--dir=x", "--top", "5"]),
                         ["--no-news", "--top", "5"])


# --- F4. schedule_windows: show changes nothing, --yes required, exact schtasks arguments ----------------

class Schedule(unittest.TestCase):
    def test_exact_arguments(self):
        tr = SW.subprocess.list2cmdline(["C:\\Program Files\\py.exe", SW.DAILY, "--email", "--dir",
                                         "C:\\Users\\me\\tayyib-live\\trader"])
        self.assertEqual(SW.create_args("C:\\Program Files\\py.exe", "C:\\Users\\me\\tayyib-live\\trader", 330),
                         ["schtasks", "/Create", "/TN", "tayyib-daily", "/TR", tr, "/SC", "WEEKLY", "/D",
                          "MON,TUE,WED,THU,FRI", "/ST", "16:20", "/F"])
        self.assertTrue(tr.startswith('"C:\\Program Files\\py.exe" '))
        self.assertEqual(SW.create_args("C:\\py.exe", "D:\\t", 0)[-2], "10:50")         # a PC on UTC
        a = SW.create_args("C:\\py.exe", "D:\\t", 14 * 60)                               # UTC+14: the next day
        self.assertEqual((a[-4], a[-2]), ("TUE,WED,THU,FRI,SAT", "00:50"))
        self.assertEqual(SW.delete_args(), ["schtasks", "/Delete", "/TN", "tayyib-daily", "/F"])
        self.assertEqual(SW.query_args()[:4], ["schtasks", "/Query", "/TN", "tayyib-daily"])

    def test_show_changes_nothing_and_yes_is_required(self):
        with mock.patch.object(SW.subprocess, "run", never):
            for argv in (["show"], ["install"], ["remove"], ["show", "--dir", "C:\\x\\trader"]):
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    rc = SW.main(argv)
                if argv[0] == "show":
                    self.assertEqual(rc, 0)
                    self.assertIn("schtasks /Create /TN tayyib-daily", out.getvalue())
                    self.assertIn("Nothing was changed", out.getvalue())
                    self.assertIn("16:20 IST", out.getvalue())
                else:
                    self.assertEqual(rc, 2)
                    self.assertIn("--yes", err.getvalue())


# --- F5. the dashboard: the test-email action, the Settings Email section, the first-run setup ----------

class EmailAction(ServerCase):
    def setUp(self):
        super().setUp()
        self.env = mock.patch.dict(os.environ, {})
        self.env.start()
        os.environ.pop(A.PW_ENV, None)

    def tearDown(self):
        self.env.stop()
        super().tearDown()

    def wait(self, timeout=60):
        t = time.time()
        while time.time() - t < timeout:
            s = self.get("/api/run/status")
            if s["state"] != "running":
                return s
            time.sleep(0.1)
        self.fail("run did not finish")

    def test_only_email_report_test(self):
        self.assertEqual(A.run_request({"email_test": True}), ("email_test", {}))
        self.assertEqual(A.email_argv(), ["test"])
        r, out = self.post("/api/run", {"email_test": True})
        self.assertEqual(r.status, 400)                                    # no password: refused before it starts
        self.assertEqual(out["error"], "TAYYIB_SMTP_PASSWORD is not set: see User guide, Get the list by email")
        self.assertEqual(self.get("/api/run/status")["state"], "idle")
        os.environ[A.PW_ENV] = SECRET
        self.srv.runner.email_script = script(self.scripts, "fake_email.py", '''
            import sys
            print("args", sys.argv[1:])
            print("test email sent to 1 address via smtp.gmail.com:465: check your inbox (and the spam folder)")
        ''')
        r, s = self.post("/api/run", {"email_test": True})
        self.assertEqual((r.status, s["kind"], s["command"]), (200, "email_test", "tayyib-email test"))
        s = self.wait()
        self.assertEqual(s["state"], "ok", s)
        self.assertEqual(s["lines"][0], "args ['test']")
        for bad in ({"email_test": False}, {"email_test": "yes"}, {"email_test": True, "to": "x@y.com"},
                    {"email_test": True, "skip_news": True}, {"email": "send"}, {"send": True},
                    {"email_test": {"cmd": "send"}}):
            r, _ = self.post("/api/run", bad)
            self.assertEqual(r.status, 400, bad)

    def test_failure_text_and_one_at_a_time(self):
        os.environ[A.PW_ENV] = SECRET
        self.srv.runner.email_script = script(self.scripts, "fake_email.py", '''
            import sys, time
            time.sleep(2)
            sys.stderr.write("error: the test email was not sent: SMTPAuthenticationError 535: bad login\\n")
            sys.exit(1)
        ''')
        r, _ = self.post("/api/run", {"email_test": True})
        self.assertEqual(r.status, 200)
        for body in ({"email_test": True}, {"skip_news": False}, {"backtest": {"years": 3}}):
            r, out = self.post("/api/run", body)
            self.assertEqual(r.status, 409, body)
            self.assertIn("a run is already going (a test email", out["error"])
        s = self.wait()
        self.assertEqual(s["state"], "failed")
        self.assertIn("SMTPAuthenticationError 535", s["error"])

    def test_password_never_in_the_api(self):
        os.environ[A.PW_ENV] = SECRET
        self.write("config.json", {"email": {"from": "me@example.com"}})
        for path in ("/api/settings", "/api/meta", "/api/run/status", "/api/today"):
            r, out = self.req(path)
            self.assertNotIn(SECRET, json.dumps(out), path)
        st = D.email_status()                                   # still used by the CLI-facing parts
        self.assertEqual((st["password_set"], st["password_text"]), (True, "Password: set"))
        os.environ.pop(A.PW_ENV)
        st = D.email_status()
        self.assertEqual((st["password_set"], st["password_text"]), (False, "Password: not set"))
        self.assertIn('setx TAYYIB_SMTP_PASSWORD', st["setx"])
        # v0.2.7: email is an advanced setting (config.json only): no Email group on the Settings page
        s = self.get("/api/settings")
        self.assertNotIn("email", s)
        self.assertFalse([g for g in s["groups"] if g["id"] == "email"])

    def test_host_check_and_methods(self):
        r, _ = self.req("/api/settings", host="evil.example")
        self.assertEqual(r.status, 403)
        r, _ = self.req("/api/run", "PUT", {"email_test": True}, self.good())
        self.assertEqual(r.status, 405)
        r, _ = self.post("/api/run", {"email_test": True}, Origin="http://evil.example")
        self.assertEqual(r.status, 403)


class FirstRun(ServerCase):
    def test_setup_saves_only_validated_fields(self):
        m = self.get("/api/meta")
        self.assertTrue(m["first_run"])
        su = m["setup"]
        self.assertEqual(su["keys"], ["capital", "broker", "max_risk_per_trade_pct"])        # v0.2.7: no email
        self.assertEqual([p["value"] for p in su["risk_presets"]], [0.5, 1.0, 1.5, 2.0])
        self.assertNotIn("email", su)
        with mock.patch.dict(os.environ, {A.PW_ENV: SECRET}):
            m2 = self.get("/api/meta")
        self.assertNotIn(SECRET, json.dumps(m2))                          # never the value
        for bad in ({"capital": 5}, {"max_risk_per_trade_pct": 9}, {"broker": "robinhood"}, {"broker": "custom"},
                    {"email.from": "me@example.com"}, {"email.password": SECRET}, {"email.enabled": True},
                    {"product": "MIS"}):
            body = {"version": su["version"], "set": dict({"capital": 200000}, **bad), "reset": []}
            r, out = self.post("/api/config", body)
            self.assertEqual(r.status, 400, bad)
            self.assertFalse(os.path.exists(os.path.join(self.dir, "config.json")), bad)
        r, out = self.post("/api/config", {"version": su["version"], "reset": [], "set": {
            "capital": 250000, "broker": "groww", "max_risk_per_trade_pct": 0.5}})
        self.assertEqual(r.status, 200, out)
        self.assertEqual(self.read("config.json"), {"capital": 250000, "broker": "groww", "max_risk_per_trade_pct": 0.5})
        self.assertFalse(self.get("/api/meta")["first_run"])

    def test_page(self):
        self.assertIn("function openSetup(su)", PAGE)
        self.assertIn('postJSON("/api/config", { version:su.version, set:set, reset:[] })', PAGE)
        self.assertIn('postJSON("/api/run", { email_test:true })', PAGE)
        self.assertIn('text:"Send test email"', PAGE)
        self.assertNotRegex(PAGE, r'type:"password"')                      # no password field anywhere
        self.assertIn("if (m.first_run && m.setup", PAGE)


class StartBat(unittest.TestCase):
    def test_start_bat(self):
        bat = open(os.path.join(ROOT, "start.bat"), encoding="utf-8").read()
        self.assertIn("where py", bat)
        self.assertIn('if not defined TAYYIB_DIR set "TAYYIB_DIR=%USERPROFILE%\\tayyib-live\\trader"', bat)
        self.assertIn('mkdir "%TAYYIB_DIR%"', bat)
        self.assertIn('py "%~dp0tayyib-dashboard\\dashboard.py"', bat)
        self.assertNotIn("TAYYIB_SMTP_PASSWORD", bat)


# --- E. the drawdown labels -------------------------------------------------------------------------------

class DrawdownLabels(unittest.TestCase):
    def boxes_clear(self, marks):
        lines = [(m["x"], m["y1"], m["y2"]) for m in marks]
        for m in marks:
            x0, y0, x1, y1 = m["box"]
            for lx, ly1, ly2 in lines:
                crosses = x0 <= lx <= x1 and not (y1 < ly1 or y0 > ly2)
                self.assertFalse(crosses, (m, lx))
        a, b = marks[0]["box"], marks[1]["box"]
        self.assertTrue(a[3] < b[1] or b[3] < a[1] or a[2] < b[0] or b[2] < a[0], (a, b))

    def test_close_dates_far_dates_and_edges(self):
        for px, tx in ((150, 160), (150, 152), (150, 400), (600, 612), (700, 705), (55, 60)):
            marks = D.dd_marks(px, "peak 2022-01-14", tx, "trough 2022-01-21 (−21.11%)", 760, 124)
            self.boxes_clear(marks)
            for m in marks:
                self.assertGreaterEqual(m["box"][0], 0)
                self.assertLessEqual(m["box"][2], 760)
        m = D.dd_marks(700, "peak 2026-10-01", 705, "trough 2026-10-20 (−3.10%)", 760, 124)
        self.assertEqual([x["anchor"] for x in m], ["end", "end"])               # flipped at the right edge
        self.assertIn('"text-anchor":m.anchor', PAGE)
        self.assertIn("y1:m.y1, y2:m.y2", PAGE)


class Docs(unittest.TestCase):
    def test_version_and_docs(self):
        self.assertTrue(tc.VERSION >= "0.2.3")              # pinned exactly by the newest test file
        guide = open(os.path.join(ROOT, "docs", "USER_GUIDE.md"), encoding="utf-8").read()
        faq = open(os.path.join(ROOT, "docs", "FAQ.md"), encoding="utf-8").read()
        self.assertIn("Get the list by email", guide)
        self.assertIn("Start without Claude Code", guide)
        self.assertIn("Can I email the list to my friends?", faq)
        self.assertIn("SEBI", faq)
        self.assertIn("tayyib-email", open(os.path.join(ROOT, "AGENTS.md"), encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
