"""Soil-functions routes of the GUI API on a tiny synthetic dataset: no network, no real data.
Each sample is read on its own; only the KEGG-module cards compare it with other well-sequenced samples."""
import datetime as dt

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from cropfit import api, funguild, microbe_roles
from cropfit.api_functions import AGREEMENT_TEXT, CARRIER_TERMS, Measured, _agreement, _cards, _pathways


@pytest.fixture
def client(tmp_path, monkeypatch):
    proc = tmp_path / "data" / "processed"
    proc.mkdir(parents=True)
    monkeypatch.setattr(api, "PROCESSED", proc)
    pd.DataFrame([dict(plotID="P_001", site="P", lat=39.2, lon=-96.6, half_m=20.0)]).to_parquet(proc / "plot_geometry.parquet")
    pd.DataFrame([dict(metagenome_key="nmdc:dobj-a", site="P", plotID="P_001", date="2022-06-06", n_ko_genes=800_000,
                       ko_depth_ok=True),
                  dict(metagenome_key="nmdc:dobj-s", site="P", plotID="P_001", date="2017-06-05", n_ko_genes=900,
                       ko_depth_ok=False)]).to_parquet(proc / "metagenomes.parquet")
    genes = {"narG/nxrA": 300, "nirK": 200, "norB": 120, "nosZ": 20, "nrfA": 10, "pmoA-amoA": 40, "hao": 10,
             "narH/nxrB": 50, "nifH": 2, "ureC": 100, "phoD": 60, "gcd": 40, "acdS": 30, "phlD": 0, "pcoC/copC": 8,
             "cusA": 30}
    group = {"narG/nxrA": "denitrification", "nirK": "denitrification", "norB": "denitrification", "nosZ": "nosZ",
             "nrfA": "dnra", "pmoA-amoA": "nitrification", "hao": "nitrification", "narH/nxrB": "nitrification",
             "nifH": "n_fixation", "ureC": "urease", "phoD": "p_mobilisation", "gcd": "p_mobilisation", "acdS": "acdS",
             "phlD": "phlD", "pcoC/copC": "copper_resistance", "cusA": "copper_resistance"}
    rows = [dict(metagenome_key="nmdc:dobj-a", ko="K0", gene=g, function_group=group[g], count=n, per_genome_eq=n / 500,
                 per_million=0.0) for g, n in genes.items()]
    rows += [dict(metagenome_key="nmdc:dobj-s", ko="K0", gene="nirK", function_group="denitrification", count=1,
                  per_genome_eq=0.1, per_million=0.0)]
    pd.DataFrame(rows).to_parquet(proc / "ko_panel.parquet")
    pd.DataFrame([dict(plotID="P_001", collectDate=dt.date(2022, 6, 8), ammonium_n_mgkg=4.0, nitrate_n_mgkg=15.0,
                       n_cores=3, net_n_min_mgkg_d=-0.3, net_nitrif_mgkg_d=-0.1, n_pairs=3, site="P")]
                 ).to_parquet(proc / "neon_inorganic_n.parquet")
    pd.DataFrame([dict(plotID="P_001", collectDate=dt.date(2022, 6, 6), organic_c_pct=1.2, total_n_pct=0.1,
                       cn_ratio=12.0, ph_water=7.2, ph_cacl2=6.8, soil_moisture=0.1, n_cores=3, site="P")]
                 ).to_parquet(proc / "neon_chem.parquet")
    F = lambda key, genus, pct: dict(metagenome_key=key, genus=genus, rel_abund_pct=pct)  # noqa: E731
    pd.DataFrame([F("nmdc:dobj-a", "Mortierella", 40.0), F("nmdc:dobj-a", "Fusarium", 30.0),
                  F("nmdc:dobj-a", "Trichoderma", 10.0), F("nmdc:dobj-a", "Glomus", 0.2),
                  F("nmdc:dobj-a", "unclassified_Fungi", 19.8),
                  F("nmdc:dobj-s", "Mortierella", 60.0), F("nmdc:dobj-s", "Fusarium", 40.0)]
                 ).to_parquet(proc / "joined_fungi_genus.parquet")
    G = lambda genus, cat, path, para: dict(genus=genus, trophic_mode="", guilds="", primary_guild="", category=cat,  # noqa: E731
                                            can_be_plant_pathogen=path, can_parasitise_fungi=para, confidence="Probable")
    pd.DataFrame([G("Mortierella", "saprotroph", False, False), G("Fusarium", "plant_pathogen", True, False),
                  G("Trichoderma", "fungal_parasite", True, True), G("Glomus", "arbuscular_mycorrhizal", False, False)]
                 ).to_parquet(proc / "fungal_guilds.parquet")
    return TestClient(api.create_app())


