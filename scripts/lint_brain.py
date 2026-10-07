#!/usr/bin/env python3
"""Lint the brain so the graph stays trustworthy. Rules: brain/RULES.md. Settings: brain.json.

Usage:
	python3 scripts/lint_brain.py --all       report on every note in the brain folder
	python3 scripts/lint_brain.py --staged    check staged brain notes (the pre-commit hook)

Checks:
	links       every [[wikilink]] resolves to a note or file in the repo
	issue logs  required keys, status and role enums, summary length,
	            `updated` on or after the newest `### YYYY-MM-DD` log heading
	hubs        an `as_of` date and a `lifecycle` enum
	supersede   `superseded_by:` and inline `[superseded ...]` markers carry a link
	facts       in `anchored: true` notes, every `###` fact has anchors + verified
	            (or a recheck date), a source and a scope
	schedule    in `brain/Schedule.md` (optional), every entry has a `next` date or TBD, a known
	            kind, a valid cadence and well formed `moves`

Standard library only (Python 3.9+).
"""
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainconfig  # noqa: E402

SKIP_DIRS = {".git", ".obsidian", ".trash", "node_modules"}
LINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")
INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LOG_DATE_RE = re.compile(r"^###\s+(\d{4}-\d{2}-\d{2})\s*$")
PLACEHOLDER_RE = re.compile(r"YYYY|xxx|XXX|[<>{}]")
FACT_META_RE = re.compile(r"^- (anchors|verified|recheck|source|scope):\s*(.*)$")
REPO_KEY = r"[A-Za-z0-9_.-]+(?:@[A-Za-z0-9_./-]+)?"
ANCHOR_RE = re.compile(r"`(%s):(symbol:)?([^`]+)`" % REPO_KEY)
VERIFIED_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})((?:\s*·\s*%s\s+[0-9a-f]{7,40})+)\s*$" % REPO_KEY)
VERIFIED_PAIR_RE = re.compile(r"(%s)\s+([0-9a-f]{7,40})" % REPO_KEY)
SCHEDULE_KINDS = {"milestone", "recurring", "task", "meeting"}
CADENCE_WORD = r"(?:none|weekly|monthly|quarterly)"
CADENCE_RE = re.compile(r"^%s(?: until \d{4}-\d{2}-\d{2}, then %s)?$" % (CADENCE_WORD, CADENCE_WORD))
MOVE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*→\s*(\d{4}-\d{2}-\d{2})$")
SCHEDULE_META_RE = re.compile(r"^- (next|kind|cadence|moves|after|affects|about|source|calendar|last):\s*(.*)$")


def vault_names(root):
	"""Lowercased names a wikilink can resolve to: note basenames (no .md), file names, and repo relative paths."""
	names = set()
	for dirpath, dirnames, filenames in os.walk(root):
		dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
		rel_dir = os.path.relpath(dirpath, root)
		for name in filenames:
			rel = name if rel_dir == "." else os.path.join(rel_dir, name)
			names.add(name.lower())
			names.add(rel.lower())
			if name.endswith(".md"):
				names.add(name[:-3].lower())
				names.add(rel[:-3].lower())
	return names


def strip_code(lines):
	"""Blank out fenced blocks and inline code, keeping line numbers."""
	out = []
	in_fence = False
	for line in lines:
		if line.lstrip().startswith("```"):
			in_fence = not in_fence
			out.append("")
			continue
		if in_fence:
			out.append("")
			continue
		out.append(INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), line))
	return out


def parse_frontmatter(lines):
	"""Return ({key: (value, line_no)}, end_index). Top level `key: value` pairs only; YAML comments stripped."""
	meta = {}
	if not lines or lines[0].strip() != "---":
		return meta, 0
	for i in range(1, len(lines)):
		line = lines[i]
		if line.strip() == "---":
			return meta, i + 1
		m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
		if m:
			value = re.sub(r"(^|\s)#.*$", "", m.group(2)).strip()
			if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
				value = value[1:-1]
			meta[m.group(1)] = (value, i + 1)
	return meta, 0


def parse_facts(text):
	"""Facts in an `anchored: true` note: each `### ` heading plus the `- key: value` bullets right under it."""
	facts = []
	current = None
	in_fence = False
	in_meta = False
	for i, line in enumerate(text.split("\n"), 1):
		if line.lstrip().startswith("```"):
			in_fence = not in_fence
			continue
		if in_fence:
			continue
		if line.startswith("### "):
			current = {"heading": line[4:].strip(), "line": i, "anchors": [], "verified": {},
				"verified_date": None, "verified_raw": None, "recheck": None, "source": None, "scope": None}
			facts.append(current)
			in_meta = True
			continue
		if line.startswith("## ") or line.startswith("# "):
			current = None
			continue
		if current is None or not in_meta:
			continue
		m = FACT_META_RE.match(line)
		if not m:
			if line.strip():
				in_meta = False  # body text ends the metadata bullets
			continue
		key, value = m.group(1), m.group(2).strip()
		if key == "anchors":
			current["anchors"] = [(r, "symbol" if s else "path", v) for r, s, v in ANCHOR_RE.findall(value)]
		elif key == "verified":
			current["verified_raw"] = value
			vm = VERIFIED_RE.match(value)
			if vm:
				current["verified_date"] = vm.group(1)
				current["verified"] = dict(VERIFIED_PAIR_RE.findall(vm.group(2)))
		else:
			current[key] = value
	return facts


