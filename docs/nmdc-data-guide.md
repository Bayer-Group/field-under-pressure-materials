# NMDC cropland metagenomes: data guide (KONA & STER)

What the files pulled by [`scripts/pull_nmdc_cropland.py`](../scripts/pull_nmdc_cropland.py) contain, how to interpret and use them, and how the two cropland sites differ.

*Profiled on 2026-11-21 over the 170 samples with processed outputs (KONA 51, STER 119; 183 biosamples total, 13 STER samples have metadata only). Figures are medians per sample unless stated.*

**The key finding:** the two farms differ more in **how they were sequenced** than in their biology. Normalise for depth and batch before comparing them.

---

## 1. Layout and file formats

```
data/nmdc/
  samples.csv           one row per biosample: soil chemistry, location, date
  data_objects.csv      every NMDC file linked to each sample (incl. raw reads, BAMs, MAGs not downloaded) + URL
  files/<SITE>/<sample name>/
      kraken2_report.tsv  gottcha2_report_full.tsv  centrifuge_report.tsv
      ko.tsv  ec.tsv  qc_filterStats.txt  annotation_stats.tsv
```

A sample name such as `KONA_001-M-16-31.5-20190619` breaks down as plot `KONA_001`, **M**ineral horizon, core depth 16–31.5 cm, collected 2019-06-19. Each metagenome is a **composite of 3 soil cores from one plot**.

| File | Shape | What it means | Practical use |
|---|---|---|---|
| `kraken2_report.tsv` | Tree, ~5–9k rows, no header. Columns: % reads in clade, reads in clade, reads assigned exactly here, rank code (U/R/D/P/C/O/F/G/S, with suffixes such as `S1` for sub-ranks), NCBI taxID, indented name | Read-based taxonomy at every rank | **Main taxonomy table.** Filter rank `G` or `P` and use column 2 (clade reads). |
| `gottcha2_report_full.tsv` | Long table with header: `LEVEL, NAME, TAXID, READ_COUNT, …, REL_ABUNDANCE, …` | Conservative, signature-based classifier with low false positives | High-confidence check. Mostly empty for shallow samples. |
| `centrifuge_report.tsv` | Flat table with header: `name, taxID, taxRank, genomeSize, numReads, numUniqueReads, abundance` (~4–5k rows) | A third read classifier | Cross-check Kraken2 hits. |
| `ko.tsv` | **One row per predicted gene**, no header. Columns: gene ID, IMG gene OID, `KO:Kxxxxx`, % identity, query start/end, subject start/end, e-value, bit score, alignment length | KEGG Orthology assignment of assembled genes | Count rows per KO to get a function profile. |
| `ec.tsv` | Same layout, with `EC:x.x.x.x` (a gene can have several rows) | Enzyme Commission numbers | Same as KO, alternative vocabulary. |
| `qc_filterStats.txt` | `key=value` lines | Read QC in/out | `outputReads` / `outputBases` = **sequencing depth**. Use for normalisation and filtering. |
| `annotation_stats.tsv` | Text report | Assembly size (`final_fasta`), genes predicted per method | How much of the sample assembled into genes. |
| `samples.csv` | 183 rows × 28 columns: id, name, site, plot, horizon, depth, date, lat/lon, elev, `ph`, `temp_c`, `water_content_g_per_g`, `org_carb_pct`, `nitro_pct`, `carb_nitro_ratio`, … , `has_kraken2`, `has_ko` | Environmental side of the join | Join key: `name` = folder name. |

### Interpretation caveats

- **~90 % of reads are unclassified by Kraken2** (87–94 %). Report taxa as *% of classified reads*, never as % of the community.
- **Fungi are absent from the taxonomy outputs.** *Fusarium*, *Rhizoctonia*, *Verticillium*, *Trichoderma* and *Pythium* are 0.000 % in every sample. That is a reference-database gap, not real absence. **Fungal disease signals must come from NEON ITS data** (`DP1.10081.002` / `DP1.10108.001`), not from these files.
- KO/EC tables describe only **assembled** genes. Their size depends heavily on depth: shallow samples assemble poorly, so most of their genes are never annotated.

## 2. How to use it in practice

