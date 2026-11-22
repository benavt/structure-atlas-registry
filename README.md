# Structure Atlas Registry

Canonical metadata registry for protein structure clustering targets (**Target
Records**) and project-specific target portals (**Project Registries**).

## Ubiquitous Language: Where Data Lives & How It Is Shared

Each system has **one non-overlapping responsibility**:

| Layer | Role | What Lives Here | Access & Sharing |
| --- | --- | --- | --- |
| **GitHub: `Structure_Clustering`** | **Software Engine** | Analysis, packing (`ca_i16_hex`), score-bundle, portal-builder, and SSD-sync code. Versioned via immutable semver tags on `main` (e.g. `v0.2.0`). | Public code; **never** stores scientific payloads or collaborator emails. |
| **GitHub: `structure-atlas-registry`** (this repo) | **Canonical Index** | Lightweight JSON **Target Records** (`targets/<id>.json`) and **Project Registries** (`projects/<project>.json`) linking targets, software tags, Zenodo DOIs, SHA-256 digests, and Cloudflare Pages URLs. | Public metadata only; **never** stores coordinates, score tables, private hostnames/paths, or email allowlists (enforced in CI). |
| **GitHub: Project Repos** (`benavt/LS_AIS`, `benavt/Jernigan`, `benavt/domenico-targets`, …) | **Scientific Config** | Construct FASTAs, residue-cohort definitions, analysis plans, and provenance configs. | Code/config only; no bulk model archives or built site shards. |
| **Cloudflare Pages** (`<project>-structure-atlas.pages.dev`) | **Interactive Web Layer** | Static visualization shards (UMAP/PCA/t-SNE, `ca_i16_hex` Cα packs, representatives, MCMC/DISCO panels, Bonsai trees, Cα distance maps). | **Per-project Access Mode:** starts `private` behind its own **Cloudflare Zero Trust Access** Email OTP allowlist; switches to `public` at the **same URL** upon release. `structure-atlas-private.pages.dev` serves as the owner-only internal staging workbench. |
| **Zenodo** (`sandbox.zenodo.org` → `zenodo.org`) | **Immutable Data Archive & DOI Authority** | Full scientific payloads (`models.tar.gz`, 3-tier regularized `model_scores.csv` / `residue_scores.csv` / `ensemble_scores.csv`, `score_manifest.json`, `manifest.json`, `CITATION.cff`, `sequence.fasta`). | **Sandbox** for pre-release draft review; **Production** mints permanent Concept + Version DOIs (versionable for future score/code updates). |
| **Local External SSD Mirror** (`structure-clustering sync-ssd`) | **Local Read-Only Mirror** | Verbatim `0444` download of Zenodo depositions, verified by MD5 + SHA-256 and tracked in `mirror-registry.json`. | Local workstation mirror; paired with cluster archive + Zenodo Production DOI as the 3-receipt gate before ephemeral scratch retirement. |

GitHub Pages is retired for Structure Clustering projects (preserving legacy `SCHERAGA_POSTER`).

## Repository Layout

- `targets/<target_id>.json` — One canonical **Target Record** per released
  biological target (`sequence_sha256`, `owner_project`, `projects[]`,
  `zenodo_concept_doi`, `current_release`, and immutable `releases[]`).
- `projects/<project_id>.json` — One **Project Registry** per scientific
  project (`canonical_site`, `access_mode`, optional `staged_targets[]` live on
  the project's private Cloudflare Pages portal, and ordered linked-list
  `targets[]` of graduated, Zenodo-pinned releases).
- `schemas/` — JSON Schemas for Target Records and Project Registries.
- `scripts/validate_registry.py` — Deterministic cross-reference, linked-list,
  DOI, SHA-256, and privacy validator enforced in CI.

## Validation

```bash
python3 scripts/validate_registry.py
pytest -q
```