def test_samples_of_a_plot(client):
    s = client.get("/api/plots/P_001/functions").json()
    assert [(x["sample_id"], x["deep_enough"]) for x in s] == [("mg-dobj-s", False), ("mg-dobj-a", True)]
    assert client.get("/api/plots/NOPE/functions").status_code == 404
    assert client.get("/api/functions/mg-nope").status_code == 404


def test_profile_reads_the_sample_on_its_own(client):
    p = client.get("/api/functions/mg-dobj-a").json()
    def keys(x):
        if isinstance(x, dict):
            return set(x) | set().union(*(keys(v) for v in x.values()))
        return set().union(*(keys(v) for v in x)) if isinstance(x, list) else set()
    assert not keys(p) & {"percentile", "relative", "reference", "ref_min", "ref_median", "ref_max",
                          "n2o_ratio_percentile"}                       # no ranking without the module tables
    den = next(x for x in p["pathways"] if x["kegg_module"] == "M00529")
    assert den["complete"] and [s["copies"] for s in den["steps"]] == [300, 200, 120, 20]
    fix = next(x for x in p["pathways"] if x["kegg_module"] == "M00175")
    assert fix["steps"][0]["status"] == "trace"                               # 2 copies < MIN_COUNT
    cards = {c["card"]: c for c in p["cards"]}
    n = cards["nitrogen"]
    assert "full denitrification pathway" in n["finding"] and "No nitrogen fixation" in n["finding"]
    assert any(i["kind"] == "risk" and "About 6 genes that make N2O" in i["text"] for i in n["implications"])
    assert any("pH 7.2" in i["text"] and "ammonia" in i["text"] for i in n["implications"])   # urea at pH >= 7
    assert p["measured"]["soil_moisture"] == 0.1


def test_fungal_roles_from_the_same_cores(client):
    p = client.get("/api/functions/mg-dobj-a").json()
    f = p["fungi"]
    assert f["same_cores"] and f["named_pct"] == pytest.approx(80.2)
    roles = {r["role"]: r for r in f["roles"]}
    assert roles["saprotroph"]["pct"] == pytest.approx(49.9, abs=0.1)        # 40 of the 80.2 named
    assert sum(r["pct"] for r in f["roles"]) == pytest.approx(100, abs=0.2)
    card = next(c for c in p["cards"] if c["card"] == "fungi")
    assert "<1% from mycorrhizal fungi" in card["finding"]
    assert any("Fusarium" in i["text"] for i in card["implications"] if i["kind"] == "risk")
    assert any("Trichoderma" in i["text"] for i in card["implications"] if i["kind"] == "upside")


def test_shallow_sample_keeps_measured_and_fungal_cards(client):
    p = client.get("/api/functions/mg-dobj-s").json()
    cards = {c["card"]: c for c in p["cards"]}
    assert not p["deep_enough"] and p["notes"][0].startswith("Too few genes")
    assert cards["nitrogen"]["status"] == "unknown" and cards["nitrogen"]["headline"] == "Too few genes to tell"
    assert cards["fungi"]["status"] == "notice"                               # fungi do not depend on gene depth
    assert "Fusarium alone is 40% of fungal DNA" in cards["fungi"]["flag"]
    assert cards["n_now"]["status"] == "unknown"                              # no NEON visit within a week of 2017
    assert all(s["status"] == "too_few_genes" for s in p["pathways"][0]["steps"][2:])


def test_cards_are_ranked_by_confidence(client):
    cards = client.get("/api/functions/mg-dobj-a").json()["cards"]
    rank = [(c["status"] == "unknown", {"high": 0, "medium": 1, "low": 2}[c["confidence"]]) for c in cards]
    assert rank == sorted(rank) and cards[0]["basis"] == "measured"


