#!/usr/bin/env python3
"""Run today's list and email it every trading day, with Windows Task Scheduler.

  py tools/schedule_windows.py show                 the exact schtasks command and what it does (changes nothing)
  py tools/schedule_windows.py install --yes        create (or replace) the task "tayyib-daily"
  py tools/schedule_windows.py remove --yes         delete the task "tayyib-daily"
  py tools/schedule_windows.py status               is it there, and when it runs next
  options: --dir TRADER_FOLDER (default: TAYYIB_DIR, else .\\trader if it exists, else
           %USERPROFILE%\\tayyib-live\\trader)

The task runs on weekdays at 16:20 IST (after the 3:30 PM close and the data settling), with the full path to
py.exe: tayyib-daily/daily.py --email --dir TRADER_FOLDER. On a holiday in your settings it makes no list and
sends nothing. It only ever creates, replaces or deletes the task named "tayyib-daily".

The PC must be on and you logged in at that time: a sleeping or shut laptop misses the run (Task Scheduler can
"run whether user is logged on or not" if you set that yourself in its window; it then asks for your Windows
password, which this script never handles). Standard library only; places no order.
"""
import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASK = "tayyib-daily"
IST_RUN = (16, 20)
DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
DAILY = os.path.join(ROOT, "tayyib-daily", "daily.py")


def find_py():
    """The full path to py.exe (the Python launcher); else the Python running this."""
    return shutil.which("py") or shutil.which("py.exe") or sys.executable


def default_dir():
    if os.environ.get("TAYYIB_DIR"):
        return os.path.abspath(os.environ["TAYYIB_DIR"])
    if os.path.isdir(os.path.join(os.getcwd(), "trader")):
        return os.path.abspath("trader")
    return os.path.join(os.path.expanduser("~"), "tayyib-live", "trader")


def local_time(utc_offset_min):
    """16:20 IST in this computer's time zone -> (HH:MM, day shift): -1, 0 or +1."""
    mins = IST_RUN[0] * 60 + IST_RUN[1] - 330 + utc_offset_min
    shift = -1 if mins < 0 else 1 if mins >= 24 * 60 else 0
    mins %= 24 * 60
    return "%02d:%02d" % (mins // 60, mins % 60), shift


def this_offset():
    off = dt.datetime.now().astimezone().utcoffset()
    return int(off.total_seconds() // 60) if off is not None else 330


def task_command(py, data_dir):
    """The /TR string: py.exe, the daily script with --email, and the trader folder."""
    return subprocess.list2cmdline([py, DAILY, "--email", "--dir", data_dir])


def create_args(py, data_dir, utc_offset_min=330):
    hhmm, shift = local_time(utc_offset_min)
    days = ",".join(DAYS[(i + shift) % 7] for i in range(5))
    return ["schtasks", "/Create", "/TN", TASK, "/TR", task_command(py, data_dir), "/SC", "WEEKLY", "/D", days,
            "/ST", hhmm, "/F"]


def delete_args():
    return ["schtasks", "/Delete", "/TN", TASK, "/F"]


def query_args():
    return ["schtasks", "/Query", "/TN", TASK, "/V", "/FO", "LIST"]


def explain(py, data_dir, args, offset):
    hhmm, shift = local_time(offset)
    L = ["Task: %s (only this name is ever created, replaced or deleted)" % TASK,
         "Runs: weekdays (Mon-Fri) at 16:20 IST = %s on this computer%s%s" % (
             hhmm, "" if offset == 330 else " (its clock is UTC%+d:%02d, not IST)" % (offset // 60, abs(offset) % 60),
             "" if not shift else ", which is the %s day here" % ("previous" if shift < 0 else "next")),
         "Python: %s" % py,
         "Command: tayyib-daily --email: makes today's list (as tayyib-daily does without it), then emails it to",
         "         your own inbox when email is on in Settings and TAYYIB_SMTP_PASSWORD is set",
         "Trader folder: %s%s" % (data_dir, "" if os.path.isdir(data_dir) else "  (does not exist yet)"),
         "On a holiday in your settings: no list, no email (logged as market closed).",
         "The PC must be on and you logged in at that time: a sleeping laptop misses the run.",
         "",
         "schtasks command:",
         "  " + subprocess.list2cmdline(args)]
    return "\n".join(L)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("show", "install", "remove", "status"))
    p.add_argument("--yes", action="store_true", help="needed for install and remove")
    p.add_argument("--dir", default=None, help="the trader folder (default: TAYYIB_DIR, ./trader, ~/tayyib-live/trader)")
    a = p.parse_args(argv)
    py, data_dir, offset = find_py(), os.path.abspath(a.dir) if a.dir else default_dir(), this_offset()
    args = create_args(py, data_dir, offset)
    if a.cmd == "show":
        print(explain(py, data_dir, args, offset))
        print("\nNothing was changed. To create it: py tools/schedule_windows.py install --yes")
        return 0
    if a.cmd in ("install", "remove") and not a.yes:
        sys.stderr.write("refused: %s changes Windows Task Scheduler; run it again with --yes (see `show` first)\n"
                         % a.cmd)
        return 2
    if os.name != "nt":
        sys.stderr.write("this is for Windows (schtasks); on macOS / Linux use cron: see the User guide\n")
        return 2
    run = args if a.cmd == "install" else delete_args() if a.cmd == "remove" else query_args()
    r = subprocess.run(run, capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    if a.cmd == "status" and r.returncode != 0:
        print("not installed: no task named %s" % TASK)
        return 0
    print(out.strip())
    if r.returncode == 0 and a.cmd == "install":
        print(explain(py, data_dir, args, offset))
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
