from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import calculate  # noqa: E402
import input_contract  # noqa: E402


def simple_project() -> dict:
    return {
        "project": {
            "name": "陌生酒店签约前测算",
            "rooms": 3,
            "workstations": 8,
            "term_years": 1,
            "operating_days": 360,
        },
        "contract": {
            "jwl_share": 0.5,
            "owner_share": 0.5,
            "exit_occ_threshold": 0.5,
            "equipment_depreciation_years": 3,
            "renovation_depreciation_years": 3,
            "high_season_share": 0.4,
            "high_season_premium": 0.3,
            "low_season_premium": 0.1,
        },
        "revenue": {
            "mode": "adr_occ",
            "base_occ": 0.5,
            "egame_adr": 100,
            "traditional_adr": 80,
            "traditional_occ": 0.5,
            "hourly_eligible_room_share": 0,
            "hourly_turnovers_per_room_day": 0,
            "hourly_rate": 0,
            "ancillary_rate": 0,
            "online_share": 0,
        },
        "public_costs": {
            "ota_commission_rate": 0,
            "traffic_rate": 0,
            "mystery_shopper_kol_rate": 0,
            "offline_promotion_rate": 0,
            "ota_performance_monthly": 0,
            "turnover_tax_rate": 0,
        },
        "jwl": {
            "capex": {"cloud_box_per_seat": 100},
            "opex_monthly": {},
            "replacement": {"year": 1, "amount": 0},
        },
        "owner": {
            "capex": {},
            "incremental_opex_monthly": {},
            "allocated_opex_monthly": {},
        },
        "finance": {
            "discount_rate": 0,
            "hurdle_irr": 0,
            "maximum_discounted_payback_years": 3,
            "exit_occ_safety_buffer": 0.1,
        },
        "metadata": {"data_confidence": "high"},
    }


class RoomTypeUnderwritingTests(unittest.TestCase):
    def test_room_types_are_calculated_from_their_own_adr_and_occ(self) -> None:
        project = simple_project()
        project["revenue"]["room_types"] = [
            {
                "name": "双人电竞房",
                "rooms": 2,
                "workstations_per_room": 2,
                "egame_adr": 100,
                "base_occ": 0.5,
            },
            {
                "name": "四人电竞房",
                "rooms": 1,
                "workstations_per_room": 4,
                "egame_adr": 300,
                "base_occ": 0.25,
            },
        ]

        result = calculate.run(project)

        first = result["base_case"]["annual"][0]
        self.assertAlmostEqual(63_000, first["overnight_revenue"])
        self.assertAlmostEqual(63_000, first["gross_revenue"])
        self.assertAlmostEqual(450 / 1_080, first["occ"])
        self.assertAlmostEqual(140, first["adr"])

    def test_room_type_inventory_must_tie_to_project_totals(self) -> None:
        project = simple_project()
        project["project"]["workstations"] = 7
        project["revenue"]["room_types"] = [
            {
                "name": "双人电竞房",
                "rooms": 2,
                "workstations_per_room": 2,
                "egame_adr": 100,
                "base_occ": 0.5,
            },
            {
                "name": "四人电竞房",
                "rooms": 1,
                "workstations_per_room": 4,
                "egame_adr": 300,
                "base_occ": 0.25,
            },
        ]

        with self.assertRaises(calculate.ModelError) as caught:
            calculate.run(project)

        self.assertIn("机位", str(caught.exception))

    def test_strict_schema_accepts_room_type_underwriting_input(self) -> None:
        project = simple_project()
        project["revenue"]["room_types"] = [
            {
                "name": "双人电竞房",
                "rooms": 2,
                "workstations_per_room": 2,
                "egame_adr": 100,
                "base_occ": 0.5,
            },
            {
                "name": "四人电竞房",
                "rooms": 1,
                "workstations_per_room": 4,
                "egame_adr": 300,
                "base_occ": 0.25,
            },
        ]

        input_contract.validate_project_input(project)

    def test_room_type_adr_sensitivity_changes_jwl_npv(self) -> None:
        project = simple_project()
        project["revenue"]["room_types"] = [
            {
                "name": "双人电竞房",
                "rooms": 2,
                "workstations_per_room": 2,
                "egame_adr": 100,
                "base_occ": 0.5,
            },
            {
                "name": "四人电竞房",
                "rooms": 1,
                "workstations_per_room": 4,
                "egame_adr": 300,
                "base_occ": 0.25,
            },
        ]

        result = calculate.run(project)

        adr_driver = next(item for item in result["sensitivity"] if item["driver"] == "电竞ADR")
        self.assertGreater(adr_driver["absolute_impact_rank_value"], 0)


