# Risk models

Two models, one feeding the other: the **septoria assessment** says whether the weather has favoured the disease in a susceptible
growth stage, and the **spray window** looks for weather in the next hours that may suit a treatment, but only when the
assessment gives a signal. Both state conditions, not a diagnosis, and neither instructs anyone to spray.

Thresholds are starting values for the hackathon. Each one records where it comes from: **literature**, **regulation** or a
**team assumption**. Agronomic and legal values need expert verification before any real use.

## Septoria (winter wheat)

Rules: `backend/app/domain/septoria.py`; thresholds: `config/septoria.toml`; specification: [curated layer contract](curated_layer_contract.md).
Assessed for every crop area and local day.

**Wet hours.** An hour is wet when relative humidity is at least 85 % or precipitation is above 0.2 mm. A missing value never
makes an hour dry by default.

**Risk class.** `H` is the longest run of consecutive wet hours in the 72 hours that end at the last hour of the day.

| Class | Rule | Origin |
| --- | --- | --- |
| high | H ≥ 20 h | literature (SPOT-IT) |
| medium | H ≥ 10 h | team assumption |
| low | otherwise | |

`risk_index` places a day on a 0 to 1 scale for the map: 0 at no wet hours, 0.5 at the medium threshold and 1 at the high
threshold and above.

**Growth stage.** Septoria is assessed in BBCH 30–59. The stage is estimated from degree days (base 3 °C) since the vegetation
resumed (the first 5 days in a row with a mean of at least 3 °C after 1 February): zone A below 160 °C·day, B up to 510, C above.
A farmer's BBCH entry overrides the estimate; without an estimate the calendar window 1 April to 30 June is used.

**Status**, first match wins:

| Status | Meaning |
| --- | --- |
| `stage_unknown` | not winter wheat, or the stage cannot be judged |
| `out_of_window` | outside the susceptible stage |
| `protected` | a recorded spray still protects the crop (10 days by default, the farmer's value otherwise) |
| `insufficient_data` | less than 80 % of the hours have data (assumption), or a long gap could change the class |
| `uncertain` | missing hours (a gap of up to 4 h) could move H across a threshold |
| `ok` | the class is definite |

A day without a definite class is never shown as low risk.

**Signal.** `conditions_met` is true when the status is `ok`, the class is `high` and the growth zone is B or C. This flag is the
input of the spray window.

Measured on 2024 data (Mazowieckie, April to June), the high class occurs on about 1 % of cell-days, so a signal is rare by design.

## Spray window

Rules: `backend/app/domain/spray_window.py`; limits: `config/spray_window.toml`; endpoints: [API](api.md#spray-window).
Computed on request and never stored.

1. **Signal.** Without `conditions_met` for today no window is proposed (`no_signal`), and the answer says why: `protected`,
   `risk_not_high`, `out_of_window`, `zone_not_b_or_c` and so on.
2. **Hours.** Each of the next 72 hours of the crop area's grid cell is checked:

   | Condition | Limit | Origin |
   | --- | --- | --- |
   | mean wind at 10 m | ≤ 4 m/s | regulation (Dz.U. 2026 poz. 353, from 1 April 2026) |
   | gusts | ≤ 6 m/s (wind limit + 2) | team assumption |
   | temperature | 5–25 °C | team assumption |
   | precipitation | ≤ 0.2 mm per hour | team assumption |

   A missing value makes the hour unknown, never good. The farmer's working hours (`work_from`, `work_to`) can only exclude hours.
3. **Windows.** A window is a run of at least 4 good hours (2 h to spray and 2 h without rain after it). Up to three are returned:
   those with at least 1 m/s of margin below the wind limit first (`confident`, otherwise `borderline`), then the earlier one.
   `latest_start` is the end of the window minus the 2 rain-free hours. A window starting 48 h or more ahead is `indicative`.
4. **Status:** `no_signal`, `no_forecast` (no weather for the hours), `window_now`, `window_later` or `no_window`.

## Limits of the prototype

- **Replay, not a forecast.** The "forecast" is the real weather of the following hours in 2024, so windows look better than a
  real forecast would make them. Every spray window answer says so (`notes.source = "replay"`).
- **Wind height.** Wind is taken at 10 m; the boom works lower, and no correction is made.
- **No product check.** The tool does not check the product, its label or its approval for the crop; that remains the farmer's
  responsibility, and every answer carries this disclaimer.
- **One crop and disease.** Other diseases (white mould of soybean, leaf spot of maize, NCLB) are configured but disabled.
- **Nearest cell.** A crop area takes the weather of the grid cell nearest to its centroid, with no interpolation.
