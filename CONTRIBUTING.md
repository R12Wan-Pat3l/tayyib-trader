# Contributing

Thank you for helping. How changes work here:

- **Only the maintainer (@R12Wan-Pat3l) can change this repository.** Nobody else can push to it.
- To suggest a change: **fork** the repo, make your change on a branch in your fork, and open a
  **pull request**. The maintainer reviews it and merges it only if they approve. Every file is owned
  by the maintainer (see `.github/CODEOWNERS`), so no pull request can be merged without that review.
- Small fixes (typos, a broken news feed, a wrong charge rate, a halal screen mismatch) are very welcome.
  For anything bigger, open an issue first so we can agree on it.

## Rules every change must keep

1. Halal-compliant stocks only. Do not weaken the screen or its defaults.
2. CNC delivery only. No intraday, F&O, short selling, margin or MTF, in code or in docs.
3. Nothing places, modifies or cancels an order without the user's explicit yes for that exact
   order. Pull requests that add automatic order placement will not be merged.
4. Standard library only, Python 3.8+. No new dependencies.
5. Edit `core/tayyib_core.py`, never the copies in skill folders, then `python3 tools/sync_core.py`.
6. `python3 -m unittest discover -s tests` must pass, and new behaviour needs a test.

## Halal methodology changes

Changes to thresholds, excluded industries or the known-excluded list need a source (a published
Shariah methodology, a fatwa from a recognised body, or an index provider's document) linked in the
pull request.

## Never commit

Your `trader/` folder, broker keys, tokens, passwords or account numbers.

## Releasing (maintainer)

1. Bump `"version"` in `.claude-plugin/plugin.json` (e.g. 0.1.0 -> 0.1.1). Without this,
   `claude plugin update` tells existing users they are already up to date.
2. Add the changes to `CHANGELOG.md`.
3. Tests green, `python3 tools/sync_core.py --check` clean, then tag `vX.Y.Z` and publish the release.
