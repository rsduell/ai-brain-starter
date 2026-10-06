---
type: brain-issue
issue: DEMO-1
tracker: https://tracker.example.com/issue/DEMO-1
human: none
repositories:
  - app
role: author
branches:
  - app:demo-1-retry-sensor-upload
prs:
  - https://github.com/example/app/pull/42
status: done
updated: "2026-10-06"
---

# AI DEMO-1 · Retry failed sensor uploads

human note: none
tracker: [DEMO-1](https://tracker.example.com/issue/DEMO-1)
branch: `demo-1-retry-sensor-upload` (app)
PR: [app #42](https://github.com/example/app/pull/42)

## summary
- **what:** failed sensor uploads now retry with backoff instead of being dropped (fictional example).
- **PR:** [app #42](https://github.com/example/app/pull/42) merged 2026-10-03 as `9f1e2d3`.
- **open:** nothing.
- **gotchas:** promoted to [[Demo-Dev]].
- **promoted:** [[Demo-Dev.build]] · [[Demo-Dev.testing]]

## log

### 2026-10-06
- `brain` · Promoted the two gotchas to [[Demo-Dev]] at close.

### 2026-10-03
- `app` 15:10 · PR #42 merged (`9f1e2d3`) after review; reviewer asked for a jitter cap, added in `4c5d6e7`.

### 2026-10-01
- `app` 10:20 · Local build failed on JDK 25 (`Unsupported class file major version 69`). Fixed by pointing Gradle at JDK 17. Worth promoting.
- `app` 16:45 · Retry test passed even with the fix removed: the fake uploader never suspended. Added `yield()` to the fake; the test now fails without the fix.