def test_nitrate_thresholds():
    m = lambda no3: Measured(date=dt.date(2022, 6, 6), ammonium_n_mgkg=1.0, nitrate_n_mgkg=no3, net_n_min_mgkg_d=None,  # noqa: E731
                             net_nitrif_mgkg_d=None, ph_water=None, organic_c_pct=None, total_n_pct=None,
                             cn_ratio=None, soil_moisture=None)
    status = lambda no3: next(c.status for c in _cards({}, _pathways({}, False), None, m(no3), False, pd.DataFrame())  # noqa: E731
                              if c.card == "n_now")
    assert (status(30), status(15), status(5)) == ("good", "watch", "act")


def test_funguild_primary_guild_and_category():
    assert funguild.primary_guild("Endophyte-|Plant Pathogen|-Plant Saprotroph") == "Plant Pathogen"
    assert funguild.primary_guild("Arbuscular Mycorrhizal") == "Arbuscular Mycorrhizal"
    assert funguild.primary_guild("") is None
    assert funguild.category("Undefined Saprotroph") == "saprotroph"
    assert funguild.category("Arbuscular Mycorrhizal") == "arbuscular_mycorrhizal"
    assert funguild.category(None) == "unknown"
    recs = pd.DataFrame([dict(taxon="Fusarium", taxonomicLevel="13", trophicMode="Pathotroph",
                              guild="Endophyte-|Plant Pathogen|", confidenceRanking="Possible"),
                         dict(taxon="Trichoderma", taxonomicLevel="13", trophicMode="Pathotroph",
                              guild="|Fungal Parasite|-Plant Pathogen", confidenceRanking="Probable"),
                         dict(taxon="Fusarium oxysporum", taxonomicLevel="20", trophicMode="Pathotroph",
                              guild="|Plant Pathogen|", confidenceRanking="Probable")])
    t = funguild.guild_table(recs).set_index("genus")
    assert list(t.index) == ["Fusarium", "Trichoderma"]                       # genus level only
    assert t.loc["Trichoderma", "can_parasitise_fungi"] and t.loc["Trichoderma", "can_be_plant_pathogen"]


def test_cards_are_coloured_only_by_stated_rules(client):
    cards = {c["card"]: c for c in client.get("/api/functions/mg-dobj-a").json()["cards"]}
    assert all(c["headline"] for c in cards.values())
    assert cards["nitrogen"]["status"] == "info" and cards["nitrogen"]["flag"] is None     # norB:nosZ = 6 < 10
    assert cards["fungi"]["status"] == "notice"                               # Fusarium 30 of 80.2 named = 37%
    assert cards["soil"]["status"] == "info"                                  # pH 7.2, organic carbon 1.2%: no risk band
    assert {c["status"] for k, c in cards.items() if k in ("p_release", "copper", "root_health")} == {"info"}


def test_nitrogen_card_flags_missing_n2o_removal():
    copies = {"narG/nxrA": 50, "nirK": 40, "norB": 30, "nosZ": 0}
    card = next(c for c in _cards(copies, _pathways(copies, True), None, None, True, pd.DataFrame())
                if c.card == "nitrogen")
    assert card.status == "notice" and "no N2O-removing gene" in card.flag


# ---------------------------------------------------------------- named carriers (docs/microbe_roles.md 6.3)
@pytest.fixture
def with_names(client, role_files):
    """The functions fixture plus a Kraken2 genus table for the same metagenome (the roles fixture genera)."""
    L = lambda rank, name, phylum, reads: dict(metagenome_key="nmdc:dobj-a", rank=rank, name=name, domain="Bacteria",  # noqa: E731
                                               phylum=phylum, reads=reads)
    pd.DataFrame([L("domain", "Bacteria", None, 90_000), L("domain", "Archaea", None, 10_000),
                  L("genus", "Streptomyces", "Actinobacteria", 20_000), L("genus", "Bradyrhizobium", "Proteobacteria", 10_000),
                  L("genus", "Nitrososphaera", "Thaumarchaeota", 5_000)]).to_parquet(api.PROCESSED / "taxa_lineage.parquet")
    return client


