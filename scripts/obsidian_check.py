#!/usr/bin/env python3
"""Check that a vault is ready for agents to work through the Obsidian CLI. Rules: brain/RULES.md → Obsidian CLI.

Usage:
	python3 scripts/obsidian_check.py [--vault DIR]

Runs from the vault (DIR defaults to the current folder) or from the kit's clone with --vault. Checks, in order:
	cli         `obsidian` is on the PATH (else prints how to turn it on for this platform)
	version     the Obsidian installer is 1.12.7 or later
	vault       DIR is open in Obsidian as a vault, and its name (sessions in other repos pass vault=<name>)
	links       "Automatically update internal links" is on, so `obsidian move` keeps links working
Every problem comes with its fix. When all pass, it prints the line for your global agent instructions.
Exit 0 when ready, 1 otherwise. Standard library only.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

MIN_INSTALLER = (1, 12, 7)


VERSION_RE = re.compile(r"^\s*(\d+)\.(\d+)\.(\d+)(?:\s*\(installer\s+(\d+)\.(\d+)\.(\d+)\))?")


def parse_installer(text):
	"""The installer version from `obsidian version` as a tuple of ints, or None."""
	m = VERSION_RE.match(text)
	if not m:
		return None
	groups = m.groups()
	return tuple(int(g) for g in (groups[3:] if groups[3] else groups[:3]))


def vault_name(vaults_output, folder):
	"""The name `obsidian vaults verbose` gives the vault at folder, or None."""
	want = os.path.realpath(folder)
	for line in vaults_output.splitlines():
		name, _, path = line.partition("\t")
		if path and os.path.realpath(path.strip()) == want:
			return name
	return None


def setup_steps(platform):
	"""How to turn the CLI on, for sys.platform values darwin, win32 and linux."""
	steps = [
		"The Obsidian CLI isn't on your PATH. To turn it on:",
		"1. Use the Obsidian installer 1.12.7 or later (https://obsidian.md/download).",
		"2. In Obsidian: Settings → General → Command line interface, then follow the prompt to register it.",
	]
	if platform == "darwin":
		steps.append("3. macOS asks for an administrator password to create /usr/local/bin/obsidian. If it's still missing: "
			"sudo ln -sf /Applications/Obsidian.app/Contents/MacOS/obsidian-cli /usr/local/bin/obsidian")
	elif platform == "win32":
		steps.append("3. Registration adds Obsidian to your PATH: restart the terminal before running this again.")
	else:
		steps.append('3. Registration copies it to ~/.local/bin/obsidian: put ~/.local/bin on your PATH '
			'(export PATH="$PATH:$HOME/.local/bin" in ~/.bashrc or ~/.zshrc) and open a new terminal.')
	steps.append("Updated from an older Obsidian and it still isn't found? Turn the setting off and on again, then restart the terminal.")
	return steps


def global_line(name, folder):
	"""The line to add to the global agent instructions."""
	return ('Write notes in %s through the Obsidian CLI (obsidian vault="%s" ...): frontmatter with property:set, '
		"new notes with create path=, moves with move, body text with your edit tool. Never sed, awk or a shell "
		"redirect on a note (RULES.md → Obsidian CLI)." % (folder, name))


def links_on(folder):
	try:
		return json.loads(Path(folder, ".obsidian", "app.json").read_text(encoding="utf-8")).get("alwaysUpdateLinks") is True
	except (OSError, ValueError):
		return False


def check(folder, which=shutil.which, run=None, platform=sys.platform):
	"""(ok, messages). run(args) returns the CLI's stdout."""
	run = run or run_cli
	if not which("obsidian"):
		return False, setup_steps(platform)
	try:
		installer = parse_installer(run(["version"]))
		vaults = run(["vaults", "verbose"])
	except subprocess.TimeoutExpired:
		return False, ["Obsidian didn't answer within a minute: start Obsidian, wait until it has opened, and run this again."]
	if installer is None or installer < MIN_INSTALLER:
		shown = ".".join(map(str, installer)) if installer else "unknown"
		return False, ["Obsidian installer %s is older than 1.12.7: download the current installer from "
			"https://obsidian.md/download and install it over the old one (the app's own updates don't update "
			"the installer)." % shown]
	name = vault_name(vaults, folder)
	if name is None:
		return False, ["Obsidian doesn't know %s as a vault: in Obsidian, open the vault switcher → Open folder as vault "
			"→ choose this folder, then run this again." % os.path.realpath(folder)]
	if not links_on(folder):
		return False, ['Turn on Settings → Files and links → Automatically update internal links in the "%s" vault, '
			"so `obsidian move` keeps links working, then run this again." % name]
	return True, [
		'Obsidian CLI ready: vault "%s" at %s (installer %s).' % (name, os.path.realpath(folder), ".".join(map(str, installer))),
		"Add this line to your global agent instructions (README → Using it while you work in other repos):",
		global_line(name, os.path.realpath(folder)),
	]


def run_cli(args):
	return subprocess.run(["obsidian"] + args, capture_output=True, text=True, timeout=60).stdout


def main(argv):
	parser = argparse.ArgumentParser(description="Check that a vault is ready for agents to work through the Obsidian CLI.")
	parser.add_argument("--vault", default=".", help="the vault folder (default: the current folder)")
	args = parser.parse_args(argv)
	ok, messages = check(str(Path(args.vault).expanduser()))
	print("\n".join(messages))
	return 0 if ok else 1


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
