"""Load brain.json from the repo root, falling back to these defaults for any key it leaves out."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
	# Folder (relative to the repo root) that holds the agent notes.
	"brain_dir": "brain",
	# Issue logs are named "<prefix><TICKET>.md", e.g. "AI PROJ-123.md". The prefix keeps them
	# distinct from a human note named "PROJ-123.md" so wikilinks stay unambiguous.
	"issue_log_prefix": "AI ",
	# A ticket key in your tracker (Linear, Jira, GitHub issues as "GH-123", ...).
	"ticket_pattern": "[A-Z][A-Z0-9]+-\\d+",
	"issue_statuses": ["backlog", "in progress", "in review", "in QA", "merged", "done", "advised"],
	"issue_roles": ["author", "reviewer", "advisor"],
	"issue_required_keys": ["issue", "tracker", "repositories", "role", "branches", "prs", "status", "updated"],
	"summary_max_lines": 12,
	"hub_lifecycles": ["active", "submitted", "archived"],
	"fact_scopes": ["personal", "team", "provisional"],
	# Code repos that anchored facts point at: {"name": "path"}. Unlisted names resolve to
	# <projects_dir>/<name>.
	"projects_dir": "~/Projects",
	"repos": {},
}


def load(root=ROOT):
	cfg = dict(DEFAULTS)
	path = Path(root, "brain.json")
	if path.exists():
		cfg.update(json.loads(path.read_text(encoding="utf-8")))
	return cfg


def repo_path(cfg, name):
	path = cfg["repos"].get(name) or str(Path(cfg["projects_dir"]) / name)
	return Path(path).expanduser()