def test_no_carriers_without_taxa_lineage(client):
    p = client.get("/api/functions/mg-dobj-a").json()
    assert p["carriers"] == [] and not any(c["card"] == "bacteria_pathogens" for c in p["cards"])
    assert all(g["term_id"] is not None for g in p["groups"] if g["group"] in ("phlD", "hcnA", "nosZ"))
    assert next(g for g in p["groups"] if g["group"] == "urease")["term_id"] is None
    assert {x["name"]: x["term_id"] for x in p["pathways"]}["Urea breakdown"] is None
    assert {x["name"]: x["term_id"] for x in p["pathways"]}["Denitrification"] == "denitrification"
    assert {r["role"]: (r["label"], r["term_id"]) for r in p["fungi"]["roles"]}["saprotroph"] == ("Decomposers", "decomposer")
    cards = {c["card"]: c for c in p["cards"]}
    assert cards["nitrogen"]["carrier_terms"] == ["n_fixation", "nitrification", "denitrification", "nosZ", "dnra"]
    assert cards["p_release"]["carrier_terms"] == ["p_mobilisation"] and cards["fungi"]["carrier_terms"] == []


def test_carriers_next_to_genes(with_names):
    p = with_names.get("/api/functions/mg-dobj-a").json()
    assert [c["term_id"] for c in p["carriers"]] == CARRIER_TERMS
    c = {x["term_id"]: x for x in p["carriers"]}
    fix = c["n_fixation"]                                       # nifH 2 copies: trace; Bradyrhizobium 10%
    assert (fix["genes"], fix["agreement"], fix["pct"], fix["label"]) == ("trace", "both", 10.0, "Nitrogen fixers")
    assert fix["top"][0]["name"] == "Bradyrhizobium" and fix["top"][0]["term_id"] == "legume_symbiont"
    assert fix["top"][0]["pct"] == 10.0 and fix["agreement_text"].startswith("Only a trace of the genes")  # not "found"
    assert c["nitrification"]["agreement"] == "both" and c["nitrification"]["top"][0]["name"] == "Nitrososphaera"
    assert c["denitrification"]["agreement"] == "genes_only" and c["denitrification"]["top"] == []   # Bradyrhizobium's row is low
    assert c["chitinase"]["genes"] == "not_found" and c["chitinase"]["agreement"] == "neither"
    ab = c["antibiotic_producer"]                               # phlD 0, hcnA missing: not found, yet Streptomyces is named
    assert ab["agreement"] == "names_only" and ab["agreement_text"].endswith("cover only some antimicrobial producers.")
    assert ab["ko_groups"] == ["phlD", "hcnA"] and ab["top"][0]["species_examples"] == ["Streptomyces griseus"]
    assert ab["top"][0]["description"].startswith("Thread-forming")
    assert any(n.startswith("Who may carry it:") for n in p["notes"])
    assert next(g for g in p["groups"] if g["group"] == "phlD")["term_id"] == "antibiotic_producer"


def test_stub_cards_keep_their_carrier_terms(with_names):
    cards = {c["card"]: c for c in with_names.get("/api/functions/mg-dobj-s").json()["cards"]}
    assert cards["root_health"]["carrier_terms"] == ["antibiotic_producer", "acdS", "chitinase"]
    assert cards["root_health"]["headline"] == "Too few genes to tell"


def test_agreement_table_has_one_case_per_value():
    assert _agreement("nosZ", "found", 0.5)[0] == "both" and _agreement("nosZ", "trace", 0.5)[0] == "both"
    assert _agreement("nosZ", "found", 0.05)[0] == "genes_only" and _agreement("nosZ", "found", 0.1)[0] == "both"
    assert _agreement("nosZ", "not_found", 0.5)[0] == "names_only"
    assert _agreement("nosZ", "not_found", 0.0)[0] == "neither"
    assert _agreement("nosZ", "too_few_genes", 5.0) == ("unknown", "Too few genes to compare with the named carriers.")
    assert _agreement("antibiotic_producer", "not_found", 0.0)[1].startswith(AGREEMENT_TEXT["neither"] + " The marker")


