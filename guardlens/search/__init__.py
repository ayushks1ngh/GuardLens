"""Footage search: find past alerts by describing them ("person in a red jacket").

Snapshots (and crops of detected objects) are embedded with a CLIP-family model on the CPU and
stored in SQLite; a text query is embedded the same way and matched by cosine similarity, then
blended with plain-text matches over triage captions. Everything is local: no image leaves the
device for search. Indexing is off until enabled, because the model downloads on first use.
"""
from guardlens.search.service import search_service  # noqa: F401
