# Agent instructions

This repo is an agent written knowledge base (a "brain"). Before reading or writing anything under `brain/`, read `brain/RULES.md`. It is the only copy of the rules.

In short:
- **Answering:** start at `brain/INDEX.md`, read the cluster hub, grep the cluster, open only the matching leaf.
- **Working on a ticket:** log it as you go in `brain/issues/AI <TICKET>.md` and point to it from today's `brain/daily/AI Log YYYY-MM-DD.md`. Tag bullets `[used: ...]`, `[rediscovered: ...]`, `[miss]` or `[why]` when they apply (RULES.md → Measuring).
- **Journal:** if `journal/` exists, today's entry pairs with today's daily log; write only below its divider (RULES.md → Journal).
- **Dates:** if `brain/Schedule.md` exists, dated things go there (RULES.md → Schedule).
- **Documents in `inbox/ingest/`:** ingest them into a cluster (RULES.md → Ingesting documents).
- **Commit** explicit paths after each unit of work. The pre-commit hook lints what you staged.
