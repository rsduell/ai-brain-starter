#!/usr/bin/env python3
"""The brain's schedule (optional): what's due, overdue and coming up. Entries live in brain/Schedule.md.
Rules: brain/RULES.md → Schedule.

Usage:
	python3 scripts/schedule.py report [--today YYYY-MM-DD] [--sprints sprints.json] [--events events.json]
	python3 scripts/schedule.py done "<entry title>" [--on YYYY-MM-DD]
	python3 scripts/schedule.py mark [--scan <commit>] [--report <ISO time>]

report  prints a "## Due and coming up" section to paste into a daily note. The window runs from
        tomorrow through Friday of next week. Sources: Schedule.md entries (with `after:` and
        `moves:`), anchored facts that need a recheck, stale hubs, issue logs due for compaction,
        `- [ ] **YYYY-MM-DD** · task` todos in the human_dirs folders, and optional JSON files an agent
        fetched for you:
            sprints.json  [{"number", "startsAt", "endsAt"}, ...] (Linear's cycles come in this shape;
                          endsAt is exclusive, and a gap between sprints is shown as a break)
            events.json   one off calendar events: [{"summary", "start" (YYYY-MM-DD...), "url"}, ...]
done    records a finished entry: `- last:` = the date, and `next` moves on by cadence (monthly: last
        day of next month; quarterly: last day of the next quarter; weekly: +7 days; "<c> until D,
        then <c2>"). An entry with cadence none moves under "## Done".
mark    sets `last_scan` (where the next date scan starts) and/or `last_report` (when the report
        last ran; milestone reminders use it) in Schedule.md's frontmatter.
Standard library only.
"""
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainconfig  # noqa: E402
from lint_brain import parse_frontmatter, parse_moves, parse_schedule  # noqa: E402

ROOT = brainconfig.ROOT
LINK_TITLE_RE = re.compile(r"\[\[Schedule#([^\]|]+)")
DATED_TODO_RE = re.compile(r"^\s*- \[ \] \*\*(\d{4}-\d{2}-\d{2})\*\*\s*·?\s*(.*)$")
LOG_HEADING_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2})\s*$")
NUDGE_DAYS = (14, 7, 3, 1)
MILESTONE_HORIZON = 60
STALE_HUB_DAYS = 60
COMPACT_AFTER_DAYS = 14
COMPACT_MIN_BULLETS = 4


def schedule_path(root, cfg):
	return Path(root, cfg["brain_dir"], "Schedule.md")


def d(s):
	return dt.date.fromisoformat(s)


def fmt(day):
	return "%s %s" % (day.strftime("%a"), day.strftime("%m-%d"))


def window_end(today):
	"""Friday of next week."""
	monday = today - dt.timedelta(days=today.weekday())
	return monday + dt.timedelta(days=4 + 7)


def last_day_of_month(year, month):
	nxt = dt.date(year + (month == 12), month % 12 + 1, 1)
	return nxt - dt.timedelta(days=1)


