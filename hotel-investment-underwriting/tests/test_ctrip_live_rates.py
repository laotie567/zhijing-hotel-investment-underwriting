"""Regression tests for the Ui.Vision + OpenCLI Ctrip live-rate boundary."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import collect_market_evidence  # noqa: E402
import market_evidence_contract  # noqa: E402


ATTESTATION_KEY = "market-evidence-test-key-with-at-least-32-bytes"


def request() -> dict:
    value = {
        "contract_version": "market-evidence-collection/v2",
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
    identifiers = sorted(
        item["candidate"]["provider_place_id"] for item in value["candidate_inventory"]
    )
    value["candidate_pool"] = {
        "status": "complete",
        "source_engine": "playwright",
        "source_profile": "360-map-v1",
        "center": value["target"]["center"],
        "candidate_count": len(identifiers),
        "candidate_ids_sha256": hashlib.sha256(
            json.dumps(identifiers, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "candidate_snapshot_sha256": market_evidence_contract._candidate_snapshot_sha256(
            [item["candidate"] for item in value["candidate_inventory"]]
        ),
    }
    return value


def result() -> dict:
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "contract_version": "market-evidence-collection/v2",
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
            "collection_status": "complete",
            "pricing_context": request()["pricing_context"],
            "candidates": [
                {
                    **copy.deepcopy(request()["candidate_inventory"][0]["candidate"]),
                    "benchmark_selected": True,
                    "room_type_evidence": [
                        {
                            "room_type": "双人电竞房",
                            "room_type_provider_id": "candidate-001:room-1",
                            "source_url": "https://hotels.ctrip.com/hotels/detail/?hotelId=133623094",
                            "observed_at": timestamp,
                        }
                    ],
                }
            ],
        },
        "competitor_report": {"candidate_media": []},
        "spatial_collection": request()["candidate_pool"],
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

        with patch.dict(
            os.environ,
            {"MARKET_EVIDENCE_RECEIPT_HMAC_KEY": ATTESTATION_KEY},
            clear=True,
        ), patch.object(collect_market_evidence, "_run_process", side_effect=fake_runner), patch.object(
            collect_market_evidence.market_evidence_runtime, "require_ready"
        ):
            collected = collect_market_evidence.collect(request(), engine="ctrip-live-rates", timeout_seconds=120)

        self.assertEqual("ctrip-live-rates", collected["collector"]["engine"])
        self.assertEqual("node", captured["command"][0])
        self.assertTrue(str(captured["command"][1]).endswith("ctrip_live_rates.mjs"))
        self.assertEqual(120, captured["timeout"])
        self.assertIn("attestation", collected)

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

    def test_tax_scope_conflict_or_total_stay_price_never_becomes_a_p2_adr_offer(self) -> None:
        script = """
import { networkRates, observation } from './collector/ctrip_live_rates.mjs';
const context = {check_in_date:'2026-08-20',nights:2,guests:2,currency:'CNY'};
const conflict = observation({
  network:{room_id:'room-2',room_name:'双人电竞房',rate_plan_name:'可取消',price:300,availability:'available',tax_included:false,cancellation_policy:'免费取消'},
  dom:{room_id:'room-2',room_name:'双人电竞房',price:300,availability:'available',tax_included:true,cancellation_policy:'免费取消',workstations:2},
  price_match:true
}, context, 'https://hotels.ctrip.com/hotels/detail/?hotelId=1', '2026-08-13T00:00:00Z');
const totalOnly = networkRates({roomName:'双人电竞房',totalPrice:600,available:true,cancelPolicy:'免费取消',taxInfo:'含税'}, '/room-list');
console.log(JSON.stringify({conflict, totalOnly}));
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

        self.assertFalse(value["conflict"]["adr_eligible"])
        self.assertIn("tax_scope_mismatch", value["conflict"]["qualification_gaps"])
        self.assertEqual([], value["totalOnly"])

    def test_unverified_page_context_never_marks_a_p2_observation_adr_eligible(self) -> None:
        script = """
import { networkRates, domRates, matchRates, observation } from './collector/ctrip_live_rates.mjs';
const network = networkRates({roomName:'双人电竞房 2台电脑',roomId:'room-2',salePrice:328,available:true,cancelPolicy:'免费取消',taxInfo:'含税'}, '/room-list');
const dom = domRates({room_blocks:[{room_id:'room-2',text:'双人电竞房 2台电脑\\n¥328\\n可订\\n含税\\n免费取消'}]});
const match = matchRates(network, dom)[0];
console.log(JSON.stringify(observation(match, {check_in_date:'2026-08-20',nights:1,guests:2,currency:'CNY'}, 'https://hotels.ctrip.com/hotels/detail/?hotelId=1', '2026-08-13T00:00:00Z', false)));
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

        self.assertFalse(value["adr_eligible"])
        self.assertIn("pricing_context_unverified", value["qualification_gaps"])

    def test_unverified_dom_parser_never_marks_a_p2_observation_adr_eligible(self) -> None:
        """A layout drift may retain legacy text, but cannot retain ADR authority."""

        script = """
