"""Tests for portable Mac Mini/Hermes collection-runtime readiness checks."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import market_evidence_runtime  # noqa: E402


class MarketEvidenceRuntimeTests(unittest.TestCase):
    def test_ego_missing_on_a_mac_gives_an_install_action_not_a_hidden_fallback(self) -> None:
        with patch.object(market_evidence_runtime.platform, "system", return_value="Darwin"), patch.object(
            market_evidence_runtime.shutil, "which", return_value=None
        ):
            result = market_evidence_runtime.check_engine("ego-browser")

        self.assertEqual("action_required", result["state"])
        self.assertIn("Ego Lite", result["install_hint"])

    def test_kimi_requires_both_adapter_and_connected_browser(self) -> None:
        adapter = {"state": "action_required", "summary": "adapter missing", "install_hint": "install adapter"}
        daemon = {"state": "ready", "summary": "browser ready"}
        with patch.object(market_evidence_runtime, "_configured_command", return_value=adapter), patch.object(
            market_evidence_runtime, "_kimi_daemon_status", return_value=daemon
        ):
            result = market_evidence_runtime.check_engine("kimi-webbridge")

        self.assertEqual("action_required", result["state"])
        self.assertEqual(adapter, result["details"]["adapter"])
        self.assertEqual(daemon, result["details"]["daemon"])

    def test_preflight_is_machine_readable_for_hermes(self) -> None:
        with patch.object(
            market_evidence_runtime,
            "check_engine",
            side_effect=lambda engine: {"state": "ready", "summary": engine},
        ):
            result = market_evidence_runtime.preflight(["playwright", "ego-browser"])

        self.assertEqual("market-evidence-runtime/v1", result["runtime_contract"])
        self.assertEqual({"playwright", "ego-browser"}, set(result["engines"]))

    def test_kimi_preflight_does_not_expose_extension_specific_metadata(self) -> None:
        raw_status = {
            "running": True,
            "extension_connected": True,
            "version": "1.2.3",
            "extension_id": "host-specific-value",
        }
        completed = market_evidence_runtime.subprocess.CompletedProcess(
            args=["kimi-webbridge", "status"], returncode=0, stdout=json.dumps(raw_status)
        )
        executable = MagicMock()
        executable.is_file.return_value = True
        executable.__str__.return_value = "/tmp/kimi-webbridge"
        with patch.object(market_evidence_runtime, "KIMI_EXECUTABLE", executable), patch.object(
            market_evidence_runtime, "subprocess"
        ) as mocked_subprocess:
            mocked_subprocess.run.return_value = completed
            result = market_evidence_runtime._kimi_daemon_status()

        self.assertEqual("ready", result["state"])
        self.assertNotIn("extension_id", result["details"])

    def test_ctrip_mapping_plugin_probe_never_searches_a_real_hotel(self) -> None:
        completed = market_evidence_runtime.subprocess.CompletedProcess(
            args=["opencli", "ctrip", "search", "--help"], returncode=0
        )
        with patch.object(market_evidence_runtime.subprocess, "run", return_value=completed) as run:
            self.assertTrue(market_evidence_runtime._ctrip_search_plugin_ready("opencli"))

        self.assertEqual(["opencli", "ctrip", "search", "--help"], run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
