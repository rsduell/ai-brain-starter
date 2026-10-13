#!/usr/bin/env python3
"""Adopt this kit into a vault, and later update the vault from it.

ADOPT.md is the procedure an agent follows; this script does the mechanical part: what each kit file
needs, applying what is safe, and recording answers. State lives in the vault's kit.lock.json.

Usage (from the kit's clone; --kit defaults to the clone this script is in):
	python3 scripts/kit_sync.py init    --vault DIR [--map brain=_ai-brain]... [--component journal=declined]...
	python3 scripts/kit_sync.py plan    --vault DIR [--json] [--map ...] [--component ...]
	                                    changes nothing; --map and --component preview answers before init
	python3 scripts/kit_sync.py apply   --vault DIR (--safe | PATH...)  only new, update-clean, update-merge
	python3 scripts/kit_sync.py resolve --vault DIR PATH [--take-kit]   after an answer: keep the vault file as merged, or take the kit's
	python3 scripts/kit_sync.py decide  --vault DIR --id ID --choice vault|kit|merged|skip --vault-text T --kit-text T
	                                    [--note N] [--path KITPATH]...
	python3 scripts/kit_sync.py check   --vault DIR

PATH is always a kit path (`scripts/lint_brain.py`); `vault_path` is where that file lives in the vault.
Actions `plan` reports:
	new               not in the vault yet (or already identical there)
	exists-in-vault   a different vault file sits where the kit file would go: ask
	unchanged         the vault copy matches the kit
	update-clean      the kit changed, the vault copy didn't
	update-merge      both changed, and they merge cleanly
	conflict          both changed the same lines: ask
	vault-edited      the vault changed it, the kit didn't: nothing to do
	missing-in-vault  adopted before, gone from the vault now: ask
	kept-vault        a decision keeps the vault's version
	recheck           a decision kept the vault's version, and the kit's side changed since: ask
	removed-in-kit    adopted before, gone from the kit now: reported, never deleted
	declined          its component was declined
	example, kit-only never adopted
Standard library plus git. Python 3.9.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

LOCK_NAME = "kit.lock.json"
KIT_HOME = Path(__file__).resolve().parent.parent
SAFE = {"new", "update-clean", "update-merge"}
CHOICES = {"vault", "kit", "merged", "skip"}
KEEP_CHOICES = {"vault", "skip"}
COMPONENT_STATES = {"adopted", "declined"}
LOCK_KEYS = ["kit_source", "kit_commit", "path_map", "components", "files", "decisions"]
ORDER = [
	"conflict", "exists-in-vault", "recheck", "missing-in-vault", "removed-in-kit",
	"new", "update-clean", "update-merge",
	"vault-edited", "kept-vault", "unchanged", "declined",
]
ASK = {"conflict", "exists-in-vault", "recheck", "missing-in-vault", "removed-in-kit"}
QUIET = {"vault-edited", "kept-vault", "unchanged", "declined", "example", "kit-only"}


def git(kit, *args, check=True):
	return subprocess.run(["git", "-C", str(kit)] + list(args), check=check, capture_output=True)


def head(kit):
	return git(kit, "rev-parse", "HEAD").stdout.decode().strip()


def blob(kit, commit, path):
	r = git(kit, "rev-parse", "--verify", "-q", "%s:%s" % (commit, path), check=False)
	return r.stdout.decode().strip() if r.returncode == 0 else None


def blob_bytes(kit, sha):
	return git(kit, "cat-file", "blob", sha).stdout


def hash_file(kit, path):
	# Absolute, or git -C <kit> would hash the kit's own file of the same relative name.
	return git(kit, "hash-object", "--", str(Path(path).resolve())).stdout.decode().strip()


def is_executable(kit, commit, path):
	out = git(kit, "ls-tree", commit, "--", path).stdout.decode().split()
	return bool(out) and out[0] == "100755"


def today():
	return datetime.date.today().isoformat()


def short_home(path):
	path = str(Path(path).expanduser().resolve())
	home = str(Path.home())
	return "~" + path[len(home):] if path.startswith(home + os.sep) else path


def load_manifest(kit, commit=None):
	if commit is None:
		text = Path(kit, "kit.json").read_text(encoding="utf-8")
	else:
		text = git(kit, "show", "%s:kit.json" % commit).stdout.decode("utf-8")
	return json.loads(text)


def empty_lock(kit):
	return {
		"kit_source": short_home(kit), "kit_commit": None, "kit_applied": None, "adopted": None, "updated": None,
		"path_map": {}, "components": {}, "files": {}, "decisions": [],
	}


def load_lock(vault):
	path = Path(vault, LOCK_NAME)
	if not path.exists():
		return None
	return json.loads(path.read_text(encoding="utf-8"))


def save_lock(vault, lock):
	Path(vault, LOCK_NAME).write_text(json.dumps(lock, indent="\t") + "\n", encoding="utf-8")


def stamp(vault, kit, lock, commit):
	"""kit_applied: the last kit commit anything came from. kit_commit: the commit the vault is fully in sync
	with, so the next update's "what changed" starts there. It moves only when nothing is left to apply or answer."""
	lock["kit_applied"] = commit
	lock["updated"] = today()
	if not any(open_item(e) for e in plan_with(vault, kit, lock, commit)):
		lock["kit_commit"] = commit
		lock["adopted"] = lock.get("adopted") or today()


