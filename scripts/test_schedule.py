"""Tests for schedule.py. Run: python3 -m unittest discover -s scripts"""
import datetime as dt
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import schedule  # noqa: E402

D = dt.date.fromisoformat
SPRINTS = [
	{"number": 8, "startsAt": "2026-09-21T06:00:00.000Z", "endsAt": "2026-10-05T06:00:00.000Z"},
	{"number": 9, "startsAt": "2026-10-12T06:00:00.000Z", "endsAt": "2026-10-26T06:00:00.000Z"},
	{"number": 10, "startsAt": "2026-11-02T06:00:00.000Z", "endsAt": "2026-11-16T06:00:00.000Z"},
]


class ScheduleTest(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.root = Path(self.tmp.name)
		(self.root / "brain" / "issues").mkdir(parents=True)

	def tearDown(self):
		self.tmp.cleanup()

	def write_schedule(self, body, frontmatter=""):
		(self.root / "brain" / "Schedule.md").write_text("---\ntype: brain-schedule\n%s---\n\n%s" % (frontmatter, body))

	def test_window_ends_friday_of_next_week_from_wednesday(self):
		today = D("2026-10-07")

		end = schedule.window_end(today)

		self.assertEqual(end, D("2026-10-16"))

	def test_window_ends_friday_of_next_week_from_friday(self):
		today = D("2026-10-09")

		end = schedule.window_end(today)

		self.assertEqual(end, D("2026-10-16"))

	def test_past_entry_is_overdue(self):
		self.write_schedule("## One off\n\n### Send the invite\n- next: 2026-10-05\n- kind: task\n")

		out = schedule.report(self.root, D("2026-10-07"))

		self.assertIn("Overdue\n- [ ] [[Schedule#Send the invite|Send the invite]] · due Mon 10-05", out)

	def test_entry_in_window_is_coming_up(self):
		self.write_schedule("## Recurring\n\n### Review\n- next: 2026-10-15\n- kind: recurring\n- cadence: monthly\n")

		out = schedule.report(self.root, D("2026-10-07"))

		self.assertIn("Coming up\n- Thu 10-15 · [[Schedule#Review|Review]]", out)

	def test_after_entry_is_due_the_day_after_its_milestone(self):
		self.write_schedule(
			"## Milestones\n\n### Code freeze\n- next: 2026-10-13\n- kind: milestone\n\n"
			"## One off\n\n### Merge the branch\n- next: TBD\n- kind: task\n- after: [[Schedule#Code freeze]]\n")

		out = schedule.report(self.root, D("2026-10-07"))

		self.assertIn("- Wed 10-14 · [[Schedule#Merge the branch|Merge the branch]]", out)

	def test_milestone_shows_countdown_and_prep_nudge_at_seven_days(self):
		self.write_schedule("## Milestones\n\n### Code freeze\n- next: 2026-10-14\n- kind: milestone\n- affects: [[AI PROJ-7]]\n")

		out = schedule.report(self.root, D("2026-10-07"))

		self.assertIn("Milestones: Code freeze Wed 10-14 (7 days)", out)
		self.assertIn("in 7 days: anything to prep? Affects [[AI PROJ-7]]", out)

	def test_tbd_milestone_is_listed_without_a_date(self):
		self.write_schedule("## Milestones\n\n### 2.0 release\n- next: TBD\n- kind: milestone\n")

		out = schedule.report(self.root, D("2026-10-07"))

		self.assertIn("Milestones: 2.0 release (date TBD)", out)

	def test_sprint_line_between_sprints(self):
		today = D("2026-10-07")

		line = schedule.sprint_line(SPRINTS, today)

		self.assertEqual(line, "between sprints · Sprint 9 starts Mon 10-12")

	def test_sprint_line_inside_a_sprint(self):
		today = D("2026-10-14")

		line = schedule.sprint_line(SPRINTS, today)

		self.assertEqual(line, "Sprint 9 · 8 working days left · ends Fri 10-23 · break 10-26 to 10-30")

	def test_moves_override_the_shown_date(self):
		self.write_schedule("## Recurring\n\n### Review\n- next: 2026-10-15\n- kind: recurring\n- cadence: monthly\n- moves: 2026-10-15 → 2026-10-16\n")

		out = schedule.report(self.root, D("2026-10-07"))

		self.assertIn("- Fri 10-16 · [[Schedule#Review|Review]]", out)

	def test_done_monthly_moves_to_last_day_of_next_month(self):
		self.write_schedule("## Recurring\n\n### Review\n- next: 2026-10-31\n- kind: recurring\n- cadence: monthly\nBody.\n")

		following = schedule.done(self.root, "Review", D("2026-10-31"))

		self.assertEqual(following, D("2026-11-30"))
		text = (self.root / "brain" / "Schedule.md").read_text()
		self.assertIn("- next: 2026-11-30\n", text)
		self.assertIn("- last: 2026-10-31\nBody.", text)

	def test_done_switches_from_monthly_to_quarterly_after_until(self):
		cadence = "monthly until 2026-12-31, then quarterly"

		following = schedule.next_date(cadence, D("2026-12-31"))

		self.assertEqual(following, D("2027-03-31"))

	def test_quarterly_moves_to_next_quarter_end(self):
		cadence = "quarterly"

		following = schedule.next_date(cadence, D("2027-03-31"))

		self.assertEqual(following, D("2027-06-30"))

	def test_done_without_cadence_moves_entry_to_done(self):
		self.write_schedule("## One off\n\n### Send the invite\n- next: 2026-10-05\n- kind: task\n")

		following = schedule.done(self.root, "Send the invite", D("2026-10-07"))

		self.assertIsNone(following)
		text = (self.root / "brain" / "Schedule.md").read_text()
		self.assertLess(text.index("## Done"), text.index("### Send the invite"))

	def test_mark_sets_and_replaces_frontmatter_fields(self):
		self.write_schedule("## One off\n", frontmatter="last_scan: abc\n")

		schedule.mark(self.root, scan="def", report_time="2026-10-07T13:00:00Z")

		text = (self.root / "brain" / "Schedule.md").read_text()
		self.assertIn("last_scan: def\nlast_report: 2026-10-07T13:00:00Z\n---", text)

	def test_dated_todo_in_a_human_note_shows_when_due(self):
		(self.root / "notes").mkdir()
		(self.root / "notes" / "Launch plan.md").write_text("- [ ] **2026-10-07** · Book the room\n")
		self.write_schedule("")

		out = schedule.report(self.root, D("2026-10-07"))

		self.assertIn("Today\n- [ ] Book the room (from [[Launch plan]])", out)

	def test_old_busy_log_section_is_due_for_compaction(self):
		(self.root / "brain" / "issues" / "AI PROJ-1.md").write_text("## summary\n- x\n\n## log\n\n### 2026-09-14\n- a\n- b\n- c\n- d\n")
		self.write_schedule("")

		out = schedule.report(self.root, D("2026-10-07"))

		self.assertIn("Compact old log sections (promote first) in 1 issue log: [[AI PROJ-1]]", out)


if __name__ == "__main__":
	unittest.main()
