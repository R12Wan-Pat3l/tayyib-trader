#!/usr/bin/env python3
"""Print the release notes for a tag from CHANGELOG.md.

Includes the tag's own section plus any older sections that were never tagged
(e.g. v0.1.4 also carries v0.1.3), stopping at the previous tagged version.
  python3 tools/release_notes.py v0.1.4 > notes.md"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sections(text):
    parts = re.split(r"^## v(\S+)[^\n]*\n", text, flags=re.M)
    heads = re.findall(r"^(## v\S+[^\n]*)\n", text, flags=re.M)
    return [(v, h, body.strip()) for v, h, body in zip(parts[1::2], heads, parts[2::2])]


def main():
    tag = sys.argv[1]
    ver = tag.lstrip("v")
    try:
        tags = set(subprocess.run(["git", "tag"], capture_output=True, text=True, cwd=ROOT).stdout.split())
    except OSError:
        tags = set()
    secs = sections(open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read())
    idx = [v for v, _, _ in secs].index(ver) if ver in [v for v, _, _ in secs] else None
    if idx is None:
        sys.exit("CHANGELOG.md has no section for %s" % tag)
    out = []
    for k, (v, head, body) in enumerate(secs[idx:]):
        if k > 0 and "v" + v in tags:
            break
        out.append("%s\n\n%s" % (head, body))
    repo = "https://github.com/R12Wan-Pat3l/tayyib-trader/blob/main/"
    out = [re.sub(r"\]\((?!https?://|#)([^)]+)\)", lambda m: "](%s%s)" % (repo, m.group(1)), x) for x in out]
    out.append("Install or update: `/plugin marketplace add R12Wan-Pat3l/tayyib-trader` then "
               "`/plugin install tayyib-trader@tayyib-trader` (existing users: "
               "`claude plugin update tayyib-trader@tayyib-trader`).\n\n"
               "Not financial advice. Not a fatwa.")
    # UTF-8 on every OS: the notes can hold a rupee sign, which cp1252 (Windows pipes) cannot encode
    sys.stdout.buffer.write(("\n\n".join(out) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
