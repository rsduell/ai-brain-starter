---
type: brain-node
cluster: Demo-Dev
anchored: true
derived: true
relates:
  - "[[Demo-Dev]]"
---

# Demo-Dev.build

Local setup and builds for the fictional `app` repo. In a real cluster, facts carry `anchors:` and `verified:` tied to the repo (see `templates/Code Facts Leaf.md`); these examples use recheck dates because `app` doesn't exist.

### Gradle needs JDK 17; JDK 25 fails the build
- recheck: 2027-01-04
- source: [[AI DEMO-1]] 2026-10-01
- scope: team
`Unsupported class file major version 69` means Gradle is running on JDK 25. Point the IDE's Gradle JDK and `JAVA_HOME` at JDK 17.
