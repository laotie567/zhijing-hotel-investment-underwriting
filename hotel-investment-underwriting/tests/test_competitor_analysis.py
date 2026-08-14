"""Public behavior tests for the Skill's mandatory 2km competitor analysis."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import competitor_analysis  # noqa: E402


def source(*, confidence: str = "high") -> dict[str, str]:
    return {
        "source_platform": "dianping",
        "source_url": "https://www.dianping.com/shop/example",
        "observed_at": "2026-08-12T09:10:00+08:00",
        "confidence": confidence,
    }


def candidate(
    place_id: str,
    longitude: float,
    *,
    esports_positioning: str = "primary",
    provider: str = "amap",
    confidence: str = "high",
    prices: list[float] | None = None,
) -> dict:
    return {
        "provider": provider,
        "provider_place_id": place_id,
        "name": f"{place_id} 电竞酒店",
        "coordinate_system": "GCJ-02",
        "longitude": longitude,
        "latitude": 30.0,
        "property_kind": "lodging",
        "esports_positioning": esports_positioning,
        "operating_status": "operating",
        "source": source(confidence=confidence),
        "room_offers": [
            {
                "room_type": "双人电竞房",
                "room_type_provider_id": f"{place_id}:room-2",
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
            for price in (prices or [])
        ],
    }


def complete_input(candidates: list[dict]) -> dict:
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


class CompetitorAnalysisTests(unittest.TestCase):
    def test_reports_only_primary_esports_hotels_inside_two_kilometers_and_uses_median_adr(self) -> None:
        result = competitor_analysis.analyze_competitors(
            complete_input(
                [
                    candidate("P-1", 104.001, prices=[240]),
                    candidate("P-2", 104.002, prices=[260]),
                    candidate("P-3", 104.003, prices=[280]),
                    candidate("I-1", 104.0015, esports_positioning="incidental", prices=[180]),
                    candidate("O-1", 104.03, prices=[999]),
                ]
            )
        )

        self.assertEqual("complete", result["status"])
        self.assertEqual(3, result["formal_competitor_count"])
        self.assertEqual(["P-1", "P-2", "P-3"], [item["provider_place_id"] for item in result["competitors"]])
        self.assertEqual(
            {"I-1": "incidental_esports_rooms", "O-1": "excluded_out_of_range"},
            {item["provider_place_id"]: item["classification"] for item in result["excluded"]},
        )
        self.assertEqual(
            {
                "workstations": 2,
                "status": "available",
                "sample_count": 3,
                "minimum_adr": 240.0,
                "median_adr": 260.0,
                "maximum_adr": 280.0,
                "recommended_adr": 260.0,
                "low_confidence_excluded_property_count": 0,
            },
            result["pricing_by_workstations"][0],
        )

    def test_refuses_to_claim_a_competitor_result_without_a_confirmed_location(self) -> None:
        request = complete_input([candidate("P-1", 104.001, prices=[240])])
        request["confirmed_location"]["status"] = "candidate"

        result = competitor_analysis.analyze_competitors(request)

        self.assertEqual("needs_location_confirmation", result["status"])
        self.assertEqual([], result["competitors"])
        self.assertEqual(["confirmed_location.status"], result["missing_inputs"])

    def test_partial_collection_keeps_the_analysis_visible_but_suppresses_price_recommendation(self) -> None:
        request = complete_input(
            [
                candidate("P-1", 104.001, prices=[240]),
                candidate("P-2", 104.002, prices=[260]),
                candidate("P-3", 104.003, prices=[280]),
            ]
        )
        request["collection_status"] = "partial"

        result = competitor_analysis.analyze_competitors(request)

        self.assertEqual("evidence_insufficient", result["status"])
        self.assertEqual(3, result["formal_competitor_count"])
        self.assertEqual("collection_incomplete", result["pricing_by_workstations"][0]["status"])
        self.assertIsNone(result["pricing_by_workstations"][0]["recommended_adr"])

    def test_missing_shared_pricing_context_blocks_an_adr_recommendation(self) -> None:
        request = complete_input(
            [
                candidate("P-1", 104.001, prices=[240]),
                candidate("P-2", 104.002, prices=[260]),
                candidate("P-3", 104.003, prices=[280]),
            ]
        )
        del request["pricing_context"]

        result = competitor_analysis.analyze_competitors(request)

        self.assertEqual("complete", result["status"])
        self.assertEqual(["pricing_context"], result["pricing_context_missing"])
        pricing = result["pricing_by_workstations"][0]
        self.assertEqual("pricing_context_missing", pricing["status"])
        self.assertIsNone(pricing["minimum_adr"])
        self.assertIsNone(pricing["median_adr"])
        self.assertIsNone(pricing["maximum_adr"])
        self.assertIsNone(pricing["recommended_adr"])

    def test_invalid_shared_pricing_context_blocks_an_adr_recommendation(self) -> None:
        request = complete_input(
            [
                candidate("P-1", 104.001, prices=[240]),
                candidate("P-2", 104.002, prices=[260]),
                candidate("P-3", 104.003, prices=[280]),
            ]
        )
        request["pricing_context"]["currency"] = "USD"

        result = competitor_analysis.analyze_competitors(request)

        self.assertEqual(["pricing_context.currency"], result["pricing_context_missing"])
        pricing = result["pricing_by_workstations"][0]
        self.assertEqual("pricing_context_missing", pricing["status"])
        self.assertIsNone(pricing["minimum_adr"])
        self.assertIsNone(pricing["median_adr"])
        self.assertIsNone(pricing["maximum_adr"])
        self.assertIsNone(pricing["recommended_adr"])

    def test_an_ota_price_without_the_exact_context_or_available_status_is_not_an_adr_sample(self) -> None:
        request = complete_input(
            [
                candidate("P-1", 104.001, prices=[240]),
                candidate("P-2", 104.002, prices=[260]),
                candidate("P-3", 104.003, prices=[280]),
            ]
        )
        request["candidates"][0]["room_offers"][0]["pricing_context"]["guests"] = 1
        request["candidates"][1]["room_offers"][0]["availability"] = "sold_out"

        result = competitor_analysis.analyze_competitors(request)

        pricing = result["pricing_by_workstations"][0]
        self.assertEqual("insufficient_samples", pricing["status"])
        self.assertEqual(1, pricing["sample_count"])
        self.assertIsNone(pricing["recommended_adr"])

    def test_ego_dom_only_p1_price_is_visible_but_cannot_change_adr(self) -> None:
        request = complete_input(
            [
                candidate("P-1", 104.001, prices=[240]),
                candidate("P-2", 104.002, prices=[260]),
                candidate("P-3", 104.003, prices=[280]),
            ]
        )
        request["candidates"][0]["pricing_observations"] = [
            {
                "room_type": "顶配电竞双人房",
                "room_type_provider_id": "P-1:ego-dom:1",
                "price_type": "P1",
                "display_price": 999,
                "currency": "CNY",
                "availability": "available",
                "pricing_context": request["pricing_context"],
                "source_url": "https://hotels.ctrip.com/hotels/detail/?hotelId=1",
                "observed_at": "2026-08-13T14:44:37+08:00",
                "network_verified": False,
                "dom_verified": True,
                "price_match": False,
                "adr_eligible": False,
                "qualification_gaps": ["network_evidence_missing", "tax_scope_unknown"],
            }
        ]

        result = competitor_analysis.analyze_competitors(request)

        self.assertEqual(999, result["competitors"][0]["pricing_observations"][0]["display_price"])
        pricing = result["pricing_by_workstations"][0]
        self.assertEqual(260.0, pricing["recommended_adr"])
        self.assertEqual(3, pricing["sample_count"])

    def test_page_room_type_evidence_is_visible_but_never_an_adr_offer(self) -> None:
        request = complete_input(
            [
                candidate("P-1", 104.001, prices=[240]),
                candidate("P-2", 104.002, prices=[260]),
                candidate("P-3", 104.003, prices=[280]),
            ]
        )
        request["candidates"][0]["room_type_evidence"] = [
            {
                "room_type": "四人电竞大床房",
                "room_type_provider_id": "P-1:ego-dom:room-type:1",
                "source_url": "https://hotels.ctrip.com/hotels/detail/?hotelId=1",
                "observed_at": "2026-08-14T10:00:00+08:00",
            }
        ]

        result = competitor_analysis.analyze_competitors(request)

        self.assertEqual("complete", result["status"])
        self.assertEqual(
            "四人电竞大床房",
            result["competitors"][0]["room_type_evidence"][0]["room_type"],
        )
        self.assertEqual(260.0, result["pricing_by_workstations"][0]["recommended_adr"])

    def test_rejects_untraceable_room_type_evidence_from_a_complete_collection(self) -> None:
        request = complete_input([candidate("P-1", 104.001, prices=[240])])
        request["candidates"][0]["room_type_evidence"] = [{"room_type": "无来源房型"}]

        result = competitor_analysis.analyze_competitors(request)

        self.assertEqual("evidence_insufficient", result["status"])
        self.assertIn("candidate[P-1].room_type_evidence", result["missing_inputs"])

    def test_low_confidence_sources_remain_visible_but_do_not_count_toward_adr(self) -> None:
        result = competitor_analysis.analyze_competitors(
            complete_input(
                [
                    candidate("P-1", 104.001, confidence="low", prices=[240]),
                    candidate("P-2", 104.002, confidence="low", prices=[260]),
                    candidate("P-3", 104.003, confidence="low", prices=[280]),
                ]
            )
        )

        pricing = result["pricing_by_workstations"][0]
        self.assertEqual("complete", result["status"])
        self.assertEqual(3, result["formal_competitor_count"])
        self.assertEqual("insufficient_confident_samples", pricing["status"])
        self.assertEqual(0, pricing["sample_count"])
        self.assertEqual(3, pricing["low_confidence_excluded_property_count"])
        self.assertIsNone(pricing["recommended_adr"])

    def test_insufficient_confident_samples_do_not_expose_a_partial_adr_aggregate(self) -> None:
        result = competitor_analysis.analyze_competitors(
            complete_input(
                [
                    candidate("P-1", 104.001, confidence="high", prices=[240]),
                    candidate("P-2", 104.002, confidence="medium", prices=[260]),
                    candidate("P-3", 104.003, confidence="low", prices=[280]),
                ]
            )
        )

        pricing = result["pricing_by_workstations"][0]
        self.assertEqual("insufficient_confident_samples", pricing["status"])
        self.assertEqual(2, pricing["sample_count"])
        self.assertEqual(1, pricing["low_confidence_excluded_property_count"])
        self.assertIsNone(pricing["minimum_adr"])
        self.assertIsNone(pricing["median_adr"])
        self.assertIsNone(pricing["maximum_adr"])
        self.assertIsNone(pricing["recommended_adr"])

    def test_low_confidence_price_does_not_change_an_otherwise_valid_adr(self) -> None:
        result = competitor_analysis.analyze_competitors(
            complete_input(
                [
                    candidate("P-1", 104.001, confidence="high", prices=[240]),
                    candidate("P-2", 104.002, confidence="medium", prices=[260]),
                    candidate("P-3", 104.003, confidence="high", prices=[280]),
                    candidate("P-4", 104.004, confidence="low", prices=[999]),
                ]
            )
        )

        pricing = result["pricing_by_workstations"][0]
        self.assertEqual(4, result["formal_competitor_count"])
        self.assertEqual("available", pricing["status"])
        self.assertEqual(3, pricing["sample_count"])
        self.assertEqual(1, pricing["low_confidence_excluded_property_count"])
        self.assertEqual(240.0, pricing["minimum_adr"])
        self.assertEqual(260.0, pricing["median_adr"])
        self.assertEqual(280.0, pricing["maximum_adr"])
        self.assertEqual(260.0, pricing["recommended_adr"])

    def test_multiple_offers_from_one_property_count_as_one_independent_pricing_sample(self) -> None:
        result = competitor_analysis.analyze_competitors(
            complete_input([candidate("P-1", 104.001, prices=[240, 260, 280])])
        )

        pricing = result["pricing_by_workstations"][0]
        self.assertEqual("complete", result["status"])
        self.assertEqual(1, result["formal_competitor_count"])
        self.assertEqual(1, pricing["sample_count"])
        self.assertEqual("insufficient_samples", pricing["status"])
        self.assertIsNone(pricing["median_adr"])
        self.assertIsNone(pricing["recommended_adr"])

    def test_duplicate_provider_ids_block_a_formal_competitor_conclusion(self) -> None:
        result = competitor_analysis.analyze_competitors(
            complete_input(
                [
                    candidate("P-1", 104.001, prices=[240]),
                    candidate("P-1", 104.002, prices=[260]),
                    candidate("P-2", 104.003, prices=[280]),
                ]
            )
        )

        self.assertEqual("evidence_insufficient", result["status"])
        self.assertEqual(1, result["formal_competitor_count"])
        self.assertEqual(2, sum(item["classification"] == "evidence_insufficient" for item in result["excluded"]))
        self.assertIn(
            "candidate[P-1].provider_place_id_unique",
            result["missing_inputs"],
        )
        self.assertIsNone(result["pricing_by_workstations"][0]["recommended_adr"])

    def test_subject_property_is_never_counted_as_its_own_competitor(self) -> None:
        subject = candidate("target-place", 104.0, prices=[240])
        result = competitor_analysis.analyze_competitors(
            complete_input(
                [
                    subject,
                    candidate("P-1", 104.001, prices=[260]),
                    candidate("P-2", 104.002, prices=[280]),
                ]
            )
        )

        self.assertEqual("complete", result["status"])
        self.assertEqual(2, result["formal_competitor_count"])
        self.assertEqual("excluded_subject_property", result["excluded"][0]["classification"])
        self.assertEqual("insufficient_samples", result["pricing_by_workstations"][0]["status"])
        self.assertIsNone(result["pricing_by_workstations"][0]["recommended_adr"])

    def test_incomplete_candidate_evidence_blocks_a_complete_conclusion_and_adr(self) -> None:
        request = complete_input(
            [
                candidate("P-1", 104.001, prices=[240]),
                candidate("P-2", 104.002, prices=[260]),
                candidate("P-3", 104.003, prices=[280]),
            ]
        )
        del request["candidates"][2]["source"]

        result = competitor_analysis.analyze_competitors(request)

        self.assertEqual("evidence_insufficient", result["status"])
        self.assertEqual(2, result["formal_competitor_count"])
        self.assertEqual(
            "evidence_insufficient",
            result["excluded"][0]["classification"],
        )
        self.assertIn("candidate[P-3].source.source_url", result["missing_inputs"])
        self.assertEqual("collection_incomplete", result["pricing_by_workstations"][0]["status"])
        self.assertIsNone(result["pricing_by_workstations"][0]["recommended_adr"])

    def test_rejects_a_candidate_with_a_non_gcj_coordinate_system(self) -> None:
        request = complete_input([candidate("P-1", 104.001, prices=[240])])
        request["candidates"][0]["coordinate_system"] = "WGS-84"

        result = competitor_analysis.analyze_competitors(request)

        self.assertEqual("evidence_insufficient", result["status"])
        self.assertEqual(0, result["formal_competitor_count"])
        self.assertIn("coordinate_system", result["excluded"][0]["pending_fields"])

    def test_rejects_a_candidate_from_a_different_map_provider(self) -> None:
        result = competitor_analysis.analyze_competitors(
            complete_input([candidate("P-1", 104.001, provider="other-map", prices=[240])])
        )

        self.assertEqual("evidence_insufficient", result["status"])
        self.assertEqual(0, result["formal_competitor_count"])
        self.assertIn("provider_match", result["excluded"][0]["pending_fields"])

    def test_does_not_treat_a_cross_provider_id_collision_as_the_subject_property(self) -> None:
        result = competitor_analysis.analyze_competitors(
            complete_input(
                [
                    candidate(
                        "target-place",
                        104.0,
                        provider="other-map",
                        prices=[240],
                    )
                ]
            )
        )

        self.assertEqual("evidence_insufficient", result["status"])
        self.assertEqual("evidence_insufficient", result["excluded"][0]["classification"])
        self.assertIn("provider_match", result["excluded"][0]["pending_fields"])

    def test_records_verified_non_competitors_as_excluded_not_missing_evidence(self) -> None:
        non_lodging = candidate("N-1", 104.001, prices=[240])
        non_lodging["property_kind"] = "non_lodging"
        closed = candidate("C-1", 104.002, prices=[260])
        closed["operating_status"] = "closed"
        incidental = candidate("I-1", 104.003, esports_positioning="incidental", prices=[280])

        result = competitor_analysis.analyze_competitors(
            complete_input([non_lodging, closed, incidental])
        )

        self.assertEqual("complete", result["status"])
        self.assertEqual(0, result["formal_competitor_count"])
        self.assertEqual(
            {
                "N-1": "excluded_non_lodging",
                "C-1": "excluded_not_operating",
                "I-1": "incidental_esports_rooms",
            },
            {item["provider_place_id"]: item["classification"] for item in result["excluded"]},
        )

    def test_out_of_range_candidate_with_missing_source_still_blocks_completion(self) -> None:
        out_of_range = candidate("O-1", 104.03, prices=[999])
        del out_of_range["source"]

        result = competitor_analysis.analyze_competitors(
            complete_input([candidate("P-1", 104.001, prices=[240]), out_of_range])
        )

        self.assertEqual("evidence_insufficient", result["status"])
        self.assertEqual("excluded_out_of_range", result["excluded"][0]["classification"])
        self.assertIn(
            "candidate[O-1].source.source_url",
            result["missing_inputs"],
        )

    def test_non_lodging_candidate_does_not_need_irrelevant_esports_or_hotel_status_facts(self) -> None:
        non_lodging = candidate("N-1", 104.001)
        non_lodging["property_kind"] = "non_lodging"
        del non_lodging["esports_positioning"]
        del non_lodging["operating_status"]

        result = competitor_analysis.analyze_competitors(complete_input([non_lodging]))

        self.assertEqual("complete", result["status"])
        self.assertEqual("excluded_non_lodging", result["excluded"][0]["classification"])

    def test_includes_a_candidate_exactly_on_the_two_kilometer_boundary(self) -> None:
        with patch.object(competitor_analysis, "_haversine_meters", return_value=2_000.0):
            result = competitor_analysis.analyze_competitors(
                complete_input([candidate("P-1", 104.001, prices=[240])])
            )

        self.assertEqual("complete", result["status"])
        self.assertEqual(1, result["formal_competitor_count"])


if __name__ == "__main__":
    unittest.main()
