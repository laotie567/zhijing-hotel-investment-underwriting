"""Local runtime readiness checks for portable page-evidence collection.

This module deliberately contains no browser automation.  It gives Hermes and
other hosts one deterministic answer about what must be installed on the
machine running the Skill, including a human-readable remediation for Mac mini
deployments.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
COLLECTOR_ROOT = PACKAGE_ROOT / "collector"
KIMI_EXECUTABLE = Path.home() / ".kimi-webbridge" / "bin" / "kimi-webbridge"
EGO_INSTALL_URL = "https://lite.ego.app/document/zh/docs/quick-start"
KIMI_INSTALL_URL = "https://kimi.com/features/webbridge"

EXTERNAL_ENGINE_ENVIRONMENT = {
    "kimi-webbridge": "MARKET_EVIDENCE_KIMI_WEBBRIDGE_COMMAND",
    "crawl4ai": "MARKET_EVIDENCE_CRAWL4AI_COMMAND",
    "xcrawl": "MARKET_EVIDENCE_XCRAWL_COMMAND",
    "opencli": "MARKET_EVIDENCE_OPENCLI_COMMAND",
}
CTRIP_UIVISION_INSTALL_URL = "https://chromewebstore.google.com/detail/ui-vision-rpa/gcbalfbdmfieckjlnblleoemohcganoc"
OPENCLI_INSTALL_URL = "https://github.com/jackwener/OpenCLI"
UIVISION_BRIDGE_PACKAGE = "uivision-mcp-bridge"
UIVISION_MCP_TOKEN_FILE = Path.home() / ".uivision_mcp_token"
CTRIP_DOM_PARSER = PACKAGE_ROOT / "scripts" / "ctrip_dom_parser.py"
CTRIP_DOM_REGISTRY = COLLECTOR_ROOT / "ctrip_element_registry.json"
SCRAPLING_REQUIREMENTS = COLLECTOR_ROOT / "requirements-scrapling.txt"
LOCAL_PARSER_PYTHON = COLLECTOR_ROOT / ".venv" / "bin" / "python"


def _status(
    state: str,
    summary: str,
    *,
    install_hint: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"state": state, "summary": summary}
    if install_hint:
        result["install_hint"] = install_hint
    if details:
        result["details"] = details
    return result


def _configured_command(engine: str) -> dict[str, Any]:
    environment_key = EXTERNAL_ENGINE_ENVIRONMENT[engine]
    configured = os.environ.get(environment_key, "").strip()
    if not configured:
        if engine == "kimi-webbridge":
            return _status(
                "action_required",
                "Kimi WebBridge adapter is not configured.",
                install_hint=(
                    f"Install and connect Kimi WebBridge ({KIMI_INSTALL_URL}), then set "
                    f"{environment_key} to an adapter command that reads/writes the collection JSON contract."
                ),
            )
        return _status(
            "action_required",
            f"{engine} adapter is not configured.",
            install_hint=(
                f"Install the approved {engine} runtime and set {environment_key} to its "
                "JSON-stdin adapter command."
            ),
        )
    try:
        executable = shlex.split(configured)[0]
    except ValueError:
        return _status("failed", f"{environment_key} is not a valid shell command.")
    if shutil.which(executable) is None and not Path(executable).is_file():
        return _status(
            "action_required",
            f"Configured {engine} adapter executable is unavailable: {executable}",
            install_hint=f"Install the configured adapter, or correct {environment_key}.",
        )
    return _status(
        "ready",
        f"{engine} adapter command is configured.",
        details={"environment_variable": environment_key, "executable": executable},
    )


def _ego_status() -> dict[str, Any]:
    if platform.system() != "Darwin":
        return _status(
            "action_required",
            "Ego Lite profile runs only on a macOS host with Ego Lite installed.",
            install_hint=(
                "Use the Playwright profile on this host, or run this profile on the Mac mini "
                f"after installing Ego Lite: {EGO_INSTALL_URL}"
            ),
        )
    executable = shutil.which("ego-browser")
    if executable is None:
        return _status(
            "action_required",
            "Ego Lite command `ego-browser` is unavailable.",
            install_hint=(
                "Install Ego Lite, complete its onboarding/skill installation, then restart Hermes. "
                f"Guide: {EGO_INSTALL_URL}"
            ),
        )
    return _status(
        "ready",
        "Ego Lite runtime is available. Log into the approved OTA in Ego Lite before a live-price run.",
        details={"executable": executable},
    )


def _playwright_status() -> dict[str, Any]:
    if shutil.which("node") is None:
        return _status(
            "action_required",
            "Node.js is unavailable for the bundled Playwright collector.",
            install_hint="Install Node.js LTS, then run `npm ci` and `npx playwright install chromium` in collector/.",
        )
    try:
        probe = subprocess.run(
            [
                "node",
                "-e",
                (
                    "const fs=require('fs'); const {chromium}=require('playwright'); "
                    "const executable=chromium.executablePath(); "
                    "if (!executable || !fs.existsSync(executable)) process.exit(2);"
                ),
            ],
            cwd=COLLECTOR_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _status(
            "action_required",
            "The bundled Playwright package or Chromium browser could not be verified.",
            install_hint="Run `npm ci` and `npx playwright install chromium` in hotel-investment-underwriting/collector/.",
        )
    if probe.returncode != 0:
        return _status(
            "action_required",
            "The bundled Playwright package or Chromium browser is not installed.",
            install_hint="Run `npm ci` and `npx playwright install chromium` in hotel-investment-underwriting/collector/.",
        )
    return _status("ready", "Bundled Playwright runtime and Chromium browser are available.")


def _ctrip_search_plugin_ready(opencli: str) -> bool:
    """Verify the local OpenCLI Ctrip command without searching a hotel page."""

    try:
        probe = subprocess.run(
            [opencli, "ctrip", "search", "--help"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=12,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def _ctrip_opencli_profile_ready(opencli: str) -> bool:
    """Require exactly one connected Browser Bridge: the dedicated worker.

    OpenCLI's ``browser … bind`` refuses to select a tab when two Chrome
    Browser Bridge profiles are connected, even if one is marked ``default``.
    Fail at preflight rather than letting a live collection reach a page and
    then return an opaque RPA error.
    """

    try:
        probe = subprocess.run(
            [opencli, "profile", "list"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            timeout=12,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if probe.returncode != 0:
        return False
    connected = [line for line in probe.stdout.splitlines() if "— connected" in line]
    return len(connected) == 1 and all(
        marker in connected[0] for marker in ("ctrip-price-worker", "default")
    )


def _ctrip_dom_parser_python() -> str | None:
    """Select the isolated parser interpreter without accepting shell syntax."""

    configured = os.environ.get("MARKET_EVIDENCE_PARSER_PYTHON", "").strip()
    if configured:
        # The Node adapter calls this as an executable argument, not through a
        # shell. Reject a multi-token value here so deployment failures are
        # clear and cannot turn into arbitrary local commands.
        try:
            tokens = shlex.split(configured)
        except ValueError:
            return None
        if len(tokens) != 1:
            return None
        executable = tokens[0]
        return executable if shutil.which(executable) or Path(executable).is_file() else None
    if LOCAL_PARSER_PYTHON.is_file():
        return str(LOCAL_PARSER_PYTHON)
    return shutil.which("python3.11")


def _ctrip_dom_parser_status() -> dict[str, Any]:
    """Verify the parser-only Scrapling runtime without opening a browser."""

    missing = [str(path.relative_to(PACKAGE_ROOT)) for path in (CTRIP_DOM_PARSER, CTRIP_DOM_REGISTRY, SCRAPLING_REQUIREMENTS) if not path.is_file()]
    if missing:
        return _status(
            "failed",
            "Bundled Ctrip DOM parser files are missing from this Skill package.",
            details={"missing": missing},
        )
    executable = _ctrip_dom_parser_python()
    install_hint = (
        "Install the isolated parser runtime: `python3.11 -m venv collector/.venv && "
        "collector/.venv/bin/python -m pip install -r collector/requirements-scrapling.txt`. "
        "Or set MARKET_EVIDENCE_PARSER_PYTHON to one Python 3.10+ executable."
    )
    if executable is None:
        return _status(
            "action_required",
            "Python 3.10+ is unavailable for the offline Scrapling Ctrip DOM parser.",
            install_hint=install_hint,
        )
    try:
        probe = subprocess.run(
            [
                executable,
                "-c",
                (
                    "import sys; "
                    "assert sys.version_info >= (3, 10); "
                    "import scrapling; "
                    "assert getattr(scrapling, 'Selector', None) is not None"
                ),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=12,
        )
    except (OSError, subprocess.TimeoutExpired):
        probe = None
    if probe is None or probe.returncode != 0:
        return _status(
            "action_required",
            "The offline Scrapling Ctrip DOM parser runtime is not ready.",
            install_hint=install_hint,
            details={"python": executable},
        )
    return _status(
        "ready",
        "Python 3.10+ and the parser-only Scrapling runtime are available for Ctrip DOM validation.",
        details={"python": executable, "registry": "ctrip-element-registry/v1"},
    )


def _ctrip_live_rates_status() -> dict[str, Any]:
    """Check only deployment prerequisites; never open a booking page or read a session."""

    chrome_path = Path("/Applications/Google Chrome.app")
    chrome_ready = chrome_path.exists()
    opencli = shutil.which("opencli")
    bridge = shutil.which(UIVISION_BRIDGE_PACKAGE)
    details: dict[str, Any] = {
        "chrome": {"ready": chrome_ready, "path": str(chrome_path) if chrome_ready else None},
        "opencli": {"ready": opencli is not None, "executable": opencli},
        "uivision_bridge": {"ready": bridge is not None, "executable": bridge},
        "profile": "ctrip-price-worker",
    }
    if not chrome_ready:
        return _status(
            "action_required",
            "Google Chrome is required for the Ctrip live-rate worker.",
            install_hint="Install Google Chrome, then create the ctrip-price-worker profile.",
            details=details,
        )
    if opencli is None:
        return _status(
            "action_required",
            "OpenCLI is unavailable for the Ctrip live-rate worker.",
            install_hint=f"Install OpenCLI and its Browser Bridge: {OPENCLI_INSTALL_URL}",
            details=details,
        )
    if bridge is None:
        return _status(
            "action_required",
            "Ui.Vision MCP Bridge is unavailable; no page action will be attempted.",
            install_hint=(
                f"Install Ui.Vision in the dedicated Chrome profile ({CTRIP_UIVISION_INSTALL_URL}), "
                f"then install {UIVISION_BRIDGE_PACKAGE} globally and pair its local bridge."
            ),
            details=details,
        )
    if not UIVISION_MCP_TOKEN_FILE.is_file():
        return _status(
            "action_required",
            "Ui.Vision has not been paired with its local MCP Bridge yet.",
            install_hint=(
                "Start the installed Ui.Vision MCP Bridge once to obtain the local pairing token, "
                "paste it in Ui.Vision Settings > AI in ctrip-price-worker, then retry preflight."
            ),
            details=details,
        )
    if not _ctrip_opencli_profile_ready(opencli):
        return _status(
            "action_required",
            "OpenCLI requires exactly one connected Browser Bridge profile: ctrip-price-worker (default).",
            install_hint=(
                "Keep OpenCLI Browser Bridge enabled only in the ctrip-price-worker Chrome profile; "
                "disable it in every other connected Chrome profile, run `opencli profile use ctrip-price-worker`, "
                "then retry preflight."
            ),
            details=details,
        )
    ctrip_search_ready = _ctrip_search_plugin_ready(opencli)
    details["ctrip_search"] = {"ready": ctrip_search_ready}
    if not ctrip_search_ready:
        return _status(
            "action_required",
            "OpenCLI Ctrip search command is unavailable; automatic hotel mapping cannot be verified.",
            install_hint=(
                "Install or enable the approved OpenCLI Ctrip integration in the ctrip-price-worker "
                "profile, then run `opencli ctrip search --help` and retry preflight."
            ),
            details=details,
        )
    dom_parser = _ctrip_dom_parser_status()
    details["scrapling_dom_parser"] = dom_parser
    if dom_parser["state"] != "ready":
        return _status(
            "action_required" if dom_parser["state"] == "action_required" else "failed",
            "Ctrip live-rate collection requires the bundled offline Scrapling DOM parser.",
            install_hint=dom_parser.get("install_hint"),
            details=details,
        )
    # Ui.Vision's side panel connects to the specific stdio bridge process
    # created for a live batch and does not automatically reconnect when a
    # short-lived preflight process exits. The collector therefore owns the
    # definitive, same-process handshake and waits before any page action.
    details["uivision_live_handshake"] = {
        "required": True,
        "when": "after the live ctrip-live-rates collection command starts",
        "action": "keep the ctrip-price-worker Ui.Vision side panel open and click Test if it has not connected",
    }
    return _status(
        "ready",
        "Chrome, OpenCLI Browser Bridge and the Ui.Vision pairing prerequisites are ready. A live Ctrip batch waits for its same-process side-panel handshake before any page action.",
        details=details,
    )


def _kimi_daemon_status() -> dict[str, Any]:
    if not KIMI_EXECUTABLE.is_file():
        return _status(
            "action_required",
            "Kimi WebBridge daemon/extension is not installed on this Mac.",
            install_hint=f"Install and connect Kimi WebBridge: {KIMI_INSTALL_URL}",
        )
    try:
        process = subprocess.run(
            [str(KIMI_EXECUTABLE), "status"],
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            timeout=10,
        )
        details = json.loads(process.stdout) if process.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        details = {}
    # ``kimi-webbridge status`` can contain host-specific extension metadata.
    # Preflight is an operational hand-off, not a diagnostic dump: retain only
    # the readiness facts that Hermes and an operator need.
    safe_details = {
        key: details[key]
        for key in ("version", "extension_version", "running", "extension_connected")
        if key in details
    }
    if details.get("running") is True and details.get("extension_connected") is True:
        return _status(
            "ready",
            "Kimi WebBridge daemon and extension are connected.",
            details=safe_details or None,
        )
    return _status(
        "action_required",
        "Kimi WebBridge is installed but the daemon or browser extension is not connected.",
        install_hint=(
            f"Open the Kimi WebBridge extension, connect it, then retry. Guide: {KIMI_INSTALL_URL}"
        ),
        details=safe_details or None,
    )


def check_engine(engine: str) -> dict[str, Any]:
    """Return a machine-readable readiness result without changing host state."""

    if engine == "ego-browser":
        return _ego_status()
    if engine == "playwright":
        return _playwright_status()
    if engine == "ctrip-live-rates":
        return _ctrip_live_rates_status()
    if engine == "kimi-webbridge":
        adapter = _configured_command(engine)
        daemon = _kimi_daemon_status()
        if adapter["state"] == "ready" and daemon["state"] == "ready":
            return _status("ready", "Kimi WebBridge adapter and browser connection are ready.", details={"adapter": adapter, "daemon": daemon})
        return _status("action_required", "Kimi WebBridge cannot collect until both adapter and browser connection are ready.", install_hint=adapter.get("install_hint") or daemon.get("install_hint"), details={"adapter": adapter, "daemon": daemon})
    if engine in EXTERNAL_ENGINE_ENVIRONMENT:
        return _configured_command(engine)
    return _status("failed", f"Unknown page collection engine: {engine}")


def preflight(engines: list[str]) -> dict[str, Any]:
    return {
        "runtime_contract": "market-evidence-runtime/v1",
        "host": {"platform": platform.system(), "machine": platform.machine()},
        "engines": {engine: check_engine(engine) for engine in engines},
    }


def require_ready(engine: str) -> None:
    result = check_engine(engine)
    if result["state"] == "ready":
        return
    hint = result.get("install_hint")
    suffix = f" {hint}" if isinstance(hint, str) and hint else ""
    raise RuntimeError(f"{result['summary']}{suffix}")
