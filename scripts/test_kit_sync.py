"""Tests for kit_sync.py. Run: python3 -m unittest discover -s scripts

Each test builds a throwaway kit (a git repo with a kit.json) and a throwaway vault.
"""
import contextlib
import datetime
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kit_sync  # noqa: E402

KIT_ROOT = Path(__file__).resolve().parent.parent

MANIFEST = {
	"paths": {"brain": "brain", "scripts": "scripts", "journal": "journal"},
	"components": {
		"core": {"optional": False, "describe": "rules", "files": [
			{"path": "CLAUDE.md", "kind": "rules"},
			{"path": "brain/RULES.md", "kind": "rules"},
		]},
		"lint": {"optional": False, "describe": "lint", "files": [
			{"path": "scripts/lint_brain.py", "kind": "code"},
		]},
		"journal": {"optional": True, "describe": "journal", "files": [
			{"path": "templates/Journal Entry.md", "kind": "template"},
		]},
		"examples": {"role": "example", "describe": "examples", "files": [
			{"path": "brain/Example.md", "kind": "rules"},
		]},
	},
}

FILES = {
	"CLAUDE.md": "Read brain/RULES.md.\n",
	"brain/RULES.md": "line 1\nline 2\nline 3\nline 4\nline 5\n",
	"scripts/lint_brain.py": "print('lint')\n",
	"templates/Journal Entry.md": "# journal\n",
	"brain/Example.md": "# example\n",
}


def git(repo, *args):
	return subprocess.run(
		["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t"] + list(args),
		check=True, capture_output=True, text=True,
	).stdout.strip()


