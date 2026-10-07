"""Tests for brain_metrics.py. Run: python3 -m unittest discover -s scripts"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_metrics  # noqa: E402
import brainconfig  # noqa: E402


def fact(heading, source, verified="2026-10-06 · app abc1234"):
	return "### %s\n- anchors: `app:a.kt`\n- verified: %s\n- source: %s\n- scope: team\nBody.\n\n" % (heading, verified, source)


LEAF_HEAD = "---\ntype: brain-node\nanchored: true\n---\n\n# Dev.build\n\n"


class BrainMetricsTest(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.root = Path(self.tmp.name)
		self.cfg = dict(brainconfig.DEFAULTS)
		(self.root / "brain" / "issues").mkdir(parents=True)
		self.git("init", "-q")
		self.git("config", "user.email", "t@t")
		self.git("config", "user.name", "t")
		self.leaf = self.root / "brain" / "Dev.build.md"
		self.leaf.write_text(LEAF_HEAD + fact("Old fact", "[[AI PROJ-1]] 2026-10-01"))
		self.commit("seed", "2026-10-06T12:00:00")

	def tearDown(self):
		self.tmp.cleanup()

	def git(self, *args, date=None):
		env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date) if date else None
		subprocess.run(["git", "-C", str(self.root)] + list(args), check=True, capture_output=True, env=env)

	def commit(self, message, date):
		self.git("add", "-A")
		self.git("commit", "-q", "-m", message, date=date)

	def write_issue(self, name, text):
		(self.root / "brain" / "issues" / name).write_text(text)

	def test_tags_are_counted_only_inside_the_window(self):
		self.write_issue("AI PROJ-2.md", "## log\n\n### 2026-10-20\n- `app` · fixed it [used: [[Dev.build]]] [why]\n\n### 2026-10-01\n- `app` · old [miss]\n")

		counts, used = brain_metrics.window_tags(self.root, self.cfg, "2026-10-07", "2026-10-27")

		self.assertEqual((counts["used"], counts["why"], counts["miss"]), (1, 1, 0))
		self.assertEqual(used["Dev.build"], 1)

	def test_old_fact_with_new_source_counts_as_relearned(self):
		self.leaf.write_text(LEAF_HEAD + fact("Old fact", "[[AI PROJ-1]] 2026-10-01 · [[AI PROJ-9]] 2026-10-15") + fact("New fact", "[[AI PROJ-9]] 2026-10-15"))
		self.commit("promote", "2026-10-15T12:00:00")

		hits, new_facts = brain_metrics.relearned(self.root, self.cfg, "Dev", "2026-10-07", "2026-10-27")

		self.assertEqual([(h[1], h[2]) for h in hits], [("Old fact", ["PROJ-9"])])
		self.assertEqual(new_facts, 1)

	def test_verified_bump_is_noise_and_superseded_marker_is_caught(self):
		self.leaf.write_text(LEAF_HEAD + fact("Old fact", "[[AI PROJ-1]] 2026-10-01", verified="2026-10-20 · app def5678"))
		self.commit("recheck: still true", "2026-10-20T12:00:00")
		self.leaf.write_text(LEAF_HEAD + fact("Old fact [superseded 2026-10-22 → [[X]]: gone]", "[[AI PROJ-1]] 2026-10-01", verified="2026-10-20 · app def5678"))
		self.commit("recheck: wrong now", "2026-10-22T12:00:00")

		bumps, superseded = brain_metrics.flag_outcomes(self.root, self.cfg, "Dev", "2026-10-07", "2026-10-27")

		self.assertEqual((bumps, superseded), (1, 1))

	def test_closed_tickets_without_promoted_line_are_reported(self):
		self.write_issue("AI PROJ-3.md", '---\nstatus: done\nupdated: "2026-10-20"\n---\n## summary\n- **promoted:** none\n')
		self.write_issue("AI PROJ-4.md", '---\nstatus: merged\nupdated: "2026-10-21"\n---\n## summary\n- what\n')
		self.write_issue("AI PROJ-5.md", '---\nstatus: in review\nupdated: "2026-10-21"\n---\n')

		closed, promoted = brain_metrics.promotion(self.root, self.cfg, "2026-10-07", "2026-10-27")

		self.assertEqual((sorted(closed), promoted), (["AI PROJ-3", "AI PROJ-4"], ["AI PROJ-3"]))

	def test_baseline_counts_facts_learned_on_two_tickets(self):
		self.leaf.write_text(LEAF_HEAD + fact("Twice", "[[AI PROJ-1]] 2026-10-01 · [[AI PROJ-2]] 2026-10-03") + fact("Once", "[[AI PROJ-1]] 2026-10-01"))

		total, multi = brain_metrics.baseline(self.root, self.cfg, "Dev")

		self.assertEqual((total, [f["heading"] for f in multi]), (2, ["Twice"]))

	def test_headings_in_the_hub_are_not_facts(self):
		(self.root / "brain" / "Dev.md").write_text("---\ntype: brain-hub\n---\n\n## Reviews\n\n### Review log\nNone yet.\n")

		total, _ = brain_metrics.baseline(self.root, self.cfg, "Dev")

		self.assertEqual(total, 1)


if __name__ == "__main__":
	unittest.main()
