"""Tests for `scripts/build_project_page.py`."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from build_project_page import render_project_page, validate_project_repo  # noqa: E402
from validate_registry import RegistryValidationError  # noqa: E402


def _write(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = content.encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _make_project_repo(root: Path, score_text: str = "model_id,energy,foxs_chi2\nm0,-12.5,4.75\n") -> Path:
    (root / "project.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "ls-ais",
                "title": "LS_AIS Structure Atlas",
                "description": "Project target registry.",
                "canonical_site": "https://ls-ais-structure-atlas.pages.dev/",
            }
        ),
        encoding="utf-8",
    )
    tdir = root / "targets" / "pdcd2"
    score_sha = _write(tdir / "scores/model_scores.csv", score_text)
    mem_sha = _write(tdir / "clustering/memberships.csv", "model_id,cluster\nm0,P0\n")
    rep_sha = _write(tdir / "representatives/P0.pdb", "ATOM      1  CA  MET A   1       0.000   0.000   0.000  1.00  0.00           C\nEND\n")
    ens_sha = _write(tdir / "ensembles/S1_mcmc50.pdb", "MODEL        1\nENDMDL\n")
    rpt_sha = _write(tdir / "reports/summary.pdf", "%PDF-1.4\n%%EOF\n")

    (tdir / "target.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "target_id": "pdcd2",
                "display_name": "PDCD2",
                "cohort_id": "complete-11000",
                "model_count": 11000,
                "residue_scopes": ["A:1-364", "A:120-170 + A:220-270"],
                "interactive_atlas_url": "https://ls-ais-structure-atlas.pages.dev/targets/pdcd2/",
                "zenodo_doi": "10.5281/zenodo.1234567",
                "scores": [
                    {
                        "id": "proteinebm_foxs",
                        "label": "ProteinEBM & FoXS χ²",
                        "tier": "model",
                        "path": "scores/model_scores.csv",
                        "sha256": score_sha,
                    }
                ],
                "clustering": {
                    "memberships_path": "clustering/memberships.csv",
                    "memberships_sha256": mem_sha,
                    "cluster_count": 8,
                    "state_count": 1,
                },
                "representatives": [
                    {
                        "cluster": "P0",
                        "model_id": "afsample2__0904",
                        "path": "representatives/P0.pdb",
                        "sha256": rep_sha,
                    }
                ],
                "ensembles": [
                    {
                        "label": "State S1",
                        "state": "S1",
                        "method": "MCMC",
                        "model_count": 50,
                        "path": "ensembles/S1_mcmc50.pdb",
                        "sha256": ens_sha,
                    }
                ],
                "reports": [
                    {
                        "title": "PDCD2 Final Report",
                        "path": "reports/summary.pdf",
                        "pages": 12,
                        "sha256": rpt_sha,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return root


def test_valid_project_repo_renders_page(tmp_path: Path) -> None:
    _make_project_repo(tmp_path)
    validated = validate_project_repo(tmp_path)
    assert len(validated["targets"]) == 1
    html_out = render_project_page(validated)
    assert "PDCD2" in html_out
    assert "targets/pdcd2/scores/model_scores.csv" in html_out
    assert "targets/pdcd2/ensembles/S1_mcmc50.pdb" in html_out
    assert "10.5281/zenodo.1234567" in html_out


def test_privacy_leak_in_score_csv_rejected(tmp_path: Path) -> None:
    _make_project_repo(tmp_path, score_text="model_id,path\nm0,/scratch/benavt/secret.pdb\n")
    with pytest.raises(RegistryValidationError, match="Privacy violation"):
        validate_project_repo(tmp_path)


def test_sha256_mismatch_rejected(tmp_path: Path) -> None:
    _make_project_repo(tmp_path)
    (tmp_path / "targets/pdcd2/scores/model_scores.csv").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="sha256 mismatch"):
        validate_project_repo(tmp_path)


def test_path_traversal_rejected(tmp_path: Path) -> None:
    _make_project_repo(tmp_path)
    manifest = tmp_path / "targets/pdcd2/target.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["scores"][0]["path"] = "../project.json"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RegistryValidationError, match="path traversal"):
        validate_project_repo(tmp_path)
