"""Microbe roles: ontology, summary rule, roll-up and the curated fungal override (docs/microbe_roles.md).
Small fixtures only; the real annotation files are checked when they exist."""
import pandas as pd
import pytest

from cropfit import microbe_roles as mr
from cropfit.config import RULES

COLS = mr.ANNOTATION_COLUMNS
ENUM_CONF, ENUM_EVID = {"high", "medium", "low"}, {"curated_db", "well_known_genus", "some_species", "inferred"}


def rows(*r):
    """Annotation frame from (domain, genus, term, confidence[, evidence, source]) tuples."""
    return pd.DataFrame([dict(domain=x[0], genus=x[1], term_id=x[2], confidence=x[3],
                              evidence=x[4] if len(x) > 4 else "some_species",
                              source=x[5] if len(x) > 5 else "llm:test", species_examples="", note="") for x in r],
                        columns=COLS)


def taxa(**pct):
    return pd.DataFrame([dict(name=n, phylum=None, pct=p, reads=int(p * 1000)) for n, p in pct.items()],
                        columns=["name", "phylum", "pct", "reads"])


def terms_of(df, genus):
    return set(df.loc[df["genus"] == genus, "term_id"])


def conf_of(df, genus, term):
    return df[(df["genus"] == genus) & (df["term_id"] == term)].iloc[0]["confidence"]


# ---------------------------------------------------------------- ontology and annotation files
def test_ontology_is_a_depth_first_tree():
    onto = mr.load_ontology()
    assert len(onto) == 32 and set(onto[onto["depth"] == 0]["term_id"]) == set(mr.POLARITIES)
    assert (onto["polarity"] == onto["root"]).all()
    ids = list(onto["term_id"])
    for t in ids:                                   # the term's subtree directly follows it
        sub = mr.subtree(onto, t)
        assert ids[ids.index(t): ids.index(t) + len(sub)] == sub
    panel = set(pd.read_csv(RULES / "ko_panel.csv")["function_group"])
    assert {g for gs in onto["ko_groups"] for g in gs} <= panel
    assert mr.terms_for_ko_group(onto, "phlD") == ["antibiotic_producer"]
    assert mr.terms_for_ko_group(onto, "urease") == []


def test_ontology_rejects_a_bad_tree(tmp_path):
    bad = tmp_path / "o.csv"
    head = "term_id,parent_id,label,polarity,ko_group,description\n"
    bad.write_text(head + "a,useful,A,useful,,x\nuseful,,Useful,useful,,x\n")           # parent comes later
    with pytest.raises(ValueError, match="comes later"):
        mr.load_ontology(bad)
    bad.write_text(head + "useful,,Useful,useful,,x\na,useful,A,harmful,,x\n")           # polarity != root
    with pytest.raises(ValueError, match="polarity"):
        mr.load_ontology(bad)


def test_real_annotation_files_are_valid_when_present():
    ann_f, gen_f = RULES / "microbe_annotations.csv", RULES / "microbe_genera.csv"
    if not ann_f.exists():
        pytest.skip("annotation files not merged yet")
    ann, onto = mr.load_llm_annotations(ann_f), mr.load_ontology()
    assert set(ann["term_id"]) <= set(onto["term_id"])
    assert set(ann["confidence"]) <= ENUM_CONF and set(ann["evidence"]) <= ENUM_EVID - {"curated_db"}
    assert set(ann["domain"]) <= {"Bacteria", "Archaea", "Fungi"}
    assert not ann.duplicated(["domain", "genus", "term_id"]).any()
    for _, sub in ann.groupby(["domain", "genus"]):
        if set(sub["term_id"]) & set(mr.UNKNOWN_TERMS):
            assert len(sub) == 1
    gen = pd.read_csv(gen_f)
    assert set(zip(ann["domain"], ann["genus"])) <= set(zip(gen["domain"], gen["genus"]))


def test_missing_files_mean_empty_roles(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "ANNOTATIONS_FILE", tmp_path / "none.csv")
    monkeypatch.setattr(mr, "GENERA_FILE", tmp_path / "none2.csv")
    assert mr.load_llm_annotations().empty and list(mr.load_llm_annotations().columns) == COLS
    assert mr.load_descriptions() == {} and mr.describe("bacteria", "Streptomyces") is None
    ru = mr.roll_up(taxa(Streptomyces=30.0), "bacteria", ann=mr.load_annotations(tmp_path))
    assert ru.summary.set_index("class_id").loc["unknown", "pct"] == 30 and ru.annotated_pct == 0
    assert ru.term_genera["row_term_id"].tolist() == ["unknown"] and ru.term_genera["source"].iloc[0] == "unannotated"


# ---------------------------------------------------------------- summary class
def test_summary_class_rule():
    sc = mr.summary_class
    assert sc(["useful", "harmful"]) == "mixed" and sc(["harmful", "context", "background"]) == "harmful"
    assert sc(["useful", "context"]) == "useful" and sc(["context", "background"]) == "context"
    assert sc(["background"]) == "background" and sc(["unknown"]) == "unknown" and sc([]) == "unknown"


