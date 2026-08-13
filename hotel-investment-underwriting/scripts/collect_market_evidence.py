#!/usr/bin/env python3
"""Run a versioned browser-page collection adapter without a Codex UI.

The command is deliberately a small host tool, not a second underwriting
application.  It validates input, invokes one explicitly selected page engine,
validates the returned receipt, and emits only portable JSON.  Any Agent runtime
can call it over stdin/CLI or local HTTP.
"""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any

import market_evidence_contract
import market_evidence_runtime


_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_PLAYWRIGHT_RUNNER = _PACKAGE_ROOT / "collector" / "playwright_360_map.mjs"
_EGO_RUNNER = _PACKAGE_ROOT / "collector" / "ego_ctrip.mjs"
_CTRIP_LIVE_RATES_RUNNER = _PACKAGE_ROOT / "collector" / "ctrip_live_rates.mjs"
_EXTERNAL_ENGINE_ENVIRONMENT = {
    "kimi-webbridge": "MARKET_EVIDENCE_KIMI_WEBBRIDGE_COMMAND",
    "crawl4ai": "MARKET_EVIDENCE_CRAWL4AI_COMMAND",
    "xcrawl": "MARKET_EVIDENCE_XCRAWL_COMMAND",
    "opencli": "MARKET_EVIDENCE_OPENCLI_COMMAND",
}


class CollectionExecutionError(RuntimeError):
    """Raised when the requested page engine cannot produce one receipt."""


def _load_input(path: str) -> dict[str, Any]:
    if path == "-":
        value = json.load(sys.stdin)
        if not isinstance(value, dict):
            raise market_evidence_contract.MarketEvidenceContractError(
                "stdin must contain one JSON object"
            )
        return value
    return market_evidence_contract.load_json_object(path)


