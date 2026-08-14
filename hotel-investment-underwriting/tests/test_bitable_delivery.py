"""Tests for the Feishu Bitable delivery manifest.

The manifest is deliberately a transport contract: it must expose the current
underwriting result without introducing formulas or a second financial model.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import bitable_delivery  # noqa: E402
import market_evidence_contract  # noqa: E402
import run  # noqa: E402


ATTESTATION_KEY = "market-evidence-test-key-with-at-least-32-bytes"


def complete_competitor_input() -> dict:
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
                        "source_url": "https://hotels.ctrip.com/hotels/detail/?hotelId=1",
                        "observed_at": "2026-08-12T09:10:00+08:00",
                    }
                ],
                "pricing_observations": [
                    {
                        "room_type": "双人电竞房",
                        "room_type_provider_id": f"P-{index}:room-2",
                        "price_type": "P2",
                        "display_price": price,
                        "currency": "CNY",
                        "availability": "available",
                        "tax_included": True,
                        "cancellation_policy": "免费取消",
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
                        "adr_eligible": True,
                        "qualification_gaps": [],
                    }
                ],
                "benchmark_selected": True,
                "room_type_evidence": [
                    {
                        "room_type": "双人电竞房",
                        "room_type_provider_id": f"P-{index}:room-type-1",
                        "source_url": "https://hotels.ctrip.com/hotels/detail/?hotelId=1",
                        "observed_at": "2026-08-12T09:10:00+08:00",
                    }
                ],
                "market_profile": {
                    "meituan_badge": "金冠",
                    "opening_or_renovation": "2025年装修",
                    "room_count": 22,
                    "image_quality": "有修图，有视频",
                    "facilities": "RTX 5070、165Hz显示器、免费洗衣",
                    "features": "双人开黑房",
                    "rating": 4.8,
                    "review_count": 120,
                    "surroundings": "近商圈与地铁站",
                },
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
    image = {
        "caption": "双人电竞房公开图",
        "data_uri": (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
            "AAAADUlEQVQIHWP4z8DwHwAFgAI/ScL9XQAAAABJRU5ErkJggg=="
        ),
        "source_url": "https://www.example.com/image",
    }
    return {
        "candidate_media": [
            {
                "provider_place_id": f"P-{index}",
                "renovation_observation": "公开房图显示暖色木饰面与双机位桌面。",
                "observation_source_url": "https://www.example.com/observation",
                "images": [image],
            }
            for index in range(1, 4)
        ]
    }


def page_receipt(competitors: dict, report: dict) -> dict:
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    candidates = competitors["candidates"]
    center = competitors["confirmed_location"]
    candidate_ids_sha256 = hashlib.sha256(
        json.dumps(
            sorted(candidate["provider_place_id"] for candidate in candidates),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "contract_version": "market-evidence-collection/v2",
        "status": "complete",
        "collector": {
            "engine": "ctrip-live-rates",
            "engine_version": "test",
            "source_profile": "ctrip-live-rates-v1",
            "started_at": timestamp,
            "finished_at": timestamp,
            "page_sources": [{"url": "https://hotels.ctrip.com/hotels/detail/?hotelId=1", "status": 200}],
        },
        "target_resolution": center,
        "coverage": {
            "candidates": {"status": "complete", "observed_count": len(candidates)},
            "benchmark_set": {"status": "complete", "observed_count": len(candidates)},
            "room_types": {"status": "complete", "observed_count": len(candidates)},
            "images": {"status": "complete", "observed_count": len(candidates)},
            "pricing": {"status": "complete", "observed_count": len(candidates)},
        },
        "collection_gaps": [],
        "competitor_analysis": competitors,
        "competitor_report": report,
        "spatial_collection": {
            "status": "complete",
            "source_engine": "playwright",
            "source_profile": "360-map-v1",
            "center": center,
            "candidate_count": len(candidates),
            "candidate_ids_sha256": candidate_ids_sha256,
            "candidate_snapshot_sha256": market_evidence_contract._candidate_snapshot_sha256(candidates),
        },
    }
class BitableDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._attestation_environment = patch.dict(
            os.environ,
            {"MARKET_EVIDENCE_RECEIPT_HMAC_KEY": ATTESTATION_KEY},
        )
        self._attestation_environment.start()
        self.addCleanup(self._attestation_environment.stop)
        self.project_input = json.loads(
            (ROOT / "references" / "sample-predeal-hotel.json").read_text(
                encoding="utf-8"
            )
        )
        self.defaults = json.loads(
            (ROOT / "references" / "benchmark-defaults.json").read_text(
                encoding="utf-8"
            )
        )

    def _request(self) -> dict:
        competitors = complete_competitor_input()
        report = competitor_report_input()
        receipt = market_evidence_contract.attest_collection_result(
            page_receipt(competitors, report)
        )
        return {
            "project_input": copy.deepcopy(self.project_input),
            "market_evidence": receipt,
            "competitor_analysis": competitors,
            "competitor_report": report,
        }

    def _refresh_attestation(self, request: dict) -> None:
        """Re-bind deliberate fixture edits to the host-issued test receipt."""

        receipt = request["market_evidence"]
        receipt.pop("attestation", None)
        receipt["competitor_analysis"] = request["competitor_analysis"]
        receipt["competitor_report"] = request["competitor_report"]
        request["market_evidence"] = market_evidence_contract.attest_collection_result(receipt)

    def test_manifest_contains_the_standard_template_and_all_delivery_tables(self) -> None:
        request = self._request()
        result = run.run(request, defaults=self.defaults)

        manifest = bitable_delivery.build_manifest(result, request, self.defaults)

        self.assertEqual("1.3", manifest["manifest_version"])
        self.assertEqual("skill_is_calculation_owner", manifest["write_policy"]["calculation_owner"])
        self.assertTrue(manifest["delivery_gate"]["payload_write_eligible"])
        self.assertEqual(
            "待写入核验",
            manifest["records"]["项目测算总表"][0]["交付载荷状态"],
        )
        self.assertEqual("complete", manifest["delivery_gate"]["market_evidence_status"])
        self.assertEqual("available", manifest["delivery_gate"]["adr_evidence_status"])
        self.assertEqual("ready_for_review", manifest["delivery_gate"]["investment_decision_scope"])
        self.assertEqual(3, manifest["delivery_gate"]["expected_visual_attachment_count"])
        self.assertEqual(
            {
                "项目测算总表",
                "输入参数与来源",
                "投资与成本明细",
                "年度收入与现金流",
                "情景与敏感性",
                "房型配置",
                "2km竞品",
                "竞品报价与视觉证据",
            },
            {table["name"] for table in manifest["template"]["tables"]},
        )
        self.assertEqual(
            set(manifest["records"]),
            {table["name"] for table in manifest["template"]["tables"]},
        )
        self.assertTrue(manifest["links"])

        for table in manifest["template"]["tables"]:
            self.assertNotIn("formula", {field["type"] for field in table["fields"]})
            self.assertNotIn("lookup", {field["type"] for field in table["fields"]})
        evidence_table = next(
            table
            for table in manifest["template"]["tables"]
            if table["name"] == "竞品报价与视觉证据"
        )
        attachment_status = next(
            field for field in evidence_table["fields"] if field["name"] == "附件状态"
        )
        self.assertEqual(
            ["无附件", "待上传", "已上传"],
            [option["name"] for option in attachment_status["options"]],
        )

    def test_manifest_preserves_core_finance_without_recalculation(self) -> None:
        request = self._request()
        result = run.run(request, defaults=self.defaults)
        financial_before = copy.deepcopy(result["financial_result"])

        manifest = bitable_delivery.build_manifest(result, request, self.defaults)
        summary = manifest["records"]["项目测算总表"][0]
        base = result["financial_result"]["base_case"]

        self.assertEqual(result["financial_result"], financial_before)
        self.assertEqual(result["input_sha256"], summary["输入SHA256"])
        self.assertEqual(
            base["jwl"]["static_payback_months_rounded_up"],
            summary["智竞静态回本（月，向上取整）"],
        )
        self.assertEqual(
            base["jwl"]["discounted_payback_months_rounded_up"],
            summary["智竞动态回本（月，向上取整）"],
        )
        self.assertEqual(base["jwl"]["npv"], summary["智竞NPV（元）"])
        self.assertEqual(base["owner_fully_loaded"]["npv"], summary["业主完全成本NPV（元）"])
        self.assertEqual(result["workflow"]["status"], summary["结论范围"])

    def test_manifest_maps_current_and_historical_competitor_fields_and_media(self) -> None:
        request = self._request()
        request["competitor_analysis"]["candidates"][0]["room_type_evidence"] = [
            {
                "room_type": "双人电竞大床房",
                "room_type_provider_id": "P-1:ego-dom:room-type:1",
                "source_url": "https://hotels.ctrip.com/hotels/detail/?hotelId=1",
                "observed_at": "2026-08-14T10:00:00+08:00",
            }
        ]
        request["competitor_analysis"]["candidates"][0]["benchmark_selected"] = True
        request["competitor_analysis"]["candidates"][0]["benchmark_rank"] = 1
        request["competitor_analysis"]["candidates"][0]["benchmark_selection_reason"] = (
            "固定标杆排序：有公开房型图；距目标111米"
        )
        self._refresh_attestation(request)
        result = run.run(request, defaults=self.defaults)

        manifest = bitable_delivery.build_manifest(result, request, self.defaults)
        competitor = manifest["records"]["2km竞品"][0]
        evidence = manifest["records"]["竞品报价与视觉证据"]

        self.assertEqual("金冠", competitor["美团等级/冠"])
        self.assertEqual(22, competitor["房间数"])
        self.assertEqual(4.8, competitor["平台评分"])
        self.assertEqual(1, competitor["标杆排序"])
        self.assertIn("固定标杆排序", competitor["标杆筛选依据"])
        self.assertEqual(3, len(manifest["attachments"]))
        self.assertEqual("竞品报价与视觉证据", manifest["attachments"][0]["table"])
        self.assertIn("data:image/png;base64,", manifest["attachments"][0]["data_uri"])
        self.assertEqual("P-1-room-1.png", manifest["attachments"][0]["filename"])
        self.assertEqual("已上传", manifest["attachments"][0]["status_after_upload"])
        self.assertIn("报价", {row["证据类型"] for row in evidence})
        self.assertIn("房型观察", {row["证据类型"] for row in evidence})
        self.assertIn("价格观察", {row["证据类型"] for row in evidence})
        self.assertIn("视觉", {row["证据类型"] for row in evidence})
        room_type = next(row for row in evidence if row["证据类型"] == "房型观察")
        self.assertEqual("双人电竞大床房", room_type["房型"])
        self.assertTrue(room_type["DOM已验证"])
        observation = next(row for row in evidence if row["证据类型"] == "价格观察")
        self.assertTrue(observation["可进入ADR"])
        self.assertEqual("", observation["ADR排除原因"])

    def test_attachment_file_extension_and_name_are_safe_for_the_validated_image_types(self) -> None:
        self.assertEqual("jpg", bitable_delivery._image_extension("data:image/jpeg;base64,AA=="))
        self.assertEqual("png", bitable_delivery._image_extension("data:image/png;base64,AA=="))
        self.assertEqual("webp", bitable_delivery._image_extension("data:image/webp;base64,AA=="))
        self.assertEqual(
            "P_1-room-2.jpg",
            bitable_delivery._attachment_filename("P/1", 2, "data:image/jpeg;base64,AA=="),
        )

    def test_manifest_exposes_all_merged_input_paths_and_the_annual_schedule(self) -> None:
        request = self._request()
        result = run.run(request, defaults=self.defaults)

        manifest = bitable_delivery.build_manifest(result, request, self.defaults)
        input_paths = {
            row["模型路径"] for row in manifest["records"]["输入参数与来源"]
        }
        annual = manifest["records"]["年度收入与现金流"]

        self.assertIn("project.rooms", input_paths)
        self.assertIn("jwl.capex.cloud_box_per_seat", input_paths)
        self.assertIn("finance.discount_rate", input_paths)
        self.assertIn("revenue.first_year_monthly_occ_schedule[0]", input_paths)
        self.assertEqual(
            len(result["financial_result"]["base_case"]["annual"]),
            len(annual),
        )
        self.assertEqual(1, annual[0]["预测年度"])

    def test_pre_evaluation_status_remains_visible_when_no_competitor_evidence_exists(self) -> None:
        request = {"project_input": copy.deepcopy(self.project_input)}
        result = run.run(request, defaults=self.defaults)

        manifest = bitable_delivery.build_manifest(result, request, self.defaults)
        summary = manifest["records"]["项目测算总表"][0]

        self.assertEqual("pre_evaluation_only", summary["结论范围"])
        self.assertEqual("needs_location_confirmation", summary["2km竞品状态"])
        self.assertEqual("待补证据", summary["交付载荷状态"])
        self.assertIn("2km竞品", summary["交付待补项"])
        self.assertEqual("已提供", manifest["records"]["房型配置"][0]["交付状态"])
        self.assertEqual("待补2km竞品", manifest["records"]["2km竞品"][0]["交付状态"])
        self.assertEqual("待补视觉图片", manifest["records"]["竞品报价与视觉证据"][0]["交付状态"])
        self.assertFalse(manifest["delivery_gate"]["payload_write_eligible"])
        self.assertEqual("not_collected", manifest["delivery_gate"]["market_evidence_status"])
        self.assertEqual("not_collected", manifest["delivery_gate"]["adr_evidence_status"])
        self.assertEqual("pre_evaluation_only", manifest["delivery_gate"]["investment_decision_scope"])

    def test_delivery_manifest_writes_a_visible_room_type_gap_when_room_mix_is_missing(self) -> None:
        request = self._request()
        del request["project_input"]["revenue"]["room_types"]
        result = run.run(request, defaults=self.defaults)

        manifest = bitable_delivery.build_manifest(result, request, self.defaults)

        room_gap = manifest["records"]["房型配置"]
        self.assertEqual(1, len(room_gap))
        self.assertEqual("待补房型", room_gap[0]["交付状态"])
        self.assertIn("非房型数据", room_gap[0]["房型名称"])
        self.assertIn("房型配置", manifest["delivery_gate"]["blocking_items"])

    def test_delivery_gate_marks_each_formal_competitor_without_an_image_as_pending(self) -> None:
        request = self._request()
        # The public entrypoint only accepts report facts bound to the same
        # page receipt; mutate that receipt rather than sending a detached
        # report payload.
        request["market_evidence"]["competitor_report"]["candidate_media"] = []
        request["competitor_report"] = request["market_evidence"]["competitor_report"]
        request["market_evidence"]["status"] = "partial"
        request["market_evidence"]["coverage"]["images"] = {
            "status": "partial",
            "observed_count": 0,
        }
        request["market_evidence"]["collection_gaps"] = ["竞品图片待补齐"]
        self._refresh_attestation(request)
        result = run.run(request, defaults=self.defaults)

        manifest = bitable_delivery.build_manifest(result, request, self.defaults)

        pending = [
            row
            for row in manifest["records"]["竞品报价与视觉证据"]
            if row["交付状态"] == "待补视觉图片"
        ]
        self.assertEqual(3, len(pending))
        self.assertTrue(all(row["附件状态"] == "无附件" for row in pending))
        self.assertEqual("待补证据", manifest["delivery_gate"]["status"])
        self.assertFalse(manifest["delivery_gate"]["payload_write_eligible"])

    def test_delivery_gate_requires_images_only_for_explicit_deep_research_benchmarks(self) -> None:
        request = self._request()
        for index, candidate in enumerate(request["competitor_analysis"]["candidates"], start=1):
            candidate["benchmark_selected"] = index == 1
        request["competitor_report"]["candidate_media"] = [
            request["competitor_report"]["candidate_media"][0]
        ]
        request["market_evidence"]["coverage"]["benchmark_set"]["observed_count"] = 1
        request["market_evidence"]["coverage"]["room_types"]["observed_count"] = 1
        request["market_evidence"]["coverage"]["images"]["observed_count"] = 1
        request["market_evidence"]["coverage"]["pricing"]["observed_count"] = 1
        self._refresh_attestation(request)
        result = run.run(request, defaults=self.defaults)

        manifest = bitable_delivery.build_manifest(result, request, self.defaults)
        pending = [
            row
            for row in manifest["records"]["竞品报价与视觉证据"]
            if row["交付状态"] == "待补视觉图片"
        ]

        self.assertEqual([], pending)
        self.assertTrue(manifest["delivery_gate"]["payload_write_eligible"])

    def test_payload_write_verification_never_promotes_partial_adr_evidence_to_decision_evidence(self) -> None:
        request = self._request()
        request["market_evidence"]["status"] = "partial"
        request["market_evidence"]["coverage"]["pricing"] = {
            "status": "partial",
            "observed_count": 0,
        }
        request["market_evidence"]["collection_gaps"] = ["P2 同条件价格仍待补齐"]
        for candidate in request["competitor_analysis"]["candidates"]:
            candidate["room_offers"] = []
            candidate["pricing_observations"] = []
        self._refresh_attestation(request)
        result = run.run(request, defaults=self.defaults)

        manifest = bitable_delivery.build_manifest(result, request, self.defaults)

        self.assertTrue(manifest["delivery_gate"]["payload_write_eligible"])
        self.assertEqual("partial", manifest["delivery_gate"]["market_evidence_status"])
        self.assertEqual("partial", manifest["delivery_gate"]["adr_evidence_status"])
        self.assertEqual(
            "ready_for_review",
            manifest["delivery_gate"]["investment_decision_scope"],
        )
        self.assertEqual(
            "待写入核验",
            manifest["records"]["项目测算总表"][0]["交付载荷状态"],
        )

    def test_partial_competitor_collection_writes_a_visible_collection_gap(self) -> None:
        request = self._request()
        request["competitor_analysis"]["collection_status"] = "partial"
        request["market_evidence"]["status"] = "partial"
        request["market_evidence"]["spatial_collection"]["status"] = "partial"
        self._refresh_attestation(request)
        result = run.run(request, defaults=self.defaults)

        manifest = bitable_delivery.build_manifest(result, request, self.defaults)

        gaps = [
            row
            for row in manifest["records"]["2km竞品"]
            if row["交付状态"] == "待补2km竞品"
        ]
        self.assertEqual(1, len(gaps))
        self.assertEqual("待补证据", manifest["delivery_gate"]["status"])
        self.assertIn("2km竞品", manifest["delivery_gate"]["blocking_items"])

    def test_bitable_rejects_malformed_delivery_only_market_profile(self) -> None:
        request = self._request()
        request["competitor_analysis"]["candidates"][0]["market_profile"]["rating"] = 5.1
        self._refresh_attestation(request)
        result = run.run(request, defaults=self.defaults)

        with self.assertRaisesRegex(
            bitable_delivery.BitableDeliveryError,
            r"market_profile\.rating is invalid",
        ):
            bitable_delivery.build_manifest(result, request, self.defaults)

    def test_public_cli_emits_a_bitable_manifest(self) -> None:
        request = self._request()
        with TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            request_path = temporary_path / "request.json"
            defaults_path = temporary_path / "defaults.json"
            request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            defaults_path.write_text(
                json.dumps(self.defaults, ensure_ascii=False), encoding="utf-8"
            )
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
                    "bitable",
                ],
            ):
                with patch("sys.stdout", stdout):
                    self.assertEqual(0, run.main())

        manifest = json.loads(stdout.getvalue())
        self.assertEqual("feishu_bitable", manifest["delivery_type"])
        self.assertEqual("智竞酒店投资分析交付", manifest["template"]["base_name"])


if __name__ == "__main__":
    unittest.main()
