> **GeoEarth Junction project:** See [PROJECT.md](PROJECT.md) for our product requirements, first iteration, team and open decisions. The merged bridge setup and its current limitations are in [README2.md](README2.md). The organizer materials below are retained for reference.

# field-under-pressure-materials

Near-real-time crop risk map · [Field Under Pressure](https://geo-hackathon.g.location360.ag/)

**When / where:** 20-22 Nov 2026 · University of Warsaw, Faculty of Geology, detailed schedule on the website.

**What you will build:**
- weather-driven risk detection
- crop disease & pest detection
- yield & soil analytics
- output as a platform / dashboard

**Data and source documentation for the hackathon**

The hackathon datasets are hosted in S3 cloud storage. Links will be provided short before the event and will expire after the event.

**No AWS account is required.**

---

## Getting started

This repo is both the **materials hub** and a **starting point for your team’s work**. Clone it, keep organizer docs as-is, and build your prototype here (or in a fork).

1. **Clone the repo** (one shared repo per team).
   ```bash
   git clone https://github.com/Bayer-Group/field-under-pressure-materials.git
   cd field-under-pressure-materials
   ```
2. **Create your team’s branch** and do all work there (do not commit on `main`):
   ```bash
   git checkout -b team/<your-team-name>
   ```
3. **Create a Python environment** (3.10+) and install starters:
   ```bash
   python -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
4. **Skim the challenge** on the [event site](https://geo-hackathon.g.location360.ag/). Full brief + agenda at the opening ceremony.
5. **Pick a track** and fill in [`templates/TEAM_README.md`](templates/TEAM_README.md) (team, one-liner, scope, data checklist).
6. **Read the data docs** in [`data/`](data/) — choose only the AOIs / sources you need (disk space adds up).
7. **Download data** when organizers share links (see [How to get the data](#how-to-get-the-data)). Keep large files **outside git** (ignored by `.gitignore`) or on a shared drive / cloud.
8. **Run a starter notebook** under [`notebooks/`](notebooks/) (e.g. Sentinel-2 Earth Search) to confirm your setup.
9. **Work in the cloud if you prefer** (Colab, Kaggle, Codespaces, or Google Earth Engine with a personal account) — same idea: don’t commit big downloads; document paths in the team README.
10. **Commit code and docs only** — not Parquet/GeoTIFF dumps, `.env`, or credentials.
11. **When your work is ready, push your team branch to origin:**
    ```bash
    git push -u origin team/<your-team-name>
    ```
12. **Before Sunday submission:** update the team README with how to run your demo and what to show.

> More challenge detail at kickoff. Questions on data links → organizers.

## How to get the data

Depending on your planned work and your goal you can work locally or in a cloud.

**Local work:**

1. Use the download links shared by the organizers.
2. Download each needed package locally (or into your team’s shared drive, cloud storage).
3. Work from the local copy.

   **Note:** Due to the amount of data make sure you have enough space for the datasets needed. Choose and download AOI datasets.

**Cloud work:**

If you consider cloud work with bigger datasets or with additional datasets available in the cloud, you may review the following solutions.
 
| Platform	| Best For	| Key Perks & Verification |
|-----------|-----------|--------------------------|
| Google Colab |	Training models and running Python notebooks	| Gives free access to cloud GPUs and TPUs in your browser. Works with any regular Google account, so no special .edu email verification is needed. |
| Hugging Face Spaces |	Hosting live AI demos and class projects	| Lets you host interactive machine learning web apps using Gradio or Streamlit for free. Gives your class project a shareable public URL without managing servers. |
| Kaggle Notebooks |	Data science projects and heavy datasets	| Provides up to 30 hours per week of free GPU quota and pre-installed AI libraries. Requires only a standard account and phone verification. |
| GitHub Student Developer Pack |	Unlocking extra AI and hosting credits	| Unlocks free access to GitHub Codespaces, Copilot, and partner cloud credits. Accepts custom school emails when you upload a photo of your student ID or enrollment proof. |


### Data formats

You will find different data formats. You should be familiar with most of them.
Please check however if you know how to work with .parquet files. Additionally, some datasets have H3 index assigned (level 10). If you haven't worked with H3 indexes we encourage you to learn about the solution.

More details in the datasets documentation.

### After download

```bash
# Example: inspect a Parquet file (Python)
# pip install pyarrow pandas
python -c "import pandas as pd; print(pd.read_parquet('Dolnośląskie_daily_2020.parquet').head())"
```

## Dataset overview

You will find the information in the data [README.md](data/README.md)

## Datasets in detail

You will find the details in the [data directory](data)

## Licensing & usage

1. Data is for hackathon use only unless stated otherwise.
2. Download via the provided links only; links expire after the event.
3. Cite sources as listed in each dataset section.

## Tools usage

1. Some tools and platforms are suggested as examples. 
2. The students need to make sure that they are using tools according to the respective agreements.