def open_item(entry):
	if entry["action"] in ASK:
		return True
	return entry["action"] in SAFE and entry["component_state"] in ("adopted", "undecided")


def vault_path(manifest, lock, path):
	"""Where a kit file lives in the vault: the lock's record, else the kit path through the path map."""
	if path in lock["files"]:
		return lock["files"][path]["vault_path"]
	best = None
	for name, prefix in manifest.get("paths", {}).items():
		if path.startswith(prefix + "/") and (best is None or len(prefix) > len(best[1])):
			best = (name, prefix)
	if best is None:
		return path
	name, prefix = best
	target = lock["path_map"].get(name, prefix).strip("/")
	rest = path[len(prefix) + 1:]
	return rest if target in ("", ".") else target + "/" + rest


def component_state(name, component, lock):
	role = component.get("role")
	if role == "example":
		return "example"
	if role == "kit":
		return "kit-only"
	return lock["components"].get(name) or ("undecided" if component.get("optional") else "adopted")


def decision_for(lock, path):
	found = None
	for d in lock["decisions"]:
		if path in d.get("paths", []):
			found = d
	return found


def merge(ours, base, theirs):
	"""Three way merge with git merge-file: returns (clean, merged bytes)."""
	with tempfile.TemporaryDirectory() as tmp:
		names = []
		for name, data in (("ours", ours), ("base", base), ("theirs", theirs)):
			p = Path(tmp, name)
			p.write_bytes(data)
			names.append(str(p))
		r = subprocess.run(["git", "merge-file", "-p", "-q"] + names, capture_output=True)
	if r.returncode > 127:
		raise RuntimeError("git merge-file failed: %s" % r.stderr.decode("utf-8", "replace").strip())
	return r.returncode == 0, r.stdout


def classify(vault, kit, manifest, lock, commit, name, component, item):
	path = item["path"]
	state = component_state(name, component, lock)
	entry = {
		"path": path, "component": name, "component_state": state, "kind": item.get("kind"),
		"vault_path": vault_path(manifest, lock, path),
	}
	if state in ("example", "kit-only", "declined"):
		entry["action"] = state
		return entry
	head_blob = blob(kit, commit, path)
	if head_blob is None:
		raise ValueError("kit.json lists %s, but the kit has no such file at %s" % (path, commit[:7]))
	decision = decision_for(lock, path)
	if decision and decision["choice"] in KEEP_CHOICES:
		entry["decision"] = decision["id"]
		entry["action"] = "recheck" if blob(kit, decision["kit_basis"], path) != head_blob else "kept-vault"
		return entry
	target = Path(vault, entry["vault_path"])
	locked = lock["files"].get(path)
	if locked is None:
		if target.exists() and hash_file(kit, target) != head_blob:
			entry["action"] = "exists-in-vault"
		else:
			entry["action"] = "new"
	elif not target.exists():
		entry["action"] = "missing-in-vault"
	else:
		ours, base = hash_file(kit, target), locked["base"]
		if ours == head_blob:
			entry["action"] = "unchanged"
		elif base == head_blob:
			entry["action"] = "vault-edited"
		elif ours == base:
			entry["action"] = "update-clean"
		else:
			clean, _ = merge(target.read_bytes(), blob_bytes(kit, base), blob_bytes(kit, head_blob))
			entry["action"] = "update-merge" if clean else "conflict"
	return entry


def plan(vault, kit, path_map=None, components=None):
	"""What each kit file needs. path_map and components preview answers in memory; nothing is written."""
	lock = load_lock(vault) or empty_lock(kit)
	lock["path_map"].update(path_map or {})
	lock["components"].update(components or {})
	return plan_with(vault, kit, lock, head(kit))


