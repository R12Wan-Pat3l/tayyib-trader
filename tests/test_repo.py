import json
import os
import re
import subprocess
import sys
import unittest

from _util import ROOT

SKILLS = sorted(d for d in os.listdir(ROOT) if d.startswith("tayyib-"))


class Repo(unittest.TestCase):
    def test_seventeen_skills(self):
        self.assertEqual(len(SKILLS), 17)

    def test_skill_md_frontmatter(self):
        for d in SKILLS:
            txt = open(os.path.join(ROOT, d, "SKILL.md"), encoding="utf-8").read()
            m = re.match(r"---\nname: (\S+)\ndescription: >-\n((?:  .+\n)+)argument-hint: .+\n---\n", txt)
            self.assertTrue(m, d)
            self.assertEqual(m.group(1), d)
            self.assertLess(len(m.group(2)), 1024, d)

    def test_core_copies_in_sync(self):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "sync_core.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout)

    def test_each_skill_runs_alone(self):
        for d in SKILLS:
            helpers = {"tayyib_core.py", "actions.py"} if d == "tayyib-dashboard" else {"tayyib_core.py"}
            scripts = [f for f in os.listdir(os.path.join(ROOT, d)) if f.endswith(".py") and f not in helpers]
            self.assertEqual(len(scripts), 1, d)
            p = subprocess.run([sys.executable, os.path.join(ROOT, d, scripts[0]), "--help"],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, d + p.stderr)

    def test_manifests(self):
        pl = json.load(open(os.path.join(ROOT, ".claude-plugin", "plugin.json")))
        mk = json.load(open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")))
        self.assertEqual(pl["name"], mk["plugins"][0]["name"])
        json.load(open(os.path.join(ROOT, "config.example.json")))

    def test_readme_lists_every_skill(self):
        readme = open(os.path.join(ROOT, "README.md")).read()
        for d in SKILLS:
            self.assertIn(d, readme)


if __name__ == "__main__":
    unittest.main()


class Versions(unittest.TestCase):
    def test_versions_agree(self):
        pl = json.load(open(os.path.join(ROOT, ".claude-plugin", "plugin.json")))["version"]
        core = re.search(r'VERSION = "([^"]+)"', open(os.path.join(ROOT, "core", "tayyib_core.py")).read()).group(1)
        mcp = re.search(r'VERSION = "([^"]+)"', open(os.path.join(ROOT, "mcp", "server.py")).read()).group(1)
        top = re.search(r"^## v(\S+)", open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read(), re.M).group(1)
        self.assertEqual(len({pl, core, mcp, top}), 1,
                         "bump every version together: plugin.json %s, core %s, mcp %s, CHANGELOG %s"
                         % (pl, core, mcp, top))


class ReleaseNotes(unittest.TestCase):
    def test_notes_for_top_version(self):
        top = re.search(r"^## v(\S+)", open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read(), re.M).group(1)
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "release_notes.py"), "v" + top],
                           capture_output=True, encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="cp1252"))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(p.stdout.startswith("## v" + top))
        self.assertNotIn("](docs/", p.stdout)                          # links made absolute
        self.assertIn("Not a fatwa", p.stdout)
        self.assertNotEqual(subprocess.run([sys.executable, os.path.join(ROOT, "tools", "release_notes.py"),
                                            "v9.9.9"], capture_output=True, text=True).returncode, 0)
