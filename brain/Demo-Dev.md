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

## Team doc candidates
Every `scope: team` fact is a candidate for the repo's own docs; the repo owner decides.
- [[Demo-Dev.build]]: the JDK 17 requirement
