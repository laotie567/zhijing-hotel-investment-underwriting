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

    def test_ctrip_opencli_profile_must_be_named_connected_and_default(self) -> None:
        completed = market_evidence_runtime.subprocess.CompletedProcess(
            args=["opencli", "profile", "list"],
            returncode=0,
            stdout=(
                "Connected Browser Bridge profiles\n\n"
                "  profile-b ctrip-price-worker default — connected v1.0.22\n"
            ),
        )
        with patch.object(market_evidence_runtime.subprocess, "run", return_value=completed) as run:
            self.assertTrue(market_evidence_runtime._ctrip_opencli_profile_ready("opencli"))

        self.assertEqual(["opencli", "profile", "list"], run.call_args.args[0])

    def test_ctrip_opencli_profile_rejects_a_second_connected_browser_bridge(self) -> None:
        completed = market_evidence_runtime.subprocess.CompletedProcess(
            args=["opencli", "profile", "list"],
            returncode=0,
            stdout=(
                "Connected Browser Bridge profiles\n\n"
                "  profile-a developer-chrome-default — connected v1.0.22\n"
                "  profile-b ctrip-price-worker default — connected v1.0.22\n"
            ),
        )
        with patch.object(market_evidence_runtime.subprocess, "run", return_value=completed):
            self.assertFalse(market_evidence_runtime._ctrip_opencli_profile_ready("opencli"))

    def test_ctrip_opencli_profile_ignores_a_disconnected_other_profile(self) -> None:
        completed = market_evidence_runtime.subprocess.CompletedProcess(
            args=["opencli", "profile", "list"],
            returncode=0,
            stdout=(
                "Connected Browser Bridge profiles\n\n"
                "  profile-a developer-chrome-default — disconnected\n"
                "  profile-b ctrip-price-worker default — connected v1.0.22\n"
            ),
        )
        with patch.object(market_evidence_runtime.subprocess, "run", return_value=completed):
            self.assertTrue(market_evidence_runtime._ctrip_opencli_profile_ready("opencli"))

    def test_ctrip_preflight_declares_same_process_live_handshake(self) -> None:
        parser = {"state": "ready", "summary": "parser ready"}
        with patch.object(market_evidence_runtime.Path, "exists", return_value=True), patch.object(
            market_evidence_runtime.Path, "is_file", return_value=True
        ), patch.object(market_evidence_runtime.shutil, "which", return_value="/tmp/tool"), patch.object(
            market_evidence_runtime, "_ctrip_opencli_profile_ready", return_value=True
        ), patch.object(market_evidence_runtime, "_ctrip_search_plugin_ready", return_value=True), patch.object(
            market_evidence_runtime, "_ctrip_dom_parser_status", return_value=parser
        ):
            result = market_evidence_runtime._ctrip_live_rates_status()

        self.assertEqual("ready", result["state"])
        self.assertTrue(result["details"]["uivision_live_handshake"]["required"])

    def test_ctrip_dom_parser_preflight_requires_a_local_python310_scrapling_runtime(self) -> None:
        with patch.object(market_evidence_runtime, "_ctrip_dom_parser_python", return_value="/tmp/python"), patch.object(
            market_evidence_runtime.subprocess,
            "run",
            return_value=market_evidence_runtime.subprocess.CompletedProcess(args=["/tmp/python"], returncode=1),
        ):
            result = market_evidence_runtime._ctrip_dom_parser_status()

        self.assertEqual("action_required", result["state"])
        self.assertIn("requirements-scrapling.txt", result["install_hint"])


if __name__ == "__main__":
    unittest.main()