class OwnerOpportunityCostTests(unittest.TestCase):
    def test_negative_owner_fully_loaded_cashflow_is_flagged_for_deal_decision(self) -> None:
        project = simple_project()
        project["owner"]["allocated_opex_monthly"]["rent_property_per_room"] = 50_000

        result = calculate.run(project)

        self.assertLess(result["base_case"]["annual"][0]["owner_fully_loaded_net_cashflow"], 0)
        self.assertTrue(
            any("业主完全成本" in item for item in result["decision"]["cautions"]),
            result["decision"],
        )

    def test_owner_economic_view_subtracts_replaced_traditional_contribution_once(self) -> None:
        project = simple_project()
        project["project"].update({"rooms": 1, "workstations": 1})
        project["contract"].update({"jwl_share": 0.3, "owner_share": 0.7})
        project["revenue"].update(
            {
                "egame_adr": 200,
                "base_occ": 0.5,
                "traditional_adr": 100,
                "traditional_occ": 0.5,
                "traditional_contribution_margin_rate": 0.8,
            }
        )
        project["jwl"]["capex"]["cloud_box_per_seat"] = 0

        result = calculate.run(project)

        first = result["base_case"]["annual"][0]
        self.assertAlmostEqual(18_000, first["traditional_baseline_revenue"])
        self.assertAlmostEqual(14_400, first["replaced_traditional_contribution"])
        self.assertAlmostEqual(25_200, first["owner_incremental_net_cashflow"])
        self.assertAlmostEqual(10_800, first["owner_economic_incremental_net_cashflow"])
        self.assertAlmostEqual(10_800, result["base_case"]["owner_economic_incremental"]["cashflows"][1])

    def test_strict_schema_accepts_traditional_contribution_margin(self) -> None:
        project = simple_project()
        project["revenue"]["traditional_contribution_margin_rate"] = 0.8

        input_contract.validate_project_input(project)

    def test_negative_owner_economic_npv_is_flagged_for_deal_decision(self) -> None:
        project = simple_project()
        project["contract"].update({"jwl_share": 0.9, "owner_share": 0.1})
        project["revenue"].update(
            {
                "traditional_adr": 1_000,
                "traditional_occ": 0.9,
                "traditional_contribution_margin_rate": 1.0,
            }
        )

        result = calculate.run(project)

        self.assertTrue(
            any("传统房" in item for item in result["decision"]["cautions"]),
            result["decision"],
        )


