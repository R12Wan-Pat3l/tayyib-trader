#!/usr/bin/env python3
"""Copy core/tayyib_core.py into every tayyib-* skill folder.

Each skill folder carries its own copy so it works when copied on its own
(e.g. into ~/.claude/skills/). Edit core/tayyib_core.py, then run this.
`python3 tools/sync_core.py --check` exits 1 if any copy is out of date."""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "core", "tayyib_core.py")


def skill_dirs():
    return sorted(d for d in os.listdir(ROOT) if d.startswith("tayyib-") and os.path.isdir(os.path.join(ROOT, d)))


def main():
    check = "--check" in sys.argv
    src = open(SRC, "rb").read()
    stale = []
    for d in skill_dirs():
        dst = os.path.join(ROOT, d, "tayyib_core.py")
        if not os.path.exists(dst) or open(dst, "rb").read() != src:
            stale.append(d)
            if not check:
                shutil.copyfile(SRC, dst)
    if check:
        if stale:
            print("out of date: " + ", ".join(stale))
            sys.exit(1)
        print("all %d copies match" % len(skill_dirs()))
    else:
        print("synced %d of %d skill folders" % (len(stale), len(skill_dirs())))


if __name__ == "__main__":
    main()