def parse_schedule(text):
	"""Entries in Schedule.md: each `### ` heading plus its `- key: value` bullets, with the `## ` section it sits in.

	Returns dicts: title, line, section, fields {key: value}, body (lines after the bullets).
	"""
	entries = []
	current = None
	section_name = ""
	in_meta = False
	for i, line in enumerate(text.split("\n"), 1):
		if line.startswith("## "):
			section_name = line[3:].strip()
			current = None
			continue
		if line.startswith("### "):
			current = {"title": line[4:].strip(), "line": i, "section": section_name, "fields": {}, "body": []}
			entries.append(current)
			in_meta = True
			continue
		if current is None:
			continue
		m = SCHEDULE_META_RE.match(line) if in_meta else None
		if m:
			current["fields"][m.group(1)] = m.group(2).strip()
		elif line.strip():
			in_meta = False
			current["body"].append(line)
	return entries


def parse_moves(value):
	"""`2026-12-31 → 2027-01-01 · 2027-03-31 → 2027-04-01` → {from: to}; None if malformed."""
	moves = {}
	for part in [p.strip() for p in (value or "").split("·") if p.strip()]:
		m = MOVE_RE.match(part)
		if not m:
			return None
		moves[m.group(1)] = m.group(2)
	return moves


def lint_schedule(text):
	errors = []
	for e in parse_schedule(text):
		if e["section"] in ("Done", "Ignored"):
			continue
		f, where = e["fields"], e["line"]
		nxt = f.get("next")
		if nxt is None or not (nxt == "TBD" or DATE_RE.match(nxt)):
			errors.append((where, "schedule entry needs `- next: YYYY-MM-DD` or `TBD`"))
		if f.get("kind") not in SCHEDULE_KINDS:
			errors.append((where, "schedule kind `%s` not one of: %s" % (f.get("kind"), " | ".join(sorted(SCHEDULE_KINDS)))))
		if not CADENCE_RE.match(f.get("cadence", "none")):
			errors.append((where, "cadence `%s` not `none|weekly|monthly|quarterly` or `<c> until YYYY-MM-DD, then <c>`" % f.get("cadence")))
		if "moves" in f and parse_moves(f["moves"]) is None:
			errors.append((where, "moves `%s` not `YYYY-MM-DD → YYYY-MM-DD` pairs" % f["moves"]))
	return errors


def lint_facts(text, cfg):
	errors = []
	for f in parse_facts(text):
		where = f["line"]
		if f["anchors"]:
			if not f["verified_raw"]:
				errors.append((where, "anchored fact needs `- verified: YYYY-MM-DD · <repo> <sha>`"))
			elif not f["verified_date"]:
				errors.append((where, "verified `%s` is not `YYYY-MM-DD · <repo> <sha>`" % f["verified_raw"]))
			else:
				for repo in sorted({a[0] for a in f["anchors"]} - set(f["verified"])):
					errors.append((where, "verified has no SHA for anchor repo `%s`" % repo))
		elif not f["recheck"]:
			errors.append((where, "fact needs `- anchors:` + `- verified:`, or `- recheck: YYYY-MM-DD`"))
		elif not DATE_RE.match(f["recheck"]):
			errors.append((where, "recheck `%s` is not a YYYY-MM-DD date" % f["recheck"]))
		if not f["source"]:
			errors.append((where, "fact needs `- source:`"))
		if f["scope"] not in cfg["fact_scopes"]:
			errors.append((where, "fact scope `%s` not one of: %s" % (f["scope"], " | ".join(cfg["fact_scopes"]))))
	return errors


def link_target(raw):
	target = raw.split("|", 1)[0].split("#", 1)[0]
	return target.rstrip("\\").strip()


def section(lines, heading):
	"""Return [(line_no, text)] between `## heading` and the next `## `."""
	out = []
	inside = False
	for i, line in enumerate(lines, 1):
		if line.startswith("## "):
			inside = line[3:].strip().lower() == heading
			continue
		if inside:
			out.append((i, line))
	return out


