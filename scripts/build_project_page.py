#!/usr/bin/env python3
"""Validate a per-project Structure Atlas repository and build its static Project Page.

Expected project repository layout:
  project.json
  targets/<target_id>/target.json
  targets/<target_id>/{scores,clustering,representatives,ensembles,reports}/...

Checks:
1. `project.json` and all `targets/*/target.json` conform to schema_version=1.
2. Every referenced local artifact path is relative, stays inside the repo, exists,
   and matches its declared SHA-256 checksum.
3. Zero private filesystem paths, cluster hostnames, tokens, or email addresses
   appear in any JSON/text/CSV/HTML artifact.
4. Generates a self-contained static `index.html` listing every target's scores,
   clustering artifacts, final reports, representatives, selected ensembles,
   Zenodo DOI, and interactive Cloudflare Pages Atlas link.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import sys
from typing import Any

from validate_registry import (
    DOI_RE,
    ID_RE,
    PRIVATE_LEAK_RE,
    PROJ_ID_RE,
    SHA256_RE,
    RegistryValidationError,
)

TEXT_SUFFIXES = {".json", ".csv", ".tsv", ".txt", ".md", ".html", ".yml", ".yaml", ".pdb", ".cif"}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_relpath(base: Path, rel: str, context: str) -> Path:
    if not isinstance(rel, str) or not rel or rel.startswith("/") or "\\" in rel:
        raise RegistryValidationError(f"{context}: invalid relative path {rel!r}")
    parts = Path(rel).parts
    if any(p in {"..", "."} for p in parts):
        raise RegistryValidationError(f"{context}: path traversal not allowed ({rel!r})")
    resolved = (base / rel).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError as exc:
        raise RegistryValidationError(f"{context}: path escapes base directory ({rel!r})") from exc
    if not resolved.is_file():
        raise RegistryValidationError(f"{context}: referenced file missing ({rel!r})")
    return resolved


def _check_file_privacy(path: Path, rel_display: str) -> None:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    match = PRIVATE_LEAK_RE.search(text)
    if match:
        raise RegistryValidationError(
            f"Privacy violation in {rel_display}: matched prohibited pattern {match.group(0)!r}"
        )


def _verify_artifact(target_dir: Path, rel_path: str, expected_sha: str, context: str) -> str:
    if not SHA256_RE.fullmatch(str(expected_sha)):
        raise RegistryValidationError(f"{context}: invalid sha256 {expected_sha!r}")
    resolved = _safe_relpath(target_dir, rel_path, context)
    actual = _sha256(resolved)
    if actual != expected_sha:
        raise RegistryValidationError(
            f"{context}: sha256 mismatch for {rel_path} (expected {expected_sha}, got {actual})"
        )
    _check_file_privacy(resolved, f"{target_dir.name}/{rel_path}")
    return actual


def validate_project_repo(repo_root: Path | str) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    project_file = root / "project.json"
    if not project_file.is_file():
        raise RegistryValidationError("Missing project.json at repository root")
    _check_file_privacy(project_file, "project.json")
    project = json.loads(project_file.read_text(encoding="utf-8"))
    if project.get("schema_version") != 1:
        raise RegistryValidationError("project.json: schema_version must be 1")
    pid = str(project.get("project_id", ""))
    if not PROJ_ID_RE.fullmatch(pid):
        raise RegistryValidationError(f"project.json: invalid project_id {pid!r}")
    if not str(project.get("title", "")).strip():
        raise RegistryValidationError("project.json: title is required")
    canonical_site = project.get("canonical_site")
    if canonical_site is not None and not str(canonical_site).startswith("https://"):
        raise RegistryValidationError("project.json: canonical_site must start with https://")

    targets_root = root / "targets"
    targets: list[dict[str, Any]] = []
    seen: set[str] = set()
    if targets_root.is_dir():
        for manifest_path in sorted(targets_root.glob("*/target.json")):
            target_dir = manifest_path.parent
            folder_id = target_dir.name
            _check_file_privacy(manifest_path, f"targets/{folder_id}/target.json")
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if data.get("schema_version") != 1:
                raise RegistryValidationError(f"targets/{folder_id}/target.json: schema_version must be 1")
            tid = str(data.get("target_id", ""))
            if tid != folder_id or not ID_RE.fullmatch(tid) or tid in seen:
                raise RegistryValidationError(f"targets/{folder_id}/target.json: invalid or duplicate target_id {tid!r}")
            seen.add(tid)
            if int(data.get("model_count", 0)) < 1:
                raise RegistryValidationError(f"targets/{folder_id}/target.json: model_count must be >= 1")
            if data.get("interactive_atlas_url") is not None and not str(data["interactive_atlas_url"]).startswith("https://"):
                raise RegistryValidationError(f"targets/{folder_id}/target.json: interactive_atlas_url must use https://")
            if data.get("zenodo_doi") is not None and not DOI_RE.fullmatch(str(data["zenodo_doi"])):
                raise RegistryValidationError(f"targets/{folder_id}/target.json: invalid zenodo_doi")

            for sc in data.get("scores") or []:
                if sc.get("tier") not in {"model", "residue", "ensemble"}:
                    raise RegistryValidationError(f"targets/{folder_id}: invalid score tier {sc.get('tier')!r}")
                _verify_artifact(target_dir, sc["path"], sc["sha256"], f"targets/{folder_id} score {sc.get('id')}")

            cl = data.get("clustering") or {}
            _verify_artifact(target_dir, cl["memberships_path"], cl["memberships_sha256"], f"targets/{folder_id} clustering.memberships")
            if cl.get("summary_path"):
                _verify_artifact(target_dir, cl["summary_path"], cl.get("summary_sha256", ""), f"targets/{folder_id} clustering.summary")

            for rep in data.get("representatives") or []:
                _verify_artifact(target_dir, rep["path"], rep["sha256"], f"targets/{folder_id} representative {rep.get('cluster')}")

            for ens in data.get("ensembles") or []:
                _verify_artifact(target_dir, ens["path"], ens["sha256"], f"targets/{folder_id} ensemble {ens.get('label')}")

            for rpt in data.get("reports") or []:
                if rpt.get("path"):
                    _verify_artifact(target_dir, rpt["path"], rpt["sha256"], f"targets/{folder_id} report {rpt.get('title')}")
                elif rpt.get("release_url"):
                    if not str(rpt["release_url"]).startswith("https://"):
                        raise RegistryValidationError(f"targets/{folder_id} report: release_url must use https://")
                    if not SHA256_RE.fullmatch(str(rpt.get("sha256", ""))):
                        raise RegistryValidationError(f"targets/{folder_id} report: invalid sha256")
                else:
                    raise RegistryValidationError(f"targets/{folder_id} report: must specify path or release_url")

            targets.append(data)

    return {"project": project, "targets": targets}


def render_project_page(validated: dict[str, Any]) -> str:
    project = validated["project"]
    targets = validated["targets"]
    esc = html.escape

    title = esc(project["title"])
    desc = esc(project.get("description", "Canonical project target registry, scores, clustering outputs, reports, and selected ensembles."))
    canonical_site = project.get("canonical_site")
    site_cta = (
        f'<a class="btn" href="{esc(canonical_site)}" target="_blank" rel="noopener">Open Interactive Cloudflare Atlas &rarr;</a>'
        if canonical_site
        else ""
    )

    cards: list[str] = []
    for t in targets:
        tid = esc(t["target_id"])
        tprefix = f"targets/{tid}/"
        scopes = ", ".join(esc(s) for s in (t.get("residue_scopes") or [])) or "Full construct"

        score_links = "".join(
            f'<li><a href="{esc(tprefix + s["path"])}" download>{esc(s["label"])}</a> '
            f'<span class="tag">{esc(s["tier"])}</span></li>'
            for s in (t.get("scores") or [])
        ) or '<li class="muted">None declared</li>'

        cl = t["clustering"]
        cl_links = [f'<li><a href="{esc(tprefix + cl["memberships_path"])}" download>Cluster memberships</a></li>']
        if cl.get("summary_path"):
            cl_links.append(f'<li><a href="{esc(tprefix + cl["summary_path"])}" download>Clustering summary</a></li>')
        cl_html = "".join(cl_links)

        rep_links = "".join(
            f'<li><a href="{esc(tprefix + r["path"])}" download>{esc(r["cluster"])}: {esc(r["model_id"])}</a></li>'
            for r in (t.get("representatives") or [])
        ) or '<li class="muted">None declared</li>'

        ens_links = "".join(
            f'<li><a href="{esc(tprefix + e["path"])}" download>{esc(e["label"])} ({esc(e["method"])}, {int(e["model_count"])} models)</a></li>'
            for e in (t.get("ensembles") or [])
        ) or '<li class="muted">None declared</li>'

        rpt_links = "".join(
            f'<li><a href="{esc(tprefix + r["path"] if r.get("path") else r["release_url"])}" '
            f'{"download" if r.get("path") else "target=_blank rel=noopener"}>{esc(r["title"])}</a></li>'
            for r in (t.get("reports") or [])
        ) or '<li class="muted">None declared</li>'

        badges = []
        if t.get("interactive_atlas_url"):
            badges.append(f'<a class="btn-sm" href="{esc(t["interactive_atlas_url"])}" target="_blank" rel="noopener">Interactive Atlas</a>')
        if t.get("zenodo_doi"):
            doi = esc(t["zenodo_doi"])
            badges.append(f'<a class="btn-sm ghost" href="https://doi.org/{doi}" target="_blank" rel="noopener">Zenodo {doi}</a>')

        cards.append(
            f"""<article class="card" data-target="{tid}">
  <header class="card-head">
    <div>
      <h2>{esc(t["display_name"])} <span class="mono">{tid}</span></h2>
      <p class="meta">{int(t["model_count"]):,} models &middot; Cohort <code>{esc(t["cohort_id"])}</code> &middot; Scopes: {scopes}</p>
    </div>
    <div class="actions">{"".join(badges)}</div>
  </header>
  <div class="grid">
    <div><h3>Scores</h3><ul>{score_links}</ul></div>
    <div><h3>Clustering</h3><ul>{cl_html}</ul></div>
    <div><h3>Reports</h3><ul>{rpt_links}</ul></div>
    <div><h3>Representatives</h3><ul>{rep_links}</ul></div>
    <div><h3>Selected Ensembles</h3><ul>{ens_links}</ul></div>
  </div>
