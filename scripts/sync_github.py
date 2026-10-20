#!/usr/bin/env python3
"""Synchronise labels, jalons (milestones) et issues GitHub depuis project/roadmap.yml.

Idempotent : relancer ne crée aucun doublon. S'appuie uniquement sur l'API REST
GitHub (aucune dépendance à `gh`). Seule dépendance externe : PyYAML.

Exemples :
  python scripts/sync_github.py --dry-run
  python scripts/sync_github.py
  python scripts/sync_github.py --update          # met à jour les issues existantes
  python scripts/sync_github.py --only m0,m1      # limite à certains jalons
  python scripts/sync_github.py --repo owner/nom  # force le dépôt cible
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML manquant. Installez-le :  pip install pyyaml")


API = "https://api.github.com"
DEFAULT_PLAN = Path(__file__).resolve().parent.parent / "project" / "roadmap.yml"


def detect_repo() -> str | None:
    try:
        url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return None
    if "github.com" not in url:
        return None
    if url.startswith("git@"):
        path = url.split(":", 1)[1]
    else:
        path = url.split("github.com/", 1)[1]
    if path.endswith(".git"):
        path = path[:-4]
    return path.strip("/")


class GitHub:
    def __init__(self, repo: str, token: str, dry_run: bool = False) -> None:
        self.repo = repo
        self.token = token
        self.dry_run = dry_run
        self.offline = dry_run and not token
        self.created = {"labels": 0, "milestones": 0, "issues": 0, "updated": 0, "closed": 0}

    def _call(self, method: str, path: str, data=None, allow_404: bool = False):
        url = path if path.startswith("http") else API + path
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "p9-roadmap-sync")
        if body:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            if allow_404 and exc.code == 404:
                return None
            detail = exc.read().decode()[:400]
            raise SystemExit(f"HTTP {exc.code} sur {method} {url}\n{detail}")

    def _paginate(self, path: str) -> list:
        if self.offline:
            return []
        results, url = [], API + path
        while url:
            req = urllib.request.Request(url)
            req.add_header("Accept", "application/vnd.github+json")
            req.add_header("Authorization", f"Bearer {self.token}")
            req.add_header("X-GitHub-Api-Version", "2022-11-28")
            req.add_header("User-Agent", "p9-roadmap-sync")
            with urllib.request.urlopen(req) as resp:
                results.extend(json.loads(resp.read().decode()))
                link = resp.headers.get("Link", "")
            url = None
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.split(";")[0].strip().strip("<>")
        return results

    def check(self) -> None:
        data = self._call("GET", f"/repos/{self.repo}")
        print(f"Dépôt cible : {data['full_name']}  (issues: {data.get('has_issues')})")
        if not data.get("has_issues", True):
            print("  ! Les issues sont désactivées sur ce dépôt (Settings > Features).")

    def sync_labels(self, labels: list[dict]) -> None:
        existing = {lbl["name"]: lbl for lbl in self._paginate(f"/repos/{self.repo}/labels?per_page=100")}
        for lbl in labels:
            name = lbl["name"]
            payload = {
                "name": name,
                "color": lbl.get("color", "ededed").lstrip("#"),
                "description": lbl.get("description", ""),
            }
            if name in existing:
                if any(existing[name].get(k) != payload[k] for k in ("color", "description")):
                    print(f"  ~ label màj  {name}")
                    if not self.dry_run:
                        self._call("PATCH", f"/repos/{self.repo}/labels/{name}", payload)
                continue
            print(f"  + label      {name}")
            self.created["labels"] += 1
            if not self.dry_run:
                self._call("POST", f"/repos/{self.repo}/labels", payload)

    def sync_milestones(self, milestones: list[dict]) -> dict[str, int]:
        existing = {m["title"]: m for m in self._paginate(f"/repos/{self.repo}/milestones?state=all&per_page=100")}
        mapping: dict[str, int] = {}
        for ms in milestones:
            title = ms["title"]
            mapping[ms["key"]] = existing[title]["number"] if title in existing else -1
            if title in existing:
                print(f"  = jalon      {title} (#{existing[title]['number']})")
                continue
            print(f"  + jalon      {title}")
            self.created["milestones"] += 1
            if not self.dry_run:
                payload = {"title": title, "description": ms.get("description", "")}
                if ms.get("due_on"):
                    payload["due_on"] = ms["due_on"]
                created = self._call("POST", f"/repos/{self.repo}/milestones", payload)
                mapping[ms["key"]] = created["number"]
        return mapping

    def sync_issues(self, issues: list[dict], ms_map: dict[str, int], update: bool) -> None:
        existing = {
            it["title"]: it
            for it in self._paginate(f"/repos/{self.repo}/issues?state=all&per_page=100")
            if "pull_request" not in it
        }
        for issue in issues:
            title = issue["title"]
            milestone = ms_map.get(issue.get("milestone"))
            if milestone == -1:
                milestone = None
            payload = {
                "title": title,
                "body": issue.get("body", ""),
                "labels": issue.get("labels", []),
            }
            if milestone:
                payload["milestone"] = milestone
            if issue.get("assignees"):
                payload["assignees"] = issue["assignees"]

            if title in existing:
                number = existing[title]["number"]
                if update:
                    print(f"  ~ issue màj  #{number} {title}")
                    self.created["updated"] += 1
                    if not self.dry_run:
                        self._call("PATCH", f"/repos/{self.repo}/issues/{number}", payload)
                else:
                    print(f"  = issue      #{number} {title}")
                continue
            print(f"  + issue      {title}")
            self.created["issues"] += 1
            if not self.dry_run:
                self._call("POST", f"/repos/{self.repo}/issues", payload)

    def close_completed(self, completed: list[str], scoped_titles: set[str]) -> None:
        if not completed:
            return
        existing = {
            it["title"]: it
            for it in self._paginate(f"/repos/{self.repo}/issues?state=all&per_page=100")
            if "pull_request" not in it
        }
        for title in completed:
            if scoped_titles and title not in scoped_titles:
                continue
            it = existing.get(title)
            if not it:
                print(f"  ! terminée mais introuvable : {title}")
                continue
            if it["state"] == "closed":
                print(f"  = déjà fermée  #{it['number']} {title}")
                continue
            print(f"  \u2713 fermée      #{it['number']} {title}")
            self.created["closed"] += 1
            if not self.dry_run:
                self._call("PATCH", f"/repos/{self.repo}/issues/{it['number']}", {"state": "closed"})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synchronise la roadmap GitHub du Projet 9.")
    parser.add_argument("--repo", help="owner/nom (défaut : remote git origin)")
    parser.add_argument("--plan", default=str(DEFAULT_PLAN), help="chemin du fichier YAML de roadmap")
    parser.add_argument("--token", default=os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--only", help="liste de clés de jalons à limiter, ex: m0,m1")
    parser.add_argument("--update", action="store_true", help="mettre à jour les issues existantes")
    parser.add_argument("--dry-run", action="store_true", help="afficher sans rien modifier")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    plan_path = Path(args.plan)
    if not plan_path.exists():
        sys.exit(f"Fichier introuvable : {plan_path}")
    plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))

    repo = args.repo or detect_repo()
    if not repo:
        sys.exit("Dépôt introuvable. Utilisez --repo owner/nom ou configurez git remote origin.")
    if not args.token and not args.dry_run:
        sys.exit("Token manquant. export GH_TOKEN=... (scope repo / Issues: write)")

    only = {s.strip() for s in args.only.split(",")} if args.only else None

    milestones = plan.get("milestones", [])
    milestones = [m for m in milestones if not only or m["key"] in only]
    allowed = {m["key"] for m in milestones}
    issues = [i for i in plan.get("issues", []) if i.get("milestone") in allowed]

    print(f"Mode : {'DRY-RUN (aucune écriture)' if args.dry_run else 'ÉCRITURE'}")
    gh = GitHub(repo, args.token or "", dry_run=args.dry_run)
    if not args.dry_run:
        gh.check()

    print("\n[1/4] Labels")
    gh.sync_labels(plan.get("labels", []))

    print("\n[2/4] Jalons")
    ms_map = gh.sync_milestones(milestones)

    print("\n[3/4] Issues")
    gh.sync_issues(issues, ms_map, update=args.update)

    print("\n[4/4] État (issues terminées listées dans roadmap.yml)")
    gh.close_completed(plan.get("completed", []), {i["title"] for i in issues})

    print(
        "\nRésumé : "
        f"{gh.created['labels']} label(s), {gh.created['milestones']} jalon(s), "
        f"{gh.created['issues']} issue(s), {gh.created['updated']} mise(s) à jour, "
        f"{gh.created['closed']} fermeture(s)."
    )
    if args.dry_run:
        print("(dry-run : rien n'a été créé)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
