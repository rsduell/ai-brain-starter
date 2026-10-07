---
type: brain-schedule
---

# Schedule

Optional. Everything dated in one list: recurring reviews, milestones, follow ups, deadlines. Human notes keep dates in plain language; formatted dates live only here. `python3 scripts/schedule.py report` turns it into a "Due and coming up" list. Rules: `brain/RULES.md` → Schedule.

Fictional examples below; replace them with your own.

## Milestones

### App 2.0 release
- next: TBD
- kind: milestone
- cadence: none
- source: fictional example
- calendar: no
Ask for the date when it's set. The report counts down and asks about prep at 14, 7, 3 and 1 days.

## Recurring

### Demo-Dev review
- next: 2026-10-30
- kind: recurring
- cadence: monthly until 2026-12-31, then quarterly
- about: [[Demo-Dev#Reviews]]
- source: fictional example
- calendar: no
Follow [[Demo-Dev#Reviews]]. Finish with `python3 scripts/schedule.py done "Demo-Dev review"`.

## One off

## Ignored
