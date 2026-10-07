---
type: brain-hub
cluster: Demo-Dev
lifecycle: active
as_of: "2026-10-06"
relates:
  - "[[Demo-Dev.build]]"
  - "[[Demo-Dev.testing]]"
---

# Demo-Dev hub

Fictional example. What agents learned building and testing the `app` repo, promoted from issue logs when tickets close. Repo docs come first; this holds what they don't say.

**Start of work in `app`:** read this hub, run `python3 scripts/check_facts.py`, read the matching leaf before a build or test task, and grep `brain/Demo-Dev*.md` for an error before debugging from scratch.

## TRAVERSE
- won't build, JDK, local setup → [[Demo-Dev.build]]
- tests that pass when they shouldn't, fakes, coroutines → [[Demo-Dev.testing]]

## one screen facts
- Gradle needs JDK 17; JDK 25 fails with `major version 69`.
- Fakes of suspending calls must `yield()`, or cancellation tests prove nothing.

## Reviews
Is this cluster paying off? Count it rather than going by feel (`brain/RULES.md` → Measuring).

**Schedule:** [[Schedule#Demo-Dev review]], monthly to the end of the year, then quarterly.

**Run:** `python3 scripts/brain_metrics.py --cluster Demo-Dev --since <day after the previous review>` and `python3 scripts/check_facts.py`. Paste the block into the review log below with a one line verdict and what you decided, then `python3 scripts/schedule.py done "Demo-Dev review"`.

**Baseline** (taken when the cluster was seeded, 2026-10-06): 2 facts, none cited by two or more issue logs (`--baseline`). Compare each window's relearned and rediscovered counts against it.

### Review log
None yet.

## Team doc candidates
Every `scope: team` fact is a candidate for the repo's own docs; the repo owner decides.
- [[Demo-Dev.build]]: the JDK 17 requirement
