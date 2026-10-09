# AI Brain starter

A knowledge base that AI coding agents (Claude Code, Codex, Cursor) build, maintain and answer from, in plain Markdown inside a Git repo. Open it in Obsidian if you like the graph view; any editor works.

It's a form of RAG (retrieval augmented generation) without a vector database. Agents read each source once and write small, cited fact notes. Later questions are answered with a map plus exact text search.

## Why bother

Every agent session starts with amnesia. Without a memory you pay the same costs over and over:
- **You repeat yourself.** A correction ("don't do X in this repo") lasts one session.
- **Agents rediscover traps on your time.** The build that breaks on the wrong JDK gets debugged again next week.
- **Agents get things confidently wrong.** An old fact that a newer document overturned looks just as true to an agent.

The brain makes each correction and each trap cost you once. The rest of the design exists so that memory doesn't go stale.

## Why not a vector database

Standard RAG splits documents into chunks, embeds them, and retrieves the chunks most *similar* to a question. That's a poor fit when:
- **Questions are about identifiers** ("what does REQ-7 require?", "which commit fixed that?"). Similarity search is weakest on exact IDs; `grep` is perfect at them.
- **The collection is small and curated:** dozens or hundreds of notes, not millions of pages.
- **Facts change.** A chunk and its correction are both "similar" to the question, and both come back.
- **Answers need sources** someone can check.

So the work moves to when knowledge comes in: an agent turns sources into small notes, each cited to a page or row. Retrieval becomes cheap and exact. If you ever find questions missing because of wording ("due date" vs "closing response date"), add a vector index *beside* grep as a fallback, not instead of it.

## How it works

**Three kinds of agent notes**, all under `brain/`:

| Part | Holds | Example |
|---|---|---|
| **Clusters** | Facts from source documents or learned about a codebase: one hub note plus small topic notes | `Campus-Grant.md`, `Campus-Grant.requirements.md` |
| **Issue logs** | Everything agents did on one ticket: decisions, commits, PR state, gotchas, with a 12 line summary on top | `issues/AI DEMO-1.md` |
| **Daily logs** | The day's index, one line per ticket | `daily/AI Log 2026-10-06.md` |

**Knowledge in (ingest).** Drop documents in `inbox/ingest/` and ask the agent to ingest them:
1. It moves them to `assets/` and writes a `.txt` copy of each, with page and row markers.
2. It extracts facts (not summaries), each cited.
3. It splits them into notes **shaped by the questions people ask**.
4. It writes a hub with a question → note map.

**Answers out.** Index → cluster hub → map → grep for the ID → one to three small notes → source text only if exact wording matters. The agent's context stays small.

**Staying trustworthy:**
- **Provenance:** every fact cites its source file and page or row.
- **Facts vs opinion:** analysis is tagged `derived: true` and kept out of source fact notes.
- **Supersession markers:** when a newer source overturns a fact, the old line gets `[superseded 2026-10-06 → amendment 1: 14 days]`, so a search hit carries its own warning.
- **Freshness:** hubs carry `lifecycle` (`active`, `submitted`, `archived`) and an `as_of` date.
- **Code facts tied to code:** what agents learn about a codebase is anchored to files and symbols, and `scripts/check_facts.py` flags facts whose code changed on `origin/HEAD`, with the commits and PRs that changed it.
- **Lint on every commit:** a pre-commit hook blocks broken links, invalid statuses, overlong summaries, stale dates and malformed facts.
- **Git history:** every agent change is a reviewable, revertable commit.
- **Measured, not felt:** issue log bullets are tagged when a fact helped (`[used]`), when an agent hit a trap the brain already knew (`[rediscovered]`) or didn't (`[miss]`). `scripts/brain_metrics.py` counts those, plus lessons learned twice and how often change flags were noise, for a monthly or quarterly review against a baseline.

The full rules agents follow are in [`brain/RULES.md`](brain/RULES.md). Read that file to understand the system in depth.

## Quickstart

Needs Python 3.9+ and Git. Optional: `gh` (GitHub CLI) for PR lookups, `openpyxl` for spreadsheets, and on Linux or Windows `pdftotext` (poppler) and `pandoc` for PDFs and Word files.

1. Copy this folder and start a repo:
	```
	cp -R ai-brain-starter ~/my-brain && cd ~/my-brain
	git init && git config core.hooksPath hooks
	python3 -m unittest discover -s scripts      # 61 tests should pass
	python3 scripts/lint_brain.py --all          # should print nothing
	```