import { networkRates, domRates, matchRates, observation } from './collector/ctrip_live_rates.mjs';
const network = networkRates({roomName:'双人电竞房 2台电脑',roomId:'room-2',salePrice:328,available:true,cancelPolicy:'免费取消',taxInfo:'含税'}, '/room-list');
const dom = domRates({room_blocks:[{room_id:'room-2',text:'双人电竞房 2台电脑\\n¥328\\n可订\\n含税\\n免费取消'}]});
const match = matchRates(network, dom)[0];
console.log(JSON.stringify(observation(match, {check_in_date:'2026-08-20',nights:1,guests:2,currency:'CNY'}, 'https://hotels.ctrip.com/hotels/detail/?hotelId=1', '2026-08-13T00:00:00Z', true, false)));
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

        self.assertFalse(value["adr_eligible"])
        self.assertIn("dom_parser_unverified", value["qualification_gaps"])

    def test_live_batch_waits_for_the_side_panel_connection_before_actions(self) -> None:
        script = """
import { waitForUiVisionExtension } from './collector/ctrip_live_rates.mjs';
let calls = 0;
const bridge = { tool: async () => ({content:[{type:'text', text: ++calls < 3 ? 'NOT connected' : 'CONNECTED'}]}) };
console.log(JSON.stringify({connected: await waitForUiVisionExtension(bridge, 1, 0), calls}));
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

        self.assertTrue(value["connected"])
        self.assertEqual(3, value["calls"])

    def test_created_macro_uses_the_returned_ui_vision_folder_path(self) -> None:
        """Ui.Vision saves agent macros below ``AI Generated/`` under its final name."""

        script = """
