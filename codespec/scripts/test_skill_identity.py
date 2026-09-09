# -*- coding: utf-8 -*-
"""Public identity and lightweight-boundary contract for codespec."""

from pathlib import Path
import re
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]


class SkillIdentityContractTest(unittest.TestCase):
    def test_public_identity_is_codespec(self):
        content = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertEqual("codespec", SKILL_ROOT.name)
        self.assertRegex(content, r"(?m)^name:\s*codespec\s*$")
        self.assertIn("/codespec", content)
        self.assertIsNone(re.search(r"(?<![\w-])/ar(?:\s|$)", content))

    def test_lightweight_variant_has_no_oracle_or_build_executor(self):
        forbidden_files = {
            "reasoner_support.py",
            "executor_support.py",
            "design-reasoner-prompt.txt",
            "build-worker-prompt.txt",
            "opencode-worker-profile.md",
        }
        existing = {path.name for path in SKILL_ROOT.rglob("*") if path.is_file()}

        self.assertTrue(forbidden_files.isdisjoint(existing))
        skill_content = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotRegex(skill_content, r"(?i)oracle|worker-argv|set-session|set-default")


if __name__ == "__main__":
    unittest.main()