def test_genus_summary_ignores_low_rows():
    onto = mr.load_ontology()
    gs = mr.genus_summary(rows(("Bacteria", "A", "n_fixation", "high"), ("Bacteria", "A", "root_soilborne_pathogen", "low"),
                               ("Bacteria", "B", "decomposer", "low")), onto).set_index("genus")
    assert gs.loc["A", "summary_class"] == "useful" and gs.loc["A", "terms"] == ["n_fixation"]
    assert gs.loc["B", "summary_class"] == "unknown" and gs.loc["B", "terms"] == []


# ---------------------------------------------------------------- roll-up
def test_roll_up_partition_and_overlapping_terms():
    ann = rows(("Bacteria", "Bradyrhizobium", "legume_symbiont", "high"),
               ("Bacteria", "Bradyrhizobium", "n_fixation", "medium"),          # two rows in one subtree
               ("Bacteria", "Streptomyces", "antibiotic_producer", "high"),
               ("Bacteria", "Streptomyces", "plant_pathogen", "medium"),
               ("Archaea", "Nitrososphaera", "nitrification", "high"))
    ru = mr.roll_up(taxa(Bradyrhizobium=10.0, Streptomyces=20.0, Nitrososphaera=5.0, Unknownia=2.0), "bacteria", ann=ann)
    s = ru.summary.set_index("class_id")
    assert list(ru.summary["class_id"]) == [c for c, _ in mr.SUMMARY_CLASSES]
    assert s.loc["useful", "pct"] == 10 and s.loc["mixed", "pct"] == 20 and s.loc["context", "pct"] == 5
    assert s.loc["unknown", "pct"] == 2 and s["pct"].sum() == pytest.approx(ru.named_pct) == 37
    assert s["pct_of_named"].sum() == pytest.approx(100) and s.loc["mixed", "top"] == ["Streptomyces"]
    t = ru.terms.set_index("term_id")
    assert t.loc["n_fixation", "pct"] == 10 and t.loc["nutrient_supply", "pct"] == 10     # counted once
    assert t.loc["useful", "pct"] == 30 and t.loc["harmful", "pct"] == 20 and t.loc["nitrification", "pct"] == 5
    assert t.loc["unknown", "pct"] == 2 and t.loc["denitrification", "n_genera"] == 0
    rep = ru.term_genera.set_index(["term_id", "name"])
    assert rep.loc[("n_fixation", "Bradyrhizobium"), "row_term_id"] == "legume_symbiont"   # high beats medium
    assert rep.loc[("unknown", "Unknownia"), "source"] == "unannotated" and ru.annotated_pct == 35
    assert ru.sources == ["llm:test"]


def test_roll_up_matches_domain_by_sample_kind():
    ann = rows(("Fungi", "Same", "decomposer", "high"), ("Bacteria", "Same", "n_fixation", "high"))
    assert mr.roll_up(taxa(Same=10.0), "fungi", ann=ann).genera["summary_class"].iloc[0] == "background"
    assert mr.roll_up(taxa(Same=10.0), "bacteria", ann=ann).genera["summary_class"].iloc[0] == "useful"


def test_roll_up_unknown_subtree_rows_and_empty_sample():
    ann = rows(("Bacteria", "Odd", "doubtful_assignment", "low"))
    ru = mr.roll_up(taxa(Odd=4.0), "bacteria", ann=ann)
    assert ru.genera["summary_class"].iloc[0] == "unknown" and ru.annotated_pct == 4      # annotated, any confidence
    assert ru.term_genera.iloc[0]["row_term_id"] == "doubtful_assignment"                 # any-confidence unknown row
    empty = mr.roll_up(taxa(), "fungi", ann=ann)
    assert empty.named_pct == 0 and (empty.summary["pct_of_named"] == 0).all() and empty.term_genera.empty


# ---------------------------------------------------------------- curated fungal mapping and override
def ft(**kw):
    base = dict(genus="X", primary_lifestyle="", secondary_lifestyle="", plant_pathogenic_capacity="")
    return pd.DataFrame([{**base, **kw}])


def guild(genus, category, confidence="Probable", primary="Some Guild"):
    return pd.DataFrame([dict(genus=genus, category=category, primary_guild=primary, confidence=confidence)])


def merged(llm, fungaltraits=None, guilds=None):
    cur = mr.curated_fungal_rows(fungaltraits, guilds)
    return mr.merge_fungal(llm, cur, mr.curated_record_genera(fungaltraits, guilds))