class MonthlyRampTests(unittest.TestCase):
    def test_six_month_exit_redline_is_checked_as_a_rolling_window(self) -> None:
        project = simple_project()
        project["project"].update(
            {
                "rooms": 1,
                "workstations": 1,
                "operating_days": 365,
                "opening_date": "2027-01-01",
            }
        )
        project["revenue"].update(
            {
                "base_occ": 0.70,
                "first_year_monthly_occ_schedule": [0.49] * 6 + [0.90] * 6,
            }
        )
        project["jwl"]["capex"]["cloud_box_per_seat"] = 0

        result = calculate.run(project)

        assessment = result["base_case"]["contract_exit_assessment"]
        self.assertEqual("triggered", assessment["status"])
        self.assertEqual([1], assessment["triggered_window_start_months"])
        self.assertTrue(
            any("连续六个月" in item for item in result["decision"]["hard_failures"]),
            result["decision"],
        )

    def test_first_year_monthly_ramp_uses_actual_calendar_days(self) -> None:
        project = simple_project()
        project["project"].update(
            {
                "rooms": 1,
                "workstations": 1,
                "operating_days": 365,
                "opening_date": "2027-01-01",
            }
        )
        project["revenue"].update(
            {
                "egame_adr": 100,
                "base_occ": 0.9,
                "first_year_monthly_occ_schedule": [
                    0.1,
                    0.2,
                    0.3,
                    0.4,
                    0.5,
                    0.6,
                    0.7,
                    0.8,
                    0.9,
                    1.0,
                    1.0,
                    1.0,
                ],
            }
        )
        project["jwl"]["capex"]["cloud_box_per_seat"] = 0

        result = calculate.run(project)

        monthly = result["base_case"]["monthly"]
        first = result["base_case"]["annual"][0]
        self.assertEqual(12, len(monthly))
        self.assertAlmostEqual(310, monthly[0]["overnight_revenue"])
        self.assertAlmostEqual(3_100, monthly[-1]["overnight_revenue"])
        self.assertAlmostEqual(22_900, first["overnight_revenue"])
        self.assertAlmostEqual(229 / 365, first["occ"])

    def test_strict_schema_accepts_opening_date_and_monthly_ramp(self) -> None:
        project = simple_project()
        project["project"]["opening_date"] = "2027-01-01"
        project["revenue"]["first_year_monthly_occ_schedule"] = [0.5] * 12

        input_contract.validate_project_input(project)

    def test_monthly_ramp_requires_exactly_twelve_months(self) -> None:
        project = simple_project()
        project["project"]["opening_date"] = "2027-01-01"
        project["revenue"]["first_year_monthly_occ_schedule"] = [0.5] * 11

        with self.assertRaises(calculate.ModelError) as caught:
            calculate.run(project)

        self.assertIn("12", str(caught.exception))

    def test_strict_schema_rejects_more_than_twelve_ramp_months(self) -> None:
        project = simple_project()
        project["project"]["opening_date"] = "2027-01-01"
        project["revenue"]["first_year_monthly_occ_schedule"] = [0.5] * 13

        with self.assertRaises(input_contract.InputContractError):
            input_contract.validate_project_input(project)

    def test_monthly_costs_and_party_cashflows_reconcile_to_year_one(self) -> None:
        project = simple_project()
        project["project"].update(
            {
                "rooms": 1,
                "workstations": 1,
                "operating_days": 365,
                "opening_date": "2027-01-01",
            }
        )
        project["revenue"]["first_year_monthly_occ_schedule"] = [0.5] * 12
        project["public_costs"]["ota_performance_monthly"] = 50
        project["jwl"]["capex"]["cloud_box_per_seat"] = 0
        project["jwl"]["opex_monthly"]["ota_team_fixed"] = 100

        result = calculate.run(project)

        monthly = result["base_case"]["monthly"]
        first = result["base_case"]["annual"][0]
        self.assertAlmostEqual(600, sum(row["ota_performance_cost"] for row in monthly))
        self.assertAlmostEqual(first["public_cost_total"], sum(row["public_cost_total"] for row in monthly))
        self.assertAlmostEqual(first["jwl_cash_opex"], sum(row["jwl_cash_opex"] for row in monthly))
        self.assertAlmostEqual(first["jwl_net_cashflow"], sum(row["jwl_net_cashflow"] for row in monthly))

    def test_monthly_ramp_occ_sensitivity_changes_jwl_npv(self) -> None:
        project = simple_project()
        project["project"].update(
            {
                "rooms": 1,
                "workstations": 1,
                "operating_days": 365,
                "opening_date": "2027-01-01",
            }
        )
        project["revenue"]["first_year_monthly_occ_schedule"] = [0.5] * 12

        result = calculate.run(project)

        occ_driver = next(item for item in result["sensitivity"] if item["driver"] == "入住率OCC")
        self.assertGreater(occ_driver["absolute_impact_rank_value"], 0)


class PaybackMonthTests(unittest.TestCase):
    def test_static_payback_months_follow_the_historical_monthly_formula(self) -> None:
        """Initial CapEx / first-year average monthly operating net cash."""

        project = simple_project()
        project["project"].update({"rooms": 1, "workstations": 1})
        project["jwl"]["capex"] = {"cloud_box_per_seat": 5_000}

        result = calculate.run(project)
        jwl = result["base_case"]["jwl"]

        self.assertAlmostEqual(750, jwl["first_year_average_monthly_operating_net_cashflow"])
        self.assertAlmostEqual(5000 / 750, jwl["static_payback_months"])
        self.assertEqual(7, jwl["static_payback_months_rounded_up"])
        self.assertAlmostEqual(
            jwl["discounted_payback_years"] * 12,
            jwl["discounted_payback_months"],
        )
        self.assertEqual(7, jwl["discounted_payback_months_rounded_up"])
        self.assertIn("静态回本7个月", result["feishu_summary"])
        self.assertIn("动态回本7个月", result["feishu_summary"])

    def test_static_payback_months_are_not_reported_when_first_year_cash_is_nonpositive(self) -> None:
        project = simple_project()
        project["project"].update({"rooms": 1, "workstations": 1})
        project["jwl"]["opex_monthly"] = {"other_fixed": 1_000}

        result = calculate.run(project)
        jwl = result["base_case"]["jwl"]

        self.assertLessEqual(jwl["first_year_average_monthly_operating_net_cashflow"], 0)
        self.assertIsNone(jwl["static_payback_months"])
        self.assertIsNone(jwl["static_payback_months_rounded_up"])
        self.assertIsNone(jwl["discounted_payback_months"])
        self.assertIsNone(jwl["discounted_payback_months_rounded_up"])


