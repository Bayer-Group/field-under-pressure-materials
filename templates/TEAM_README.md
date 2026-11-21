# [Team name] — Field Under Pressure

**Track:** Weather risk | Disease & pest | Yield & soil | Platform / dashboard  
**Event:** [Field Under Pressure](https://geo-hackathon.g.location360.ag/) · 20–22 Nov 2026

## Team
| Name | Role | Contact |
|------|------|---------|
|      |      |         |

## One-liner
What grower decision does this help? (spray / treat / harvest / wait)

## Problem & scope
- Focus area (crop, region, risk type):
- In scope for the weekend:
- Explicitly out of scope:

## Data we use
- [ ] Weather
- [ ] Satellite (Sentinel-2 / …)
- [ ] Soil
- [ ] Cropland
- Notes / paths (local only — do not commit large files):

## How to run
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# put downloaded data somewhere local, then set path below or in a .env
jupyter notebook notebooks/
```

## Set up Git hooks

Run these commands from the repository root in your Python environment after cloning.

```bash
python -m pip install pre-commit
python -m pre_commit install --install-hooks
```

Ruff checks Python files and notebooks before each commit. The `commit-msg` hook checks Conventional Commits messages such as `chore(git): ignore local W&B logs`.

Run `python -m pre_commit run ruff-check --all-files` to check the repository before committing.

## Demo notes (Sunday)
- What to show (1–2 screens / maps):
- Key result / insight:
- Known limits / next steps:

## Links
- Repo:
- Slides / recording (if any):
