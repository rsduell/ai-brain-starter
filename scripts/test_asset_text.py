"""Tests for asset_text.py's docling routing. Run: python3 -m unittest discover -s scripts

A fake docling Python stands in for the real one, so these run without docling installed.
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import asset_text  # noqa: E402


class AssetTextDoclingTest(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.root = Path(self.tmp.name)
		self.calls = self.root / "docling-calls.txt"

	def tearDown(self):
		self.tmp.cleanup()

	def fake_docling(self, reply):
		"""A stand in for docling's Python: logs that it ran and prints `reply` with the first file's path filled in."""
		script = self.root / "fake-python"
		script.write_text(
			"#!/bin/sh\necho ran >> '%s'\nshift 2\nprintf '%%s' '%s' | sed \"s|PATH|$1|\"\n" % (self.calls, reply)
		)
		script.chmod(0o755)
		return str(script)

	def run_main(self, args, docling):
		with mock.patch.dict(os.environ, {"DOCLING_PYTHON": docling}), contextlib.redirect_stdout(io.StringIO()):
			return asset_text.main(args)

	def test_docling_text_becomes_the_sidecar(self):
		deck = self.root / "deck.pptx"
		deck.write_bytes(b"not really a deck")
		docling = self.fake_docling('[{"path": "PATH", "text": "=== page 1 ===\\n\\n| a | b |"}]')

		self.run_main([str(deck)], docling)

		sidecar = (self.root / "deck.pptx.txt").read_text()
		self.assertTrue(sidecar.startswith("source: deck.pptx · extracted "))
		self.assertIn("(docling)", sidecar.splitlines()[0])
		self.assertIn("=== page 1 ===\n\n| a | b |", sidecar)

	def test_fast_skips_docling(self):
		deck = self.root / "deck.pptx"
		deck.write_bytes(b"not really a deck")
		docling = self.fake_docling('[{"path": "PATH", "text": "from docling"}]')

		self.run_main(["--fast", str(deck)], docling)

		self.assertFalse(self.calls.exists())
		self.assertFalse((self.root / "deck.pptx.txt").exists())

	def test_docling_error_leaves_a_file_with_no_plain_extractor_skipped(self):
		deck = self.root / "deck.pptx"
		deck.write_bytes(b"not really a deck")
		docling = self.fake_docling('[{"path": "PATH", "error": "ConversionError: bad file"}]')

		self.run_main([str(deck)], docling)

		self.assertFalse((self.root / "deck.pptx.txt").exists())

	def test_missing_docling_python_is_not_found(self):
		missing = str(self.root / "no-such-python")

		with mock.patch.dict(os.environ, {"DOCLING_PYTHON": missing}):
			found = asset_text.docling_python()

		self.assertIsNone(found)


if __name__ == "__main__":
	unittest.main()
