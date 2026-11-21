"""Shared fixtures: small microbe-role annotation files (docs/microbe_roles.md section 9) instead of the real ones."""
import pytest

from cropfit import microbe_roles

ANNOTATIONS = """domain,genus,term_id,confidence,evidence,source,species_examples,note
Bacteria,Streptomyces,antibiotic_producer,high,well_known_genus,llm:test,Streptomyces griseus,
Bacteria,Streptomyces,root_soilborne_pathogen,medium,some_species,llm:test,Streptomyces scabies,potato scab
Bacteria,Bradyrhizobium,legume_symbiont,high,well_known_genus,llm:test,Bradyrhizobium japonicum,
Bacteria,Bradyrhizobium,denitrification,low,some_species,llm:test,Bradyrhizobium diazoefficiens,
Archaea,Nitrososphaera,nitrification,high,well_known_genus,llm:test,Nitrososphaera viennensis,
Fungi,Fusarium,root_soilborne_pathogen,high,some_species,llm:test,Fusarium oxysporum,
Fungi,Fusarium,mycotoxin_producer,high,well_known_genus,llm:test,Fusarium graminearum,
Fungi,Mortierella,unknown,low,inferred,llm:test,,
"""
GENERA = """domain,genus,description
Bacteria,Streptomyces,Thread-forming soil bacteria that break down residues and make many antibiotics. A few species cause potato scab.
Fungi,Fusarium,Common soil and residue fungi; several species cause root rot or head blight.
"""


@pytest.fixture
def role_files(tmp_path, monkeypatch):
    """Point the microbe-role loaders at the small fixture files; the real ontology stays."""
    (tmp_path / "ann.csv").write_text(ANNOTATIONS)
    (tmp_path / "genera.csv").write_text(GENERA)
    monkeypatch.setattr(microbe_roles, "ANNOTATIONS_FILE", tmp_path / "ann.csv")
    monkeypatch.setattr(microbe_roles, "GENERA_FILE", tmp_path / "genera.csv")
    return tmp_path
