"""Tests for the platform-neutral browser evidence boundary."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import collect_market_evidence  # noqa: E402
import market_evidence_contract  # noqa: E402
import run  # noqa: E402


def request() -> dict:
    return {
        "contract_version": "market-evidence-collection/v2",
        "request_id": "test-001",
        "target": {
            "name": "笨酒店",
            "address": "成都市成华区望平街滨河路6号",
            "city_id": "510100",
            "center": {
                "provider": "360地图",
                "provider_place_id": "target-place",
                "coordinate_system": "GCJ-02",
                "longitude": 104.089545,
                "latitude": 30.654181,
                "status": "confirmed",
            },
        },
        "search": {
            "provider_profile": "360-map-v1",
            "query": "电竞酒店",
            "radius_meters": 2000,
        },
        "pricing_context": {
            "check_in_date": "2026-08-20",
            "nights": 1,
            "guests": 2,
            "currency": "CNY",
        },
        "required_evidence": {"room_types": True, "images": True, "pricing": True},
    }


def selected_inventory() -> list[dict]:
    return [
        {
            "candidate": {
                "provider": "360地图",
                "provider_place_id": "candidate-001",
                "name": "测试电竞酒店",
                "coordinate_system": "GCJ-02",
                "longitude": 104.09,
                "latitude": 30.65,
                "property_kind": "lodging",
                "esports_positioning": "primary",
                "operating_status": "operating",
                "source": {
                    "source_platform": "360地图页面",
                    "source_url": "https://m.map.360.cn/m/search/detail/pid=candidate-001",
                    "observed_at": "2026-08-13T09:00:00+08:00",
                    "confidence": "medium",
                },
            },
            "benchmark_selected": True,
            "ota_property": {
                "platform": "携程",
                "property_id": "100962994",
                "property_url": "https://m.ctrip.com/html5/hotel/hoteldetail/100962994.html",
                "match_method": "page_exact_manual",
                "matched_at": "2026-08-13T09:00:00+08:00",
            },
        }
    ]


def spatial_pool(inventory: list[dict], center: dict, *, status: str = "complete") -> dict:
    identifiers = sorted(item["candidate"]["provider_place_id"] for item in inventory)
    return {
        "status": status,
        "source_engine": "playwright",
        "source_profile": "360-map-v1",
        "center": center,
        "candidate_count": len(inventory),
        "candidate_ids_sha256": hashlib.sha256(
            json.dumps(identifiers, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def result(*, status: str = "partial") -> dict:
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    inventory = []
    for index in range(3):
        entry = copy.deepcopy(selected_inventory()[0])
        entry["candidate"]["provider_place_id"] = f"candidate-{index:03d}"
        inventory.append(entry)
    candidates = [entry["candidate"] for entry in inventory]
    return {
        "contract_version": "market-evidence-collection/v2",
        "request_id": "test-001",
        "status": status,
        "collector": {
            "engine": "playwright",
            "engine_version": "151.0",
            "source_profile": "360-map-v1",
            "started_at": timestamp,
            "finished_at": timestamp,
            "page_sources": [
                {"url": "https://restapi.map.360.cn/api/simple?keyword=test", "status": 200}
            ],
        },
        "target_resolution": request()["target"]["center"],
        "coverage": {
            "candidates": {"status": "complete", "observed_count": 3},
            "benchmark_set": {"status": "complete", "observed_count": 2},
            "room_types": {"status": "complete", "observed_count": 4},
            "images": {"status": "partial", "observed_count": 2},
            "pricing": {"status": "not_collected", "observed_count": 0},
        },
        "collection_gaps": ["当前页面来源未完成同条件房态与报价采集；不得生成竞品 ADR 建议"],
        "competitor_analysis": {
            "confirmed_location": request()["target"]["center"],
            "collection_status": "partial",
            "pricing_context": request()["pricing_context"],
            "candidates": candidates,
        },
        "competitor_report": {"title": "测试页面调研", "candidate_media": []},
    }


class MarketEvidenceContractTests(unittest.TestCase):
    def test_v1_receipts_fail_closed_after_the_v2_contract_migration(self) -> None:
        legacy_request = request()
        legacy_request["contract_version"] = "market-evidence-collection/v1"
        with self.assertRaisesRegex(market_evidence_contract.MarketEvidenceContractError, "v2"):
            market_evidence_contract.validate_collection_request(legacy_request)

        legacy_result = result()
        legacy_result["contract_version"] = "market-evidence-collection/v1"
        with self.assertRaisesRegex(market_evidence_contract.MarketEvidenceContractError, "v2"):
            market_evidence_contract.validate_collection_result(legacy_result)

    def test_request_defaults_and_2km_boundary_are_normalized(self) -> None:
        normalized = market_evidence_contract.validate_collection_request(request())

        self.assertEqual(2_000, normalized["search"]["radius_meters"])
        self.assertEqual(1_000, normalized["search"]["max_candidates"])
        self.assertEqual("CNY", normalized["pricing_context"]["currency"])
        self.assertEqual([], normalized["candidate_inventory"])

        too_many = request()
        too_many["search"]["max_candidates"] = 1_001
        with self.assertRaisesRegex(market_evidence_contract.MarketEvidenceContractError, "1 and 1000"):
            market_evidence_contract.validate_collection_request(too_many)

    def test_selected_price_visual_benchmark_requires_explicit_ota_identity_bridge(self) -> None:
        value = request()
        value["search"]["provider_profile"] = "ctrip-hotel-v1"
        value["candidate_inventory"] = selected_inventory()
        value["candidate_pool"] = spatial_pool(
            value["candidate_inventory"], value["target"]["center"]
        )

        normalized = market_evidence_contract.validate_collection_request(value)

        self.assertEqual("100962994", normalized["candidate_inventory"][0]["ota_property"]["property_id"])
        del value["candidate_inventory"][0]["ota_property"]
        with self.assertRaisesRegex(market_evidence_contract.MarketEvidenceContractError, "ota_property"):
            market_evidence_contract.validate_collection_request(value)

    def test_2km_benchmark_set_is_hard_capped_at_eight(self) -> None:
        invalid = request()
        invalid["search"]["max_benchmark_candidates"] = 9
        with self.assertRaisesRegex(market_evidence_contract.MarketEvidenceContractError, "between 0 and 8"):
            market_evidence_contract.validate_collection_request(invalid)

        invalid = request()
        invalid["search"]["provider_profile"] = "ctrip-hotel-v1"
        inventory = []
        for index in range(9):
            entry = copy.deepcopy(selected_inventory()[0])
            entry["candidate"]["provider_place_id"] = f"candidate-{index:03d}"
            entry["ota_property"]["property_id"] = f"property-{index:03d}"
            inventory.append(entry)
        invalid["candidate_inventory"] = inventory
        invalid["candidate_pool"] = spatial_pool(inventory, invalid["target"]["center"])
        with self.assertRaisesRegex(market_evidence_contract.MarketEvidenceContractError, "at most 8"):
            market_evidence_contract.validate_collection_request(invalid)

    def test_collection_patch_contains_only_public_skill_input_fields(self) -> None:
        patch = market_evidence_contract.skill_request_patch(result())

        self.assertEqual(
            {"market_evidence", "competitor_analysis", "competitor_report"}, set(patch)
        )
        self.assertEqual("partial", patch["competitor_analysis"]["collection_status"])

    def test_partial_ota_receipt_may_preserve_completed_spatial_collection(self) -> None:
        value = result()
        value["competitor_analysis"]["collection_status"] = "complete"
        value["spatial_collection"] = spatial_pool(
            [{"candidate": candidate} for candidate in value["competitor_analysis"]["candidates"]],
            value["competitor_analysis"]["confirmed_location"],
        )

        normalized = market_evidence_contract.validate_collection_result(value)

        self.assertEqual("partial", normalized["status"])
        self.assertEqual("complete", normalized["competitor_analysis"]["collection_status"])

    def test_partial_receipt_cannot_claim_a_complete_spatial_pool_without_one(self) -> None:
        value = result()
        value["competitor_analysis"]["collection_status"] = "complete"
        value["competitor_analysis"]["candidates"] = []

        with self.assertRaisesRegex(market_evidence_contract.MarketEvidenceContractError, "spatial"):
            market_evidence_contract.validate_collection_result(value)

    def test_complete_spatial_receipt_requires_a_confirmed_target_and_unique_provider_ids(self) -> None:
        missing_center = result()
        missing_center["competitor_analysis"]["collection_status"] = "complete"
        missing_center["target_resolution"] = None
        missing_center["competitor_analysis"]["confirmed_location"] = None
        missing_center["spatial_collection"] = spatial_pool(
            [{"candidate": candidate} for candidate in missing_center["competitor_analysis"]["candidates"]],
            request()["target"]["center"],
        )
        with self.assertRaisesRegex(market_evidence_contract.MarketEvidenceContractError, "target_resolution"):
            market_evidence_contract.validate_collection_result(missing_center)

        duplicate_ids = result()
        duplicate_ids["competitor_analysis"]["collection_status"] = "complete"
        duplicate_ids["competitor_analysis"]["candidates"][1]["provider_place_id"] = (
            duplicate_ids["competitor_analysis"]["candidates"][0]["provider_place_id"]
        )
        duplicate_ids["spatial_collection"] = spatial_pool(
            [{"candidate": candidate} for candidate in duplicate_ids["competitor_analysis"]["candidates"]],
            duplicate_ids["competitor_analysis"]["confirmed_location"],
        )
        with self.assertRaisesRegex(market_evidence_contract.MarketEvidenceContractError, "unique"):
            market_evidence_contract.validate_collection_result(duplicate_ids)

    def test_complete_result_rejects_uncollected_price_or_partial_images(self) -> None:
        invalid = result(status="complete")
        invalid["competitor_analysis"]["collection_status"] = "complete"

        with self.assertRaisesRegex(
            market_evidence_contract.MarketEvidenceContractError,
            "complete coverage",
        ):
            market_evidence_contract.validate_collection_result(invalid)

    def test_unknown_engine_is_rejected_before_an_agent_can_merge_evidence(self) -> None:
        invalid = result()
        invalid["collector"]["engine"] = "codex-computer-use"

        with self.assertRaisesRegex(
            market_evidence_contract.MarketEvidenceContractError,
            "unsupported page collector engine",
        ):
            market_evidence_contract.validate_collection_result(invalid)

    def test_bundled_engine_cannot_claim_another_profile_in_a_standalone_receipt(self) -> None:
        invalid = result()
        invalid["collector"]["engine"] = "ctrip-live-rates"

        with self.assertRaisesRegex(
            market_evidence_contract.MarketEvidenceContractError,
            "ctrip-live-rates-v1",
        ):
            market_evidence_contract.validate_collection_result(invalid)

    def test_playwright_is_explicit_default_and_receipt_is_validated(self) -> None:
        captured: dict[str, object] = {}

        def fake_runner(command: list[str], payload: dict, timeout: int) -> dict:
            captured["command"] = command
            captured["payload"] = payload
            captured["timeout"] = timeout
            return result()

        with patch.object(collect_market_evidence, "_run_process", side_effect=fake_runner), patch.object(
            collect_market_evidence.market_evidence_runtime, "require_ready"
        ):
            collected = collect_market_evidence.collect(request(), engine="playwright", timeout_seconds=120)

        self.assertEqual("playwright", collected["collector"]["engine"])
        self.assertEqual("node", captured["command"][0])
        self.assertEqual(120, captured["timeout"])
        self.assertEqual("market-evidence-collection/v2", captured["payload"]["contract_version"])

    def test_collector_rejects_a_center_different_from_the_confirmed_request(self) -> None:
        payload = request()
        received = result()
        different_center = copy.deepcopy(payload["target"]["center"])
        different_center["longitude"] = 104.0
        received["target_resolution"] = different_center
        received["competitor_analysis"]["confirmed_location"] = different_center

        with patch.object(collect_market_evidence, "_run_process", return_value=received), patch.object(
            collect_market_evidence.market_evidence_runtime, "require_ready"
        ):
            with self.assertRaisesRegex(
                collect_market_evidence.CollectionExecutionError,
                "target center differs",
            ):
                collect_market_evidence.collect(payload, engine="playwright", timeout_seconds=120)

    def test_missing_optional_engine_never_silently_falls_back_to_playwright(self) -> None:
        with patch.dict("os.environ", {}, clear=True), patch.object(
            collect_market_evidence.market_evidence_runtime, "require_ready"
        ):
            with self.assertRaisesRegex(
                collect_market_evidence.CollectionExecutionError,
                "MARKET_EVIDENCE_CRAWL4AI_COMMAND",
            ):
                collect_market_evidence.collect(request(), engine="crawl4ai", timeout_seconds=120)

    def test_request_rejects_any_radius_larger_than_the_business_2km_scope(self) -> None:
        invalid = copy.deepcopy(request())
        invalid["search"]["radius_meters"] = 2_001

        with self.assertRaisesRegex(market_evidence_contract.MarketEvidenceContractError, "radius_meters"):
            market_evidence_contract.validate_collection_request(invalid)

    def test_underwriting_rejects_evidence_tampered_after_collection(self) -> None:
        project_input = json.loads(
            (ROOT / "references" / "sample-predeal-hotel.json").read_text(encoding="utf-8")
        )
        defaults = json.loads(
            (ROOT / "references" / "benchmark-defaults.json").read_text(encoding="utf-8")
        )
        receipt = result()
        tampered = {
            "project_input": project_input,
            "market_evidence": receipt,
            "competitor_analysis": {"collection_status": "complete", "candidates": []},
        }

        with self.assertRaisesRegex(run.SkillRunError, "must exactly match"):
            run.run(tampered, defaults=defaults)


if __name__ == "__main__":
    unittest.main()
