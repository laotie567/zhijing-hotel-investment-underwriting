from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import calculate  # noqa: E402


def nested(value: dict, path: str):
    current = value
    for part in path.split("."):
        if part.isdigit():
            current = current[int(part)]
        else:
            current = current[part]
    return current


class GoldenMasterTests(unittest.TestCase):
    def test_corrected_kai_bin_case_matches_frozen_outputs(self) -> None:
        case = json.loads(
            (ROOT / "tests" / "golden" / "kai-bin-corrected-v3.json").read_text(encoding="utf-8")
        )
        project = json.loads((ROOT / case["input"]).read_text(encoding="utf-8"))
        defaults = json.loads((ROOT / case["defaults"]).read_text(encoding="utf-8"))

        result = calculate.run(project, defaults)

        self.assertEqual(
            "IEEE-754 binary64; no hidden intermediate rounding",
            result["model_conventions"]["calculation_precision"],
        )

        for path, expectation in case["expected"].items():
            self.assertAlmostEqual(
                expectation["value"],
                nested(result, path),
                delta=expectation["tolerance"],
                msg=path,
            )

    def test_predeal_room_mix_ramp_opportunity_and_negotiation_match_frozen_outputs(self) -> None:
        case = json.loads(
            (ROOT / "tests" / "golden" / "predeal-hotel-v1.json").read_text(encoding="utf-8")
        )
        project = json.loads((ROOT / case["input"]).read_text(encoding="utf-8"))

        result = calculate.run(project)

        for path, expectation in case["expected"].items():
            self.assertAlmostEqual(
                expectation["value"],
                nested(result, path),
                delta=expectation["tolerance"],
                msg=path,
            )


if __name__ == "__main__":
    unittest.main()
