"""Public-contract tests for the offline Scrapling Ctrip DOM parser."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
PARSER = ROOT / "scripts" / "ctrip_dom_parser.py"
FIXTURES = ROOT / "tests" / "fixtures" / "ctrip"


def parser_python() -> str:
    configured = os.environ.get("MARKET_EVIDENCE_PARSER_PYTHON", "").strip()
    if configured:
        return configured
    local = ROOT / "collector" / ".venv" / "bin" / "python"
    return str(local) if local.is_file() else "python3.11"


def payload(name: str) -> dict:
    return {
        "source_url": "https://hotels.ctrip.com/hotels/detail/?hotelId=1001",
        "dom_fragment": (FIXTURES / name).read_text(encoding="utf-8"),
        "pricing_context": {
            "check_in_date": "2026-08-20",
            "nights": 1,
            "guests": 2,
            "currency": "CNY",
        },
    }


def run_parser(value: dict, *arguments: str) -> dict:
    completed = subprocess.run(
        [parser_python(), str(PARSER), "--input", "-", *arguments],
        input=json.dumps(value, ensure_ascii=False),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


class CtripDomParserTests(unittest.TestCase):
    def test_offline_parser_returns_a_complete_structured_room_and_query_evidence(self) -> None:
        value = payload("room-panel-v1.html")

        result = run_parser(value)

        self.assertEqual("ctrip-dom-parser/v1", result["parser_version"])
        self.assertEqual("ctrip-element-registry/v1", result["registry_version"])
        self.assertEqual(
            hashlib.sha256(value["dom_fragment"].encode("utf-8")).hexdigest(),
            result["evidence"]["dom_fragment_sha256"],
        )
        self.assertTrue(result["context_evidence"]["verified"])
        self.assertEqual(
            {
                "room_id": "room-101",
                "room_name": "双人电竞大床房",
                "rate_plan_name": "含双早 · 免费取消",
                "display_price": 328,
                "availability": "available",
                "tax_included": True,
                "cancellation_policy": "免费取消",
                "workstations": 2,
                "selector_source": "primary",
                "adaptive_recovered": False,
                "requires_cross_validation": True,
            },
            result["rooms"][0],
        )

    def test_layout_drift_uses_only_a_previously_saved_container_as_an_adaptive_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / "adaptive.sqlite"
            run_parser(
                payload("room-panel-v1.html"),
                "--adaptive-store",
                str(store),
                "--save-adaptive",
            )

            result = run_parser(
                payload("room-panel-v1-layout-drift.html"),
                "--adaptive-store",
                str(store),
                "--enable-adaptive",
            )

        self.assertEqual("adaptive", result["room_container"]["selector_source"])
        self.assertTrue(result["room_container"]["adaptive_recovered"])
        self.assertEqual(328, result["rooms"][0]["display_price"])
        self.assertTrue(result["rooms"][0]["requires_cross_validation"])

    def test_parser_is_offline_and_rejects_a_non_http_source_identity(self) -> None:
        value = payload("room-panel-v1.html")
        value["source_url"] = "file:///private/room.html"

        completed = subprocess.run(
            [parser_python(), str(PARSER), "--input", "-"],
            input=json.dumps(value, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(0, completed.returncode)
        self.assertIn("source_url", completed.stderr)

    def test_parser_rejects_a_lookalike_domain_not_owned_by_ctrip(self) -> None:
        value = payload("room-panel-v1.html")
        value["source_url"] = "https://notctrip.com/hotels/detail/?hotelId=1001"

        completed = subprocess.run(
            [parser_python(), str(PARSER), "--input", "-"],
            input=json.dumps(value, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(0, completed.returncode)
        self.assertIn("source_url", completed.stderr)

    def test_missing_tax_text_is_unknown_not_an_inferred_tax_exclusion(self) -> None:
        value = payload("room-panel-v1.html")
        value["dom_fragment"] = value["dom_fragment"].replace(
            '<span data-testid="tax-scope">含税</span>',
            '<span data-testid="tax-scope"></span>',
        )

        result = run_parser(value)

        self.assertIsNone(result["rooms"][0]["tax_included"])


if __name__ == "__main__":
    unittest.main()
