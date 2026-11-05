# tayyib-trader

Start with docs/PROJECT_BRIEF.md (what exists, decisions made, data files, the user's setup).

Read AGENTS.md: the rules there (halal only, CNC only, never place orders, explicit yes) apply to every
change and every answer. Edit core/tayyib_core.py, never the copies in skill folders, then run
`python3 tools/sync_core.py` and `python3 -m unittest discover -s tests`.