</article>"""
        )

    body = "\n".join(cards) if cards else '<p class="empty">No targets registered in this project repository yet.</p>'
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} &middot; Target Registry</title>
<style>
  :root {{ --bg:#f8fafc; --fg:#0f172a; --muted:#475569; --card:#ffffff; --border:#e2e8f0; --accent:#0f4c81; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:system-ui,-apple-system,sans-serif; background:var(--bg); color:var(--fg); line-height:1.5; }}
  main {{ max-width:1120px; margin:0 auto; padding:2rem 1.25rem 4rem; }}
  .hero {{ display:flex; flex-wrap:wrap; justify-content:space-between; align-items:flex-end; gap:1rem; padding-bottom:1.5rem; border-bottom:1px solid var(--border); margin-bottom:1.5rem; }}
  .hero h1 {{ margin:0 0 .35rem; font-size:1.75rem; }}
  .hero p {{ margin:0; color:var(--muted); max-width:68ch; }}
  .btn, .btn-sm {{ display:inline-block; text-decoration:none; background:var(--accent); color:#fff; padding:.55rem .95rem; border-radius:8px; font-weight:600; font-size:.9rem; }}
  .btn-sm {{ padding:.35rem .7rem; font-size:.82rem; }}
  .btn-sm.ghost {{ background:transparent; color:var(--accent); border:1px solid var(--accent); }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:1.25rem; margin-bottom:1.25rem; }}
  .card-head {{ display:flex; flex-wrap:wrap; justify-content:space-between; gap:.75rem; align-items:flex-start; border-bottom:1px solid var(--border); padding-bottom:.85rem; margin-bottom:.9rem; }}
  .card-head h2 {{ margin:0; font-size:1.2rem; }}
  .mono {{ font-family:ui-monospace,monospace; font-size:.82rem; color:var(--muted); font-weight:400; margin-left:.35rem; }}
  .meta {{ margin:.25rem 0 0; color:var(--muted); font-size:.88rem; }}
  .actions {{ display:flex; gap:.5rem; flex-wrap:wrap; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(195px,1fr)); gap:1rem; }}
  .grid h3 {{ margin:0 0 .4rem; font-size:.85rem; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }}
  .grid ul {{ margin:0; padding-left:1.1rem; font-size:.88rem; }}
  .grid li {{ margin-bottom:.25rem; }}
  .tag {{ font-size:.72rem; background:#e2e8f0; color:#334155; padding:.1rem .4rem; border-radius:999px; }}
  .muted, .empty {{ color:var(--muted); }}
  a {{ color:var(--accent); }}
</style>
</head>
<body>
<main>
  <header class="hero">
    <div>
      <h1>{title}</h1>
      <p>{desc}</p>
    </div>
    <div>{site_cta}</div>
  </header>
  {body}
</main>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="Path to project repository root")
    parser.add_argument("--output", help="Optional output HTML path (e.g. _site/index.html)")
    args = parser.parse_args(argv)
    try:
        validated = validate_project_repo(args.repo)
    except RegistryValidationError as exc:
        print(f"PROJECT REGISTRY VALIDATION FAILED: {exc}", file=sys.stderr)
        return 1
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_project_page(validated), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "ok",
                "project_id": validated["project"]["project_id"],
                "targets_validated": len(validated["targets"]),
                "output": args.output,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
