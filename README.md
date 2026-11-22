# Structure Atlas Registry

Canonical public metadata registry for individually released protein structure
clustering targets (**Target Records**) and project-specific ordered target
rosters (**Project Registries**).

This repository stores **metadata, Zenodo DOIs, `Structure_Clustering` software
release pins, Cloudflare Pages URLs, and SHA-256 digests only**. Raw coordinate
archives live permanently on **Zenodo**; interactive static bundles live on
**Cloudflare Pages** (`*.pages.dev`); temporary feature previews live on
**GitHub Pages** built from `Structure_Clustering@experimental`.

## Repository Layout

- `targets/<target_id>.json` — One canonical **Target Record** per released
  biological target, recording construct sequence SHA-256, `owner_project`,
  `projects[]`, `zenodo_concept_doi`, `current_release`, and immutable
  `releases[]` (versioned Zenodo Version DOIs + `Structure_Clustering` release
  tags + 3-tier `Score Bundle` manifest SHA-256 + canonical URL).
- `projects/<project_id>.json` — One **Project Registry** per scientific
  project, acting as an ordered linked list (`prev_target_id` /
  `next_target_id`) of pinned Target Releases and Zenodo Version DOIs. Multiple
  projects may reference the same canonical Target Record without duplicating
  coordinate archives or Zenodo depositions.
- `schemas/` — JSON Schemas for Target Records, Project Registries, and 3-tier
  `score_manifest.json` bundles.
- `scripts/validate_registry.py` — Deterministic cross-reference, linked-list,
  DOI, SHA-256, and privacy validator enforced in CI.

## Validation

```bash
python3 scripts/validate_registry.py
pytest -q
```
