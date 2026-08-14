"""Regression guards for the Ego Lite Ctrip P1 evidence adapter."""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent


class EgoCtripContractTests(unittest.TestCase):
    def test_no_inventory_is_a_structured_completed_pricing_outcome(self) -> None:
        source = (ROOT / "collector" / "ego_ctrip.mjs").read_text(encoding="utf-8")

        self.assertIn('"NO_INVENTORY"', source)
        self.assertIn("pricingResolvedCandidateCount", source)
        self.assertIn("本酒店目前不接受预订", source)

    def test_page_room_types_are_written_as_traceable_non_price_evidence(self) -> None:
        source = (ROOT / "collector" / "ego_ctrip.mjs").read_text(encoding="utf-8")

        self.assertIn("candidate.room_type_evidence", source)
        self.assertIn("room_type_provider_id", source)
        self.assertIn("source_url: bookingUrl", source)
        self.assertIn("structured bookable-room", source)
        self.assertNotIn("rawBody.split", source)


if __name__ == "__main__":
    unittest.main()
