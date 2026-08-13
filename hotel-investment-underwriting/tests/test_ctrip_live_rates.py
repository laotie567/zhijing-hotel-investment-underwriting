"""Regression tests for the Ui.Vision + OpenCLI Ctrip live-rate boundary."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import collect_market_evidence  # noqa: E402
import market_evidence_contract  # noqa: E402


def request() -> dict:
    return {
        "contract_version": "market-evidence-collection/v1",
        "request_id": "ctrip-live-test",
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
            "provider_profile": "ctrip-live-rates-v1",
            "query": "电竞酒店",
            "radius_meters": 2000,
            "max_images_per_candidate": 1,
        },
        "pricing_context": {
            "check_in_date": "2026-08-20",
            "nights": 1,
            "guests": 2,
            "currency": "CNY",
        },
        "required_evidence": {"room_types": True, "images": True, "pricing": True},
        "candidate_inventory": [
            {
                "candidate": {
                    "provider": "360地图",
                    "provider_place_id": "candidate-001",
                    "name": "奕界电竞酒店(春熙路店)",
                    "coordinate_system": "GCJ-02",
                    "longitude": 104.077821,
                    "latitude": 30.658039,
                    "property_kind": "lodging",
                    "esports_positioning": "primary",
                    "operating_status": "operating",
                    "source": {
                        "source_platform": "360地图页面",
                        "source_url": "https://m.map.360.cn/m/search/detail/pid=candidate-001",
                        "observed_at": "2026-08-13T09:00:00+08:00",
                        "confidence": "high",
                    },
                },
                "benchmark_selected": True,
            }
        ],
    }


def result() -> dict:
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "contract_version": "market-evidence-collection/v1",
        "request_id": "ctrip-live-test",
        "status": "partial",
        "collector": {
            "engine": "ctrip-live-rates",
            "engine_version": "test",
            "source_profile": "ctrip-live-rates-v1",
            "started_at": timestamp,
            "finished_at": timestamp,
            "page_sources": [{"url": "https://hotels.ctrip.com/hotels/detail/?hotelId=133623094", "status": 200}],
        },
        "target_resolution": request()["target"]["center"],
        "coverage": {
            "candidates": {"status": "complete", "observed_count": 1},
            "benchmark_set": {"status": "complete", "observed_count": 1},
            "room_types": {"status": "complete", "observed_count": 1},
            "images": {"status": "partial", "observed_count": 0},
            "pricing": {"status": "partial", "observed_count": 0},
        },
        "collection_gaps": ["AUTH_REQUIRED：需要人工登录"],
        "collection_issues": [
            {"code": "AUTH_REQUIRED", "message": "携程页面要求登录后才能展示同条件价格。", "retryable": True, "provider_place_id": "candidate-001"}
        ],
        "competitor_analysis": {
            "confirmed_location": request()["target"]["center"],
            "collection_status": "partial",
            "pricing_context": request()["pricing_context"],
            "candidates": [],
        },
        "competitor_report": {"candidate_media": []},
    }


class CtripLiveRatesTests(unittest.TestCase):
    def test_live_rate_profile_can_request_deterministic_ota_mapping(self) -> None:
        normalized = market_evidence_contract.validate_collection_request(request())

        self.assertNotIn("ota_property", normalized["candidate_inventory"][0])

    def test_legacy_ctrip_profile_still_requires_explicit_ota_mapping(self) -> None:
        invalid = request()
        invalid["search"]["provider_profile"] = "ctrip-hotel-v1"

        with self.assertRaisesRegex(market_evidence_contract.MarketEvidenceContractError, "ota_property"):
            market_evidence_contract.validate_collection_request(invalid)

    def test_live_rate_receipt_has_structured_human_action_issue(self) -> None:
        normalized = market_evidence_contract.validate_collection_result(result())

        self.assertEqual("AUTH_REQUIRED", normalized["collection_issues"][0]["code"])
        self.assertTrue(normalized["collection_issues"][0]["retryable"])

    def test_unknown_collection_issue_code_is_rejected(self) -> None:
        invalid = result()
        invalid["collection_issues"][0]["code"] = "COOKIE_EXFILTRATED"

        with self.assertRaisesRegex(market_evidence_contract.MarketEvidenceContractError, "issue"):
            market_evidence_contract.validate_collection_result(invalid)

    def test_live_rate_engine_uses_only_the_bundled_adapter(self) -> None:
        captured: dict[str, object] = {}

        def fake_runner(command: list[str], payload: dict, timeout: int) -> dict:
            captured["command"] = command
            captured["payload"] = payload
            captured["timeout"] = timeout
            return result()

        with patch.object(collect_market_evidence, "_run_process", side_effect=fake_runner), patch.object(
            collect_market_evidence.market_evidence_runtime, "require_ready"
        ):
            collected = collect_market_evidence.collect(request(), engine="ctrip-live-rates", timeout_seconds=120)

        self.assertEqual("ctrip-live-rates", collected["collector"]["engine"])
        self.assertEqual("node", captured["command"][0])
        self.assertTrue(str(captured["command"][1]).endswith("ctrip_live_rates.mjs"))
        self.assertEqual(120, captured["timeout"])

    def test_network_and_dom_must_match_before_an_offer_is_adr_eligible(self) -> None:
        script = """
