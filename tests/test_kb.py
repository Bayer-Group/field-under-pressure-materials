"""Tests for cropfit.kb: normalisation, FungalTraits filter, USDA host table, download. Offline and synthetic."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cropfit import kb

FIX = Path(__file__).parent / "fixtures"
FT_CSV = FIX / "fungaltraits_sample.csv"
USDA_CSV = FIX / "usda_fungus_host_sample.csv"
SYN = {"Rhizoctonia": "Rhizoctonia_complex", "Thanatephorus": "Rhizoctonia_complex",
       "Ceratobasidium": "Rhizoctonia_complex", "Gibberella": "Fusarium"}


def taxa_df(rows):
    """Mini crop_host_taxa with host_genus / host_epithet filled like load_crop_host_taxa."""
    df = pd.DataFrame(rows, columns=["host_taxon", "rank", "crop_group"])
    p = df["host_taxon"].map(kb.parse_binomial)
    df["host_genus"], df["host_epithet"] = [x[0] for x in p], [x[1] for x in p]
    return df


TAXA = taxa_df([("Zea", "genus", "corn"), ("Zea mays", "species", "corn"), ("Glycine max", "species", "soybean"),
                ("Triticum", "genus", "winter_wheat"), ("Triticum", "genus", "spring_wheat"),
                ("Triticum aestivum", "species", "winter_wheat"), ("Triticum aestivum", "species", "spring_wheat"),
                ("Triticum vulgare", "species", "winter_wheat"), ("Triticum vulgare", "species", "spring_wheat"),
                ("Medicago x varia", "species", "alfalfa")])


def ft_rows(*specs):
    """specs: (genus, phylum, primary, secondary)."""
    return pd.DataFrame([{"genus_raw": g, "phylum": ph, "primary_lifestyle": p, "secondary_lifestyle": s,
                          "plant_pathogenic_capacity": None, "comment_on_lifestyle": None}
                         for g, ph, p, s in specs])


def usda_slim(*recs):
    """recs: (fungus sciName, host string, litnum) -> slim frame via parse_binomial, as read_usda_fungus_host does."""
    rows = []
    for sci, host, lit in recs:
        fg, fe = kb.parse_binomial(sci)
        hg, he = kb.parse_binomial(host)
        rows.append({"fungus_genus": kb.normalise_genus(fg), "fungus_epithet": fe, "host_raw": host,
                     "host_genus": hg, "host_epithet": he, "litnum": str(lit)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------- names

def test_normalise_genus():
    assert kb.normalise_genus("  fusarium ") == "Fusarium"
    assert kb.normalise_genus("Fusarium_sp") == "Fusarium"
    assert kb.normalise_genus("Fusarium spp.") == "Fusarium"
    assert kb.normalise_genus("FUSARIUM sp.") == "Fusarium"
    for bad in (None, np.nan, "", "  ", "unclassified_Fungi", "Hypocreales_fam_Incertae_sedis", "nan"):
        assert kb.normalise_genus(bad) is None


def test_canonical_genus_uses_synonyms():
    assert kb.canonical_genus("thanatephorus", SYN) == "Rhizoctonia_complex"
    assert kb.canonical_genus("Gibberella_sp", SYN) == "Fusarium"
    assert kb.canonical_genus("Alternaria", SYN) == "Alternaria"
    assert kb.canonical_genus("unclassified_x", SYN) is None


def test_repo_synonym_file_has_plan_rows():
    syn = kb.load_genus_synonyms()
    assert syn["Gibberella"] == "Fusarium"
    assert {syn[g] for g in ("Rhizoctonia", "Thanatephorus", "Ceratobasidium")} == {"Rhizoctonia_complex"}
    assert "Cochliobolus" not in syn


@pytest.mark.parametrize("name,expected", [
    ("Fusarium graminearum Schwabe", ("Fusarium", "graminearum")),
    ("Gibberella zeae (Schwein.) Petch", ("Gibberella", "zeae")),
    ("Fusarium oxysporum f. sp. lycopersici", ("Fusarium", "oxysporum")),
    ("Zea mays subsp. mays", ("Zea", "mays")),
    ("Medicago x varia Martyn", ("Medicago", "varia")),
    ("Medicago ×varia", ("Medicago", "varia")),
    ("Fusarium sp.", ("Fusarium", None)),
    ("Fusarium spp.", ("Fusarium", None)),
    ("Fusarium", ("Fusarium", None)),
    ("Fusarium cf. solani", ("Fusarium", None)),
    ("Triticum sp.", ("Triticum", None)),
    ("", (None, None)),
    (None, (None, None)),
    ("123 junk", (None, None)),
])
def test_parse_binomial(name, expected):
    assert kb.parse_binomial(name) == expected


# ---------------------------------------------------------------------------------------------- FungalTraits

def test_parse_fungaltraits_csv_finds_header_and_strips():
    ft = kb.parse_fungaltraits(FT_CSV)       # two junk rows above the header
    assert list(ft.columns) == ["genus_raw", "phylum", "primary_lifestyle", "secondary_lifestyle",
                                "plant_pathogenic_capacity", "comment_on_lifestyle"]
    assert len(ft) == 13
    assert "Alternaria" in set(ft["genus_raw"])            # trailing space stripped
    assert "Alternaria " not in set(ft["genus_raw"])
    bip = ft[ft["genus_raw"] == "Bipolaris"].iloc[0]
    assert bip["primary_lifestyle"] == "litter_saprotroph" and bip["secondary_lifestyle"] == "plant_pathogen"
    assert bip["plant_pathogenic_capacity"] is None         # empty cell -> None
    tri = ft[ft["genus_raw"] == "Trichoderma"].iloc[0]
    assert tri["plant_pathogenic_capacity"] == "Leaf/Fruit/Seed_pathogen"


def test_parse_fungaltraits_xlsx_equals_csv(tmp_path):
    raw = pd.read_csv(FT_CSV, header=None, dtype=str, keep_default_na=False)
    xlsx = tmp_path / "ft.xlsx"
    raw.to_excel(xlsx, header=False, index=False)
    pd.testing.assert_frame_equal(kb.parse_fungaltraits(xlsx), kb.parse_fungaltraits(FT_CSV))


def test_parse_fungaltraits_without_genus_header_raises(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError, match="GENUS"):
        kb.parse_fungaltraits(p)


def test_classify_genera_on_fixture():
    g = kb.classify_genera(kb.parse_fungaltraits(FT_CSV), SYN).set_index("genus")
    assert list(kb.classify_genera(kb.parse_fungaltraits(FT_CSV), SYN).columns) == kb.GENERA_COLUMNS
    assert g.loc["Fusarium", "passes_filter"] and g.loc["Fusarium", "passed_by"] == "primary_lifestyle"
    assert g.loc["Gibberella", "canonical_genus"] == "Fusarium"
    assert g.loc["Thanatephorus", "canonical_genus"] == "Rhizoctonia_complex"
    # secondary-only pass
    assert g.loc["Bipolaris", "passes_filter"] and g.loc["Bipolaris", "passed_by"] == "secondary_lifestyle"
    # capacity-only (biocontrol mycoparasite) must fail but the capacity is reported
    assert not g.loc["Trichoderma", "passes_filter"]
    assert g.loc["Trichoderma", "exclusion_reason"] == "not_plant_pathogen"
    assert g.loc["Trichoderma", "plant_pathogenic_capacity"] == "Leaf/Fruit/Seed_pathogen"
    # non-fungal phylum and oomycete guard
    assert g.loc["Labyrinthula", "exclusion_reason"] == "non_fungal" and not g.loc["Labyrinthula", "passes_filter"]
    assert g.loc["Pythium", "exclusion_reason"] == "oomycete" and not g.loc["Pythium", "passes_filter"]
    # duplicate genus passes when any row passes; one output row
    assert g.loc["Cladosporium", "passes_filter"] and g.loc["Cladosporium", "duplicate_rows"] == 2
    assert g.loc["Alternaria", "passes_filter"]
    assert not g.loc["Mortierella", "passes_filter"]
    assert g.index.is_unique


def test_oomycete_guard_applies_even_in_fungal_phylum():
    ft = ft_rows(("Phytophthora", "Ascomycota", "plant_pathogen", None),
                 ("Aphanomyces", "Ascomycota", None, "plant_pathogen"))
    g = kb.classify_genera(ft, {}).set_index("genus")
    assert not g["passes_filter"].any()
    assert set(g["exclusion_reason"]) == {"oomycete"}


def test_classify_duplicate_failing_rows_report_reason():
    ft = ft_rows(("Foo", "Ascomycota", "soil_saprotroph", None), ("Foo", "Ascomycota", "litter_saprotroph", None))
    g = kb.classify_genera(ft, {}).set_index("genus")
    assert not g.loc["Foo", "passes_filter"] and g.loc["Foo", "exclusion_reason"] == "not_plant_pathogen"
    assert g.loc["Foo", "primary_lifestyle"] == "litter_saprotroph|soil_saprotroph"


# ---------------------------------------------------------------------------------------------- USDA reading

def test_read_usda_fixture_quoted_fields_nulls_and_authors():
    u = kb.read_usda_fungus_host(USDA_CSV)
    assert set(u.columns) == {"fungus_genus", "fungus_epithet", "host_raw", "host_genus", "host_epithet", "litnum"}
    assert u.attrs["bad_lines"] == 0 and u.attrs["rows_read"] == 26
    assert len(u) == 21                                    # duplicate lines, \N fungus and \N host rows dropped
    assert not u.duplicated().any()
    assert u["fungus_genus"].notna().all() and u["host_genus"].notna().all()
    assert not u["host_raw"].str.contains(r"\\N", regex=True).any()
    r = u[u["host_raw"] == "Triticum vulgare"].iloc[0]
    assert (r["fungus_genus"], r["fungus_epithet"]) == ("Gibberella", "zeae")     # author stripped
    fo = u[(u["fungus_genus"] == "Fusarium") & (u["fungus_epithet"] == "oxysporum") & (u["host_raw"] == "Glycine max")]
    assert len(fo) == 2                                    # f. sp. and plain: two literature records
    sp = u[(u["fungus_genus"] == "Fusarium") & u["fungus_epithet"].isna()]
    assert len(sp) == 1 and sp.iloc[0]["host_raw"] == "Zea mays"


def test_read_usda_with_stats_and_small_chunks():
    u1 = kb.read_usda_fungus_host(USDA_CSV)
    u2, st = kb.read_usda_fungus_host(USDA_CSV, chunksize=5, with_stats=True)
    assert st == {"bad_lines": 0, "rows_read": 26}
    pd.testing.assert_frame_equal(u1.sort_values(list(u1.columns)).reset_index(drop=True),
                                  u2.sort_values(list(u2.columns)).reset_index(drop=True))


# ---------------------------------------------------------------------------------------------- crop mapping

def crops_of(host, taxa=TAXA):
    u = usda_slim(("Fusarium graminearum", host, 1))
    return set(kb.assign_crop_groups(u, taxa)["crop_group"])


def test_assign_crop_groups():
    assert crops_of("Zea sp.") == {"corn"}
    assert crops_of("Zea") == {"corn"}
    assert crops_of("Zea mays subsp. mays") == {"corn"}              # subsp. matched via epithet
    assert crops_of("Zea mays var. indentata") == {"corn"}
    assert crops_of("Triticum vulgare") == {"winter_wheat", "spring_wheat"}   # old synonym -> both wheats
    assert crops_of("Triticum sp.") == {"winter_wheat", "spring_wheat"}
    assert crops_of("Medicago x varia Martyn") == {"alfalfa"}
    assert crops_of("Sorghum sp.", taxa_df([("Sorghum bicolor", "species", "sorghum")])) == set()
    assert crops_of("Zea diploperennis") == set()                    # wild teosinte not mapped
    assert crops_of("Poa pratensis") == set()


def test_load_crop_host_taxa_repo_file_is_valid():
    t = kb.load_crop_host_taxa()
    assert set(t["crop_group"]) <= set(kb.SCORED_CROPS)
    assert not ((t["host_taxon"] == "Sorghum") & (t["rank"] == "genus")).any()   # Sorghum sp. maps to nothing


def test_load_crop_host_taxa_rejects_bad_rows(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("host_taxon,rank,crop_group,note\nZea mays,species,not_a_crop,\n")
    with pytest.raises(ValueError, match="SCORED_CROPS"):
        kb.load_crop_host_taxa(p)
    p.write_text("host_taxon,rank,crop_group,note\nZea mays,family,corn,\n")
    with pytest.raises(ValueError, match="rank"):
        kb.load_crop_host_taxa(p)


# ---------------------------------------------------------------------------------------------- H table

@pytest.fixture(scope="module")
def host_from_fixture():
    u = kb.read_usda_fungus_host(USDA_CSV)
    taxa = kb.load_crop_host_taxa()
    host, sc = kb.build_genus_crop_host(u, taxa, SYN)
    return host.set_index(["genus", "crop_group"]), sc


def test_host_table_shape_and_columns(host_from_fixture):
    host, sc = host_from_fixture
    assert list(host.reset_index().columns) == kb.HOST_COLUMNS
    assert list(sc.columns) == kb.SPECIES_CROP_COLUMNS
    genera = set(host.index.get_level_values(0))
    assert genera == {"Fusarium", "Bipolaris", "Macrophomina", "Rhizoctonia_complex", "Phoma", "Gaeumannomyces",
                      "Sclerotinia"}
    assert len(host) == len(genera) * len(kb.SCORED_CROPS)      # every documented genus has a row per crop


def test_fusarium_counts_species_not_records_and_merges_gibberella(host_from_fixture):
    host, _ = host_from_fixture
    # species: graminearum, oxysporum (f. sp. collapsed), poae, verticillioides + Gibberella zeae (merged)
    for crop in kb.SCORED_CROPS:
        assert host.loc[("Fusarium", crop), "n_species_documented"] == 5
    w = host.loc[("Fusarium", "winter_wheat")]
    assert w["n_species_on_crop"] == 2 and w["h"] == pytest.approx(2 / 5)
    assert w["species_on_crop"] == "Fusarium graminearum; Gibberella zeae"
    assert host.loc[("Fusarium", "spring_wheat"), "h"] == w["h"]
    soy = host.loc[("Fusarium", "soybean")]
    assert soy["n_species_on_crop"] == 1 and soy["n_records_on_crop"] == 2   # 2 records, 1 species
    assert soy["h"] == pytest.approx(1 / 5)


def test_genus_only_records_counted_separately(host_from_fixture):
    host, _ = host_from_fixture
    corn = host.loc[("Fusarium", "corn")]
    # graminearum (Zea mays) + verticillioides (host "Zea sp." via the genus rule); "Fusarium sp." not a species
    assert corn["n_species_on_crop"] == 2 and corn["h"] == pytest.approx(2 / 5)
    assert corn["n_genus_only_records_on_crop"] == 1
    assert host["n_genus_only_records_on_crop"].sum() == 1


def test_macrophomina_hosts_and_unmapped_sorghum_sp(host_from_fixture):
    host, _ = host_from_fixture
    for crop in ("sorghum", "sunflower", "corn"):             # corn via "Zea mays subsp. mays"
        assert host.loc[("Macrophomina", crop), "h"] == 1.0
    assert host.loc[("Macrophomina", "winter_wheat"), "h"] == 0.0
    # Gaeumannomyces only on "Sorghum sp." -> documented but h = 0 everywhere
    assert (host.loc["Gaeumannomyces", "h"] == 0).all()
    assert (host.loc["Gaeumannomyces", "n_species_documented"] == 1).all()
    assert (host.loc["Sclerotinia", "h"] == 0).all()           # non-crop host only


def test_bipolaris_genus_level_host_row_maps_to_both_wheats(host_from_fixture):
    host, _ = host_from_fixture
    for crop in ("winter_wheat", "spring_wheat", "barley_oats"):
        assert host.loc[("Bipolaris", crop), "h"] == pytest.approx(0.5)     # sorokiniana of {sorokiniana, oryzae}
    assert host.loc[("Bipolaris", "corn"), "h"] == 0.0
    assert host.loc[("Phoma", "alfalfa"), "h"] == 1.0           # Medicago x varia -> alfalfa


def test_rhizoctonia_complex_species_pooled(host_from_fixture):
    host, sc = host_from_fixture
    assert host.loc[("Rhizoctonia_complex", "soybean"), "n_species_documented"] == 2
    assert host.loc[("Rhizoctonia_complex", "soybean"), "h"] == 1.0
    assert host.loc[("Rhizoctonia_complex", "corn"), "h"] == 0.5
    assert "Thanatephorus cucumeris" in set(sc["species"])
    assert set(sc["canonical_genus"]) >= {"Rhizoctonia_complex"}


def test_undocumented_genus_has_no_row_and_empty_inputs():
    host, sc = kb.build_genus_crop_host(usda_slim(("Fusarium graminearum", "Zea mays", 1)), TAXA, SYN)
    assert set(host["genus"]) == {"Fusarium"}                  # nothing documented for e.g. Alternaria
    assert "Alternaria" not in set(host["genus"])
    # genus-only fungus records alone do not document a genus
    host2, _ = kb.build_genus_crop_host(usda_slim(("Colletotrichum sp.", "Zea mays", 1)), TAXA, SYN)
    assert host2.empty


def test_crops_argument_restricts_rows():
    host, _ = kb.build_genus_crop_host(usda_slim(("Fusarium graminearum", "Zea mays", 1)), TAXA, SYN, crops=("corn",))
    assert list(host["crop_group"]) == ["corn"] and host.iloc[0]["h"] == 1.0


# ---------------------------------------------------------------------------------------------- download

class FakeResp:
    def __init__(self, chunks, fail_after=None):
        self.chunks, self.fail_after, self.closed = chunks, fail_after, False
        self.url = "https://s3.example.invalid/presigned?X-Amz-Signature=SECRET"   # redirect target

    def iter_content(self, chunk_size=None):
        for i, c in enumerate(self.chunks):
            if self.fail_after is not None and i >= self.fail_after:
                raise ConnectionError("boom")
            yield c

    def close(self):
        self.closed = True


def test_download_file_atomic_write_and_manifest(tmp_path, monkeypatch):
    calls = []
    chunks = [b"abc", b"", b"defg", b"h" * 10]
    monkeypatch.setattr(kb.http, "get", lambda url, **kw: calls.append((url, kw)) or FakeResp(chunks))
    dest = tmp_path / "raw" / "data.bin"
    e = kb.download_file("https://example.invalid/file", dest, source_version="v1")
    payload = b"".join(chunks)
    assert dest.read_bytes() == payload
    assert not dest.with_name("data.bin.part").exists()
    assert calls[0][0] == "https://example.invalid/file" and calls[0][1].get("stream") is True
    assert e["bytes"] == len(payload) and e["sha256"] == hashlib.sha256(payload).hexdigest()
    assert e["url"] == "https://example.invalid/file" and e["source_version"] == "v1"
    man = json.loads((dest.parent / "manifest.json").read_text())
    assert man["data.bin"] == e
    assert "SECRET" not in json.dumps(man) and "s3.example" not in json.dumps(man)   # no redirect URL recorded

    # existing file is kept (no new request); refresh re-downloads
    again = kb.download_file("https://example.invalid/file", dest)
    assert again == e and len(calls) == 1
    kb.download_file("https://example.invalid/file", dest, refresh=True)
    assert len(calls) == 2


def test_download_file_failure_leaves_no_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(kb.http, "get", lambda url, **kw: FakeResp([b"abc", b"def"], fail_after=1))
    dest = tmp_path / "data.bin"
    with pytest.raises(ConnectionError):
        kb.download_file("https://example.invalid/f", dest)
    assert not dest.exists() and not (tmp_path / "data.bin.part").exists()
    assert not (tmp_path / "manifest.json").exists()


def test_download_existing_file_without_manifest_rebuilds_entry(tmp_path):
    dest = tmp_path / "x.csv"
    dest.write_bytes(b"hello")
    e = kb.download_file("https://example.invalid/x", dest)
    assert e["bytes"] == 5 and e["sha256"] == hashlib.sha256(b"hello").hexdigest()


# ---------------------------------------------------------------------------------------------- load_kb

def test_load_kb_missing_files_names_script(tmp_path):
    with pytest.raises(FileNotFoundError, match="12_build_kb"):
        kb.load_kb(tmp_path)


def test_load_kb_roundtrip(tmp_path):
    genera = pd.DataFrame([{c: None for c in kb.GENERA_COLUMNS}])
    host = pd.DataFrame(columns=kb.HOST_COLUMNS)
    genera.to_parquet(tmp_path / kb.GENERA_TABLE, index=False)
    host.to_parquet(tmp_path / kb.HOST_TABLE, index=False)
    (tmp_path / kb.META_FILE).write_text(json.dumps({"sources": {"x": 1}}))
    k = kb.load_kb(tmp_path)
    assert k.meta == {"sources": {"x": 1}} and list(k.host.columns) == kb.HOST_COLUMNS
    assert k.synonyms["Gibberella"] == "Fusarium"
