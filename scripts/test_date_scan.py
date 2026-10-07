"""Tests for date_scan.py. Run: python3 -m unittest discover -s scripts"""
import datetime as dt
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainconfig  # noqa: E402
import date_scan  # noqa: E402

TODAY = dt.date(2026, 10, 7)


class DateScanTest(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.root = Path(self.tmp.name)
		for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
			self.git(*args)
		self.note = self.root / "notes" / "2026-10-07.md"
		self.note.parent.mkdir(parents=True)
		self.note.write_text("# Daily note\n- old line, freeze on 2026-10-30\n")
		(self.root / "brain").mkdir()
		(self.root / "brain" / "Schedule.md").write_text("---\ntype: brain-schedule\n---\n\n## Ignored\n- notes/x.md · \"Retro on 2026-11-02\"\n")
		self.git("add", "-A")
		self.git("commit", "-q", "-m", "base")
		self.base = self.git("rev-parse", "HEAD").strip()
		self.cfg = dict(brainconfig.DEFAULTS)

	def tearDown(self):
		self.tmp.cleanup()

	def git(self, *args):
		return subprocess.run(["git", "-C", str(self.root)] + list(args), check=True, capture_output=True, text=True).stdout

	def add_to_note(self, *lines):
		self.note.write_text(self.note.read_text() + "\n".join(lines) + "\n")

	def texts(self):
		return [c["text"] for c in date_scan.scan(self.root, self.base, today=TODAY, cfg=self.cfg)]

	def test_only_lines_added_since_the_commit_are_scanned(self):
		self.add_to_note("- Demo for the client on 2026-10-14")

		found = self.texts()

		self.assertEqual(found, ["- Demo for the client on 2026-10-14"])

	def test_past_absolute_date_is_dropped(self):
		self.add_to_note("- merged on 10-05")

		found = self.texts()

		self.assertEqual(found, [])

	def test_named_month_and_relative_phrases_are_found(self):
		self.add_to_note("- Send the deck by Oct 20", "- Book the room next week")

		found = self.texts()

		self.assertEqual(found, ["- Send the deck by Oct 20", "- Book the room next week"])

	def test_dates_inside_links_are_ignored(self):
		self.add_to_note("Agent log: [[AI Log 2026-10-08]]", "- see https://example.com/2026/11/15/post")

		found = self.texts()

		self.assertEqual(found, [])

	def test_last_weekday_is_a_reference_not_a_plan(self):
		self.add_to_note("- 330 million lines last Thursday")

		found = self.texts()

		self.assertEqual(found, [])

	def test_ignored_line_is_skipped(self):
		self.add_to_note("Retro on 2026-11-02")

		found = self.texts()

		self.assertEqual(found, [])

	def test_milestone_and_recurring_flags(self):
		self.add_to_note("- Code freeze 2026-10-23", "- Standup every Tuesday starting 2026-10-13")

		found = date_scan.scan(self.root, self.base, today=TODAY, cfg=self.cfg)

		self.assertEqual([c["flags"] for c in found], [["milestone?"], ["recurring?"]])

	def test_pasted_schedule_report_is_not_scanned(self):
		self.add_to_note("## Due and coming up (through Fri 10-16)", "- Thu 10-15 · Demo-Dev review", "## Notes", "- Demo on 2026-10-20")

		found = self.texts()

		self.assertEqual(found, ["- Demo on 2026-10-20"])

	def test_agent_notes_are_never_scanned(self):
		(self.root / "brain" / "Demo-Dev.md").write_text("- review on 2026-10-27\n")

		found = self.texts()

		self.assertEqual(found, [])


if __name__ == "__main__":
	unittest.main()
