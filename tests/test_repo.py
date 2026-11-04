import json
import os
import re
import subprocess
import sys
import unittest

from _util import ROOT

SKILLS = sorted(d for d in os.listdir(ROOT) if d.startswith("tayyib-"))


class Repo(unittest.TestCase):
    def test_thirteen_skills(self):
        self.assertEqual(len(SKILLS), 13)

    def test_skill_md_frontmatter(self):
        for d in SKILLS:
            txt = open(os.path.join(ROOT, d, "SKILL.md")).read()
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
            scripts = [f for f in os.listdir(os.path.join(ROOT, d)) if f.endswith(".py") and f != "tayyib_core.py"]
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