import { networkRates, domRates, matchRates, observation, verifyContext } from './collector/ctrip_live_rates.mjs';
const network = networkRates({data:{rooms:[{roomId:'room-2',roomName:'双人电竞房 2台电脑',ratePlanName:'双早',salePrice:328,available:true,cancelPolicy:'免费取消',taxInfo:'含税'}]}}, '/room-list');
const dom = domRates({room_blocks:[{room_id:'room-2',text:'双人电竞房 2台电脑\\n¥328\\n可订\\n含税\\n免费取消'}]});
const match = matchRates(network, dom)[0];
const context = {check_in_date:'2026-08-20',nights:1,guests:2,currency:'CNY'};
console.log(JSON.stringify({observation: observation(match, context, 'https://hotels.ctrip.com/hotels/detail/?hotelId=1', '2026-08-13T00:00:00Z'), context_ok: verifyContext('8月20日 8月21日 2成人', context)}));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
        )
        value = json.loads(completed.stdout)

        self.assertTrue(value["context_ok"])
        self.assertTrue(value["observation"]["price_match"])
        self.assertTrue(value["observation"]["adr_eligible"])
        self.assertEqual(2, value["observation"]["workstations"])

    def test_ota_mapping_requires_the_exact_hotel_name_before_city_suffix(self) -> None:
        script = """
import { mappingName } from './collector/ctrip_live_rates.mjs';
console.log(JSON.stringify({
  same: mappingName('奕界电竞酒店(春熙路店)') === mappingName('奕界电竞酒店(春熙路店), 成都, 四川, 中国'),
  different: mappingName('奕界电竞酒店(春熙路店)') === mappingName('奕界电竞酒店(太古里店), 成都, 四川, 中国')
}));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
        )
        value = json.loads(completed.stdout)

        self.assertTrue(value["same"])
        self.assertFalse(value["different"])

    def test_360_benchmark_selection_is_quality_ranked_and_never_exceeds_eight(self) -> None:
        script = """
import { benchmarkCandidates } from './collector/playwright_360_map.mjs';
const make = (id, {photo = false, rooms = 0, rating = 4.5, reviews = 10, distance = 100} = {}) => ({
  item: {
    pguid: id, avg_rating: rating, review_count: reviews,
    detail: { room_types: Array.from({length: rooms}, (_, i) => ({name: `房型${i}`, imgs: photo ? ['https://example.com/room.jpg'] : []})) }
  }, distance
});
const candidates = [
  make('nearest-low-evidence', {distance: 20}),
  make('photo-room-high-rating', {photo: true, rooms: 2, rating: 4.9, reviews: 100, distance: 800}),
  ...Array.from({length: 10}, (_, index) => make(`candidate-${index}`, {photo: true, rooms: 1, rating: 4.0 + index / 100, reviews: index, distance: 100 + index}))
];
const selected = benchmarkCandidates(candidates, 99);
console.log(JSON.stringify({ids: selected.map(({item}) => item.pguid), count: selected.length}));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
        )
        value = json.loads(completed.stdout)

        self.assertEqual(8, value["count"])
        self.assertEqual("photo-room-high-rating", value["ids"][0])
        self.assertNotIn("nearest-low-evidence", value["ids"])

        zero_script = """
import { benchmarkCandidates } from './collector/playwright_360_map.mjs';
console.log(JSON.stringify(benchmarkCandidates([{item:{pguid:'only', detail:{}}, distance:1}], 0).length));
"""
        zero_completed = subprocess.run(
            ["node", "--input-type=module", "-e", zero_script],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
        )
        self.assertEqual(0, json.loads(zero_completed.stdout))

    def test_360_candidates_retain_the_confirmed_center_provider_identity(self) -> None:
        script = """
import { candidateProvider } from './collector/playwright_360_map.mjs';
console.log(JSON.stringify(candidateProvider({provider:'360-map-v1'})));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
        )

        self.assertEqual("360-map-v1", json.loads(completed.stdout))

    def test_price_difference_does_not_become_an_adr_offer(self) -> None:
        script = """
import { networkRates, domRates, matchRates, observation } from './collector/ctrip_live_rates.mjs';
const network = networkRates({roomName:'双人电竞房 2台电脑',roomId:'room-2',salePrice:328,available:true,cancelPolicy:'免费取消',taxInfo:'含税'}, '/room-list');
const dom = domRates({room_blocks:[{room_id:'room-2',text:'双人电竞房 2台电脑\\n¥318\\n可订\\n含税\\n免费取消'}]});
const match = matchRates(network, dom)[0];
console.log(JSON.stringify(observation(match, {check_in_date:'2026-08-20',nights:1,guests:2,currency:'CNY'}, 'https://hotels.ctrip.com/hotels/detail/?hotelId=1', '2026-08-13T00:00:00Z')));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
        )
        value = json.loads(completed.stdout)

        self.assertFalse(value["price_match"])
        self.assertFalse(value["adr_eligible"])
        self.assertIn("network_dom_price_mismatch", value["qualification_gaps"])


if __name__ == "__main__":
    unittest.main()
