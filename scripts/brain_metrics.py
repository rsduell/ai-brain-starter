#!/usr/bin/env python3
"""Measure whether a codebase cluster pays off, for its scheduled reviews. Rules: brain/RULES.md → Measuring.

Usage:
	python3 scripts/brain_metrics.py --cluster <Project>-Dev --since YYYY-MM-DD [--until YYYY-MM-DD]
	python3 scripts/brain_metrics.py --cluster <Project>-Dev --baseline

--since is the first day of the window (use the day after the previous review). Prints a Markdown
block to paste into the hub's review log:
	tags        issue log bullets in the window tagged [used: [[leaf]]], [rediscovered: [[leaf]]],
	            [miss], [why]
	relearned   facts that existed before the window and gained a source dated inside it
	            (a later ticket learned the same lesson again)
	flags       from git history of the cluster: rechecks that only bumped `verified:` (the change
	            flag was noise) vs new `[superseded` markers (the flag caught a real change)
	promotion   issue logs that closed (merged/done, updated in the window) vs those with `promoted:`
	cluster     facts now, new facts in the window, by scope
--baseline counts facts whose sources cite two or more issue logs (lessons learned more than once).
Run it once when a cluster is seeded, so later reviews have something to compare against.
Standard library only.
"""
import datetime
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainconfig  # noqa: E402
from lint_brain import parse_facts, parse_frontmatter  # noqa: E402

TAG_RE = re.compile(r"\[(used|rediscovered): \[\[([^\]|#]+)[^\]]*\]\]\]|\[(miss|why)\]")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
LOG_HEADING_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2})\s*$")


def source_cite_re(cfg):
	"""`[[AI PROJ-1]] 2026-10-01, 2026-10-03` → ("PROJ-1", " 2026-10-01, 2026-10-03")."""
	return re.compile(r"\[\[%s((?:%s))\]\]((?:[ ,]+(?:\d{4}-\d{2}-\d{2}|summary))*)" % (
		re.escape(cfg["issue_log_prefix"]), cfg["ticket_pattern"]))


def git(root, *args):
	return subprocess.run(["git", "-C", str(root)] + list(args), capture_output=True, text=True).stdout


def cluster_files(root, cfg, cluster):
	"""The cluster's `anchored: true` notes: the ones that hold facts (the hub's headings aren't facts)."""
	return [p for p in sorted(Path(root, cfg["brain_dir"]).glob("%s*.md" % cluster)) if is_anchored(p)]


def is_anchored(path):
	meta, _ = parse_frontmatter(path.read_text(encoding="utf-8").split("\n"))
	return meta.get("anchored", ("", 0))[0] == "true"


def issue_logs(root, cfg):
	return sorted(Path(root, cfg["brain_dir"], "issues").glob("*.md"))


def window_tags(root, cfg, since, until):
	"""Count tags in issue log bullets under ### date headings inside the window."""
	counts = Counter()
	used = Counter()
	for p in issue_logs(root, cfg):
		in_window = False
		for line in p.read_text(encoding="utf-8").split("\n"):
			m = LOG_HEADING_RE.match(line)
			if m:
				in_window = since <= m.group(1) <= until
				continue
			if line.startswith("## "):
				in_window = False
			if not in_window:
				continue
			for kind, leaf, bare in TAG_RE.findall(line):
				counts[kind or bare] += 1
				if kind == "used":
					used[leaf.strip()] += 1
	return counts, used


def start_commit(root, since):
	return git(root, "rev-list", "-1", "--before=%s 00:00" % since, "HEAD").strip()


def headings_at(root, commit, rel):
	if not commit:
		return set()
	text = git(root, "show", "%s:%s" % (commit, rel))
	return {f["heading"] for f in parse_facts(text)}


def relearned(root, cfg, cluster, since, until):
	"""Facts that existed before the window and gained a source citation dated in the window."""
	cite = source_cite_re(cfg)
	start = start_commit(root, since)
	hits = []
	new_facts = 0
	for p in cluster_files(root, cfg, cluster):
		rel = os.path.relpath(p, root)
		before = headings_at(root, start, rel)
		for f in parse_facts(p.read_text(encoding="utf-8")):
			if f["heading"] not in before:
				new_facts += 1
				continue
			tickets = {t for t, dates in cite.findall(f["source"] or "")
				if any(since <= d <= until for d in DATE_RE.findall(dates))}
			if tickets:
				hits.append((rel, f["heading"], sorted(tickets)))
	return hits, new_facts


