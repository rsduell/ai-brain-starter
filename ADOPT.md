# Adopting the kit into a vault, and updating it later

For an agent working in a vault (an Obsidian vault, or any folder of notes) that should follow this kit's methods. The kit stays in its own clone; the vault gets copies of the parts it adopts, plus two files of its own:
- `kit.lock.json` at the vault root: which kit commit was applied, where each kit folder lives in the vault, which optional parts were taken or declined, and every answer the human gave. `scripts/kit_sync.py` reads and writes it.
- `RULES.local.md` beside the vault's copy of `brain/RULES.md`: everything this vault does differently from the kit, each with the kit rule it replaces. Agents read both, and `RULES.local.md` wins.

The kit's own files are copied **unchanged** wherever possible. The vault's differences go in `RULES.local.md`, not into the copies, so a later kit update applies without questions.

Run every command from the vault, pointing at the kit's clone:
```
python3 <kit>/scripts/kit_sync.py <command> --vault .
```
`<kit>` is the clone's path, for example `~/Local/ai-brain-starter`. `kit_sync.py --help` and the script's docstring list the commands and what each `plan` action means.

## Ground rules

- **Ask, never settle.** Wherever the vault and the kit do something differently, ask the human. Don't pick a side because one looks newer or tidier, and never call the kit's way the default or the correct one.
- **Label every side.** Use the question format below, every time.
- **Nothing is written before the answers.** `plan` changes nothing. Files change only through `apply` and `resolve`, after the human has answered.
- **Never delete or overwrite vault content** outside `apply` and `resolve`. `removed-in-kit` is only reported.
- **Never adopt the examples** (Campus-Grant, Demo-Dev, `AI DEMO-1`, the sample journal and note, `brain/INDEX.md`, `brain/Schedule.md`). `plan` marks them `example`.
- **Never edit the kit from a vault session.** If the kit itself needs a change, say so to the human.

## The question format

Every question names its topic, then one `Vault:` line and one `Kit:` line, each with where it comes from, then the options and what each one does:
```
Conflict: journal layout
Vault: Journal/YYYY/MM-MMMM/YYYY-MM-DD.md  (from Journal/CLAUDE.md, existing)
Kit:   journal/YYYY-MM-DD.md               (from brain/RULES.md → Journal, kit 7af5b89)
Options: keep vault (recorded in RULES.local.md) · take kit (moves 212 files) · skip the journal part
```
- The vault's source is the file (or Obsidian setting) where the vault's way is written down, or "existing" when it's only how the files are laid out.
- The kit's source is the kit file and section, with the kit commit.
- Ask at most four questions at once, most consequential first.
- For a file conflict, show the differing lines from both sides, labeled the same way.

## First adoption

1. **Read the kit:** `README.md`, `brain/RULES.md` and `kit.json` (its components and what each one is for).
2. **Survey the vault** and write down what you find:
	- its folders, and where notes, attachments, journals and templates live
	- its agent rules: `CLAUDE.md`, `AGENTS.md`, `.cursor/`, and any rules files inside folders
	- Obsidian settings, if present: `.obsidian/app.json` (`attachmentFolderPath`), `.obsidian/templates.json` (templates folder), `.obsidian/daily-notes.json` (journal folder and date format)
	- Git: is it a repo, its `.gitignore`, `core.hooksPath` and any existing hooks
	- note names used more than once (wikilinks need unique names): `find . -name '*.md' -not -path './.git/*' | sed 's|.*/||' | sort | uniq -d`
	- the tracker it uses for tickets, if any (Linear, Jira, GitHub issues), and its key pattern
3. **Propose the folder map and the parts to adopt.** For each kit folder in `kit.json` → `paths` (`brain`, `assets`, `inbox`, `notes`, `journal`, `plans`, `templates`, `scripts`, `hooks`), propose the vault folder it maps to: the vault's existing folder where one plays that role, else the kit's name. For each optional component (ingest, code-facts, metrics, journal, plans, schedule), say what it does and whether the vault seems to want it. Ask, in the question format, about each one where the vault already has its own way.
4. **Record the answers:**
	```
	kit_sync.py init --vault . --map brain=_ai-brain --map assets=_assets --component journal=declined ...
	kit_sync.py decide --vault . --id journal-layout --choice vault --vault-text "Journal/YYYY/MM-MMMM/" --kit-text "journal/YYYY-MM-DD.md" --note "..."
	```
	Give each decision a short, stable `--id`. Add `--path <kit path>` for each kit file a "keep vault" or "skip" decision covers, so a later update notices when the kit changes that file.