def plan_with(vault, kit, lock, commit):
	manifest = load_manifest(kit, commit)
	out, seen = [], set()
	for name, component in manifest["components"].items():
		for item in component["files"]:
			seen.add(item["path"])
			out.append(classify(vault, kit, manifest, lock, commit, name, component, item))
	for path, locked in lock["files"].items():
		if path not in seen:
			out.append({
				"path": path, "component": None, "component_state": None, "kind": None,
				"vault_path": locked["vault_path"], "action": "removed-in-kit",
			})
	return out


def write_file(target, data, executable):
	target.parent.mkdir(parents=True, exist_ok=True)
	target.write_bytes(data)
	if executable:
		target.chmod(target.stat().st_mode | 0o111)


def apply(vault, kit, paths, safe=False):
	entries = {e["path"]: e for e in plan(vault, kit)}
	if safe:
		chosen = [e for e in entries.values() if e["action"] in SAFE and e["component_state"] == "adopted"]
	else:
		chosen, refused = [], []
		for path in paths:
			e = entries.get(path)
			if e is None:
				refused.append("%s: not a kit file" % path)
			elif e["action"] not in SAFE:
				refused.append("%s: %s (only new, update-clean and update-merge apply)" % (path, e["action"]))
			else:
				chosen.append(e)
		if refused:
			print("apply refused, nothing written:\n\t" + "\n\t".join(refused), file=sys.stderr)
			return 1
	lock = load_lock(vault) or empty_lock(kit)
	commit = head(kit)
	for e in chosen:
		path, target = e["path"], Path(vault, e["vault_path"])
		head_blob = blob(kit, commit, path)
		if e["action"] == "update-merge":
			_, data = merge(target.read_bytes(), blob_bytes(kit, lock["files"][path]["base"]), blob_bytes(kit, head_blob))
		else:
			data = blob_bytes(kit, head_blob)
		write_file(target, data, is_executable(kit, commit, path))
		lock["files"][path] = {
			"vault_path": e["vault_path"], "base": head_blob,
			"state": "merged" if e["action"] == "update-merge" else "copied",
		}
		print("%s: %s → %s" % (e["action"], path, e["vault_path"]))
	if chosen:
		stamp(vault, kit, lock, commit)
	save_lock(vault, lock)
	return 0


def resolve(vault, kit, path, take_kit=False):
	lock = load_lock(vault) or empty_lock(kit)
	commit = head(kit)
	manifest = load_manifest(kit, commit)
	head_blob = blob(kit, commit, path)
	if head_blob is None:
		print("resolve: %s is not a kit file" % path, file=sys.stderr)
		return 1
	vp = vault_path(manifest, lock, path)
	target = Path(vault, vp)
	if take_kit:
		write_file(target, blob_bytes(kit, head_blob), is_executable(kit, commit, path))
	elif not target.exists():
		print("resolve: %s doesn't exist in the vault; use --take-kit to copy the kit's" % vp, file=sys.stderr)
		return 1
	lock["files"][path] = {"vault_path": vp, "base": head_blob, "state": "kit" if take_kit else "resolved"}
	stamp(vault, kit, lock, commit)
	save_lock(vault, lock)
	return 0


def decide(vault, kit, decision_id, choice, vault_text, kit_text, note=None, paths=()):
	if choice not in CHOICES:
		raise ValueError("choice must be one of: %s" % ", ".join(sorted(CHOICES)))
	lock = load_lock(vault) or empty_lock(kit)
	decision = {"id": decision_id, "date": today(), "vault": vault_text, "kit": kit_text, "kit_basis": head(kit), "choice": choice}
	if note:
		decision["note"] = note
	if paths:
		decision["paths"] = list(paths)
	lock["decisions"] = [d for d in lock["decisions"] if d["id"] != decision_id] + [decision]
	if lock.get("kit_applied"):
		stamp(vault, kit, lock, head(kit))
	save_lock(vault, lock)


def init(vault, kit, path_map=None, components=None):
	lock = load_lock(vault) or empty_lock(kit)
	lock["kit_source"] = short_home(kit)
	for name, state in (components or {}).items():
		if state not in COMPONENT_STATES:
			raise ValueError("component state must be adopted or declined, not %r" % state)
	lock["path_map"].update(path_map or {})
	lock["components"].update(components or {})
	save_lock(vault, lock)