1. **QC filter.** Drop samples with less than ~0.5 M output reads or less than ~10k classified Kraken2 reads. For example, one KONA 2017 sample has ~2k reads.
2. **Taxonomy matrix.** Take rank-`G` rows from each `kraken2_report.tsv` (column 2), giving samples × genera counts (~600–1,200 genera per sample). Convert to relative abundance within classified reads, then CLR (or another log-ratio) for modelling.
3. **Function matrix.** Count rows per KO in `ko.tsv`, giving samples × KO. Normalise by total annotated genes (e.g. per 10k genes). Useful markers:

   | Gene | KO | Process |
   |---|---|---|
   | amoA | K10944 | nitrification |
   | nifH | K02588 | N fixation |
   | nirK | K00368 | denitrification |
   | nirS | K15864 | denitrification |
   | norB | K04561 | denitrification |
   | nosZ | K00376 | N₂O reduction |
   | narG | K00370 | nitrate reduction |
   | ureC | K01428 | urease |
   | phoD | K01113 | P mineralisation |

4. **Join environment** from `samples.csv` on `name`. For gaps (see §3), add NEON `DP1.10086.001` core-level chemistry on plot + collection date.
5. **Control for batch.** Always carry sequencing depth and batch (site × year) as covariates. **Rarefy or subsample to equal depth** before comparing diversity or "number of genera/KOs" across samples.
6. For comparisons between years, use only the **June–August** samples. STER 2013–14 includes December and March samples.

## 3. KONA vs STER

### Sequencing: the dominant difference

| | KONA | STER |
|---|---|---|
| Bouts | 2 (2017-08, 2019-06) | 7 (2013-06, 2013-12, 2014-03, 2014-06, 2016-08, 2017-06, 2022-06) |
| Plots | 10 (7 sampled in both years) | 17 (7 plots in 3–4 years) |
| Output reads / sample | **3.0 M** (2017: 4.2 M, 2019: 2.0 M) | **19 M** overall: 2013–14 ~23 M, 2016 3.8 M, 2017 8.3 M, **2022 140 M** |
| Read length | 135–143 bp, single provider (BMI) | **101 bp in 2013–14** (pilot-era runs, different file naming), ~150 bp later (BMI) |
| Assembly size | 1.2 Mbp | 7.3 Mbp overall; **709 Mbp in 2022** |
| KO-annotated genes | ~850 | ~8,300; **~764,000 in 2022** |
| Distinct KOs | 553 | 1,987 (2022: 6,174) |
| GOTTCHA2 species | **0–1** (effectively empty) | 10 (2022: 214) |
| Kraken2 genera (≥10 reads) | 672 | 980 (2022: 1,214) |
| Kraken2 unclassified | 92 % | 91 % |

What this means:
- **KONA is shallow.** Its Kraken2 taxonomy is usable, but its function profiles are sparse. amoA is detected in only 22 % of KONA samples vs 88 % at STER, almost certainly a depth effect.
- **STER 2022 is 30–70× deeper than other batches.** Richness-type metrics will show a spurious 2022 "jump" unless you subsample.
- **STER 2013–14 is a distinct batch** (101 bp reads, mixed seasons, soil temperature down to 1 °C).

### Environment

| | KONA (eastern Kansas) | STER (northeastern Colorado, dryland) |
|---|---|---|
| Elevation | 330 m | 1,360 m |
| pH | 6.4 (5.0–7.1) | 7.1 (6.1–8.5) |
| Water content (g/g) | 0.24 | **0.15** |
| Organic C | 1.27 % (2019 only) | 0.88 % (2017, 2022) |
| N, C:N | 2019 only (C:N ~9.8) | **not provided by NMDC** |
| pH / moisture coverage | all samples | missing for 2013 and half of 2014 |

### Biology (% of classified reads, comparable after normalisation)

- **Phyla:** STER is Actinobacteria-leaning (50 % vs 39 %); KONA is Proteobacteria-leaning (45 % vs 38 %). That fits STER's drier, more alkaline soil. KONA's 2.7 % "Chordata" reads are probably host/human contamination, inflated in shallow libraries.
- **Genera:** the sites are very similar.

  | Genus | KONA | STER |
  |---|---|---|
  | *Streptomyces* | 7.3 % | 9.0 % |
  | *Bradyrhizobium* | 5.0 % | 5.4 % |
  | *Pseudomonas* | 1.7 % | 1.5 % |
  | *Ralstonia* | 0.23 % | 0.16 % |
  | *Nitrospira* | 0.15 % | 0.11 % |

- **Functions (per 10k annotated genes):** KONA has higher phoD (5.1 vs 3.9). STER has higher amoA (1.6 vs 0) and ureC (2.0 vs 0). Treat these as hints only, given KONA's depth.

## 4. Bottom line

- The **samples × genus taxonomy** (Kraken2, normalised, failed samples dropped) is the only layer comparable across both farms and all years.
- **Function comparisons** hold only within well-sequenced batches: STER 2017 and 2022, and partly 2013–14.
- **Fungal pathogen questions** need NEON ITS data. Soil **N/C:N gaps** need NEON `DP1.10086.001`.