def flag_outcomes(root, cfg, cluster, since, until):
	"""(verified bumps, superseded markers added) in commits inside the window."""
	paths = [os.path.relpath(p, root) for p in cluster_files(root, cfg, cluster)]
	if not paths:
		return 0, 0
	out = git(root, "log", "--since=%s 00:00" % since, "--until=%s 23:59" % until, "-p", "--pretty=format:@@commit", "--", *paths)
	bumps = superseded = 0
	removed = added = 0
	for line in out.split("\n") + ["@@commit"]:
		if line == "@@commit" or line.startswith("diff --git"):
			bumps += min(removed, added)
			removed = added = 0
			continue
		if line.startswith("-- verified:"):
			removed += 1
		elif line.startswith("+- verified:"):
			added += 1
		if line.startswith("+") and not line.startswith("+++") and "[superseded" in line:
			superseded += 1
	return bumps, superseded


def promotion(root, cfg, since, until):
	closed, promoted = [], []
	for p in issue_logs(root, cfg):
		text = p.read_text(encoding="utf-8")
		meta, _ = parse_frontmatter(text.split("\n"))
		status = meta.get("status", ("", 0))[0]
		updated = meta.get("updated", ("", 0))[0]
		if status in ("merged", "done") and since <= updated <= until:
			closed.append(p.stem)
			if "**promoted:**" in text:
				promoted.append(p.stem)
	return closed, promoted


def all_facts(root, cfg, cluster):
	facts = []
	for p in cluster_files(root, cfg, cluster):
		facts.extend(parse_facts(p.read_text(encoding="utf-8")))
	return facts


def baseline(root, cfg, cluster):
	cite = source_cite_re(cfg)
	facts = all_facts(root, cfg, cluster)
	multi = [f for f in facts if len({t for t, _ in cite.findall(f["source"] or "")}) >= 2]
	return len(facts), multi


def parse_args(argv):
	opts = {"--until": datetime.date.today().isoformat()}
	i = 0
	while i < len(argv):
		if argv[i] == "--baseline":
			opts["--baseline"] = True
		elif argv[i] in ("--since", "--until", "--cluster") and i + 1 < len(argv):
			opts[argv[i]] = argv[i + 1]
			i += 1
		i += 1
	return opts


def main(argv):
	root = brainconfig.ROOT
	cfg = brainconfig.load(root)
	opts = parse_args(argv)
	cluster = opts.get("--cluster")
	if not cluster or not (opts.get("--baseline") or "--since" in opts):
		print(__doc__)
		return 2
	if opts.get("--baseline"):
		total, multi = baseline(root, cfg, cluster)
		print("%d facts; %d cite two or more issue logs (learned more than once):" % (total, len(multi)))
		for f in multi:
			print("- %s" % f["heading"])
		return 0
	since, until = opts["--since"], opts["--until"]
	counts, used = window_tags(root, cfg, since, until)
	hits, new_facts = relearned(root, cfg, cluster, since, until)
	bumps, superseded = flag_outcomes(root, cfg, cluster, since, until)
	closed, promoted = promotion(root, cfg, since, until)
	facts = all_facts(root, cfg, cluster)
	scopes = Counter(f["scope"] for f in facts)
	missing = sorted(set(closed) - set(promoted))
	print("### Review %s (window %s to %s)" % (until, since, until))
	print("- **tags:** used %d · rediscovered %d · miss %d · why %d" % (counts["used"], counts["rediscovered"], counts["miss"], counts["why"]))
	if used:
		print("\t- used most: " + ", ".join("%s (%d)" % (k, v) for k, v in used.most_common(5)))
	print("- **relearned:** %d facts gained a source dated in the window" % len(hits))
	for rel, heading, tickets in hits:
		print("\t- %s · %s · %s" % (Path(rel).stem, heading, ", ".join(tickets)))
	print("- **flags:** %d rechecks only bumped `verified:` (noise) · %d `[superseded` markers added (caught)" % (bumps, superseded))
	print("- **promotion:** %d of %d tickets closed in the window have `promoted:`%s" % (
		len(promoted), len(closed), " (missing: %s)" % ", ".join(missing) if missing else ""))
	print("- **cluster:** %d facts (%s) · %d new in the window" % (
		len(facts), ", ".join("%s %d" % (k, v) for k, v in sorted(scopes.items())), new_facts))
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
