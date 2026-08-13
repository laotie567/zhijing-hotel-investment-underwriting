"""Integration tests for the single published underwriting-Skill entrypoint."""

from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import run  # noqa: E402


def competitor_input() -> dict:
    source = {
        "source_platform": "dianping",
        "source_url": "https://www.dianping.com/shop/example",
        "observed_at": "2026-08-12T09:10:00+08:00",
        "confidence": "high",
    }
    candidates = []
    for index, price in enumerate((240, 260, 280), start=1):
        candidates.append(
            {
                "provider": "amap",
                "provider_place_id": f"P-{index}",
                "name": f"竞品{index}",
                "coordinate_system": "GCJ-02",
                "longitude": 104.0 + index / 1_000,
                "latitude": 30.0,
                "property_kind": "lodging",
                "esports_positioning": "primary",
                "operating_status": "operating",
                "source": source,
                "room_offers": [
                    {
                        "room_type": "双人电竞房",
                        "room_type_provider_id": f"P-{index}:room-2",
                        "workstations": 2,
                        "nightly_price": price,
                        "availability": "available",
                        "currency": "CNY",
                        "tax_included": True,
                        "cancellation_policy": "免费取消",
                        "pricing_context": {
                            "check_in_date": "2026-08-26",
                            "nights": 1,
                            "guests": 2,
                            "currency": "CNY",
                        },
                        "source_url": "https://m.ctrip.com/html5/hotel/hoteldetail/example.html",
                        "observed_at": "2026-08-12T09:10:00+08:00",
                    }
                ],
                "pricing_observations": (
                    [
                        {
                            "room_type": "双人电竞房",
                            "room_type_provider_id": f"P-{index}:room-2",
                            "price_type": "P2",
                            "display_price": price,
                            "currency": "CNY",
                            "availability": "available",
                            "pricing_context": {
                                "check_in_date": "2026-08-26",
                                "nights": 1,
                                "guests": 2,
                                "currency": "CNY",
                            },
                            "source_url": "https://hotels.ctrip.com/hotels/detail/?hotelId=1",
                            "observed_at": "2026-08-12T09:10:00+08:00",
                            "network_verified": True,
                            "dom_verified": True,
                            "price_match": True,
                            "adr_eligible": False,
                            "qualification_gaps": ["tax_scope_unknown"],
                        }
                    ]
                    if index == 1
                    else []
                ),
            }
        )
    return {
        "confirmed_location": {
            "provider": "amap",
            "provider_place_id": "target-place",
            "coordinate_system": "GCJ-02",
            "longitude": 104.0,
            "latitude": 30.0,
            "status": "confirmed",
        },
        "collection_status": "complete",
        "pricing_context": {
            "check_in_date": "2026-08-26",
            "nights": 1,
            "guests": 2,
            "currency": "CNY",
        },
        "candidates": candidates,
    }


def competitor_report_input() -> dict:
    return {
        "title": "竞品装修与房型调研报告 <script>alert('unsafe')</script>",
        "candidate_media": [
            {
                "provider_place_id": "P-1",
                "renovation_observation": "公开房图显示暖色木饰面与双机位桌面。",
                "observation_source_url": "https://www.example.com/observation",
                "images": [
                    {
                        "caption": "双人电竞房公开图",
                        "data_uri": (
                            "data:image/png;base64,"
                            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
                            "AAAADUlEQVQIHWP4z8DwHwAFgAI/ScL9XQAAAABJRU5ErkJggg=="
                        ),
                        "source_url": "https://www.example.com/image",
                    }
                ],
            }
        ],
    }


class SkillRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project_input = json.loads(
            (ROOT / "references" / "sample-predeal-hotel.json").read_text(encoding="utf-8")
        )
        self.defaults = json.loads(
            (ROOT / "references" / "benchmark-defaults.json").read_text(encoding="utf-8")
        )

    def test_runs_mandatory_2km_analysis_and_financial_calculation_from_one_request(self) -> None:
        result = run.run(
            {
                "project_input": self.project_input,
                "competitor_analysis": competitor_input(),
            },
            defaults=self.defaults,
        )

        self.assertEqual("ok", result["status"])
        self.assertEqual("ready_for_review", result["workflow"]["status"])
        self.assertEqual("complete", result["competitor_analysis"]["status"])
        self.assertEqual(3, result["competitor_analysis"]["formal_competitor_count"])
        self.assertEqual(260.0, result["competitor_analysis"]["pricing_by_workstations"][0]["recommended_adr"])
        self.assertEqual("ok", result["financial_result"]["status"])
        self.assertEqual("ready_for_review", result["conclusion_scope"])
        self.assertEqual("ready_for_review", result["financial_result"]["conclusion_scope"])
        self.assertEqual("not_applied", result["workflow"]["competitor_pricing_to_financial_input"])
        self.assertIn("3家独立物业", result["feishu_summary"])
        expected_financial_result = run.calculate.run(self.project_input, self.defaults)
        expected_financial_result["conclusion_scope"] = "ready_for_review"
        self.assertEqual(
            expected_financial_result,
            result["financial_result"],
        )

    def test_still_returns_a_low_evidence_pre_evaluation_when_competitor_collection_is_missing(self) -> None:
        result = run.run({"project_input": self.project_input}, defaults=self.defaults)

        self.assertEqual("pre_evaluation_only", result["workflow"]["status"])
        self.assertEqual("needs_location_confirmation", result["competitor_analysis"]["status"])
        self.assertEqual("ok", result["financial_result"]["status"])
        self.assertEqual("pre_evaluation_only", result["conclusion_scope"])
        self.assertEqual(
            "pre_evaluation_only", result["financial_result"]["conclusion_scope"]
        )
        self.assertIn("2km竞品", result["workflow"]["conditions"][0])
        self.assertIn("【财务预评估】", result["feishu_summary"])

    def test_incomplete_candidate_evidence_keeps_the_combined_workflow_pre_evaluation_only(self) -> None:
        competitors = competitor_input()
        del competitors["candidates"][0]["source"]

        result = run.run(
            {"project_input": self.project_input, "competitor_analysis": competitors},
            defaults=self.defaults,
        )

        self.assertEqual("evidence_insufficient", result["competitor_analysis"]["status"])
        self.assertEqual("pre_evaluation_only", result["workflow"]["status"])

    def test_explains_when_shared_pricing_context_is_missing(self) -> None:
        competitors = competitor_input()
        del competitors["pricing_context"]

        result = run.run(
            {"project_input": self.project_input, "competitor_analysis": competitors},
            defaults=self.defaults,
        )

        self.assertEqual("ready_for_review", result["workflow"]["status"])
        self.assertIn("统一报价条件", result["workflow"]["conditions"][0])
        self.assertIn("pricing_context_missing", result["feishu_summary"])

    def test_explains_when_only_low_confidence_pricing_is_available(self) -> None:
        competitors = competitor_input()
        for candidate in competitors["candidates"]:
            candidate["source"]["confidence"] = "low"

        result = run.run(
            {"project_input": self.project_input, "competitor_analysis": competitors},
            defaults=self.defaults,
        )

        self.assertEqual("ready_for_review", result["workflow"]["status"])
        self.assertIn("中/高置信度", result["workflow"]["conditions"][0])
        self.assertIn("低置信度来源未计入", result["feishu_summary"])

    def test_rejects_unknown_project_fields_at_the_public_entrypoint(self) -> None:
        project_input = json.loads(json.dumps(self.project_input))
        project_input["project"]["unapproved_field"] = True

        with self.assertRaises(run.SkillRunError) as caught:
            run.run({"project_input": project_input}, defaults=self.defaults)

        self.assertIn("unknown field", str(caught.exception))
        self.assertIn("$.project_input.project.unapproved_field", str(caught.exception))

    def test_rejects_unknown_fields_in_external_defaults(self) -> None:
        defaults = json.loads(json.dumps(self.defaults))
        defaults["unapproved_default"] = True

        with self.assertRaises(run.SkillRunError) as caught:
            run.run({"project_input": self.project_input}, defaults=defaults)

        self.assertIn("unknown field", str(caught.exception))
        self.assertIn("$.defaults.unapproved_default", str(caught.exception))

    def test_rejects_incomplete_evidence_record_even_when_its_key_contains_overrides(self) -> None:
        project_input = json.loads(json.dumps(self.project_input))
        project_input["metadata"]["evidence"] = {"arbitrary.overrides.key": {}}

        with self.assertRaises(run.SkillRunError) as caught:
            run.run({"project_input": project_input}, defaults=self.defaults)

        self.assertIn("source_class", str(caught.exception))

    def test_internal_calculator_rejects_direct_cli_execution(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "calculate.py"), "--input", "ignored.json"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(2, completed.returncode)
        self.assertIn("internal module", completed.stderr)
        self.assertIn("run.py", completed.stderr)

    def test_cli_returns_a_controlled_error_for_an_unreadable_input(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            missing_input = Path(temporary_directory) / "missing.json"
            stderr = io.StringIO()
            with patch.object(sys, "argv", ["run.py", "--input", str(missing_input)]):
                with patch("sys.stderr", stderr):
                    self.assertEqual(2, run.main())
            self.assertIn("missing.json", stderr.getvalue())

    def test_cli_renders_a_self_contained_html_competitor_report(self) -> None:
        request = {
            "project_input": self.project_input,
            "competitor_analysis": competitor_input(),
            "competitor_report": competitor_report_input(),
        }
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            request_path = temporary_path / "request.json"
            defaults_path = temporary_path / "defaults.json"
            request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            defaults_path.write_text(json.dumps(self.defaults, ensure_ascii=False), encoding="utf-8")
            stdout = io.StringIO()
            with patch.object(
                sys,
                "argv",
                [
                    "run.py",
                    "--input",
                    str(request_path),
                    "--defaults",
                    str(defaults_path),
                    "--format",
                    "html",
                ],
            ):
                with patch("sys.stdout", stdout):
                    self.assertEqual(0, run.main())

        rendered = stdout.getvalue()
        self.assertTrue(rendered.startswith("<!doctype html>"))
        self.assertIn('<meta name="viewport"', rendered)
        self.assertIn('Content-Security-Policy', rendered)
        self.assertIn("<style>", rendered)
        self.assertNotIn("<link", rendered.lower())
        self.assertIn("2km正式竞品集合已完成", rendered)
        self.assertIn("竞品装修与房型调研报告 &lt;script&gt;", rendered)
        self.assertNotIn("<script>alert", rendered)
        self.assertIn('src="data:image/png;base64,', rendered)
        self.assertNotIn('src="http', rendered)
        self.assertIn("公开房图显示暖色木饰面", rendered)
        self.assertIn("携程页面价格观察", rendered)
        self.assertIn("仅供展示：tax_scope_unknown", rendered)
        self.assertIn("2026-08-26", rendered)
        self.assertIn("<h2>3. 视觉竞品对标</h2>", rendered)
        self.assertIn('<article class="visual-card">', rendered)
        self.assertIn("仅用于人工调价研判", rendered)
        self.assertEqual(1, rendered.count('src="data:image/png;base64,'))
        self.assertIn('<th scope="col">建议 ADR</th>', rendered)
        self.assertIn("<td>260</td>", rendered)
        self.assertNotIn("<script", rendered.lower())
        self.assertIn("table { min-width:0; table-layout:fixed; }", rendered)
        self.assertIn("p,li,th,td,h1,h2,h3,h4 { overflow-wrap:anywhere; }", rendered)

    def test_html_visual_benchmark_exposes_an_evidence_gap_without_media(self) -> None:
        request = {
            "project_input": self.project_input,
            "competitor_analysis": competitor_input(),
        }
        result = run.run(request, defaults=self.defaults)

        rendered = run.competitor_report.render_competitor_report(result, request)

        self.assertIn("<h2>3. 视觉竞品对标</h2>", rendered)
        self.assertIn("暂无可追溯的竞品房图或装修观察", rendered)
        self.assertIn("不自动变更 ADR 或财务输入", rendered)

    def test_rejects_an_external_image_in_a_portable_report(self) -> None:
        report_input = competitor_report_input()
        report_input["candidate_media"][0]["images"][0]["data_uri"] = (
            "https://example.com/room.jpg"
        )
        request = {
            "project_input": self.project_input,
            "competitor_analysis": competitor_input(),
            "competitor_report": report_input,
        }
        result = run.run(request, defaults=self.defaults)

        with self.assertRaises(run.competitor_report.CompetitorReportError) as caught:
            run.competitor_report.render_competitor_report(result, request)

        self.assertIn("data_uri", str(caught.exception))

    def test_cli_returns_a_controlled_error_for_invalid_html_evidence(self) -> None:
        request = {
            "project_input": self.project_input,
            "competitor_analysis": competitor_input(),
            "competitor_report": competitor_report_input(),
        }
        request["competitor_report"]["candidate_media"][0]["images"][0]["data_uri"] = (
            "https://example.com/room.jpg"
        )
        with TemporaryDirectory() as temporary_directory:
            request_path = Path(temporary_directory) / "request.json"
            request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            stderr = io.StringIO()
            with patch.object(
                sys,
                "argv",
                ["run.py", "--input", str(request_path), "--format", "html"],
            ):
                with patch("sys.stderr", stderr):
                    self.assertEqual(2, run.main())

        self.assertIn("data_uri", stderr.getvalue())

    def test_rejects_report_media_not_bound_to_a_submitted_candidate(self) -> None:
        report_input = competitor_report_input()
        report_input["candidate_media"][0]["provider_place_id"] = "unrelated-place"
        request = {
            "project_input": self.project_input,
            "competitor_analysis": competitor_input(),
            "competitor_report": report_input,
        }
        result = run.run(request, defaults=self.defaults)

        with self.assertRaises(run.competitor_report.CompetitorReportError) as caught:
            run.competitor_report.render_competitor_report(result, request)

        self.assertIn("absent from the formal competitor set", str(caught.exception))

    def test_rejects_report_media_bound_to_an_excluded_candidate(self) -> None:
        competitors = competitor_input()
        competitors["candidates"][0]["esports_positioning"] = "incidental"
        request = {
            "project_input": self.project_input,
            "competitor_analysis": competitors,
            "competitor_report": competitor_report_input(),
        }
        result = run.run(request, defaults=self.defaults)

        with self.assertRaises(run.competitor_report.CompetitorReportError) as caught:
            run.competitor_report.render_competitor_report(result, request)

        self.assertIn("absent from the formal competitor set", str(caught.exception))

    def test_html_default_title_comes_from_the_financial_result(self) -> None:
        request = {
            "project_input": self.project_input,
            "competitor_analysis": competitor_input(),
        }
        result = run.run(request, defaults=self.defaults)

        rendered = run.competitor_report.render_competitor_report(result, request)

        self.assertIn(
            f"{result['financial_result']['project_name']}｜2km竞品调研报告",
            rendered,
        )

    def test_html_report_surfaces_month_level_payback_from_the_core_result(self) -> None:
        request = {
            "project_input": self.project_input,
            "competitor_analysis": competitor_input(),
        }
        result = run.run(request, defaults=self.defaults)
        jwl = result["financial_result"]["base_case"]["jwl"]

        rendered = run.competitor_report.render_competitor_report(result, request)

        self.assertIn("投资回报与回本周期", rendered)
        self.assertIn("静态回本", rendered)
        self.assertIn("动态回本（折现）", rendered)
        self.assertIn(
            f"{jwl['static_payback_months_rounded_up']} 个月（测算值 {jwl['static_payback_months']:.1f}）",
            rendered,
        )

    def test_report_evidence_does_not_change_the_core_underwriting_result(self) -> None:
        core_request = {
            "project_input": self.project_input,
            "competitor_analysis": competitor_input(),
        }
        report_request = {
            **core_request,
            "competitor_report": competitor_report_input(),
        }

        core_result = run.run(core_request, defaults=self.defaults)
        report_result = run.run(report_request, defaults=self.defaults)

        self.assertEqual(core_result["competitor_analysis"], report_result["competitor_analysis"])
        self.assertEqual(core_result["financial_result"], report_result["financial_result"])
        self.assertEqual(core_result["workflow"], report_result["workflow"])
        self.assertEqual(core_result["feishu_summary"], report_result["feishu_summary"])

    def test_html_report_keeps_an_incomplete_competitor_result_pre_evaluation_only(self) -> None:
        request = {"project_input": self.project_input}
        result = run.run(request, defaults=self.defaults)

        rendered = run.competitor_report.render_competitor_report(result, request)

        self.assertIn("预评估：正式竞品结论未完成", rendered)
        self.assertIn("不构成完整的 2km 竞品或 ADR 结论", rendered)


if __name__ == "__main__":
    unittest.main()
