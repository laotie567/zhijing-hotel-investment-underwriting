"""Release-boundary tests for the one published Skill."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import subprocess
import unittest
import zipfile


SKILL_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = SKILL_ROOT.parent
SKILL_PREFIX = "hotel-investment-underwriting/"
PUBLISHED_FILES = {
    SKILL_PREFIX.rstrip("/"),
    f"{SKILL_PREFIX}.gitattributes",
    f"{SKILL_PREFIX}SKILL.md",
    f"{SKILL_PREFIX}VERSION",
    f"{SKILL_PREFIX}agents",
    f"{SKILL_PREFIX}agents/openai.yaml",
    f"{SKILL_PREFIX}references",
    f"{SKILL_PREFIX}references/benchmark-defaults.json",
    f"{SKILL_PREFIX}references/bitable-delivery.md",
    f"{SKILL_PREFIX}references/decision-policy.md",
    f"{SKILL_PREFIX}references/input-schema.md",
    f"{SKILL_PREFIX}references/market-evidence-collection.md",
    f"{SKILL_PREFIX}references/market-evidence-runtime.md",
    f"{SKILL_PREFIX}references/methodology.md",
    f"{SKILL_PREFIX}schemas",
    f"{SKILL_PREFIX}schemas/market-evidence-collection.schema.json",
    f"{SKILL_PREFIX}schemas/project-input.schema.json",
    f"{SKILL_PREFIX}schemas/skill-request.schema.json",
    f"{SKILL_PREFIX}scripts",
    f"{SKILL_PREFIX}scripts/run.py",
    f"{SKILL_PREFIX}scripts/collect_market_evidence.py",
    f"{SKILL_PREFIX}scripts/input_contract.py",
    f"{SKILL_PREFIX}scripts/market_evidence_contract.py",
    f"{SKILL_PREFIX}scripts/market_evidence_runtime.py",
    f"{SKILL_PREFIX}scripts/competitor_analysis.py",
    f"{SKILL_PREFIX}scripts/competitor_report.py",
    f"{SKILL_PREFIX}scripts/bitable_delivery.py",
    f"{SKILL_PREFIX}scripts/calculate.py",
    f"{SKILL_PREFIX}collector",
    f"{SKILL_PREFIX}collector/package.json",
    f"{SKILL_PREFIX}collector/package-lock.json",
    f"{SKILL_PREFIX}collector/playwright_360_map.mjs",
    f"{SKILL_PREFIX}collector/ego_ctrip.mjs",
    f"{SKILL_PREFIX}collector/ctrip_live_rates.mjs",
}


class ReleaseArchiveTests(unittest.TestCase):
    def test_published_skill_archive_has_an_exact_runtime_allowlist(self) -> None:
        tree = subprocess.run(
            ["git", "write-tree"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        archive = subprocess.run(
            [
                "git",
                "archive",
                "--format=zip",
                tree,
                SKILL_PREFIX.rstrip("/"),
            ],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            check=True,
        )
        names = {
            name.rstrip("/")
            for name in zipfile.ZipFile(BytesIO(archive.stdout)).namelist()
        }

        self.assertTrue(names)
        self.assertEqual(PUBLISHED_FILES, names, names)


if __name__ == "__main__":
    unittest.main()
