"""Tests for obsidian_check.py. Run: python3 -m unittest discover -s scripts"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import obsidian_check  # noqa: E402


def fake_cli(version="1.14.4 (installer 1.12.7)", vaults="", timeout=False):
	"""A stand in for run_cli: answers `version` and `vaults verbose`."""
	def run(args):
		if timeout:
			raise subprocess.TimeoutExpired(["obsidian"] + args, 60)
		return {"version": version, "vaults": vaults}[args[0]] + "\n"
	return run


def found(name):
	return "/usr/local/bin/obsidian"


def missing(name):
	return None


class ObsidianCheckTest(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.vault = Path(self.tmp.name).resolve() / "My Brain"
		(self.vault / ".obsidian").mkdir(parents=True)
		self.links(True)
		self.vaults = "Other\t/elsewhere/Other\nMy Brain\t%s\n" % self.vault

	def tearDown(self):
		self.tmp.cleanup()

	def links(self, on):
		(self.vault / ".obsidian" / "app.json").write_text(json.dumps({"alwaysUpdateLinks": on}))

	# parse_installer

	def test_installer_version_comes_from_the_parentheses(self):
		text = "1.14.4 (installer 1.12.7)"

		version = obsidian_check.parse_installer(text)

		self.assertEqual(version, (1, 12, 7))

	def test_a_bare_version_is_the_installer(self):
		text = "1.12.7\n"

		version = obsidian_check.parse_installer(text)

		self.assertEqual(version, (1, 12, 7))

	def test_an_error_has_no_version(self):
		text = 'Error: Command "version" not found.'

		version = obsidian_check.parse_installer(text)

		self.assertIsNone(version)

	# vault_name

	def test_vault_name_matches_the_folder(self):
		folder = str(self.vault)

		name = obsidian_check.vault_name(self.vaults, folder)

		self.assertEqual(name, "My Brain")

	def test_vault_name_matches_a_relative_folder(self):
		os.chdir(self.vault)
		self.addCleanup(os.chdir, os.path.dirname(os.path.abspath(__file__)))

		name = obsidian_check.vault_name(self.vaults, ".")

		self.assertEqual(name, "My Brain")

	def test_a_folder_obsidian_does_not_know_has_no_name(self):
		folder = "/somewhere/else"

		name = obsidian_check.vault_name(self.vaults, folder)

		self.assertIsNone(name)

	# setup_steps

	def test_macos_steps_name_the_setting_and_the_symlink_fallback(self):
		platform = "darwin"

		steps = "\n".join(obsidian_check.setup_steps(platform))

		self.assertIn("Settings → General → Command line interface", steps)
		self.assertIn("sudo ln -sf /Applications/Obsidian.app/Contents/MacOS/obsidian-cli /usr/local/bin/obsidian", steps)

	def test_linux_steps_put_local_bin_on_the_path(self):
		platform = "linux"

		steps = "\n".join(obsidian_check.setup_steps(platform))

		self.assertIn("~/.local/bin", steps)

	def test_windows_steps_restart_the_terminal(self):
		platform = "win32"

		steps = "\n".join(obsidian_check.setup_steps(platform))

		self.assertIn("restart the terminal", steps)

	# check

	def test_ready_vault_passes_and_prints_the_global_line(self):
		run = fake_cli(vaults=self.vaults)

		ok, messages = obsidian_check.check(str(self.vault), which=found, run=run, platform="darwin")

		self.assertTrue(ok)
		self.assertIn(obsidian_check.global_line("My Brain", str(self.vault)), messages)

	def test_missing_cli_fails_with_the_setup_steps(self):
		run = fake_cli(vaults=self.vaults)

		ok, messages = obsidian_check.check(str(self.vault), which=missing, run=run, platform="darwin")

		self.assertFalse(ok)
		self.assertTrue(set(obsidian_check.setup_steps("darwin")) <= set(messages))

	def test_old_installer_fails_and_names_the_minimum(self):
		run = fake_cli(version="1.11.4 (installer 1.11.4)", vaults=self.vaults)

		ok, messages = obsidian_check.check(str(self.vault), which=found, run=run, platform="darwin")

		self.assertFalse(ok)
		self.assertTrue(any("1.12.7" in m for m in messages))

	def test_folder_not_open_as_a_vault_fails_and_says_how_to_open_it(self):
		run = fake_cli(vaults="Other\t/elsewhere/Other\n")

		ok, messages = obsidian_check.check(str(self.vault), which=found, run=run, platform="darwin")

		self.assertFalse(ok)
		self.assertTrue(any("Open folder as vault" in m for m in messages))

	def test_link_updating_off_fails_and_names_the_setting(self):
		self.links(False)
		run = fake_cli(vaults=self.vaults)

		ok, messages = obsidian_check.check(str(self.vault), which=found, run=run, platform="darwin")

		self.assertFalse(ok)
		self.assertTrue(any("Automatically update internal links" in m for m in messages))

	def test_app_that_does_not_answer_fails_and_says_to_start_it(self):
		run = fake_cli(timeout=True)

		ok, messages = obsidian_check.check(str(self.vault), which=found, run=run, platform="darwin")

		self.assertFalse(ok)
		self.assertTrue(any("start Obsidian" in m for m in messages))

	# global_line

	def test_global_line_names_the_vault_and_its_folder(self):
		name, folder = "My Brain", "/home/me/My Brain"

		line = obsidian_check.global_line(name, folder)

		self.assertIn('vault="My Brain"', line)
		self.assertIn("/home/me/My Brain", line)


if __name__ == "__main__":
	unittest.main()
