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