def test_fusarium_override():
    llm = rows(("Fungi", "Fusarium", "root_soilborne_pathogen", "high"), ("Fungi", "Fusarium", "mycotoxin_producer", "high"),
               ("Fungi", "Fusarium", "decomposer", "high"))
    f = ft(genus="Fusarium", primary_lifestyle="plant_pathogen", secondary_lifestyle="litter_saprotroph",
           plant_pathogenic_capacity="leaf/fruit/seed_pathogen")
    m = merged(llm, f, guild("Fusarium", "plant_pathogen", "Possible"))
    assert terms_of(m, "Fusarium") == {"foliar_pathogen", "root_soilborne_pathogen", "mycotoxin_producer", "decomposer"}
    row = m[m["term_id"] == "foliar_pathogen"].iloc[0]
    assert (row["confidence"], row["source"], row["evidence"]) == ("high", "fungaltraits", "curated_db")
    assert row["note"] == "FungalTraits primary_lifestyle=plant_pathogen"
    dec = m[m["term_id"] == "decomposer"].iloc[0]
    assert (dec["confidence"], dec["source"]) == ("medium", "fungaltraits")           # replaces the LLM row
    assert m[m["term_id"] == "root_soilborne_pathogen"].iloc[0]["source"] == "llm:test"


def test_trichoderma_and_cladosporium_are_not_curated_pathogens():
    f = pd.concat([ft(genus="Trichoderma", primary_lifestyle="mycoparasite", secondary_lifestyle="foliar_endophyte",
                      plant_pathogenic_capacity="leaf/fruit/seed_pathogen"),
                   ft(genus="Cladosporium", primary_lifestyle="litter_saprotroph", secondary_lifestyle="plant_pathogen",
                      plant_pathogenic_capacity="leaf/fruit/seed_pathogen")])
    llm = rows(("Fungi", "Cladosporium", "foliar_pathogen", "high"))
    m = merged(llm, f)
    assert (conf_of(m, "Trichoderma", "mycoparasite"), conf_of(m, "Trichoderma", "endophyte"),
            conf_of(m, "Trichoderma", "foliar_pathogen")) == ("high", "medium", "low")
    c = m[(m["genus"] == "Cladosporium") & (m["term_id"] == "foliar_pathogen")].iloc[0]
    assert c["confidence"] == "low" and c["source"] == "fungaltraits"                  # curated row kept over the LLM one
    llm2 = rows(("Fungi", "Cladosporium", "root_soilborne_pathogen", "high"))
    m2 = merged(llm2, f)
    capped = m2[(m2["genus"] == "Cladosporium") & (m2["term_id"] == "root_soilborne_pathogen")].iloc[0]
    assert capped["confidence"] == "low" and capped["note"].startswith("capped: curated sources")
    classes = mr.genus_summary(m2, mr.load_ontology()).set_index("genus")["summary_class"]
    assert classes["Cladosporium"] == "background" and classes["Trichoderma"] == "useful"


def test_wood_pathogen_is_low_and_funguild_mapping():
    m = mr.curated_fungal_rows(ft(genus="W", primary_lifestyle="plant_pathogen", plant_pathogenic_capacity="wood_pathogen"),
                               pd.concat([guild("G", "saprotroph"), guild("N", "other"),
                                          guild("A", "arbuscular_mycorrhizal", "Possible")]))
    w = m[m["genus"] == "W"].iloc[0]
    assert (w["term_id"], w["confidence"]) == ("plant_pathogen", "low") and "wood/tree pathogen" in w["note"]
    assert terms_of(m, "G") == {"decomposer"} and terms_of(m, "N") == set() and conf_of(m, "A", "mycorrhizal_partner") == "low"
    assert m[m["genus"] == "G"].iloc[0]["note"] == "FUNGuild primary guild=Some Guild"
    both = mr.curated_fungal_rows(ft(genus="W", primary_lifestyle="plant_pathogen", plant_pathogenic_capacity="wood_pathogen"),
                                  guild("W", "plant_pathogen", "Highly Probable"))
    assert len(both) == 1 and both.iloc[0]["source"] == "funguild"                     # the higher confidence wins


def test_mortierella_unknown_row_is_dropped_by_a_curated_role():
    llm = rows(("Fungi", "Mortierella", "unknown", "low", "inferred"), ("Bacteria", "Mortierella", "decomposer", "high"))
    m = merged(llm, guilds=guild("Mortierella", "saprotroph"))
    fungal = m[m["domain"] == "Fungi"]
    assert list(fungal["term_id"]) == ["decomposer"] and fungal.iloc[0]["source"] == "funguild"
    assert (m["domain"] == "Bacteria").sum() == 1                                      # bacteria pass through
    kept = merged(rows(("Fungi", "Q", "doubtful_assignment", "low")), guilds=guild("Q", "saprotroph"))
    assert terms_of(kept, "Q") == {"doubtful_assignment", "decomposer"}


def test_genus_without_curated_record_keeps_llm_rows():
    llm = rows(("Fungi", "Rare", "decomposer", "medium"), ("Fungi", "Rare", "plant_pathogen", "high"))
    m = merged(llm, ft(genus="Other", primary_lifestyle="lichenized"), guild("Rare", "unknown"))
    assert terms_of(m, "Rare") == {"decomposer", "plant_pathogen"} and len(m) == 2
