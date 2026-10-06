---
type: brain-node
cluster: Demo-Dev
anchored: true
derived: true
relates:
  - "[[Demo-Dev]]"
---

# Demo-Dev.testing

### Fakes of suspending calls must yield()
- recheck: 2027-01-04
- source: [[AI DEMO-1]] 2026-10-01 · [app #42](https://github.com/example/app/pull/42)
- scope: team
A fake that never suspends lets a cancellation test pass even with the fix removed. Add `yield()` to the fake, then confirm the test fails without the fix.