class KitSyncTest(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		base = Path(self.tmp.name)
		self.kit = base / "kit"
		self.vault = base / "vault"
		self.kit.mkdir()
		self.vault.mkdir()
		git(self.kit, "init", "-q")
		self.write_kit({"kit.json": json.dumps(MANIFEST, indent="\t")})
		self.write_kit(FILES)
		self.commit_kit("first")
		self.quiet = contextlib.redirect_stdout(io.StringIO())
		self.quiet.__enter__()

	def tearDown(self):
		self.quiet.__exit__(None, None, None)
		self.tmp.cleanup()

	def write_kit(self, files):
		for rel, text in files.items():
			path = self.kit / rel
			path.parent.mkdir(parents=True, exist_ok=True)
			path.write_text(text)

	def commit_kit(self, message):
		git(self.kit, "add", "-A")
		git(self.kit, "commit", "-q", "-m", message)
		return git(self.kit, "rev-parse", "HEAD")

	def write_lock(self, lock):
		(self.vault / kit_sync.LOCK_NAME).write_text(json.dumps(lock))

	def read_lock(self):
		return json.loads((self.vault / kit_sync.LOCK_NAME).read_text())

	def actions(self):
		return {e["path"]: e for e in kit_sync.plan(str(self.vault), str(self.kit))}

	def adopt(self, *paths):
		kit_sync.init(str(self.vault), str(self.kit))
		return kit_sync.apply(str(self.vault), str(self.kit), list(paths))

	def snapshot(self):
		return {str(p.relative_to(self.vault)): p.read_bytes() for p in self.vault.rglob("*") if p.is_file()}

	# manifest (C1)

	def test_every_tracked_kit_file_is_in_one_component(self):
		listed = subprocess.run(
			["git", "-C", str(KIT_ROOT), "ls-files", "--cached", "--others", "--exclude-standard"],
			check=True, capture_output=True, text=True,
		).stdout.splitlines()

		manifest = kit_sync.load_manifest(str(KIT_ROOT))

		counted = [f["path"] for c in manifest["components"].values() for f in c["files"]]
		self.assertEqual(sorted(listed), sorted(counted))

	def test_examples_are_never_planned(self):
		kit_sync.init(str(self.vault), str(self.kit))

		actions = self.actions()

		self.assertEqual(actions["brain/Example.md"]["action"], "example")

	# plan (C3)

	def test_first_adoption_plans_new_files(self):
		kit_sync.init(str(self.vault), str(self.kit))

		actions = self.actions()

		self.assertEqual(actions["brain/RULES.md"]["action"], "new")
		self.assertEqual(actions["scripts/lint_brain.py"]["action"], "new")

	def test_existing_vault_file_is_flagged_not_overwritten(self):
		(self.vault / "CLAUDE.md").write_text("The vault's own rules.\n")
		kit_sync.init(str(self.vault), str(self.kit))

		actions = self.actions()

		self.assertEqual(actions["CLAUDE.md"]["action"], "exists-in-vault")

	def test_path_map_rewrites_destination(self):
		kit_sync.init(str(self.vault), str(self.kit), path_map={"scripts": "_scripts"})

		actions = self.actions()

		self.assertEqual(actions["scripts/lint_brain.py"]["vault_path"], "_scripts/lint_brain.py")

	def test_declined_component_is_skipped(self):
		kit_sync.init(str(self.vault), str(self.kit), components={"journal": "declined"})

		actions = self.actions()

		self.assertEqual(actions["templates/Journal Entry.md"]["action"], "declined")

	def test_kit_change_on_untouched_vault_file_is_update_clean(self):
		self.adopt("scripts/lint_brain.py")
		self.write_kit({"scripts/lint_brain.py": "print('lint v2')\n"})
		self.commit_kit("kit change")

		actions = self.actions()

		self.assertEqual(actions["scripts/lint_brain.py"]["action"], "update-clean")

	def test_nonoverlapping_edits_are_update_merge(self):
		self.adopt("brain/RULES.md")
		(self.vault / "brain/RULES.md").write_text("vault line 1\nline 2\nline 3\nline 4\nline 5\n")
		self.write_kit({"brain/RULES.md": "line 1\nline 2\nline 3\nline 4\nkit line 5\n"})
		self.commit_kit("kit change")

		actions = self.actions()

		self.assertEqual(actions["brain/RULES.md"]["action"], "update-merge")

	def test_overlapping_edits_are_conflict(self):
		self.adopt("brain/RULES.md")
		(self.vault / "brain/RULES.md").write_text("line 1\nline 2\nvault line 3\nline 4\nline 5\n")
		self.write_kit({"brain/RULES.md": "line 1\nline 2\nkit line 3\nline 4\nline 5\n"})
		self.commit_kit("kit change")

		actions = self.actions()

		self.assertEqual(actions["brain/RULES.md"]["action"], "conflict")

	def test_kept_vault_decision_rechecks_when_kit_side_changes(self):
		(self.vault / "CLAUDE.md").write_text("The vault's own rules.\n")
		kit_sync.init(str(self.vault), str(self.kit))
		kit_sync.decide(str(self.vault), str(self.kit), "agent-rules", "vault", "vault CLAUDE.md", "kit CLAUDE.md", paths=["CLAUDE.md"])
		self.write_kit({"CLAUDE.md": "Read brain/RULES.md and RULES.local.md.\n"})
		self.commit_kit("kit change")

		actions = self.actions()

		self.assertEqual(actions["CLAUDE.md"]["action"], "recheck")

	def test_file_removed_from_kit_is_reported_not_deleted(self):
		self.adopt("scripts/lint_brain.py")
		manifest = json.loads((self.kit / "kit.json").read_text())
		manifest["components"]["lint"]["files"] = []
		self.write_kit({"kit.json": json.dumps(manifest)})
		(self.kit / "scripts/lint_brain.py").unlink()
		self.commit_kit("drop lint")

		actions = self.actions()

		self.assertEqual(actions["scripts/lint_brain.py"]["action"], "removed-in-kit")
		self.assertTrue((self.vault / "scripts/lint_brain.py").exists())

	def test_plan_writes_nothing(self):
		(self.vault / "CLAUDE.md").write_text("The vault's own rules.\n")
		kit_sync.init(str(self.vault), str(self.kit))
		before = self.snapshot()

		kit_sync.plan(str(self.vault), str(self.kit))

		self.assertEqual(self.snapshot(), before)

	def test_vault_edit_without_kit_change_is_vault_edited(self):
		self.adopt("brain/RULES.md")
		(self.vault / "brain/RULES.md").write_text("vault rewrite\n")

		actions = self.actions()

		self.assertEqual(actions["brain/RULES.md"]["action"], "vault-edited")

	# apply, resolve, decide, init, check (C3)

	def test_apply_writes_file_and_lock_base(self):
		kit_sync.init(str(self.vault), str(self.kit))

		code = kit_sync.apply(str(self.vault), str(self.kit), ["scripts/lint_brain.py"])

		self.assertEqual(code, 0)
		self.assertEqual((self.vault / "scripts/lint_brain.py").read_text(), FILES["scripts/lint_brain.py"])
		self.assertEqual(self.read_lock()["files"]["scripts/lint_brain.py"]["base"], git(self.kit, "rev-parse", "HEAD:scripts/lint_brain.py"))

	def test_apply_refuses_a_conflict(self):
		self.adopt("brain/RULES.md")
		(self.vault / "brain/RULES.md").write_text("line 1\nline 2\nvault line 3\nline 4\nline 5\n")
		self.write_kit({"brain/RULES.md": "line 1\nline 2\nkit line 3\nline 4\nline 5\n"})
		self.commit_kit("kit change")
		lock_before = self.read_lock()

		code = kit_sync.apply(str(self.vault), str(self.kit), ["brain/RULES.md"])

		self.assertNotEqual(code, 0)
		self.assertEqual((self.vault / "brain/RULES.md").read_text(), "line 1\nline 2\nvault line 3\nline 4\nline 5\n")
		self.assertEqual(self.read_lock(), lock_before)

	def test_apply_merge_keeps_both_edits(self):
		self.adopt("brain/RULES.md")
		(self.vault / "brain/RULES.md").write_text("vault line 1\nline 2\nline 3\nline 4\nline 5\n")
		self.write_kit({"brain/RULES.md": "line 1\nline 2\nline 3\nline 4\nkit line 5\n"})
		self.commit_kit("kit change")

		kit_sync.apply(str(self.vault), str(self.kit), ["brain/RULES.md"])

		self.assertEqual((self.vault / "brain/RULES.md").read_text(), "vault line 1\nline 2\nline 3\nline 4\nkit line 5\n")

	def test_apply_safe_skips_undecided_optional_component(self):
		kit_sync.init(str(self.vault), str(self.kit))

		kit_sync.apply(str(self.vault), str(self.kit), [], safe=True)

		self.assertTrue((self.vault / "scripts/lint_brain.py").exists())
		self.assertFalse((self.vault / "templates/Journal Entry.md").exists())

	def test_resolve_records_base_and_keeps_vault_content(self):
		(self.vault / "CLAUDE.md").write_text("Merged by hand.\n")
		kit_sync.init(str(self.vault), str(self.kit))

		kit_sync.resolve(str(self.vault), str(self.kit), "CLAUDE.md")

		self.assertEqual((self.vault / "CLAUDE.md").read_text(), "Merged by hand.\n")
		self.assertEqual(self.read_lock()["files"]["CLAUDE.md"]["base"], git(self.kit, "rev-parse", "HEAD:CLAUDE.md"))

	def test_resolve_take_kit_writes_kit_content(self):
		(self.vault / "CLAUDE.md").write_text("The vault's own rules.\n")
		kit_sync.init(str(self.vault), str(self.kit))

		kit_sync.resolve(str(self.vault), str(self.kit), "CLAUDE.md", take_kit=True)

		self.assertEqual((self.vault / "CLAUDE.md").read_text(), FILES["CLAUDE.md"])

	def test_decide_records_choice_and_basis(self):
		kit_sync.init(str(self.vault), str(self.kit))

		kit_sync.decide(str(self.vault), str(self.kit), "journal-layout", "vault", "Journal/YYYY/", "journal/YYYY-MM-DD.md")

		decision = self.read_lock()["decisions"][0]
		self.assertEqual(decision["id"], "journal-layout")
		self.assertEqual(decision["choice"], "vault")
		self.assertEqual(decision["date"], datetime.date.today().isoformat())
		self.assertEqual(decision["kit_basis"], git(self.kit, "rev-parse", "HEAD"))
		self.assertEqual((decision["vault"], decision["kit"]), ("Journal/YYYY/", "journal/YYYY-MM-DD.md"))

	def test_init_writes_map_without_touching_files(self):
		before = self.snapshot()

		kit_sync.init(str(self.vault), str(self.kit), path_map={"brain": "_ai-brain"}, components={"journal": "declined"})

		lock = self.read_lock()
		self.assertEqual(lock["path_map"], {"brain": "_ai-brain"})
		self.assertEqual(lock["components"], {"journal": "declined"})
		self.assertEqual(set(self.snapshot()) - set(before), {kit_sync.LOCK_NAME})

	def test_check_flags_unknown_file(self):
		self.write_lock({"kit_source": str(self.kit), "kit_commit": None, "path_map": {}, "components": {}, "decisions": [],
			"files": {"scripts/gone.py": {"vault_path": "scripts/gone.py", "base": "0" * 40, "state": "copied"}}})

		errors = kit_sync.check(str(self.vault), str(self.kit))

		self.assertTrue(any("scripts/gone.py" in e for e in errors))


if __name__ == "__main__":
	unittest.main()