5. **Plan:** `kit_sync.py plan --vault .`. Then for each action that needs an answer:
	- `exists-in-vault`: the vault has its own file where the kit's would go (often `CLAUDE.md`, `AGENTS.md`, `.gitignore` or a hook). Show both, ask, and act on the answer:
		- keep the vault's file: `decide --choice vault --path <kit path>`
		- take the kit's file: `resolve <kit path> --take-kit`
		- merge them: edit the vault file by hand, show the result, then `resolve <kit path>`
	- undecided optional components: ask, then `init --component NAME=adopted|declined`, and plan again.
6. **Apply what's safe:** `kit_sync.py apply --vault . --safe` copies every `new` file in an adopted component.
7. **Fit the copies to the vault**, writing each difference into `RULES.local.md`, never into `RULES.md`:
	- `brain.json`: set `brain_dir` to the mapped brain folder, `human_dirs` to the vault's human note folders, and the ticket pattern and statuses the vault uses. This edits the copy, which is expected: config is the vault's to set.
	- `AGENTS.md` and `CLAUDE.md` at the vault root: if the brain folder is mapped, correct their `brain/RULES.md` path, and make sure they name `RULES.local.md`.
	- Git: `git config core.hooksPath <mapped hooks folder>` if the vault has no hook folder yet. If it already has a `pre-commit`, merge the kit's checks into it (step 5, merge). The kit's hook finds the lint in `scripts/`, or in any top level folder holding `lint_brain.py`.
	- Create the vault's brain index from `templates/Index.md`.
8. **Write `RULES.local.md`** beside the vault's `RULES.md`. Start it with:
	```
	# Local rules

	This vault follows the ai-brain-starter kit (kit.lock.json). Where this file and RULES.md differ, this file wins.

	## Folder map
	Paths in RULES.md are kit paths. In this vault:
	| kit | vault |
	|---|---|
	| brain/ | _ai-brain/ |
	```
	Then one section per difference: what this vault does, which kit rule it replaces (`RULES.md → Journal`), and the decision id from the lock. Include the vault's own conventions that the kit has no rule for, so agents find them in one place.
9. **Check:**
	- `kit_sync.py check --vault .` prints nothing.
	- The adopted tests pass: `python3 -m unittest discover -s <mapped scripts folder>`.
	- The lint passes: `python3 <mapped scripts folder>/lint_brain.py --all`.
	- `kit_sync.py plan --vault .` shows no `new`, `exists-in-vault` or `conflict` left in adopted components.
10. **Commit** with explicit paths: the adopted files, `kit.lock.json`, `RULES.local.md` and the edited pointer files. Name the kit commit in the message (`adopt ai-brain-starter <sha>`).

## Updating from the kit

1. **Pull the kit:** `git -C <kit> pull`.
2. **Say what changed in the kit:** `git -C <kit> log --oneline <kit_commit from kit.lock.json>..HEAD`, summarized for the human in a few lines.
3. **Plan:** `kit_sync.py plan --vault .`.
4. **Safe changes:** `new`, `update-clean` and `update-merge` in adopted components. List them, get one yes for the batch, then `kit_sync.py apply --vault . --safe`.
5. **Ask about the rest**, each in the question format:
	- `conflict`: both sides changed the same lines. Show both versions of those lines. Then keep the vault's (`decide --choice vault --path ...`), take the kit's (`resolve --take-kit`), or merge by hand and `resolve`.
	- `recheck`: an earlier decision kept the vault's way, and the kit's side has changed since. Show what changed in the kit (`git -C <kit> diff <kit_basis>..HEAD -- <path>`) and ask again. Record the new answer with `decide` under the same id, which also moves its `kit_basis` forward.
	- `missing-in-vault`: adopted once, gone from the vault now. Ask whether to restore it (`resolve --take-kit`) or record it as declined (`decide --choice skip --path ...`).
	- `removed-in-kit`: the kit dropped a file the vault still has. Ask whether to keep or delete the vault's copy. Either way, remove its entry from `files` in `kit.lock.json` so `check` passes.
	- new optional components: describe them and ask, as in first adoption.
6. **Update `RULES.local.md`** for any new or changed difference, and check that its existing sections still match what the kit's new `RULES.md` says.
7. **Check and commit** as in first adoption, with the range in the message (`ai-brain-starter <old>..<new>`).

`vault-edited`, `kept-vault`, `unchanged` and `declined` need nothing.
