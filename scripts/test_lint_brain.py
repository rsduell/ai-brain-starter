"""Tests for lint_brain.py. Run: python3 -m unittest discover -s scripts"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainconfig  # noqa: E402
import lint_brain  # noqa: E402


def issue_log(status="in review", role="author", updated="2026-10-06", log_date="2026-10-06", summary_lines=3):
	summary = "\n".join("- line %d" % n for n in range(summary_lines))
	return (
		"---\n"
		"type: brain-issue\n"
		"issue: PROJ-1\n"
		"tracker: https://tracker.example.com/PROJ-1\n"
		'human: "[[PROJ-1]]"\n'
		"repositories:\n  - app\n"
		"role: %s\n"
		"branches:\n  - app:proj-1\n"
		"prs:\n  - https://github.com/example/app/pull/1\n"
		"status: %s\n"
		'updated: "%s"\n'
		"---\n\n"
		"# AI PROJ-1 · Title\n\n"
		"human note: [[PROJ-1]]\n\n"
		"## summary\n%s\n\n"
		"## log\n\n### %s\n- work\n"
	) % (role, status, updated, summary, log_date)


class LintTest(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.root = Path(self.tmp.name)
		(self.root / "brain" / "issues").mkdir(parents=True)
		(self.root / "notes").mkdir()
		(self.root / "notes" / "Exists.md").write_text("x")
		self.cfg = dict(brainconfig.DEFAULTS)

	def tearDown(self):
		self.tmp.cleanup()

	def write(self, rel, text):
		path = self.root / rel
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(text)
		return rel

	def lint(self, rel):
		return lint_brain.lint_paths(self.root, [rel], self.cfg)

	def anchored(self, body):
		return self.write("brain/Dev.build.md", "---\ntype: brain-node\nanchored: true\n---\n\n" + body)

	def test_broken_link_is_reported(self):
		rel = self.write("brain/node.md", "see [[Missing Note]] and [[Exists]]\n")

		results = self.lint(rel)

		self.assertEqual(results, ["brain/node.md:1: unresolved link [[Missing Note]]"])

	def test_link_inside_code_is_ignored(self):
		rel = self.write("brain/node.md", "use `[[Missing]]` here\n```\n[[Also Missing]]\n```\n")

		results = self.lint(rel)

		self.assertEqual(results, [])

	def test_missing_human_note_allowed_in_issue_log_header(self):
		rel = self.write("brain/issues/AI PROJ-1.md", issue_log())

		results = self.lint(rel)

		self.assertEqual(results, [])

	def test_missing_ticket_note_rejected_in_body(self):
		rel = self.write("brain/issues/AI PROJ-1.md", issue_log() + "- follow up [[PROJ-2]]\n")

		results = self.lint(rel)

		self.assertEqual(len(results), 1)
		self.assertIn("unresolved link [[PROJ-2]]", results[0])

	def test_bad_status_is_reported(self):
		rel = self.write("brain/issues/AI PROJ-1.md", issue_log(status="review requested"))

		results = self.lint(rel)

		self.assertEqual(len(results), 1)
		self.assertIn("status `review requested`", results[0])

	def test_statuses_come_from_config(self):
		self.cfg["issue_statuses"] = ["todo", "doing", "done"]
		rel = self.write("brain/issues/AI PROJ-1.md", issue_log(status="doing"))

		results = self.lint(rel)

		self.assertEqual(results, [])

	def test_long_summary_is_reported(self):
		rel = self.write("brain/issues/AI PROJ-1.md", issue_log(summary_lines=13))

		results = self.lint(rel)

		self.assertEqual(len(results), 1)
		self.assertIn("summary has 13 lines", results[0])

	def test_stale_updated_is_reported(self):
		rel = self.write("brain/issues/AI PROJ-1.md", issue_log(updated="2026-10-01", log_date="2026-10-06"))

		results = self.lint(rel)

		self.assertEqual(len(results), 1)
		self.assertIn("older than the newest log heading", results[0])

	def test_hub_missing_lifecycle_is_reported(self):
		rel = self.write("brain/X.md", '---\ntype: brain-hub\nas_of: "2026-10-06"\n---\n')

		results = self.lint(rel)

		self.assertEqual(len(results), 1)
		self.assertIn("hub needs `lifecycle:`", results[0])

	def test_superseded_marker_without_link_is_reported(self):
		rel = self.write("brain/node.md", "### REQ-7 RISK [superseded 2026-09-22: NO]\n")

		results = self.lint(rel)

		self.assertEqual(len(results), 1)
		self.assertIn("marker has no [[link]]", results[0])

	def test_complete_anchored_fact_passes(self):
		rel = self.anchored("### Fact\n- anchors: `app:src/Flags.kt`\n- verified: 2026-10-06 · app e4e465de4\n- source: [[Exists]]\n- scope: team\nBody.\n")

		results = self.lint(rel)

		self.assertEqual(results, [])

	def test_fact_without_anchors_or_recheck_is_reported(self):
		rel = self.anchored("### Fact\n- source: [[Exists]]\n- scope: personal\nBody.\n")

		results = self.lint(rel)

		self.assertEqual(len(results), 1)
		self.assertIn("needs `- anchors:`", results[0])

	def test_verified_missing_a_repo_is_reported(self):
		rel = self.anchored("### Fact\n- anchors: `app:a.kt`, `plugin:b.kt`\n- verified: 2026-10-06 · app e4e465de4\n- source: [[Exists]]\n- scope: personal\nBody.\n")

		results = self.lint(rel)

		self.assertEqual(len(results), 1)
		self.assertIn("no SHA for anchor repo `plugin`", results[0])

	def test_fact_with_bad_scope_is_reported(self):
		rel = self.anchored("### Fact\n- recheck: 2027-01-04\n- source: [[Exists]]\n- scope: global\nBody.\n")

		results = self.lint(rel)

		self.assertEqual(len(results), 1)
		self.assertIn("fact scope `global`", results[0])

	def schedule(self, entry):
		return self.write("brain/Schedule.md", "---\ntype: brain-schedule\n---\n\n## One off\n\n" + entry)

	def test_valid_schedule_entry_passes(self):
		rel = self.schedule("### Review\n- next: 2026-10-27\n- kind: recurring\n- cadence: monthly until 2026-12-31, then quarterly\n- moves: 2026-12-31 → 2027-01-01\nDo it.\n")

		results = self.lint(rel)

		self.assertEqual(results, [])

	def test_tbd_milestone_passes(self):
		rel = self.schedule("### Release\n- next: TBD\n- kind: milestone\n")

		results = self.lint(rel)

		self.assertEqual(results, [])

	def test_schedule_entry_with_bad_date_is_reported(self):
		rel = self.schedule("### Review\n- next: Oct 27\n- kind: task\n")

		results = self.lint(rel)

		self.assertEqual(len(results), 1)
		self.assertIn("needs `- next:", results[0])

	def test_schedule_entry_with_bad_kind_and_cadence_is_reported(self):
		rel = self.schedule("### Review\n- next: 2026-10-27\n- kind: chore\n- cadence: biweekly\n")

		results = self.lint(rel)

		self.assertEqual(len(results), 2)

	def test_schedule_entry_with_bad_moves_is_reported(self):
		rel = self.schedule("### Review\n- next: 2026-10-27\n- kind: task\n- moves: 12-31 to 01-01\n")

		results = self.lint(rel)

		self.assertEqual(len(results), 1)
		self.assertIn("moves", results[0])


if __name__ == "__main__":
	unittest.main()