2. Edit `brain.json`: your ticket key pattern (Linear `ABC-123`, Jira, `GH-123`), the statuses you use, and where your code repos live (`repos` or `projects_dir`).
3. Open the folder in your agent tool and try the examples:
	- "What's the proposal deadline for the campus grant?" (it should find the amendment, not the original date)
	- "What did we learn on DEMO-1?"
	- "Is the Demo-Dev cluster paying off?" (it should run `brain_metrics.py` and read the numbers against the hub's baseline)
4. When you've seen how it works, delete the examples: `Campus-Grant*`, `Demo-Dev*`, `notes/Campus Grant.md`, `assets/Campus-Grant/`, `issues/AI DEMO-1.md`, the example daily log and `journal/2026-10-06.md`. Update `brain/INDEX.md`. Clear the example entries out of `brain/Schedule.md`, or delete it if you won't use a schedule.

## Using it while you work in other repos

The brain is most useful when agents log to it while working in your *code* repos. Add something like this to your global agent instructions (`~/.claude/CLAUDE.md` for Claude Code, `~/.codex/AGENTS.md` for Codex, a User Rule in Cursor):

```
My agent knowledge base lives at ~/my-brain. Read ~/my-brain/brain/RULES.md before your first
write to it in a session. Log real work there even when working in another repo: ticket work in
brain/issues/AI <TICKET>.md, a pointer on today's brain/daily/AI Log YYYY-MM-DD.md. Commit the
files you wrote, by explicit path. At the start of work in a repo covered by a <Project>-Dev
cluster, read that hub and run python3 ~/my-brain/scripts/check_facts.py. Tag issue log bullets
[used: [[leaf]]], [rediscovered: [[leaf]]], [miss] or [why] when they apply (RULES.md → Measuring).
```

## Everyday use

| You say | The agent |
|---|---|
| "Ingest what's in the inbox" | Builds or extends a cluster from `inbox/ingest/` |
| "What does the RFP say about X?" | Hub → grep → leaf, citing page or row |
| (working a ticket) | Keeps the ticket's issue log and today's pointer current |
| "This ticket's merged" | Promotes durable gotchas into the codebase cluster |
| "Why is this code like this?" | Follows blame → PR → review threads → ticket, and keeps a hard won answer as a fact |
| "Run the checks" | `lint_brain.py --all` and `check_facts.py` |
| "Is the Demo-Dev cluster paying off?" | `brain_metrics.py` for the window since the last review, read against the baseline |
| "Plan PROJ-123", then "implement the plan" and "verify it" in other tools (optional plans) | Files the plan in `plans/` as written; each tool records its part there |
| "Wrap up the day" (optional journal) | Summarizes today's daily log into the journal, below the divider |
| "What's coming up?" (optional schedule) | Scans your notes for new dates and asks about each, then prints due and coming up |

## Start small

You don't need all of it on day one:
1. **Issue logs and daily logs** alone already fix most of the amnesia.
2. **Add a document cluster** the first time you have a source you keep asking questions about.
3. **Add a codebase cluster** once you notice the same gotcha being rediscovered. Take a baseline when you seed it and tag issue logs from day one, so the first review has numbers.
4. **Add a journal** if you want a note of your own for each day, linked to the agents' daily log (below).
5. **Add the schedule** if dates keep slipping through your notes (below).
6. **Add plan notes** if you plan in one AI and implement or verify in another (below).

## Optional: a journal

`journal/YYYY-MM-DD.md` is your note for the day: meetings, decisions, what you worked on. It pairs with the agents' daily log for the same date, each linking the other. Above the `---` divider is yours and agents never touch it. Below it, agents keep a short list: the schedule report (if you use one), one line per ticket worked that day linking its issue log, and an end of day wrap up summarizing the daily log. Detail stays in the brain, so the journal stays readable. Rules: `brain/RULES.md` → Journal.

The date scan reads `journal/` along with `notes/`, so dates you write there reach the schedule.

## Optional: plan notes

If you plan with one AI, implement with another and verify with a third, `plans/<TICKET> Plan.md` is the handoff. Each plan goes in exactly as the planning tool wrote it, never reformatted. Around it sit a status, who did each phase, a checkbox per step for the implementer, anything the plan lacks that another AI needs, and the implementer's deviations. The verifier checks the work against it and records the result. Rules: `brain/RULES.md` → Plans.

## Optional: a schedule

`brain/Schedule.md` keeps everything dated in one list: recurring reviews (like the cluster review), milestones (a freeze, a release), follow ups and deadlines. You keep writing dates in plain language in your own notes. Each morning, ask the agent to run the routine in `brain/RULES.md` → Schedule:
1. **Date scan:** it finds dates added to your notes since the last scan ("demo on the 20th", "by Friday") and asks once whether each is a schedule item, a milestone, a calendar event or nothing.
2. **Due and coming up:** overdue and today's items, the next week and a half, milestone countdowns with prep reminders, plus brain upkeep that's due (facts to recheck, stale hubs, logs to compact).

If your agent has calendar or tracker tools, it can also add one off calendar events and your sprint dates to the report. Nothing reaches your calendar without your OK.

## Tradeoffs

- **The effort is on the way in.** Ingest and logging take agent work, and quality depends on the agent following `RULES.md`. The lint checks the mechanical parts, not judgment.
- **grep is literal.** The hub maps bridge wording; past a few hundred notes you may want a vector fallback.
- **PDF tables extract column by column.** Check table facts against the original.
- **A change flag means "this file changed", not "this fact is wrong".** Anchor to symbols rather than busy files to keep the noise down.

## Layout

```
AGENTS.md / CLAUDE.md     tell agents to read brain/RULES.md
brain.json                project settings
brain/                    the agent notes (RULES.md, INDEX.md, clusters, issues/, daily/)
assets/                   source files and their .txt sidecars
inbox/ingest/             drop zone for documents to ingest
notes/                    notes written by humans (optional)
journal/                  your day notes, paired with the daily logs (optional)
plans/                    agent plans, the handoff between AIs (optional)
templates/                hub, leaf, code facts leaf, issue log, daily log, journal entry, plan, schedule
scripts/                  lint_brain.py, check_facts.py, brain_metrics.py, asset_text.py (+ pdf_text.swift),
                          schedule.py and date_scan.py (optional schedule), tests
hooks/pre-commit          secrets, file size, lint
```
