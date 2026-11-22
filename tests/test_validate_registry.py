"""Tests for `scripts/validate_registry.py`."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from validate_registry import RegistryValidationError, validate_registry  # noqa: E402


def _make_target(target_id: str, owner: str, projects: list[str], doi: str) -> dict:
    return {
        "schema_version": 1,
        "target_id": target_id,
        "display_name": target_id.upper(),
        "accession": {"pdb": target_id.upper(), "uniprot": None, "bmrb": None},
        "construct": {"sequence_sha256": "a" * 64, "length": 150, "notes": "test"},
        "owner_project": owner,
        "projects": projects,
        "zenodo_concept_doi": "10.5281/zenodo.1000000",
        "current_release": "1.0.0",
        "releases": [
            {
                "version": "1.0.0",
                "released_at": "2026-11-22",
                "cohort_id": f"{target_id}-11k",
                "model_count": 11000,
                "structure_clustering": {
                    "tag": "v0.2.0",
                    "commit": "b" * 40,
                    "zenodo_doi": "10.5281/zenodo.9999999",
                },
                "zenodo": {
                    "environment": "production",
                    "version_doi": doi,
                    "url": f"https://doi.org/{doi}",
                    "package_sha256": "c" * 64,
                },
                "score_bundle": {
                    "schema_version": 1,
                    "manifest_sha256": "d" * 64,
                    "tiers": ["model", "residue", "ensemble"],
                },
                "canonical_url": f"https://jernigan-structure-atlas.pages.dev/targets/{target_id}/",
                "site_bundle_sha256": "e" * 64,
            }
        ],
    }


def test_repo_registry_is_valid() -> None:
    root = Path(__file__).resolve().parent.parent
    summary = validate_registry(root)
    assert summary["projects_validated"] == 5


def test_linked_list_and_cross_project_reuse(tmp_path: Path) -> None:
    (tmp_path / "targets").mkdir()
    (tmp_path / "projects").mkdir()
    (tmp_path / "targets" / "2j5x.json").write_text(
        json.dumps(_make_target("2j5x", "jernigan", ["jernigan"], "10.5281/zenodo.1000001")),
        encoding="utf-8",
    )
    (tmp_path / "targets" / "2jk4.json").write_text(
        json.dumps(_make_target("2jk4", "jernigan", ["jernigan", "domenico"], "10.5281/zenodo.1000002")),
        encoding="utf-8",
    )
    (tmp_path / "projects" / "jernigan.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "jernigan",
                "title": "Jernigan",
                "repository": "benavt/Jernigan",
                "canonical_site": "https://jernigan-structure-atlas.pages.dev/",
                "targets": [
                    {
                        "target_id": "2j5x",
                        "release_version": "1.0.0",
                        "zenodo_concept_doi": "10.5281/zenodo.1000000",
                        "zenodo_version_doi": "10.5281/zenodo.1000001",
                        "target_url": "https://jernigan-structure-atlas.pages.dev/targets/2j5x/",
                        "prev_target_id": None,
                        "next_target_id": "2jk4",
                    },
                    {
                        "target_id": "2jk4",
                        "release_version": "1.0.0",
                        "zenodo_concept_doi": "10.5281/zenodo.1000000",
                        "zenodo_version_doi": "10.5281/zenodo.1000002",
                        "target_url": "https://jernigan-structure-atlas.pages.dev/targets/2jk4/",
                        "prev_target_id": "2j5x",
                        "next_target_id": None,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "projects" / "domenico.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "domenico",
                "title": "Domenico",
                "repository": "benavt/domenico-targets",
                "canonical_site": "https://domenico-structure-atlas.pages.dev/",
                "targets": [
                    {
                        "target_id": "2jk4",
                        "release_version": "1.0.0",
                        "zenodo_concept_doi": "10.5281/zenodo.1000000",
                        "zenodo_version_doi": "10.5281/zenodo.1000002",
                        "target_url": "https://jernigan-structure-atlas.pages.dev/targets/2jk4/",
                        "prev_target_id": None,
                        "next_target_id": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    summary = validate_registry(tmp_path)
    assert summary["targets_validated"] == 2
    assert summary["project_target_links"] == {"domenico": 1, "jernigan": 2}


def test_broken_linked_list_rejected(tmp_path: Path) -> None:
    (tmp_path / "targets").mkdir()
    (tmp_path / "projects").mkdir()
    (tmp_path / "targets" / "2j5x.json").write_text(
        json.dumps(_make_target("2j5x", "jernigan", ["jernigan"], "10.5281/zenodo.1000001")),
        encoding="utf-8",
    )
    (tmp_path / "projects" / "jernigan.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "jernigan",
                "title": "Jernigan",
                "repository": "benavt/Jernigan",
                "canonical_site": "https://jernigan-structure-atlas.pages.dev/",
                "targets": [
                    {
                        "target_id": "2j5x",
                        "release_version": "1.0.0",
                        "zenodo_version_doi": "10.5281/zenodo.1000001",
                        "target_url": "https://jernigan-structure-atlas.pages.dev/targets/2j5x/",
                        "prev_target_id": "wrong",
                        "next_target_id": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RegistryValidationError, match="prev_target_id"):
        validate_registry(tmp_path)


def test_private_path_leak_rejected(tmp_path: Path) -> None:
    (tmp_path / "targets").mkdir()
    (tmp_path / "projects").mkdir()
    bad = _make_target("2j5x", "jernigan", ["jernigan"], "10.5281/zenodo.1000001")
    bad["construct"]["notes"] = "/Users/example/secret"
    (tmp_path / "targets" / "2j5x.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="Privacy violation"):
        validate_registry(tmp_path)