def step(cadence, day):
	if cadence == "weekly":
		return day + dt.timedelta(days=7)
	if cadence == "monthly":
		y, m = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
		return last_day_of_month(y, m)
	if cadence == "quarterly":
		m = day.month
		q_end = ((m - 1) // 3 + 1) * 3
		if day >= last_day_of_month(day.year, q_end):
			q_end += 3
		y = day.year + (q_end > 12)
		q_end = (q_end - 1) % 12 + 1
		return last_day_of_month(y, q_end)
	return None


def next_date(cadence, day):
	"""Next scheduled (unmoved) date after `day` for a cadence string; None for `none`."""
	m = re.match(r"^(\w+) until (\d{4}-\d{2}-\d{2}), then (\w+)$", cadence or "")
	if m:
		first, until, then = m.group(1), d(m.group(2)), m.group(3)
		candidate = step(first, day)
		return candidate if candidate and candidate <= until else step(then, day)
	return step(cadence or "none", day)


def shown_date(entry):
	"""The entry's next date with any `moves:` override applied, or None for TBD."""
	nxt = entry["fields"].get("next")
	if not nxt or nxt == "TBD":
		return None
	moves = parse_moves(entry["fields"].get("moves", "")) or {}
	return d(moves.get(nxt, nxt))


def entry_label(e):
	about = e["fields"].get("about", "")
	return "[[Schedule#%s|%s]]%s" % (e["title"], e["title"], (" · " + about) if about else "")


def collect_schedule(entries, today, end, last_run):
	"""Return (overdue, due_today, coming, milestone_line_parts, nudges)."""
	by_title = {e["title"]: e for e in entries}
	overdue, due_today, coming, parts, nudges = [], [], [], [], []
	for e in entries:
		if e["section"] in ("Done", "Ignored"):
			continue
		kind = e["fields"].get("kind")
		day = shown_date(e)
		after = LINK_TITLE_RE.search(e["fields"].get("after", ""))
		if after and after.group(1) in by_title:
			ref_day = shown_date(by_title[after.group(1)])
			day = ref_day + dt.timedelta(days=1) if ref_day else None
		if kind == "milestone":
			if day is None:
				parts.append("%s (date TBD)" % e["title"])
				continue
			left = (day - today).days
			if 0 <= left <= MILESTONE_HORIZON:
				parts.append("%s %s (%s)" % (e["title"], fmt(day), "today" if left == 0 else "%d days" % left))
			crossed = [n for n in NUDGE_DAYS if left <= n and (left == n or (last_run and (day - last_run).days > n))]
			if left > 0 and crossed:
				affects = e["fields"].get("affects", "")
				nudges.append("%s in %d days: anything to prep?%s" % (entry_label(e), left, (" Affects " + affects) if affects else ""))
			continue
		if day is None:
			continue
		if day < today:
			overdue.append((day, "%s · due %s" % (entry_label(e), fmt(day))))
		elif day == today:
			due_today.append((day, entry_label(e)))
		elif day <= end:
			coming.append((day, entry_label(e)))
	return overdue, due_today, coming, parts, nudges


def sprint_line(sprints, today):
	spans = sorted((d(c["startsAt"][:10]), d(c["endsAt"][:10]), c.get("number")) for c in sprints)
	for i, (start, end_excl, number) in enumerate(spans):
		if start <= today < end_excl:
			last_work = end_excl - dt.timedelta(days=1)
			while last_work.weekday() > 4:
				last_work -= dt.timedelta(days=1)
			left = sum(1 for k in range((last_work - today).days + 1) if (today + dt.timedelta(days=k)).weekday() < 5)
			line = "Sprint %s · %d working day%s left · ends %s" % (number, left, "" if left == 1 else "s", fmt(last_work))
			if i + 1 < len(spans) and spans[i + 1][0] > end_excl:
				gap_end = spans[i + 1][0] - dt.timedelta(days=1)
				while gap_end.weekday() > 4:
					gap_end -= dt.timedelta(days=1)
				line += " · break %s to %s" % (end_excl.strftime("%m-%d"), gap_end.strftime("%m-%d"))
			return line
		if i + 1 < len(spans) and end_excl <= today < spans[i + 1][0]:
			return "between sprints · Sprint %s starts %s" % (spans[i + 1][2], fmt(spans[i + 1][0]))
	return None


def fact_items(root, cfg, today):
	try:
		import check_facts
		_, results = check_facts.check(root, check_facts.anchored_notes(root, cfg), cfg, today=today.isoformat())
	except Exception as e:  # never let a fact check problem break the report
		return ["Fact check failed (%s): run `python3 scripts/check_facts.py`" % e.__class__.__name__]
	by_leaf = {}
	for r in results:
		if r["status"] != "ok":
			by_leaf.setdefault(Path(r["path"]).stem, []).append(r["status"])
	return ["Recheck %d fact%s in [[%s]] (%s): `python3 scripts/check_facts.py`" % (
		len(v), "" if len(v) == 1 else "s", leaf, ", ".join(sorted(set(v)))) for leaf, v in sorted(by_leaf.items())]


def hub_items(root, cfg, today):
	items = []
	for p in sorted(Path(root, cfg["brain_dir"]).glob("*.md")):
		meta, _ = parse_frontmatter(p.read_text(encoding="utf-8").split("\n"))
		if meta.get("type", ("", 0))[0] != "brain-hub" or meta.get("lifecycle", ("", 0))[0] in ("archived", "submitted"):
			continue
		as_of = meta.get("as_of", ("", 0))[0]
		if re.match(r"^\d{4}-\d{2}-\d{2}$", as_of) and (today - d(as_of)).days > STALE_HUB_DAYS:
			items.append("Refresh [[%s]] one screen facts (as_of %s)" % (p.stem, as_of))
	return items


def log_sections(text):
	"""[(date, bullet count)] for each `### YYYY-MM-DD` section under `## log`."""
	sections, in_log = [], False
	for line in text.split("\n"):
		if line.startswith("## "):
			in_log = line.strip() == "## log"
			continue
		m = LOG_HEADING_RE.match(line)
		if in_log and m:
			sections.append([m.group(1), 0])
		elif in_log and sections and line.lstrip().startswith("- "):
			sections[-1][1] += 1
	return [(day, count) for day, count in sections]


def compaction_items(root, cfg, today):
	due = []
	for p in sorted(Path(root, cfg["brain_dir"], "issues").glob("*.md")):
		sections = log_sections(p.read_text(encoding="utf-8"))
		if any(count >= COMPACT_MIN_BULLETS and (today - d(day)).days > COMPACT_AFTER_DAYS for day, count in sections):
			due.append(p.stem)
	if not due:
		return []
	return ["Compact old log sections (promote first) in %d issue log%s: %s" % (
		len(due), "" if len(due) == 1 else "s", ", ".join("[[%s]]" % n for n in due))]


def note_todos(root, cfg, today, end):
	"""Open `- [ ] **YYYY-MM-DD** · task` todos in the human_dirs folders."""
	seen, overdue, due_today, coming = set(), [], [], []
	paths = sorted(p for folder in cfg["human_dirs"] for p in Path(root, folder).rglob("*.md"))
	for p in paths:
		for line in p.read_text(encoding="utf-8").split("\n"):
			m = DATED_TODO_RE.match(line)
			if not m or (m.group(1), m.group(2)) in seen:
				continue
			seen.add((m.group(1), m.group(2)))
			day, text = d(m.group(1)), "%s (from [[%s]])" % (m.group(2), p.stem)
			if day < today:
				overdue.append((day, text + " · due %s" % fmt(day)))
			elif day == today:
				due_today.append((day, text))
			elif day <= end:
				coming.append((day, text))
	return overdue, due_today, coming


def event_items(events, today, end):
	due_today, coming = [], []
	for ev in events:
		day = d(ev["start"][:10])
		text = ev["summary"] + (" ([calendar](%s))" % ev["url"] if ev.get("url") else "")
		if day == today:
			due_today.append((day, text + " (calendar)"))
		elif today < day <= end:
			coming.append((day, text))
	return due_today, coming


def report(root, today, sprints=None, events=None, cfg=None):
	cfg = cfg or brainconfig.load(root)
	path = schedule_path(root, cfg)
	text = path.read_text(encoding="utf-8") if path.exists() else ""
	meta, _ = parse_frontmatter(text.split("\n"))
	last_report = meta.get("last_report", ("", 0))[0]
	last_run = d(last_report[:10]) if re.match(r"^\d{4}-\d{2}-\d{2}", last_report) else None
	end = window_end(today)
	overdue, due_today, coming, parts, nudges = collect_schedule(parse_schedule(text), today, end, last_run)
	j_over, j_today, j_coming = note_todos(root, cfg, today, end)
	e_today, e_coming = event_items(events or [], today, end)
	overdue += j_over
	due_today += j_today + e_today
	coming += j_coming + e_coming
	housekeeping = fact_items(root, cfg, today) + hub_items(root, cfg, today) + compaction_items(root, cfg, today)

	out = ["## Due and coming up (through %s)" % fmt(end)]
	line = sprint_line(sprints, today) if sprints else None
	if line:
		out.append("Sprint: " + line)
	if parts:
		out.append("Milestones: " + " · ".join(parts))
	if overdue:
		out.append("Overdue")
		out += ["- [ ] %s" % t for _, t in sorted(overdue)]
	if due_today or nudges or housekeeping:
		out.append("Today")
		out += ["- [ ] %s" % t for _, t in sorted(due_today)]
		out += ["- [ ] %s" % t for t in nudges + housekeeping]
	if coming:
		out.append("Coming up")
		out += ["- %s · %s" % (fmt(day), t) for day, t in sorted(coming)]
	if len(out) == 1:
		out.append("Nothing due through %s." % fmt(end))
	return "\n".join(out)


def done(root, title, on, cfg=None):
	path = schedule_path(root, cfg or brainconfig.load(root))
	lines = path.read_text(encoding="utf-8").split("\n")
	entries = [e for e in parse_schedule("\n".join(lines)) if e["section"] not in ("Done", "Ignored")]
	matches = [e for e in entries if e["title"] == title]
	if len(matches) != 1:
		raise SystemExit("no single schedule entry titled %r" % title)
	e = matches[0]
	start = e["line"] - 1
	stop = start + 1
	while stop < len(lines) and not lines[stop].startswith("#"):
		stop += 1
	block = lines[start:stop]
	block = [l for l in block if not l.startswith("- last:")]
	insert_at = max(i for i, l in enumerate(block) if l.startswith("- ")) + 1
	block.insert(insert_at, "- last: %s" % on.isoformat())
	nxt = e["fields"].get("next")
	following = next_date(e["fields"].get("cadence", "none"), d(nxt)) if nxt and nxt != "TBD" else None
	if following:
		block = [("- next: %s" % following.isoformat()) if l.startswith("- next:") else l for l in block]
		lines[start:stop] = block
	else:
		del lines[start:stop]
		while block and not block[-1].strip():
			block.pop()
		if "## Done" not in lines:
			lines += ["", "## Done", ""]
		lines += block + [""]
	path.write_text("\n".join(lines), encoding="utf-8")
	return following


def mark(root, scan=None, report_time=None, cfg=None):
	path = schedule_path(root, cfg or brainconfig.load(root))
	lines = path.read_text(encoding="utf-8").split("\n")
	end = lines.index("---", 1)
	for key, value in (("last_scan", scan), ("last_report", report_time)):
		if value is None:
			continue
		hits = [i for i in range(1, end) if lines[i].startswith(key + ":")]
		if hits:
			lines[hits[0]] = "%s: %s" % (key, value)
		else:
			lines.insert(end, "%s: %s" % (key, value))
			end += 1
	path.write_text("\n".join(lines), encoding="utf-8")


def main(argv):
	if not argv or argv[0] not in ("report", "done", "mark"):
		print(__doc__)
		return 2
	opts, positional, i = {}, [], 1
	while i < len(argv):
		if argv[i].startswith("--") and i + 1 < len(argv):
			opts[argv[i]] = argv[i + 1]
			i += 2
		else:
			positional.append(argv[i])
			i += 1
	if argv[0] == "report":
		today = d(opts.get("--today", dt.date.today().isoformat()))
		load = lambda k: json.loads(Path(opts[k]).read_text()) if k in opts else None
		print(report(ROOT, today, load("--sprints"), load("--events")))
		return 0
	if argv[0] == "mark":
		mark(ROOT, opts.get("--scan"), opts.get("--report"))
		return 0
	on = d(opts.get("--on", dt.date.today().isoformat()))
	following = done(ROOT, positional[0], on)
	print("next: %s" % (following.isoformat() if following else "moved to ## Done"))
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