def check(vault, kit):
	lock = load_lock(vault)
	if lock is None:
		return ["no %s in %s: run init first" % (LOCK_NAME, vault)]
	errors = ["lock is missing `%s`" % key for key in LOCK_KEYS if key not in lock]
	if errors:
		return errors
	manifest = load_manifest(kit, head(kit))
	known = {item["path"] for c in manifest["components"].values() for item in c["files"]}
	for path, entry in lock["files"].items():
		if path not in known:
			errors.append("%s: in the lock but not in the kit's kit.json (removed from the kit?)" % path)
		if not entry.get("base") or not entry.get("vault_path"):
			errors.append("%s: needs `base` and `vault_path`" % path)
	for name, state in lock["components"].items():
		if name not in manifest["components"]:
			errors.append("component %s: not in the kit's kit.json" % name)
		if state not in COMPONENT_STATES:
			errors.append("component %s: state %r, expected adopted or declined" % (name, state))
	for d in lock["decisions"]:
		if not d.get("id") or d.get("choice") not in CHOICES or not d.get("kit_basis"):
			errors.append("decision %s: needs an id, a choice (%s) and a kit_basis" % (d.get("id", "?"), "|".join(sorted(CHOICES))))
	return errors


def print_plan(vault, kit, entries):
	lock = load_lock(vault) or empty_lock(kit)
	synced = lock["kit_commit"][:7] if lock["kit_commit"] else ("not in sync yet" if Path(vault, LOCK_NAME).exists() else "no lock")
	applied = (lock.get("kit_applied") or "")[:7]
	print("kit %s at %s · vault %s · in sync with %s%s" % (
		short_home(kit), head(kit)[:7], vault, synced, " (last applied %s)" % applied if applied and applied != synced else ""))
	undecided = sorted({e["component"] for e in entries if e.get("component_state") == "undecided"})
	if undecided:
		print("undecided optional components (ask, then init --component NAME=adopted|declined): " + ", ".join(undecided))
	by_action = {}
	for e in entries:
		by_action.setdefault(e["action"], []).append(e)
	for action in ORDER:
		group = by_action.get(action, [])
		if not group:
			continue
		if action in QUIET:
			print("%s: %d" % (action, len(group)))
			continue
		print("%s (%d)" % (action, len(group)))
		for e in group:
			print("\t%s → %s%s" % (e["path"], e["vault_path"], "  [%s]" % e["component"] if e.get("component") else ""))


def parse_pairs(pairs, what):
	out = {}
	for pair in pairs or []:
		if "=" not in pair:
			raise SystemExit("%s takes NAME=VALUE, got %r" % (what, pair))
		key, value = pair.split("=", 1)
		out[key] = value
	return out


def main(argv):
	parser = argparse.ArgumentParser(description="Adopt the kit into a vault, or update a vault from it. Procedure: ADOPT.md")
	sub = parser.add_subparsers(dest="command", required=True)
	for name in ("init", "plan", "apply", "resolve", "decide", "check"):
		p = sub.add_parser(name)
		p.add_argument("--vault", required=True)
		p.add_argument("--kit", default=str(KIT_HOME))
		if name == "init":
			p.add_argument("--map", action="append", help="kit folder name=vault folder, e.g. brain=_ai-brain")
			p.add_argument("--component", action="append", help="name=adopted|declined")
		elif name == "plan":
			p.add_argument("--json", action="store_true")
			p.add_argument("--map", action="append", help="preview a folder map without writing it")
			p.add_argument("--component", action="append", help="preview a component choice without writing it")
		elif name == "apply":
			p.add_argument("--safe", action="store_true", help="every safe file in adopted components")
			p.add_argument("paths", nargs="*")
		elif name == "resolve":
			p.add_argument("path")
			p.add_argument("--take-kit", action="store_true")
		elif name == "decide":
			p.add_argument("--id", required=True)
			p.add_argument("--choice", required=True, choices=sorted(CHOICES))
			p.add_argument("--vault-text", required=True)
			p.add_argument("--kit-text", required=True)
			p.add_argument("--note")
			p.add_argument("--path", action="append", default=[])
	args = parser.parse_args(argv)
	vault, kit = str(Path(args.vault).expanduser().resolve()), str(Path(args.kit).expanduser().resolve())
	if args.command == "init":
		init(vault, kit, parse_pairs(args.map, "--map"), parse_pairs(args.component, "--component"))
		return 0
	if args.command == "plan":
		entries = plan(vault, kit, parse_pairs(args.map, "--map"), parse_pairs(args.component, "--component"))
		if args.json:
			print(json.dumps(entries, indent="\t"))
		else:
			print_plan(vault, kit, entries)
		return 0
	if args.command == "apply":
		if not args.safe and not args.paths:
			parser.error("apply needs --safe or kit paths")
		return apply(vault, kit, args.paths, safe=args.safe)
	if args.command == "resolve":
		return resolve(vault, kit, args.path, take_kit=args.take_kit)
	if args.command == "decide":
		decide(vault, kit, args.id, args.choice, args.vault_text, args.kit_text, args.note, args.path)
		return 0
	errors = check(vault, kit)
	for e in errors:
		print(e)
	return 1 if errors else 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
