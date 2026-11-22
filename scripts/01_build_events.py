"""Build the sampling-event registry (events, plot_geometry, event_cores) from the processed biology tables.

Offline; run after 02b_build_neon_features.py and 05_build_biology.py. Every geo dataset is linked to these
events (see cropfit/events.py).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cropfit import events

if __name__ == "__main__":
    out = events.build_all()
    ev = out["events"]
    print(f"events: {len(ev)} on {ev.plotID.nunique()} plots")
    print(ev.groupby(["site", "year"]).agg(events=("event_id", "size"), metagenome=("has_metagenome", "sum"),
                                           its=("has_its", "sum"), chem=("has_chem", "sum")).to_string())
    bio = ev[ev.has_metagenome | ev.has_its]
    print(f"events with biology: {len(bio)} on {bio.plotID.nunique()} plots")
    if "event_cores" in out:
        c = out["event_cores"]
        print(f"event_cores: {len(c)} cores, {int(c.lat.notna().sum())} with a position inside the plot")
