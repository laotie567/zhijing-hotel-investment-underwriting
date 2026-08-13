# Decision policy

## 1. Decision order

Apply the following gates in order. A later positive metric never overrides an earlier failure.

1. Contract and legal feasibility.
2. Property/technical hard gates.
3. Data completeness and evidence quality.
4. JWL cash economics.
5. Owner sustainability.
6. Downside resilience and contract redlines.

## 2. Hard failures

Return `不建议合作` when any material hard failure remains unresolved:

- illegal or unconfirmed operating/ownership/lease position;
- power, network, fire/safety or room-layout infeasibility;
- party shares do not total 100%;
- base OCC is below the contract exit redline;
- any observed six-month rolling OCC window is below the contract exit redline;
- JWL annual operating cash flow is non-positive;
- JWL NPV is non-positive;
- cash flows cannot produce a meaningful IRR because they never change sign;
- JWL cannot reach annual operating break-even even at 100% OCC;
- material formula/model reconciliation fails.

## 3. Cautions

Return at most `审慎推进` when any of these remains:

- JWL IRR is below the entered hurdle;
- JWL discounted payback exceeds the entered maximum;
- base OCC has less than the required safety buffer over the 60% exit redline;
- JWL break-even OCC is above the contract exit redline;
- esports RevPAR does not meet the contract seasonal premium floor;
- downside scenario produces negative JWL NPV;
- owner fully loaded cash flow is negative or requires unevidenced cost subsidy;
- owner fully loaded first-year cash flow or NPV is non-positive;
- owner economic-increment NPV is non-positive after replacing traditional-room contribution;
- current JWL share is below the hurdle-IRR minimum or planned initial CapEx exceeds the calculated maximum;
- multiple IRR roots exist;
- a shared-manager cost required by room count is omitted;
- hourly revenue is material but inventory overlap is untested.
- fewer than six monthly OCC observations are available to test the exit redline;

## 4. Confidence cap

Keep three dimensions separate:

- `declared_data_confidence`: the analyst's input declaration;
- `evidence_confidence`: what the source classes can support;
- `forecast_confidence`: what an independently reviewed historical backtest can support.

The effective result confidence is the lowest of the three. Without a
`forecast_validation` record, forecast confidence is `low`. A `backtested`
record can support at most `medium`; `high` requires an independently approved
validation record. A positive low-confidence result is capped at `条件性推进`.

Treat a benchmark-backed revenue forecast as low confidence unless corroborated
by current PMS/OTA data, a signed minimum guarantee and a validated forecast
record.

## 5. Default financial gates

Use these only when the user or company policy does not provide alternatives:

- JWL NPV greater than zero at the chosen discount rate;
- JWL IRR at least 20%;
- JWL discounted payback no longer than 3 years;
- base OCC at least 10 percentage points above the contract exit redline;
- owner fully loaded annual cash flow positive;
- owner economic increment positive when traditional contribution evidence is available;
- downside scenario explicitly reviewed.

These are policy thresholds, not universal finance truths. Preserve user-supplied thresholds in the input JSON.

## 6. Recommendation language

- `建议合作`: gates pass, return thresholds pass, downside is tolerable, and evidence is medium/high.
- `条件性推进`: arithmetic is attractive but data confidence is low; specify conditions precedent.
- `审慎推进`: NPV is positive but one or more return, owner, price-floor or downside cautions remain.
- `不建议合作`: a hard gate or fundamental JWL value-creation test fails.

Always name the conditions needed to improve a weak conclusion. Examples: replace assumed OCC with 12-month PMS history, obtain seat-level quote, cap cloud fee, reduce public-cost rate, add minimum revenue guarantee, or adjust room mix.
