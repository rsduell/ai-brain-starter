"""Tests for check_facts.py. Run: python3 -m unittest discover -s scripts"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainconfig  # noqa: E402
import check_facts  # noqa: E402


def git(repo, *args):
	return subprocess.run(["git", "-C", str(repo)] + list(args), check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, message):
	git(repo, "add", "-A")
	git(repo, "commit", "-q", "-m", message)
	return git(repo, "rev-parse", "--short", "HEAD")


def fact(anchors="`app:src/Flags.kt`", verified="2026-10-06 · app {sha}", extra=""):
	return (
		"### Device builds need FLAG on\n"
		"- anchors: %s\n"
		"- verified: %s\n"
		"- source: [[AI PROJ-1]] 2026-10-06\n"
		"- scope: personal\n"
		"%s"
		"Body.\n"
	) % (anchors, verified, extra)


class CheckDevFactsTest(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		base = Path(self.tmp.name)
		self.repo = base / "app"
		(self.repo / "src").mkdir(parents=True)
		git(base, "init", "-q", str(self.repo))
		git(self.repo, "config", "user.email", "t@t")
		git(self.repo, "config", "user.name", "t")
		(self.repo / "src" / "Flags.kt").write_text("const val FLAG = false\n")
		(self.repo / "src" / "Other.kt").write_text("val other = 1\n")
		self.sha = commit(self.repo, "initial")
		self.note = base / "note.md"

	def tearDown(self):
		self.tmp.cleanup()

	def run_check(self, text, today="2026-10-06"):
		self.note.write_text("---\nanchored: true\n---\n\n" + text)
		_, results = check_facts.check(self.tmp.name, [self.note], dict(brainconfig.DEFAULTS, repos={"app": str(self.repo)}), today=today)
		return results[0]

	def test_unchanged_anchor_is_ok(self):
		text = fact().format(sha=self.sha)

		result = self.run_check(text)

		self.assertEqual(result["status"], "ok")

	def test_modified_anchor_is_changed_with_pr_number(self):
		(self.repo / "src" / "Flags.kt").write_text("const val FLAG = true\n")
		commit(self.repo, "PROJ-9: Flip the flag (#1234)")
		text = fact().format(sha=self.sha)

		result = self.run_check(text)

		self.assertEqual(result["status"], "changed")
		self.assertIn("[PR #1234]", "\n".join(result["details"]))

	def test_unrelated_change_stays_ok(self):
		(self.repo / "src" / "Other.kt").write_text("val other = 2\n")
		commit(self.repo, "Touch another file")
		text = fact().format(sha=self.sha)

		result = self.run_check(text)

		self.assertEqual(result["status"], "ok")

	def test_deleted_anchor_is_missing(self):
		(self.repo / "src" / "Flags.kt").unlink()
		commit(self.repo, "Remove flags")
		text = fact().format(sha=self.sha)

		result = self.run_check(text)

		self.assertEqual(result["status"], "missing")

	def test_removed_symbol_is_missing(self):
		(self.repo / "src" / "Flags.kt").write_text("const val RENAMED = false\n")
		commit(self.repo, "Rename the flag")
		text = fact(anchors="`app:symbol:FLAG`").format(sha=self.sha)

		result = self.run_check(text)

		self.assertEqual(result["status"], "missing")

	def test_branch_anchor_checks_that_branch(self):
		git(self.repo, "checkout", "-q", "-b", "feature")
		(self.repo / "src" / "Feature.kt").write_text("val feature = 1\n")
		feature_sha = commit(self.repo, "Add a feature file")
		git(self.repo, "checkout", "-q", "-")
		text = fact(anchors="`app@feature:src/Feature.kt`", verified="2026-10-06 · app@feature {sha}").format(sha=feature_sha)

		result = self.run_check(text)

		self.assertEqual(result["status"], "ok")

	def test_branch_anchor_on_deleted_branch_is_malformed(self):
		text = fact(anchors="`app@gone:src/Flags.kt`", verified="2026-10-06 · app@gone {sha}").format(sha=self.sha)

		result = self.run_check(text)

		self.assertEqual(result["status"], "malformed")

	def test_unanchored_fact_past_recheck_is_due(self):
		text = "### Reply style\n- recheck: 2026-10-01\n- source: [[AI PROJ-1]] 2026-10-06\n- scope: personal\nBody.\n"

		result = self.run_check(text, today="2026-10-06")

		self.assertEqual(result["status"], "recheck due")

	def test_fact_with_nothing_to_check_is_malformed(self):
		text = "### Orphan fact\n- source: [[AI PROJ-1]] 2026-10-06\n- scope: personal\nBody.\n"

		result = self.run_check(text)

		self.assertEqual(result["status"], "malformed")

	def test_unknown_verified_sha_is_malformed(self):
		text = fact(verified="2026-10-06 · app deadbeef").format(sha=self.sha)

		result = self.run_check(text)

		self.assertEqual(result["status"], "malformed")


if __name__ == "__main__":
	unittest.main()