# ---------------------------------------------------------------- bacteria that include plant pathogens
def roll(*rows_, **pct):
    ann = pd.DataFrame([dict(domain="Bacteria", genus=g, term_id="root_soilborne_pathogen", confidence="high",
                             evidence=ev, source="llm:test", species_examples=sp, note="") for g, ev, sp in rows_],
                       columns=microbe_roles.ANNOTATION_COLUMNS)
    t = pd.DataFrame([dict(name=n, phylum=None, pct=p, reads=int(p * 1000)) for n, p in pct.items()])
    return microbe_roles.roll_up(t, "bacteria", ann=ann, descriptions={})


def pathogen_card(ru, reads=100_000):
    return next(c for c in _cards({}, _pathways({}, False), None, None, False, pd.DataFrame(), ru, reads)
                if c.card == "bacteria_pathogens")


def test_bacteria_pathogen_card_flags_only_mostly_pathogenic_genera():
    small = pathogen_card(roll(("Xanthomonas", "well_known_genus", "Xanthomonas campestris"), Xanthomonas=1.2))
    assert small.status == "notice" and small.flag == "Xanthomonas alone is 1.2% of bacterial DNA"
    assert small.basis == "names" and small.carrier_terms == [] and small.confidence == "low"
    assert small.headline == "1% from genera that include plant pathogens · 1% from mostly pathogenic genera"
    assert small.finding.endswith("plant pathogens: Xanthomonas 1% (X. campestris).") and small.implications[0].kind == "risk"
    assert small.evidence[0].startswith("Xanthomonas 1.20%: Root and soilborne pathogens, high confidence, llm:test")
    assert small.evidence[-1].startswith("Roles from the microbe role annotation")
    big = pathogen_card(roll(("Pseudomonas", "some_species", "Pseudomonas syringae"), Pseudomonas=20.0))
    assert big.status == "info" and big.flag is None                       # 20% of a some-species genus: no colour
    assert [i.kind for i in big.implications] == ["neutral", "neutral"]
    assert "only some species cause disease (Pseudomonas 20%)" in big.implications[0].text
    none = pathogen_card(roll(("Bacillus", "some_species", ""), Other=10.0))
    assert none.headline == "No genera known for plant pathogens" and none.status == "info"
    few = pathogen_card(roll(("Xanthomonas", "well_known_genus", ""), Xanthomonas=1.2), reads=500)
    assert few.evidence[-1] == "Few bacterial reads: small shares may be noise."


def test_pathogen_card_in_the_profile(with_names):
    p = with_names.get("/api/functions/mg-dobj-a").json()
    card = next(c for c in p["cards"] if c["card"] == "bacteria_pathogens")
    assert card["title"] == "Bacteria that include plant pathogens" and card["status"] == "info"   # Streptomyces: some species
    assert card["headline"].startswith("20% from genera that include plant pathogens")
    assert "Streptomyces 20% (S. scabies)" in card["finding"]