def lint_text(rel_path, text, names, cfg):
	"""Return a list of (line_no, message) for one note."""
	errors = []
	lines = text.split("\n")
	meta, _ = parse_frontmatter(lines)
	ticket_re = re.compile("^%s$" % cfg["ticket_pattern"])
	is_issue_log = os.path.basename(rel_path).startswith(cfg["issue_log_prefix"])

	for i, line in enumerate(strip_code(lines), 1):
		header_line = is_issue_log and (line.startswith("human note:") or line.startswith("human:"))
		for raw in LINK_RE.findall(line):
			target = link_target(raw)
			if not target or PLACEHOLDER_RE.search(target) or target.lower() in names:
				continue
			if header_line and ticket_re.match(target):
				continue  # the human ticket note is optional
			errors.append((i, "unresolved link [[%s]]" % target))
		if "[superseded" in line and not LINK_RE.search(line):
			errors.append((i, "[superseded ...] marker has no [[link]] to what replaced it"))

	if "superseded_by" in meta and not LINK_RE.search(meta["superseded_by"][0]):
		errors.append((meta["superseded_by"][1], "superseded_by must be a [[wikilink]]"))

	note_type = meta.get("type", ("", 0))[0]

	if note_type == "brain-issue":
		for key in cfg["issue_required_keys"]:
			if key not in meta:
				errors.append((1, "issue log missing frontmatter key `%s`" % key))
		for key, allowed in (("status", cfg["issue_statuses"]), ("role", cfg["issue_roles"])):
			if key in meta and meta[key][0] not in allowed:
				errors.append((meta[key][1], "%s `%s` not one of: %s" % (key, meta[key][0], " | ".join(allowed))))
		summary = [(n, t) for n, t in section(lines, "summary") if t.strip() and not t.strip().startswith("<!--")]
		if len(summary) > cfg["summary_max_lines"]:
			errors.append((summary[0][0], "summary has %d lines (max %d)" % (len(summary), cfg["summary_max_lines"])))
		log_dates = [m.group(1) for _, t in section(lines, "log") for m in [LOG_DATE_RE.match(t)] if m]
		if "updated" in meta and log_dates:
			value, line_no = meta["updated"]
			if not DATE_RE.match(value):
				errors.append((line_no, "updated `%s` is not a YYYY-MM-DD date" % value))
			elif value < max(log_dates):
				errors.append((line_no, "updated %s is older than the newest log heading %s" % (value, max(log_dates))))

	if meta.get("anchored", ("", 0))[0] == "true":
		errors.extend(lint_facts(text, cfg))

	if note_type == "brain-schedule":
		errors.extend(lint_schedule(text))

	if note_type == "brain-hub":
		as_of = meta.get("as_of")
		if not as_of or not DATE_RE.match(as_of[0]):
			errors.append((as_of[1] if as_of else 1, "hub needs `as_of: \"YYYY-MM-DD\"`"))
		lifecycle = meta.get("lifecycle")
		if not lifecycle or lifecycle[0] not in cfg["hub_lifecycles"]:
			errors.append((lifecycle[1] if lifecycle else 1, "hub needs `lifecycle:` one of: %s" % " | ".join(cfg["hub_lifecycles"])))

	return errors


def lint_paths(root, rel_paths, cfg=None, read=None):
	"""Lint the given repo relative paths. `read(rel)` returns text (defaults to the working tree)."""
	root = str(root)
	cfg = cfg or brainconfig.load(root)
	read = read or (lambda rel: Path(root, rel).read_text(encoding="utf-8"))
	names = vault_names(root)
	results = []
	for rel in sorted(rel_paths):
		for line_no, message in lint_text(rel, read(rel), names, cfg):
			results.append("%s:%d: %s" % (rel, line_no, message))
	return results


def brain_notes(root, cfg):
	return [os.path.relpath(p, root) for p in Path(root, cfg["brain_dir"]).rglob("*.md")]


def staged_brain_notes(root, cfg):
	out = subprocess.run(
		["git", "-C", root, "diff", "--cached", "--name-only", "--diff-filter=ACM", "-z"],
		check=True, capture_output=True,
	).stdout.decode("utf-8")
	prefix = cfg["brain_dir"].rstrip("/") + "/"
	return [p for p in out.split("\0") if p.startswith(prefix) and p.endswith(".md")]


def read_staged(root):
	def read(rel):
		return subprocess.run(["git", "-C", root, "show", ":" + rel], check=True, capture_output=True).stdout.decode("utf-8")
	return read


def main(argv):
	root = str(brainconfig.ROOT)
	cfg = brainconfig.load(root)
	if "--staged" in argv:
		results = lint_paths(root, staged_brain_notes(root, cfg), cfg, read_staged(root))
	elif "--all" in argv:
		results = lint_paths(root, brain_notes(root, cfg), cfg)
	else:
		print(__doc__)
		return 2
	for line in results:
		print(line)
	if results:
		print("brain lint: %d problem(s). Rules: %s/RULES.md" % (len(results), cfg["brain_dir"]), file=sys.stderr)
		return 1
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