def _run_process(command: list[str], request: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    try:
        process = subprocess.run(
            command,
            input=json.dumps(request, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise CollectionExecutionError(f"page collector executable is unavailable: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CollectionExecutionError(
            f"page collector exceeded {timeout_seconds} seconds"
        ) from exc
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip() or "no diagnostic output"
        raise CollectionExecutionError(f"page collector failed: {detail}")
    try:
        value = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise CollectionExecutionError("page collector did not return one JSON object") from exc
    if not isinstance(value, dict):
        raise CollectionExecutionError("page collector did not return one JSON object")
    return value


def _run_ego_browser(request: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    """Run the bundled Ego profile and close its isolated task space safely.

    `ego-browser nodejs` reads JavaScript from stdin, so the validated request
    is injected as a JSON string into the short-lived JavaScript program. The cleanup
    command is intentionally a separate invocation: Ego requires task-space
    completion to happen after the collection command has produced its result.
    """

    if not _EGO_RUNNER.is_file():
        raise CollectionExecutionError("bundled Ego Ctrip collector is missing")
    source = _EGO_RUNNER.read_text(encoding="utf-8")
    marker = 'const raw = process.env.MARKET_EVIDENCE_REQUEST_JSON;'
    if marker not in source:
        raise CollectionExecutionError("bundled Ego Ctrip collector has no request-input marker")
    source = source.replace(
        marker,
        "const raw = "
        + json.dumps(
            json.dumps(request, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
            ensure_ascii=False,
        )
        + ";",
        1,
    )
    try:
        process = subprocess.run(
            ["ego-browser", "nodejs"],
            input=source,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise CollectionExecutionError(
            "Ego Lite command `ego-browser` is unavailable. Install Ego Lite and restart the host. "
            "Guide: https://lite.ego.app/document/zh/docs/quick-start"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise CollectionExecutionError(f"Ego page collector exceeded {timeout_seconds} seconds") from exc
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip() or "no diagnostic output"
        raise CollectionExecutionError(f"Ego page collector failed: {detail}")
    rendered_candidates = (process.stdout.strip(), process.stderr.strip())
    envelope = None
    for rendered in rendered_candidates:
        if not rendered:
            continue
        try:
            candidate = json.loads(rendered)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            envelope = candidate
            break
    if envelope is None:
        diagnostic = next((item for item in rendered_candidates if item), "")[:2_000]
        suffix = f": {diagnostic}" if diagnostic else ""
        raise CollectionExecutionError(f"Ego page collector did not return one JSON object{suffix}")
    if not isinstance(envelope, dict) or not isinstance(envelope.get("task_space_id"), int):
        raise CollectionExecutionError("Ego page collector returned no task-space receipt")
    result = envelope.get("result")
    if not isinstance(result, dict):
        raise CollectionExecutionError("Ego page collector returned no collection result")
    cleanup = "\n".join(
        (
            f"const completion = await completeTaskSpace({envelope['task_space_id']}, {{ keep: false }});",
            "cliLog(JSON.stringify(completion));",
        )
    )
    try:
        cleanup_process = subprocess.run(
            ["ego-browser", "nodejs"],
            input=cleanup,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CollectionExecutionError("Ego collection returned evidence but task-space cleanup failed") from exc
    if cleanup_process.returncode != 0:
        detail = cleanup_process.stderr.strip() or cleanup_process.stdout.strip() or "no diagnostic output"
        raise CollectionExecutionError(f"Ego task-space cleanup failed: {detail}")
    return result


def collect(request: dict[str, Any], *, engine: str, timeout_seconds: int) -> dict[str, Any]:
    """Collect evidence with one selected engine; never silently switch engines."""

    normalized = market_evidence_contract.validate_collection_request(request)
    try:
        market_evidence_runtime.require_ready(engine)
    except RuntimeError as exc:
        raise CollectionExecutionError(str(exc)) from exc
    if engine == "playwright":
        if not _PLAYWRIGHT_RUNNER.is_file():
            raise CollectionExecutionError("bundled Playwright collector is missing")
        response = _run_process(
            ["node", str(_PLAYWRIGHT_RUNNER)], normalized, timeout_seconds
        )
    elif engine == "ego-browser":
        response = _run_ego_browser(normalized, timeout_seconds)
    elif engine == "ctrip-live-rates":
        if not _CTRIP_LIVE_RATES_RUNNER.is_file():
            raise CollectionExecutionError("bundled Ctrip live-rate collector is missing")
        response = _run_process(
            ["node", str(_CTRIP_LIVE_RATES_RUNNER)], normalized, timeout_seconds
        )
    else:
        environment_key = _EXTERNAL_ENGINE_ENVIRONMENT.get(engine)
        if environment_key is None:
            supported = ", ".join(sorted(market_evidence_contract.SUPPORTED_ENGINES))
            raise CollectionExecutionError(f"unknown page engine {engine!r}; use one of {supported}")
        configured = os.environ.get(environment_key, "").strip()
        if not configured:
            raise CollectionExecutionError(
                f"{engine} is not configured; set {environment_key} to its JSON-stdin adapter command"
            )
        response = _run_process(shlex.split(configured), normalized, timeout_seconds)
    return market_evidence_contract.validate_collection_result(response)


def _render(result: dict[str, Any], output_format: str) -> str:
    rendered: Any = (
        market_evidence_contract.skill_request_patch(result)
        if output_format == "skill-patch"
        else result
    )
    return json.dumps(rendered, ensure_ascii=False, indent=2, allow_nan=False)


def _serve(host: str, port: int, engine: str, timeout_seconds: int) -> None:
    """Expose the same local-only contract for Hermes/function-tool hosts."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - HTTP method spelling is required
            if self.path not in {"/v1/collect", "/v1/collect/skill-patch"}:
                self.send_error(HTTPStatus.NOT_FOUND, "unknown collection endpoint")
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length < 1 or content_length > 2_000_000:
                    raise CollectionExecutionError("request body must be 1..2,000,000 bytes")
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise CollectionExecutionError("request body must be one JSON object")
                result = collect(payload, engine=engine, timeout_seconds=timeout_seconds)
                body = _render(
                    result,
                    "skill-patch" if self.path.endswith("skill-patch") else "result",
                ).encode("utf-8")
                self.send_response(HTTPStatus.OK)
            except (
                CollectionExecutionError,
                market_evidence_contract.MarketEvidenceContractError,
                json.JSONDecodeError,
                UnicodeDecodeError,
                ValueError,
            ) as exc:
                body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.BAD_REQUEST)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"market-evidence collector listening on http://{host}:{port}", file=sys.stderr)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect page-sourced 2km competitor evidence for the underwriting Skill"
    )
    parser.add_argument("--input", help="Collection request JSON path, or - for stdin")
    parser.add_argument("--output", help="Write JSON to this path instead of stdout")
    parser.add_argument("--format", choices=("result", "skill-patch"), default="result")
    parser.add_argument(
        "--engine",
        choices=tuple(sorted(market_evidence_contract.SUPPORTED_ENGINES)),
        default="playwright",
    )
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--serve", metavar="HOST:PORT", help="Run local HTTP endpoints instead")
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Print local runtime readiness and Mac mini installation guidance, then exit",
    )
    parser.add_argument(
        "--all-engines",
        action="store_true",
        help="With --preflight, inspect every supported engine instead of only --engine",
    )
    args = parser.parse_args()
    if not 10 <= args.timeout_seconds <= 600:
        parser.error("--timeout-seconds must be 10..600")
    if args.preflight:
        if args.input or args.output or args.serve:
            parser.error("--preflight cannot be combined with --input, --output or --serve")
        engines = (
            sorted(market_evidence_contract.SUPPORTED_ENGINES)
            if args.all_engines
            else [args.engine]
        )
        print(json.dumps(market_evidence_runtime.preflight(engines), ensure_ascii=False, indent=2))
        return 0
    if args.all_engines:
        parser.error("--all-engines requires --preflight")
    if args.serve:
        if args.input or args.output:
            parser.error("--serve cannot be combined with --input or --output")
        try:
            host, raw_port = args.serve.rsplit(":", 1)
            port = int(raw_port)
        except ValueError:
            parser.error("--serve must be HOST:PORT")
        if host not in {"127.0.0.1", "localhost"} or not 1 <= port <= 65535:
            parser.error("--serve accepts only 127.0.0.1:PORT or localhost:PORT")
        _serve(host, port, args.engine, args.timeout_seconds)
        return 0
    if not args.input:
        parser.error("--input is required unless --serve is used")
    try:
        result = collect(_load_input(args.input), engine=args.engine, timeout_seconds=args.timeout_seconds)
        rendered = _render(result, args.format)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
    except (CollectionExecutionError, market_evidence_contract.MarketEvidenceContractError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
