"""Tests for the Feishu Bitable delivery manifest.

The manifest is deliberately a transport contract: it must expose the current
underwriting result without introducing formulas or a second financial model.
"""

from __future__ import annotations

import copy
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import bitable_delivery  # noqa: E402
import run  # noqa: E402


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
                        "workstations": 2,
                        "nightly_price": price,
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
    return {
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
        ]
    }


class BitableDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
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
        return {
            "project_input": copy.deepcopy(self.project_input),
            "competitor_analysis": complete_competitor_input(),
            "competitor_report": competitor_report_input(),
        }

    def test_manifest_contains_the_standard_template_and_all_delivery_tables(self) -> None:
        request = self._request()
        result = run.run(request, defaults=self.defaults)

        manifest = bitable_delivery.build_manifest(result, request, self.defaults)

        self.assertEqual("1.0", manifest["manifest_version"])
        self.assertEqual("skill_is_calculation_owner", manifest["write_policy"]["calculation_owner"])
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
        result = run.run(request, defaults=self.defaults)

        manifest = bitable_delivery.build_manifest(result, request, self.defaults)
        competitor = manifest["records"]["2km竞品"][0]
        evidence = manifest["records"]["竞品报价与视觉证据"]

        self.assertEqual("金冠", competitor["美团等级/冠"])
        self.assertEqual(22, competitor["房间数"])
        self.assertEqual(4.8, competitor["平台评分"])
        self.assertEqual(1, len(manifest["attachments"]))
        self.assertEqual("竞品报价与视觉证据", manifest["attachments"][0]["table"])
        self.assertIn("data:image/png;base64,", manifest["attachments"][0]["data_uri"])
        self.assertEqual("P-1-room-1.png", manifest["attachments"][0]["filename"])
        self.assertEqual("已上传", manifest["attachments"][0]["status_after_upload"])
        self.assertIn("报价", {row["证据类型"] for row in evidence})
        self.assertIn("视觉", {row["证据类型"] for row in evidence})

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
        self.assertEqual([], manifest["records"]["2km竞品"])

    def test_bitable_rejects_malformed_delivery_only_market_profile(self) -> None:
        request = self._request()
        request["competitor_analysis"]["candidates"][0]["market_profile"]["rating"] = 5.1
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
