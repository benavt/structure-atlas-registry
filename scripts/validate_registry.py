#!/usr/bin/env python3
"""Deterministic validator for Target Records and Project Registries.

Checks:
1. All `targets/*.json` conform to Target Record structure, valid SHA-256 hex,
   DOI syntax, unique release versions, and `current_release` membership.
2. All `projects/*.json` conform to Project Registry structure, valid linked-list
   pointers (`prev_target_id` / `next_target_id`), and every referenced target +
   release version + Zenodo Version DOI resolves cleanly against `targets/*.json`.
3. Zero private filesystem paths, hostnames, or credential-shaped strings appear
   anywhere in the public registry.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
DOI_RE = re.compile(r"^10\.5281/zenodo\.[0-9]+$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
PROJ_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")

PRIVATE_LEAK_RE = re.compile(
    r"(/Users/|/home/|/scratch/|/data/montelione|(?i:paxmundane)|(?i:(?:^|[^a-z])mimas(?:[^a-z]|$))|ghp_|github_pat_|AKIA[0-9A-Z]{16})"
)


class RegistryValidationError(ValueError):
    """Raised when the registry fails schema, cross-reference, or privacy checks."""


def _check_privacy(text: str, rel_path: str) -> None:
    match = PRIVATE_LEAK_RE.search(text)
    if match:
        raise RegistryValidationError(
            f"Privacy violation in {rel_path}: matched prohibited pattern {match.group(0)!r}"
        )


def _load_json(path: Path, root: Path) -> dict[str, Any]:
    rel = str(path.relative_to(root))
    raw = path.read_text(encoding="utf-8")
    _check_privacy(raw, rel)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RegistryValidationError(f"{rel} must contain a top-level JSON object")
    return data


def validate_target_record(data: dict[str, Any], filename_stem: str) -> dict[str, dict[str, Any]]:
    if data.get("schema_version") != 1:
        raise RegistryValidationError(f"targets/{filename_stem}.json: schema_version must be 1")
    tid = str(data.get("target_id", ""))
    if tid != filename_stem or not ID_RE.fullmatch(tid):
        raise RegistryValidationError(
            f"targets/{filename_stem}.json: target_id {tid!r} must match filename and regex"
        )
    owner = str(data.get("owner_project", ""))
    projects = data.get("projects") or []
    if not PROJ_ID_RE.fullmatch(owner) or owner not in projects:
        raise RegistryValidationError(
            f"targets/{filename_stem}.json: owner_project {owner!r} must be listed in projects"
        )
    construct = data.get("construct") or {}
    if not SHA256_RE.fullmatch(str(construct.get("sequence_sha256", ""))):
        raise RegistryValidationError(f"targets/{filename_stem}.json: invalid construct.sequence_sha256")
    if int(construct.get("length", 0)) < 1:
        raise RegistryValidationError(f"targets/{filename_stem}.json: construct.length must be >= 1")

    concept_doi = data.get("zenodo_concept_doi")
    if concept_doi is not None and not DOI_RE.fullmatch(str(concept_doi)):
        raise RegistryValidationError(f"targets/{filename_stem}.json: invalid zenodo_concept_doi {concept_doi!r}")

    releases = data.get("releases") or []
    if not releases:
        raise RegistryValidationError(f"targets/{filename_stem}.json: must have at least one release")
    by_version: dict[str, dict[str, Any]] = {}
    for rel in releases:
        ver = str(rel.get("version", ""))
        if not SEMVER_RE.fullmatch(ver) or ver in by_version:
            raise RegistryValidationError(f"targets/{filename_stem}.json: invalid or duplicate release version {ver!r}")
        if not DATE_RE.fullmatch(str(rel.get("released_at", ""))):
            raise RegistryValidationError(f"targets/{filename_stem}.json ({ver}): invalid released_at")
        sc = rel.get("structure_clustering") or {}
        if not sc.get("tag") or not COMMIT_RE.fullmatch(str(sc.get("commit", ""))):
            raise RegistryValidationError(f"targets/{filename_stem}.json ({ver}): invalid structure_clustering pin")
        zen = rel.get("zenodo") or {}
        if zen.get("environment") not in {"sandbox", "production"}:
            raise RegistryValidationError(f"targets/{filename_stem}.json ({ver}): invalid zenodo.environment")
        if not DOI_RE.fullmatch(str(zen.get("version_doi", ""))):
            raise RegistryValidationError(f"targets/{filename_stem}.json ({ver}): invalid zenodo.version_doi")
        if not SHA256_RE.fullmatch(str(zen.get("package_sha256", ""))):
            raise RegistryValidationError(f"targets/{filename_stem}.json ({ver}): invalid zenodo.package_sha256")
        sb = rel.get("score_bundle") or {}
        if sb.get("schema_version") != 1 or not SHA256_RE.fullmatch(str(sb.get("manifest_sha256", ""))):
            raise RegistryValidationError(f"targets/{filename_stem}.json ({ver}): invalid score_bundle")
        if not str(rel.get("canonical_url", "")).startswith("https://"):
            raise RegistryValidationError(f"targets/{filename_stem}.json ({ver}): canonical_url must use https://")
        if not SHA256_RE.fullmatch(str(rel.get("site_bundle_sha256", ""))):
            raise RegistryValidationError(f"targets/{filename_stem}.json ({ver}): invalid site_bundle_sha256")
        by_version[ver] = rel

    if data.get("current_release") not in by_version:
        raise RegistryValidationError(
            f"targets/{filename_stem}.json: current_release {data.get('current_release')!r} not in releases[]"
        )
    return by_version


def validate_project_registry(
    data: dict[str, Any],
    filename_stem: str,
    target_releases: dict[str, dict[str, dict[str, Any]]],
) -> int:
    if data.get("schema_version") != 1:
        raise RegistryValidationError(f"projects/{filename_stem}.json: schema_version must be 1")
    pid = str(data.get("project_id", ""))
    if pid != filename_stem or not PROJ_ID_RE.fullmatch(pid):
        raise RegistryValidationError(
            f"projects/{filename_stem}.json: project_id {pid!r} must match filename and regex"
        )
    if not str(data.get("canonical_site", "")).startswith("https://"):
        raise RegistryValidationError(f"projects/{filename_stem}.json: canonical_site must use https://")

    entries = data.get("targets")
    if not isinstance(entries, list):
        raise RegistryValidationError(f"projects/{filename_stem}.json: targets must be a list")

    seen: set[str] = set()
    for idx, entry in enumerate(entries):
        tid = str(entry.get("target_id", ""))
        if tid in seen:
            raise RegistryValidationError(f"projects/{filename_stem}.json: duplicate target_id {tid!r}")
        seen.add(tid)

        expected_prev = entries[idx - 1]["target_id"] if idx > 0 else None
        expected_next = entries[idx + 1]["target_id"] if idx + 1 < len(entries) else None
        if entry.get("prev_target_id") != expected_prev:
            raise RegistryValidationError(
                f"projects/{filename_stem}.json ({tid}): prev_target_id={entry.get('prev_target_id')!r}, expected {expected_prev!r}"
            )
        if entry.get("next_target_id") != expected_next:
            raise RegistryValidationError(
                f"projects/{filename_stem}.json ({tid}): next_target_id={entry.get('next_target_id')!r}, expected {expected_next!r}"
            )

        ver = str(entry.get("release_version", ""))
        if tid not in target_releases or ver not in target_releases[tid]:
            raise RegistryValidationError(
                f"projects/{filename_stem}.json ({tid}): references unknown target release {tid}@{ver}"
            )
        target_rel = target_releases[tid][ver]
        if entry.get("zenodo_version_doi") != target_rel["zenodo"]["version_doi"]:
            raise RegistryValidationError(
                f"projects/{filename_stem}.json ({tid}): zenodo_version_doi does not match Target Record"
            )
        if not str(entry.get("target_url", "")).startswith("https://"):
            raise RegistryValidationError(f"projects/{filename_stem}.json ({tid}): target_url must use https://")

    return len(entries)


def validate_registry(root: Path | str) -> dict[str, Any]:
    root_path = Path(root)
    targets_dir = root_path / "targets"
    projects_dir = root_path / "projects"

    target_releases: dict[str, dict[str, dict[str, Any]]] = {}
    if targets_dir.is_dir():
        for path in sorted(targets_dir.glob("*.json")):
            data = _load_json(path, root_path)
            target_releases[path.stem] = validate_target_record(data, path.stem)

    project_counts: dict[str, int] = {}
    if projects_dir.is_dir():
        for path in sorted(projects_dir.glob("*.json")):
            data = _load_json(path, root_path)
            project_counts[path.stem] = validate_project_registry(data, path.stem, target_releases)

    return {
        "targets_validated": len(target_releases),
        "projects_validated": len(project_counts),
        "project_target_links": project_counts,
    }


def main(argv: list[str] | None = None) -> int:
    root = Path(argv[0]) if argv else Path(__file__).resolve().parent.parent
    try:
        summary = validate_registry(root)
        print(json.dumps(summary, indent=2))
        return 0
    except (RegistryValidationError, OSError, json.JSONDecodeError) as exc:
        print(f"Registry validation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
