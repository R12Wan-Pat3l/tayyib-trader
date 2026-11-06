---
name: tayyib-email
description: >-
  Email. Sends today's halal list to the user's OWN inbox from their own computer: every banner first, the
  top PASS picks as cards (entry, stop, target, qty, rupee risk, time machine, Why), the other rows with
  their checks, the paper tracker and any held stock that is no longer compliant. A missing, stale or
  failed list sends a FAILED email, never older picks. The password comes only from the environment
  variable TAYYIB_SMTP_PASSWORD. Personal use only. Use when the user says "email me the list", "send the
  list to my inbox", "test my email", "set up the daily email".
argument-hint: "test | send [--date YYYY-MM-DD] [--dry-run]"
---

# tayyib-email

`${CLAUDE_SKILL_DIR}` is this skill's folder. Without Claude Code, run the same commands from the repo root as `python3 tayyib-email/email_report.py ...`.

**Python:** commands use `python3`. On Windows, if `python3` or `python` opens the Microsoft Store or is not found, use `py` instead (check once with `py --version`) for every command.

**If a command cannot run** (no permission, no Python, the mail server refuses), say so and stop, with the exact error it printed. Never give halal status, picks, prices or results from memory, and never write an email's contents yourself: only this script builds it.

```bash
python3 "${CLAUDE_SKILL_DIR}/email_report.py" send --dry-run          # writes trader/email/DATE.eml + DATE.html, sends nothing
python3 "${CLAUDE_SKILL_DIR}/email_report.py" test                    # a short test email (needs the password)
python3 "${CLAUDE_SKILL_DIR}/email_report.py" send                    # today's list, now
python3 "${CLAUDE_SKILL_DIR}/email_report.py" send --date 2026-11-05  # the list of that day
python3 "${CLAUDE_SKILL_DIR}/../tayyib-daily/daily.py" --email        # the daily list, then the email (the scheduled run)
```

## Personal use only

This is for the user's own inbox. Sending the list to other people can count as publishing stock
recommendations, which in India may need SEBI Research Analyst registration. If friends or team members want
it, each runs their own copy on their own computer. Never set this up to send to other people, and say why
if asked. At most 3 addresses, all the user's own.

## Settings (config.json, section "email"; the dashboard's Settings tab, Email)

| key | default | meaning |
|---|---|---|
| enabled | false | the scheduled run (`tayyib-daily --email`) sends only when on |
| smtp_host | smtp.gmail.com | mail server |
| smtp_port | 465 | 465 = SSL, 587 = STARTTLS |
| from | (empty) | the user's address: sender and login |
| to | [] | empty = to `from`; at most 3 |
| send_when | always | `always`, or `picks_only` (no email on a day with no PASS pick) |
| attach_md | true | attach the daily list as DATE.md |

**The password is never a setting.** It is read only from the environment variable `TAYYIB_SMTP_PASSWORD`
(for Gmail: an App Password, which needs 2-Step Verification). It is never written to config.json, never
logged, printed, shown on the dashboard or sent to the MCP server. Any password-like key in config.json is
refused. Never ask the user to paste the password into the chat: they set it themselves with
`setx TAYYIB_SMTP_PASSWORD "app-password"` in a new terminal, then open a new terminal (and restart the
dashboard) so it is seen.

Without the password: `test` and `send` stop with "TAYYIB_SMTP_PASSWORD is not set: see User guide, Get the
list by email"; `--dry-run` works; the scheduled run still makes the daily list and logs
"email skipped: password not set".

## What it sends

- Subject: `tayyib: 3 picks for 6 Nov 2026 (PASS 3 · WARN 2)`, `tayyib: no picks today`, or
  `tayyib: run FAILED / data stale`.
- Order: a FAILED / stale notice (if any), held stocks that are no longer compliant (red, from
  positions.json), every banner of the daily file, the top PASS picks as cards, the other rows with their
  check and reason, the paper tracker (open trades, this month's results, win rate by PASS / WARN / BLOCK),
  the notes, the personal-use note and the footer "Generated on your computer by tayyib-trader vX. You place
  orders yourself in your broker app. Not financial advice, not a fatwa."
- HTML with a plain-text alternative, inline CSS only, no images or anything loaded from the web.
- **Never invents.** The list must be that day's and made after the 3:30 PM IST close. Missing, stale or a
  failed run: the FAILED email says what is missing and shows no picks from an older file.
- Weekend or a holiday in the settings: nothing is sent, the log says "market closed".
- Every attempt goes to `trader/email/log.json` (date, time, status, how many recipients, the error), with no
  addresses and no secrets.

It writes only `trader/email/`. It places no order and talks to no broker.

Not financial advice. Not a fatwa.