@pytest.fixture
def with_modules(client):
    """Six more well-sequenced metagenomes as a reference, KEGG module completeness and the KO x lineage table."""
    proc = api.PROCESSED
    others = [f"nmdc:dobj-r{i}" for i in range(6)]
    mg = pd.read_parquet(proc / "metagenomes.parquet")
    mg["marker_mean"] = [100.0, 1.0]
    mg = pd.concat([mg, pd.DataFrame([dict(metagenome_key=k, site="P", plotID="P_001", date="2021-06-0" + str(i + 1),
                                           n_ko_genes=700_000, ko_depth_ok=True, marker_mean=100.0)
                                      for i, k in enumerate(others)])], ignore_index=True)
    mg.to_parquet(proc / "metagenomes.parquet")
    panel = pd.read_parquet(proc / "ko_panel.parquet")
    pd.concat([panel, pd.DataFrame([dict(metagenome_key=k, ko="K0", gene="nirK", function_group="denitrification",
                                         count=50, per_genome_eq=0.5, per_million=0.0) for k in others])]
              ).to_parquet(proc / "ko_panel.parquet")
    pd.DataFrame([dict(module="M00529", name="Denitrification, nitrate => nitrogen", class_a="Pathway modules",
                       class_b="Energy metabolism", class_c="Nitrogen metabolism", definition="K00370 K00368 K04561 K00376"),
                  dict(module="M00790", name="Pyrrolnitrin biosynthesis, tryptophan => pyrrolnitrin",
                       class_a="Pathway modules", class_b="Biosynthesis of other secondary metabolites",
                       class_c="Biosynthesis of other bacterial compounds", definition="K14266 K19981 K14257 K19982"),
                  dict(module="M00174", name="Methane oxidation, methanotroph, methane => formaldehyde",
                       class_a="Pathway modules", class_b="Energy metabolism", class_c="Methane metabolism",
                       definition="(K10944+K10945+K10946) K14028")]
                 ).to_parquet(proc / "kegg_modules.parquet")
    C = lambda key, mod, c: dict(metagenome_key=key, module=mod, steps_found=int(4 * c), n_steps=4,  # noqa: E731
                                 completeness=c, missing_steps=[], via_alias="")
    pd.DataFrame([C("nmdc:dobj-a", "M00529", 1.0), C("nmdc:dobj-a", "M00790", 1.0), C("nmdc:dobj-a", "M00174", 1.0)]
                 + [C(k, "M00529", 1.0 if i < 4 else 0.75) for i, k in enumerate(others)]
                 + [C(k, "M00790", 0.5) for k in others] + [C(k, "M00174", 1.0) for k in others]
                 ).to_parquet(proc / "kegg_module_completeness.parquet")
    T = lambda ko, phylum, family, genus, n, ident: dict(  # noqa: E731
        metagenome_key="nmdc:dobj-a", ko=ko, domain="Bacteria", phylum=phylum, class_="", order="", family=family,
        genus=genus, n_genes=n, identity_median=ident)
    pd.DataFrame([T("K00376", "Pseudomonadota", "Nitrobacteraceae", "Bradyrhizobium", 15, 97.0),
                  T("K00376", "Gemmatimonadota", "", "", 5, 70.0),
                  T("K04561", "Actinomycetota", "", "", 20, 65.0),
                  T("K10944", "Nitrososphaerota", "Nitrososphaeraceae", "Nitrososphaera", 30, 80.0),
                  T("K10944", "Actinomycetota", "", "", 10, 60.0),
                  T("K14266", "Pseudomonadota", "Pseudomonadaceae", "Pseudomonas", 8, 85.0),
                  T("K07787", "Pseudomonadota", "", "", 30, 70.0)]
                 ).rename(columns={"class_": "class"}).to_parquet(proc / "ko_taxa.parquet")
    pd.DataFrame([dict(metagenome_key="nmdc:dobj-a", ko=k, count=8) for k in ("K14266", "K19981", "K14257", "K19982")]
                 + [dict(metagenome_key="nmdc:dobj-a", ko="K07787", count=300)]            # 3 per genome here
                 + [dict(metagenome_key=k, ko="K07787", count=50 + 10 * i) for i, k in enumerate(others)]   # 0.5-1.0
                 ).to_parquet(proc / "ko_counts_all.parquet")
    return client


def test_cards_are_grouped_into_sections(with_modules):
    cards = {c["card"]: c for c in with_modules.get("/api/functions/mg-dobj-a").json()["cards"]}
    assert cards["n_now"]["section"] == "measured" and cards["fungi"]["section"] == "life"
    assert cards["copper"]["section"] == "life" and cards["nitrogen"]["section"] == "microbes"
    assert cards["unusual"]["section"] == "microbes"


def test_who_carries_the_nitrogen_steps_and_reference(with_modules):
    n = next(c for c in with_modules.get("/api/functions/mg-dobj-a").json()["cards"] if c["card"] == "nitrogen")
    assert "N2O removed by: proteobacteria (75%), Gemmatimonadetes (25%), Bradyrhizobium, close match (75%)" in n["who"]
    assert "Ammonium to nitrate: soil archaea (75%), actinobacteria (25%)" in n["who"]
    assert n["context"] == "Full denitrification in 4 of the 6 other well-sequenced NEON farm soils."
    assert any("About 75% of the ammonia-oxidation genes" in i["text"] for i in n["implications"])


def test_methane_needs_methanotrophs_not_ammonia_oxidisers(with_modules):
    g = next(c for c in with_modules.get("/api/functions/mg-dobj-a").json()["cards"] if c["card"] == "gases")
    assert g["headline"].startswith("No clear methane consumers")          # module complete, but genes from archaea


