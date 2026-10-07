#!/usr/bin/env python3
"""Find plain language dates added to human notes since the last scan (optional schedule).
Rules: brain/RULES.md → Schedule.

Usage:
	python3 scripts/date_scan.py [--since <commit>] [--json]

--since defaults to `last_scan` in brain/Schedule.md. Scans lines *added* since that commit
(committed or not) in the `human_dirs` folders from brain.json. Agent notes are never scanned.

A line is a candidate when it holds something date like (2026-10-20, 10-20, Oct 20, Tuesday,
tomorrow, next week, end of month, by Friday, in 3 days) and, for absolute dates, at least one is on
or after the note's own date (past references like "merged 09-28" are dropped). Headings, frontmatter
and code blocks are skipped, as are a "## Due and coming up" section pasted from the schedule
report and lines already listed under "## Ignored" in Schedule.md. A note's date is the date in its
filename (daily notes like 2026-10-07.md), else its last commit date.
Flags: `milestone?` (freeze, release, launch, deadline, demo, retreat, all hands) and `recurring?`
(weekly, every, each <weekday>). The script only finds and locates; the agent judges intent and
resolves relative dates against the note's date.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainconfig  # noqa: E402
from lint_brain import parse_frontmatter  # noqa: E402

ROOT = brainconfig.ROOT
GENERATED_SECTIONS = ("## Due and coming up",)
AGENT_FILES = ("CLAUDE.md", "AGENTS.md")
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
WEEKDAYS = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
MD_RE = re.compile(r"(?<![\d-])(\d{1,2})[-/](\d{1,2})(?![\d-])")
NAMED_RE = re.compile(r"\b(%s)[a-z]*\.? (\d{1,2})(?:st|nd|rd|th)?\b" % "|".join(MONTHS), re.I)
RELATIVE_RE = re.compile(
	r"\b(tomorrow|next (?:week|month|%s)|this (?:week|%s)|end of (?:the )?(?:day|week|month|quarter|year)|eo[dwm]\b|by %s|in \d+ (?:days?|weeks?)|%s)\b"
	% (WEEKDAYS, WEEKDAYS, WEEKDAYS, WEEKDAYS), re.I)
PAST_RE = re.compile(r"\b(?:last|past|previous) (?:week|month|%s)\b" % WEEKDAYS, re.I)
LINK_RE = re.compile(r"\[\[[^\]]*\]\]|\]\([^)]*\)|https?://\S+")
DATED_TODO_RE = re.compile(r"^\s*- \[[ x]\] \*\*\d{4}-\d{2}-\d{2}\*\*")
MILESTONE_RE = re.compile(r"\b(code )?freeze|release|launch|deadline|demo|retreat|all hands|go live|cutover\b", re.I)
RECURRING_RE = re.compile(r"\b(weekly|biweekly|monthly|every|each (?:%s|week|month))\b" % WEEKDAYS, re.I)


def git(root, *args):
	return subprocess.run(["git", "-C", str(root)] + list(args), capture_output=True, text=True)


def added_lines(root, since, folders):
	"""[(path, new line number, text)] for lines added since `since` (working tree included)."""
	out = git(root, "-c", "core.quotepath=off", "diff", "-M", "--unified=0", "--no-color", since, "--", *folders).stdout
	result, path, new_no = [], None, 0
	for line in out.split("\n"):
		if line.startswith("+++ "):
			path = line[6:].rstrip("\t") if line.startswith("+++ b/") else None
			continue
		m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
		if m:
			new_no = int(m.group(1))
			continue
		if path and line.startswith("+"):
			result.append((path, new_no, line[1:]))
			new_no += 1
	untracked = git(root, "ls-files", "--others", "--exclude-standard", "--", *folders).stdout.split("\n")
	for path in [p for p in untracked if p.endswith(".md")]:
		for i, text in enumerate(Path(root, path).read_text(encoding="utf-8").split("\n"), 1):
			result.append((path, i, text))
	return result


_NOTE_DATES = {}


def note_date(root, path):
	if (root, path) not in _NOTE_DATES:
		_NOTE_DATES[(root, path)] = _note_date(root, path)
	return _NOTE_DATES[(root, path)]


def _note_date(root, path):
	m = re.search(r"(\d{4}-\d{2}-\d{2})\.md$", path)
	if m:
		return dt.date.fromisoformat(m.group(1))
	stamp = git(root, "log", "-1", "--format=%cs", "--", path).stdout.strip()
	return dt.date.fromisoformat(stamp) if stamp else dt.date.today()


def absolute_dates(text, year):
	found = []
	for y, m, d_ in ISO_RE.findall(text):
		found.append((int(y), int(m), int(d_)))
	stripped = ISO_RE.sub(" ", text)
	for m, d_ in MD_RE.findall(stripped):
		found.append((year, int(m), int(d_)))
	for mon, d_ in NAMED_RE.findall(text):
		found.append((year, MONTHS.index(mon[:3].lower()) + 1, int(d_)))
	dates = []
	for y, m, d_ in found:
		try:
			dates.append(dt.date(y, m, d_))
		except ValueError:
			pass
	return dates


def ignored_texts(root, cfg):
	path = Path(root, cfg["brain_dir"], "Schedule.md")
	if not path.exists():
		return set()
	texts, inside = set(), False
	for line in path.read_text(encoding="utf-8").split("\n"):
		if line.startswith("## "):
			inside = line.strip() == "## Ignored"
			continue
		m = re.search(r'· "(.*)"\s*$', line) if inside else None
		if m:
			texts.add(m.group(1).strip())
	return texts


def scan(root, since, today=None, cfg=None):
	cfg = cfg or brainconfig.load(root)
	today = today or dt.date.today()
	ignored = ignored_texts(root, cfg)
	candidates, frontmatter_files, fenced = [], {}, {}
	for path, line_no, text in added_lines(root, since, cfg["human_dirs"]):
		if path.endswith(AGENT_FILES):
			continue
		if path not in frontmatter_files:
			lines = Path(root, path).read_text(encoding="utf-8").split("\n") if Path(root, path).exists() else []
			_, fm_end = parse_frontmatter(lines)
			in_fence, in_generated, fence_lines = False, False, set()
			for k, l in enumerate(lines, 1):
				if l.startswith("## "):
					in_generated = l.startswith(GENERATED_SECTIONS)
				if l.lstrip().startswith("```"):
					in_fence = not in_fence
					fence_lines.add(k)
				elif in_fence or in_generated:
					fence_lines.add(k)  # code, and a pasted schedule report
			frontmatter_files[path], fenced[path] = fm_end, fence_lines
		stripped = text.strip()
		if (not stripped or stripped.startswith("#") or line_no <= frontmatter_files[path]
				or line_no in fenced[path] or stripped in ignored or DATED_TODO_RE.match(text)):
			continue
		prose = PAST_RE.sub(" ", LINK_RE.sub(" ", text))  # links, URLs and "last Thursday" are references, not plans
		ndate = note_date(root, path)
		dates = absolute_dates(prose, ndate.year)
		relative = RELATIVE_RE.findall(prose)
		if not dates and not relative:
			continue
		if dates and not relative and all(day <= ndate or day < today for day in dates):
			continue
		flags = []
		if MILESTONE_RE.search(prose):
			flags.append("milestone?")
		if RECURRING_RE.search(prose):
			flags.append("recurring?")
		candidates.append({
			"path": path, "line": line_no, "note_date": ndate.isoformat(), "text": stripped,
			"dates": sorted({day.isoformat() for day in dates}),
			"relative": sorted({r if isinstance(r, str) else r[0] for r in relative}),
			"flags": flags,
		})
	return candidates


def main(argv):
	cfg = brainconfig.load(ROOT)
	since = None
	path = Path(ROOT, cfg["brain_dir"], "Schedule.md")
	if "--since" in argv:
		since = argv[argv.index("--since") + 1]
	elif path.exists():
		meta, _ = parse_frontmatter(path.read_text(encoding="utf-8").split("\n"))
		since = meta.get("last_scan", ("", 0))[0]
	if not since:
		print("no --since and no last_scan in %s" % os.path.relpath(path, ROOT), file=sys.stderr)
		return 2
	found = scan(ROOT, since, cfg=cfg)
	if "--json" in argv:
		print(json.dumps(found, indent=1))
		return 0
	for c in found:
		print("%s:%d (note %s)%s\n    %s" % (c["path"], c["line"], c["note_date"],
			("  [" + ", ".join(c["flags"]) + "]") if c["flags"] else "", c["text"][:200]))
	print("%d candidate line(s) since %s" % (len(found), since[:12]))
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