import { ensureMacro } from './collector/ctrip_live_rates.mjs';
const calls = [];
const bridge = { tool: async (name, args = {}) => {
  calls.push({name, args});
  if (name === 'list_macros') return {content:[{type:'text', text:'48 macros (folder paths relative to macro root):'}], isError:false};
  if (name === 'create_macro') return {content:[{type:'text', text:'AI Generated/zhijing-ctrip-wait-rates-v1 Demo and QA Test Scripts/Browser Vision (Chrome, Edge)/DemoBrowserClick.js'}], isError:false};
  if (name === 'open_macro') return {content:[{type:'text', text:'opened'}], isError:false};
  throw new Error(`unexpected ${name}`);
}};
console.log(JSON.stringify({macro: await ensureMacro(bridge), calls}));
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        value = json.loads(completed.stdout)
        self.assertEqual("AI Generated/zhijing-ctrip-wait-rates-v1", value["macro"])
        self.assertEqual(
            ["list_macros", "create_macro", "open_macro"],
            [call["name"] for call in value["calls"]],
        )
        self.assertEqual(
            "AI Generated/zhijing-ctrip-wait-rates-v1",
            value["calls"][-1]["args"]["name"],
        )

    def test_cli_accepts_the_standard_input_contract_used_by_the_host_tool(self) -> None:
        completed = subprocess.run(
            ["node", str(ROOT / "collector" / "ctrip_live_rates.mjs")],
            cwd=ROOT,
            input="{}",
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(0, completed.returncode)
        self.assertNotIn("MARKET_EVIDENCE_REQUEST_JSON is required", completed.stderr)
        self.assertIn("unsupported market evidence contract", completed.stderr)

    def test_ctrip_smoke_fixture_is_a_valid_complete_map_pool_handoff(self) -> None:
        value = json.loads(
            (ROOT / "tests" / "fixtures" / "market-evidence-ctrip-smoke.json").read_text(
                encoding="utf-8"
            )
        )

        normalized = market_evidence_contract.validate_collection_request(value)

        self.assertEqual("complete", normalized["candidate_pool"]["status"])
        self.assertEqual(1, normalized["candidate_pool"]["candidate_count"])

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

    def test_automatic_mapping_requires_a_city_extracted_from_the_target_address(self) -> None:
        script = """
import { cityFromAddress } from './collector/ctrip_live_rates.mjs';
console.log(JSON.stringify({
  chengdu: cityFromAddress('成都市青羊区万达广场商业楼 2 栋'),
  missing: cityFromAddress('万达广场商业楼 2 栋')
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

        self.assertEqual("成都", value["chengdu"])
        self.assertEqual("", value["missing"])

    def test_stale_live_rate_lock_can_be_recovered_but_a_live_pid_cannot(self) -> None:
        script = """
import { lockIsStale } from './collector/ctrip_live_rates.mjs';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
const directory = mkdtempSync(path.join(os.tmpdir(), 'zhijing-lock-test-'));
const stale = path.join(directory, 'stale.lock');
const live = path.join(directory, 'live.lock');
writeFileSync(stale, JSON.stringify({pid: 99999999, started_at: '2020-01-01T00:00:00.000Z'}));
writeFileSync(live, JSON.stringify({pid: process.pid, started_at: new Date().toISOString()}));
console.log(JSON.stringify({stale: lockIsStale(stale), live: lockIsStale(live)}));
rmSync(directory, {recursive: true, force: true});
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

        self.assertTrue(value["stale"])
        self.assertFalse(value["live"])

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

        reason_script = """
import { benchmarkSelectionReason } from './collector/playwright_360_map.mjs';
const item = {pguid:'evidence', avg_rating:4.8, review_count:120, detail:{room_types:[{name:'双人电竞房', imgs:['https://example.com/a.jpg']} ]}};
console.log(benchmarkSelectionReason({item, distance:386}));
"""
        reason_completed = subprocess.run(
            ["node", "--input-type=module", "-e", reason_script],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
        )
        self.assertIn("有公开房型图", reason_completed.stdout)
        self.assertIn("距目标386米", reason_completed.stdout)

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

    def test_360_discovery_retains_incidental_lodging_for_auditable_exclusion(self) -> None:
        script = """
import { mapCandidateFacts } from './collector/playwright_360_map.mjs';
const generic = mapCandidateFacts({name:'万达智选酒店（含电竞房）', cat_new_name:'酒店', detail:{category:'住宿服务'}});
const primary = mapCandidateFacts({name:'星际电竞酒店', cat_new_name:'酒店', detail:{category:'住宿服务'}});
console.log(JSON.stringify({generic, primary}));
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

        self.assertEqual("lodging", value["generic"]["property_kind"])
        self.assertEqual("incidental", value["generic"]["esports_positioning"])
        self.assertEqual("primary", value["primary"]["esports_positioning"])

    def test_ego_uses_the_map_pool_proof_not_an_inventory_length_heuristic(self) -> None:
        source = (ROOT / "collector" / "ego_ctrip.mjs").read_text(encoding="utf-8")

        self.assertIn('request.candidate_pool?.status === "complete"', source)
        self.assertNotIn(
            "inventory.length > 0 && inventory.length < request.search.max_candidates",
            source,
        )

    def test_p2_dom_parser_receives_raw_room_card_outerhtml_not_reconstructed_semantic_markup(self) -> None:
        source = (ROOT / "collector" / "ctrip_live_rates.mjs").read_text(encoding="utf-8")

        self.assertIn("rawRoomCards.push(element.outerHTML)", source)
        self.assertIn('data-ctrip-captured-panel="true"', source)
        self.assertNotIn("parserCards", source)
        self.assertNotIn('data-role="room-price"', source)

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