def test_unusual_names_meaningful_rare_pathways_and_who(with_modules):
    u = next(c for c in with_modules.get("/api/functions/mg-dobj-a").json()["cards"] if c["card"] == "unusual")
    assert "pyrrolnitrin (an antifungal compound" in u["headline"]
    assert u["who"] == ["Pyrrolnitrin: proteobacteria (100%)"]
    assert u["context"] == "Complete in none of the 6 other well-sequenced NEON farm soils."
    assert "Methane" not in u["headline"]                                   # complete in every other soil: not rare


def test_copper_is_compared_per_genome(with_modules):
    cu = next(c for c in with_modules.get("/api/functions/mg-dobj-a").json()["cards"] if c["card"] == "copper")
    assert "more than in the other well-sequenced farm soils" in cu["headline"]
    assert cu["context"].startswith("About 3.0 copies per bacterial genome here; 0.5-1.0 in the 6 other")
    assert cu["who"] == ["proteobacteria (100%)"]


def test_confidence_is_the_weakest_factor():
    from cropfit import confidence as conf
    f = [conf.genes(500), conf.depth(150), conf.reference(9, 1)]
    assert [x.level for x in f] == ["high", "medium", "medium"] and conf.weakest(f) == "medium"
    assert conf.weakest(f + [conf.genes(12)]) == "low" and conf.weakest([]) == "low"
    assert conf.reference(25, 1).level == "medium"                          # one site caps a large reference
    near = conf.margin(24.0, [25.0, 10.0], conf.NITRATE_MARGIN, "Nitrate", " mg/kg")
    assert near.level == "low" and near.text == "Nitrate 24 mg/kg is 1 mg/kg from the 25 mg/kg line"
    assert conf.margin(6.5, [5.5, 6.0, 7.0, 7.5], conf.PH_MARGIN, "pH", relative=False).level == "high"
    assert conf.days(0).text == "Measured on the day of the DNA sample" and conf.days(5).level == "medium"


def test_card_confidence_comes_from_its_data(with_modules):
    cards = {c["card"]: c for c in with_modules.get("/api/functions/mg-dobj-a").json()["cards"]}
    now = cards["n_now"]
    assert [f["level"] for f in now["confidence_factors"]] == ["high", "high", "high"]    # 2 days, 3 cores, 15 vs 10
    assert now["confidence"] == "high"
    cu = {f["text"]: f["level"] for f in cards["copper"]["confidence_factors"]}
    assert cu == {"38 copper-resistance gene copies": "medium",
                  "Sequenced to about 100 bacterial genomes' worth of DNA": "medium",
                  "'Who does it': genes match known genomes at about 70% identity": "medium",
                  "Compared with 6 other well-sequenced soils from 1 site": "low"}
    assert cards["copper"]["confidence"] == "low"
    assert "support" not in cards["copper"] and "who_kos" not in cards["copper"]       # internal fields stay internal
    assert cards["fungi"]["confidence_factors"][0]["text"] == "Fungi from the same soil cores as the genes"


def test_gene_cards_are_coloured_only_outside_the_reference_range(with_modules):
    cards = {c["card"]: c for c in with_modules.get("/api/functions/mg-dobj-a").json()["cards"]}
    cu = cards["copper"]                                                    # 3 per genome vs 0.5-1.0 elsewhere
    assert cu["status"] == "watch" and cu["tag"] == "More than usual"
    assert cu["flag"] == "More copper-resistance genes per genome than any other well-sequenced farm soil"
    assert cards["p_release"]["status"] == "info" and cards["p_release"]["tag"] is None


def test_unusual_headline_needs_more_than_a_trace(with_modules):
    k = pd.read_parquet(api.PROCESSED / "ko_counts_all.parquet")
    k.loc[k["ko"] == "K19982", "count"] = 1                                # one step rests on a single gene copy
    k.to_parquet(api.PROCESSED / "ko_counts_all.parquet")
    u = next(c for c in with_modules.get("/api/functions/mg-dobj-a").json()["cards"] if c["card"] == "unusual")
    assert u["headline"] == "A few less common pathways, none with a clear meaning for crops."
    assert any(f["text"] == "1 gene copy in the weakest step, of pyrrolnitrin biosynthesis" and f["level"] == "low"
               for f in u["confidence_factors"])