class NegotiationSolverTests(unittest.TestCase):
    def test_solver_returns_minimum_share_and_maximum_initial_capex_at_hurdle(self) -> None:
        project = simple_project()
        project["project"].update(
            {"rooms": 1, "workstations": 1, "term_years": 2, "operating_days": 100}
        )
        project["revenue"].update({"egame_adr": 2_000, "base_occ": 0.5})
        project["contract"].update({"jwl_share": 0.5, "owner_share": 0.5})
        project["jwl"]["capex"] = {"other_fixed": 100_000}
        project["jwl"]["opex_monthly"] = {"other_fixed": 1_000}
        project["jwl"]["replacement"] = {"year": 2, "amount": 0}
        project["finance"].update({"discount_rate": 0.1, "hurdle_irr": 0.1})

        result = calculate.run(project)

        negotiation = result["negotiation"]
        self.assertAlmostEqual(
            0.6961904761904761,
            negotiation["minimum_jwl_share_for_hurdle"],
            places=10,
        )
        self.assertAlmostEqual(
            65_950.41322314049,
            negotiation["maximum_jwl_initial_capex_at_hurdle"],
            places=6,
        )
        self.assertAlmostEqual(
            -34_049.586776859506,
            negotiation["jwl_initial_capex_headroom"],
            places=6,
        )
        self.assertTrue(
            any("最低分成" in item for item in result["decision"]["cautions"]),
            result["decision"],
        )
        self.assertTrue(
            any("最高初投" in item for item in result["decision"]["cautions"]),
            result["decision"],
        )

    def test_feishu_summary_surfaces_negotiation_floor_and_capex_ceiling(self) -> None:
        project = simple_project()

        result = calculate.run(project)

        self.assertIn("最低分成", result["feishu_summary"])
        self.assertIn("最高初投", result["feishu_summary"])


class RevparBreakEvenTests(unittest.TestCase):
    def test_revpar_mode_does_not_report_zero_break_even_occ(self) -> None:
        project = simple_project()
        project["revenue"]["mode"] = "revpar"
        project["revenue"]["egame_revpar"] = 100

        result = calculate.run(project)
        jwl = result["base_case"]["jwl"]

        self.assertIsNone(jwl["break_even_occ"])
        self.assertEqual(jwl["break_even_occ_status"], "not_applicable")
        self.assertIn("RevPAR模式", jwl["break_even_occ_reason"])
        self.assertTrue(
            any("盈亏平衡OCC不适用" in item for item in result["decision"]["cautions"]),
            result["decision"],
        )
        self.assertIn("不适用", calculate.feishu_summary(result))

    def test_revpar_room_type_sensitivity_uses_revpar_driver(self) -> None:
        project = simple_project()
        project["revenue"].update(
            {
                "mode": "revpar",
                "egame_revpar": 245,
                "room_types": [
                    {
                        "name": "双人电竞房",
                        "rooms": 2,
                        "workstations_per_room": 2,
                        "egame_revpar": 230,
                        "base_occ": 0.55,
                    },
                    {
                        "name": "四人电竞房",
                        "rooms": 1,
                        "workstations_per_room": 4,
                        "egame_revpar": 275,
                        "base_occ": 0.45,
                    },
                ],
            }
        )

        result = calculate.run(project)

        revpar_driver = next(
            item for item in result["sensitivity"] if item["driver"] == "电竞RevPAR"
        )
        self.assertGreater(revpar_driver["absolute_impact_rank_value"], 0)
        self.assertNotIn("电竞ADR", {item["driver"] for item in result["sensitivity"]})
        self.assertEqual(
            "not_applicable", result["base_case"]["jwl"]["break_even_occ_status"]
        )


if __name__ == "__main__":
    unittest.main()
