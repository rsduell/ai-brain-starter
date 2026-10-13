#!/usr/bin/env python3
"""Write a greppable `.txt` copy beside each binary asset, so nodes can cite a page or row.

Usage:
	python3 scripts/asset_text.py assets/<cluster>            every asset in a folder (skips _archive/)
	python3 scripts/asset_text.py "assets/<cluster>/file.pdf" ...    specific files
	python3 scripts/asset_text.py --fast <folder or files>    plain text only, no docling

Output is `<file>.<ext>.txt` next to the source, starting with a `source:` header line that names the extractor.
	xlsx                       `## sheet <name>`, then `r<N>\t<cells>` for each non empty row (cite as `3B r14`)
	pdf, pptx, images          docling: Markdown with tables, OCR for scans, `=== page N ===` before each page
	                           (cite as `p.12`; for pptx N is the slide)
	docx, html                 docling: Markdown with headings and tables, no page markers
	doc, rtf                   macOS `textutil`, else `pandoc` for rtf (docling can't read them)
Without docling, or with --fast, pdf falls back to plain text per page (macOS PDFKit via pdf_text.swift, else
poppler's `pdftotext`), docx and html to `textutil` or `pandoc`, and pptx and images are skipped. A file docling
fails on falls back the same way. Anything else (.numbers, .md) is skipped and listed.

docling (optional, recommended): `uv tool install docling`, or `pip install docling` into the Python running this
script. Found in that order: DOCLING_PYTHON, this Python if it can import docling, then `uv tool dir`. It runs
in one batch, about 20s to load plus a few seconds a page. Use --fast for a quick plain text pass.
Needs openpyxl for xlsx (`python3 -m pip install --user openpyxl`). Without docling on Linux or Windows,
install poppler (`pdftotext`) and pandoc.
"""
import datetime
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEXTUTIL_EXTS = {".docx", ".doc", ".html", ".htm", ".rtf"}
DOCLING_EXTS = {".pdf", ".docx", ".pptx", ".html", ".htm", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def xlsx_text(path):
	import openpyxl
	wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
	out = []
	for ws in wb.worksheets:
		out.append("## sheet %s" % ws.title)
		for n, row in enumerate(ws.iter_rows(values_only=True), 1):
			cells = ["" if c is None else " ".join(str(c).split()) for c in row]
			while cells and not cells[-1]:
				cells.pop()
			if cells:
				out.append("r%d\t%s" % (n, "\t".join(cells)))
		out.append("")
	wb.close()
	return "\n".join(out)


def run(cmd):
	return subprocess.run(cmd, check=True, capture_output=True).stdout.decode("utf-8")


def pdf_text(path):
	if sys.platform == "darwin" and shutil.which("swift"):
		return run(["swift", str(HERE / "pdf_text.swift"), str(path)]), "PDFKit"
	if shutil.which("pdftotext"):
		pages = run(["pdftotext", "-layout", str(path), "-"]).split("\f")
		text = "\n".join("=== page %d ===\n%s" % (n, page) for n, page in enumerate(pages, 1) if page.strip())
		return text, "pdftotext"
	raise RuntimeError("no PDF extractor: install docling, or poppler (pdftotext)")


def textutil_text(path):
	if shutil.which("textutil"):
		return run(["textutil", "-convert", "txt", "-stdout", str(path)]), "textutil"
	if shutil.which("pandoc") and path.suffix.lower() != ".doc":
		return run(["pandoc", "-t", "plain", "--wrap=none", str(path)]), "pandoc"
	raise RuntimeError("no extractor for %s: install pandoc (legacy .doc needs macOS textutil or LibreOffice)" % path.name)


def extract(path):
	"""Plain extractors: returns (text, extractor name) or (None, None) when there is none for this type."""
	ext = path.suffix.lower()
	if ext == ".xlsx":
		return xlsx_text(path), "openpyxl"
	if ext == ".pdf":
		return pdf_text(path)
	if ext in TEXTUTIL_EXTS:
		return textutil_text(path)
	return None, None


def docling_python():
	env = os.environ.get("DOCLING_PYTHON")
	if env:
		return env if Path(env).exists() else None
	if importlib.util.find_spec("docling") is not None:
		return sys.executable
	if shutil.which("uv"):
		try:
			tool_dir = Path(run(["uv", "tool", "dir"]).strip()) / "docling"
		except subprocess.CalledProcessError:
			return None
		for c in (tool_dir / "bin" / "python", tool_dir / "Scripts" / "python.exe"):
			if c.exists():
				return str(c)
	return None


def docling_texts(python, paths):
	"""Returns {path: markdown} for the files docling converted. Failures are printed and left out."""
	if not paths:
		return {}
	print("docling: converting %d file(s), models load first..." % len(paths), flush=True)
	proc = subprocess.run(
		[python, "-I", str(HERE / "docling_text.py")] + [str(p) for p in paths], capture_output=True,
	)
	if proc.returncode != 0:
		lines = proc.stderr.decode("utf-8", "replace").strip().splitlines()
		print("docling failed, falling back: " + (lines[-1] if lines else "exit %d" % proc.returncode))
		return {}
	out = {}
	for r in json.loads(proc.stdout.decode("utf-8")):
		if "error" in r:
			print("docling failed on %s (%s), falling back" % (r["path"], r["error"]))
		else:
			out[r["path"]] = r["text"]
	return out


def sources(args):
	for arg in args:
		p = Path(arg)
		if p.is_dir():
			for f in sorted(p.rglob("*")):
				if f.is_file() and "_archive" not in f.parts and not f.name.startswith("."):
					yield f
		else:
			yield p


def main(args):
	fast = "--fast" in args
	args = [a for a in args if a != "--fast"]
	if not args:
		print(__doc__)
		return 2
	srcs = [s for s in sources(args) if s.suffix != ".txt"]
	python = None if fast else docling_python()
	if not fast and python is None:
		print("docling not found, using plain extractors (install: uv tool install docling)")
	via_docling = docling_texts(python, [s for s in srcs if s.suffix.lower() in DOCLING_EXTS]) if python else {}
	today = datetime.date.today().isoformat()
	skipped = []
	for src in srcs:
		if str(src) in via_docling:
			text, by = via_docling[str(src)], "docling"
		else:
			try:
				text, by = extract(src)
			except (RuntimeError, subprocess.CalledProcessError) as e:
				print("failed %s: %s" % (src, e))
				continue
		if text is None:
			skipped.append(src.name)
			continue
		dest = src.with_name(src.name + ".txt")
		header = "source: %s · extracted %s by scripts/asset_text.py (%s)\n\n" % (src.name, today, by)
		dest.write_text(header + text.rstrip() + "\n", encoding="utf-8")
		print("wrote %s (%d KB, %s)" % (dest, dest.stat().st_size // 1024, by))
	if skipped:
		print("skipped (no extractor): " + ", ".join(skipped))
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
