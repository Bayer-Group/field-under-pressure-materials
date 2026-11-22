# SatOps — Field Under Pressure

**Track:** Weather risk | Disease & pest | Yield & soil | Platform / dashboard  
**Event:** [Field Under Pressure](https://geo-hackathon.g.location360.ag/) · 20–22 Nov 2026

## Team
| Name | Role | Contact |
|------|------|---------|
| Natalia Ławreszuk | Team Leader; Product Manager | tashy444 |
| Bartosz Krzyczkowski | Geospatial Analyst | mleczu |
| Krzysztof Wroniak | Soil and Meteorological Data Analyst | Cr0wek |
| Jakub Załuga | EO Data Engineer | kuba_zezolek |
| Mateusz Woźniak | Full-Stack Developer | mateusz2180 |

## One-liner
What grower decision does this help? (spray / treat / harvest / wait)
A tool that helps farmers optimize fertilizer application, reducing costs and improving efficiency.

## Problem & scope
- Focus area (crop, region, risk type): Winter wheat and maize Łowicz (łódzkie, PL); risk: nitrogen applied at the wrong time or rate
- In scope for the weekend: Lizmap field map with farmer login; Sentinel-2 NDVI/NDMI + 7 days forecast; soil profile per field; 7-days fertilization calender; management zones with variable N rates; RX exporter (Shapefile for FieldView, ISO-XML for ISOBUS); spray windows and disease risk; cost estimate; Telegram alerts
- Explicitly out of scope: automatic field segmentation; yield prediction; live tractor telemetry; full-season N budget.

## Data we use
- [x] Weather
- [x] Satellite (Sentinel-2 / …)
- [x] Soil
- [x] Cropland
- Notes / paths (local only — do not commit large files):
We decided to not put the whole system to github because our infrastructure is based on web client.

- What to show (1–2 screens / maps):
  1. Farmer map (Lizmap): fields coloured by today's fertilization status (go / caution / stop). Clicking a field opens a popup with the NDVI history and 7-day LSTM forecast, soil profile, the 7-day calendar with reasons, the recommended fertilizer, and spray-window and disease tiles.
  2. Variable-rate prescription for the machine: the field split into management zones with N rates (kg/ha) and a simulated tractor pass with fuel and fertilizer cost. The prescription exports in one click to:
     - an Rx Shapefile (zip, EPSG:4326, rate per zone) that can be imported into Climate FieldView and most terminals (John Deere, Trimble, Raven, Topcon);
     - ISO-XML TASKDATA (ISO 11783-10, grid prescription) for any ISOBUS terminal and spreader controller, loaded from a USB stick.
     
<img width="1902" height="907" alt="image" src="https://github.com/user-attachments/assets/bbaaf22e-dd74-4f97-b14f-70eab42a8562" />
<img width="1907" height="913" alt="image" src="https://github.com/user-attachments/assets/48fee9f6-d435-47bd-af30-7cd68eccbd2e" />



- Known limits / next steps:
  - Basemap ≠ analysis year: the background orthophoto (Esri / GUGiK) dates from June 2019. No weather or crop-type data were provided for 2019, so the NDVI charts, forecasts and calendar are computed for 2024. What the farmer sees on the image does not always match the charts (e.g. a different crop on the strip). A 2025 GUGiK orthophoto exists and could be used once the data are aligned to one year.
  - Field boundaries: automatic segmentation ran without Sentinel-1 radar data, which we did not receive. With optical imagery alone the boundaries were poor, so the demo farmer's fields were drawn by hand.
  - Rules and thresholds (fertilization calendar, disease wetness hours, spray window) are expert-based and not yet validated on farm records or yield data. There is no yield or ROI model, and the tractor pass is simulated.
  - The Rx files follow the published formats but have not been tested on a physical terminal.
  - Next: align basemap and data to the same season, add radar to segmentation, calibrate on farm trials, build a full-season N budget plus P/K/S, use live weather and imagery, and upload Rx directly through the FieldView / ISOBUS-TC APIs.
