"""KEGG module parsing/scoring and the KO x lineage join, on hand-made inputs: no network."""
import pandas as pd
import pytest

from cropfit import gene_taxa, kegg

DENITRIFICATION = "((K00370+K00371+K00374),(K02567+K02568)) (K00368,K15864) (K04561+K02305) K00376"


def test_parse_steps_and_operators():
    _, steps = kegg.parse(DENITRIFICATION)
    assert len(steps) == 4
    assert kegg.step_texts(DENITRIFICATION) == ["((K00370+K00371+K00374),(K02567+K02568))", "(K00368,K15864)",
                                                "(K04561+K02305)", "K00376"]


def test_complex_needs_all_members_and_alternatives_need_one():
    kos = {"K02567", "K02568", "K15864", "K04561"}            # napAB, nirS, norB without norC, no nosZ
    found, n, missing = kegg.completeness(DENITRIFICATION, kos)
    assert (found, n, missing) == (2, 4, [2, 3])
    found, _, _ = kegg.completeness(DENITRIFICATION, kos | {"K02305", "K00376"})
    assert found == 4


def test_optional_members_none_and_module_references():
    fix = "(K02588+K02586+K02591-K00531),(K22896+K22897+K22898+K22899)"
    assert kegg.completeness(fix, {"K02588", "K02586", "K02591"})[0] == 1     # K00531 is optional
    assert kegg.completeness("K00001 -- K00002", {"K00001", "K00002"})[:2] == (3, 3)
    assert kegg.completeness("M00001 K00005", {"K00005"}, {"M00001"})[0] == 2
    assert kegg.completeness("(K00001 K00002),K00003", {"K00003"})[0] == 1   # space inside parentheses = sequence


def test_old_amoa_id_satisfies_new_one_and_is_flagged():
    mods = pd.DataFrame([dict(module="M00528", definition="K28504+K10945+K10946 K10535")])
    s = kegg.score_sample(mods, {"K10944", "K10945", "K10946", "K10535"}).iloc[0]
    assert s.completeness == 1 and s.via_alias == "K28504"


def test_unparseable_definition_raises():
    with pytest.raises(ValueError):
        kegg.parse("K00001 + ? K00002")


def test_ko_taxa_join(tmp_path):
    (tmp_path / "ko.tsv").write_text("g1\t1\tKO:K00376\t90\ng2\t2\tKO:K00376\t80\ng3\t3\tKO:K01505\t70\n")
    (tmp_path / "gp.tsv").write_text(
        "g1\t9\t9\t97.0\tBacteria;Pseudomonadota;Alphaproteobacteria;Hyphomicrobiales;Nitrobacteraceae;Bradyrhizobium;B. sp.\n"
        "g2\t9\t9\t75.0\tBacteria;Pseudomonadota;Alphaproteobacteria;Hyphomicrobiales;Nitrobacteraceae;Bradyrhizobium;B. sp.\n"
        "g3\t9\t9\t88.0\tBacteria;Actinomycetota;Actinomycetes;Kitasatosporales;Streptomycetaceae;Streptomyces;S. sp.\n"
        "g4\t9\t9\t50.0\tBacteria;Chloroflexota\n")                          # gene without KO: ignored
    t = gene_taxa.ko_taxa(tmp_path / "ko.tsv", tmp_path / "gp.tsv").set_index("ko")
    assert t.loc["K00376", "genus"] == "Bradyrhizobium" and t.loc["K00376", "n_genes"] == 2
    assert t.loc["K00376", "identity_median"] == pytest.approx(86.0)
    assert t.loc["K01505", "phylum"] == "Actinomycetota" and len(t) == 2
