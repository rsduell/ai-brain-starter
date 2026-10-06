#!/usr/bin/env python3
"""Check anchored facts against the code they describe. Rules: brain/RULES.md → Codebase facts.

Usage:
	python3 scripts/check_facts.py                   every `anchored: true` note in the brain folder
	python3 scripts/check_facts.py <note.md> ...     specific notes
	options:
		--fetch                 `git fetch origin` in each referenced repo first (default: offline)
		--repo name=path        where a repo lives (overrides brain.json)

Anchors are `repo:path`, `repo:symbol:NAME`, or `repo@branch:path` for work that has not reached
the default branch yet. Each fact gets a status:
	ok           anchors exist on origin/HEAD (or origin/<branch>) and are unchanged since the verified SHA
	changed      an anchor file changed since the verified SHA (commits listed, with "(#N)" PR numbers)
	missing      an anchor file or symbol is gone
	recheck due  a fact without anchors is past its recheck date
	malformed    unknown repo, unknown SHA, branch gone, or nothing to check
Prints only facts that are not ok. Never edits notes; exit code is always 0.
"""
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainconfig  # noqa: E402
from lint_brain import parse_facts, parse_frontmatter  # noqa: E402

PR_RE = re.compile(r"\(#(\d+)\)")
ORDER = ["malformed", "missing", "changed", "recheck due", "ok"]


def git(path, *args):
	return subprocess.run(["git", "-C", str(path)] + list(args), capture_output=True, text=True)


def resolve_ref(path):
	"""origin/HEAD's branch (origin/main, origin/master), else HEAD."""
	r = git(path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
	return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "HEAD"


def repo_info(key, path):
	"""key is `repo` (origin/HEAD) or `repo@branch` (origin/<branch>, else a local <branch>)."""
	_, _, branch = key.partition("@")
	ref = resolve_ref(path)
	if branch:
		ref = next((c for c in ("origin/" + branch, branch)
			if git(path, "rev-parse", "--verify", "-q", c).returncode == 0), None)
	r = git(path, "log", "-1", "--format=%h %cs", ref) if ref else None
	sha, date = (r.stdout.split() + ["?", "?"])[:2] if r is not None and r.returncode == 0 else ("?", "?")
	return {"name": key, "path": path, "ref": ref, "sha": sha, "date": date}


def check_fact(fact, repos, today):
	"""Return (status, [detail lines])."""
	if not fact["anchors"]:
		if fact["recheck"]:
			return ("recheck due", ["recheck date %s" % fact["recheck"]]) if fact["recheck"] <= today else ("ok", [])
		return "malformed", ["no anchors and no recheck date"]
	worst = "ok"
	details = []

	def bump(status):
		nonlocal worst
		if ORDER.index(status) < ORDER.index(worst):
			worst = status

	for repo, kind, value in fact["anchors"]:
		info = repos.get(repo)
		sha = fact["verified"].get(repo)
		if info is None:
			bump("malformed")
			details.append("unknown repo `%s` (add it to brain.json repos)" % repo)
			continue
		if info["ref"] is None:
			bump("malformed")
			details.append("%s: branch not found (merged or deleted?); re-anchor the fact" % repo)
			continue
		if not sha or git(info["path"], "cat-file", "-e", sha + "^{commit}").returncode != 0:
			bump("malformed")
			details.append("%s: verified SHA `%s` not found" % (repo, sha))
			continue
		ref = info["ref"]
		if kind == "symbol":
			if git(info["path"], "grep", "-q", "-w", value, ref, "--").returncode != 0:
				bump("missing")
				details.append("%s: symbol `%s` no longer on %s" % (repo, value, ref))
			continue
		if git(info["path"], "cat-file", "-e", "%s:%s" % (ref, value)).returncode != 0:
			bump("missing")
			details.append("%s: `%s` no longer on %s" % (repo, value, ref))
			continue
		if git(info["path"], "diff", "--quiet", sha, ref, "--", value).returncode == 1:
			bump("changed")
			details.append("%s: `%s` changed since %s:" % (repo, value, sha))
			log = git(info["path"], "log", "--format=%h %s", "%s..%s" % (sha, ref), "--", value).stdout
			for entry in log.strip().splitlines()[:10]:
				pr = PR_RE.search(entry)
				details.append("    %s%s" % (entry, "  [PR #%s]" % pr.group(1) if pr else ""))
	return worst, details


def anchored_notes(root, cfg):
	out = []
	for p in sorted(Path(root, cfg["brain_dir"]).rglob("*.md")):
		meta, _ = parse_frontmatter(p.read_text(encoding="utf-8").split("\n"))
		if meta.get("anchored", ("", 0))[0] == "true":
			out.append(p)
	return out


def check(root, note_paths, cfg, today=None, fetch=False):
	"""Return (repo infos used, [result dicts]) for the given notes."""
	today = today or datetime.date.today().isoformat()
	facts = [(Path(p), f) for p in note_paths for f in parse_facts(Path(p).read_text(encoding="utf-8"))]
	repos = {}
	for key in sorted({a[0] for _, f in facts for a in f["anchors"]}):
		path = brainconfig.repo_path(cfg, key.partition("@")[0])
		if git(path, "rev-parse").returncode != 0:
			continue
		if fetch:
			git(path, "fetch", "--quiet", "origin")
		repos[key] = repo_info(key, path)
	results = []
	for p, f in facts:
		status, details = check_fact(f, repos, today)
		results.append({"path": p, "line": f["line"], "heading": f["heading"], "status": status, "details": details})
	return repos, results


def main(argv):
	root = brainconfig.ROOT
	cfg = brainconfig.load(root)
	fetch = False
	notes = []
	i = 0
	while i < len(argv):
		arg = argv[i]
		if arg == "--fetch":
			fetch = True
		elif arg == "--repo":
			name, _, path = argv[i + 1].partition("=")
			cfg["repos"] = dict(cfg["repos"], **{name: path})
			i += 1
		elif arg in ("-h", "--help"):
			print(__doc__)
			return 0
		else:
			notes.append(Path(arg))
		i += 1
	repos, results = check(root, notes or anchored_notes(root, cfg), cfg, fetch=fetch)
	for info in repos.values():
		print("%-26s %-26s %-10s %s" % (info["name"], info["ref"] or "(branch not found)", info["sha"], info["date"]))
	flagged = [r for r in results if r["status"] != "ok"]
	for r in sorted(flagged, key=lambda r: (ORDER.index(r["status"]), str(r["path"]), r["line"])):
		rel = os.path.relpath(r["path"], root) if Path(r["path"]).is_absolute() else r["path"]
		print("%s:%d  %s  %s" % (rel, r["line"], r["status"], r["heading"]))
		for d in r["details"]:
			print("    " + d)
	print("%d facts checked, %d need attention." % (len(results), len(flagged)))
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
