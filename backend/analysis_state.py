"""Identify the orchard geometry and active tree positions used by an analysis."""

from hashlib import sha256

from bson import json_util

from .orchard_layout import trees_in_layout


def layout_revision(database, orchard):
    trees = trees_in_layout(database, orchard)
    state = {
        "geometry": orchard.get("geometry"),
        "trees": [
            {key: tree.get(key) for key in ("_id", "coordinates", "species")}
            for tree in trees
        ],
    }
    return sha256(json_util.dumps(state, sort_keys=True).encode()).hexdigest()


def published_analysis(database, orchard):
    analysis = orchard.get("analysis") or {}
    revision = analysis.get("layout_revision")
    if not revision or revision != layout_revision(database, orchard):
        return {}
    return analysis
