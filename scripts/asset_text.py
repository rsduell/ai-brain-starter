#!/usr/bin/env python3
"""Write a greppable `.txt` copy beside each binary asset, so nodes can cite a page or row.

Usage:
	python3 scripts/asset_text.py assets/<cluster>            every asset in a folder (skips _archive/)
	python3 scripts/asset_text.py "assets/<cluster>/file.pdf" ...    specific files

Output is `<file>.<ext>.txt` next to the source, starting with a `source:` header line.
	xlsx                    `## sheet <name>`, then `r<N>\t<cells>` for each non empty row (cite as `3B r14`)
	pdf                     `=== page N ===` before each page (cite as `p.12`): macOS PDFKit via pdf_text.swift,
	                        else poppler's `pdftotext`
	docx, doc, html, rtf    macOS `textutil`, else `pandoc`
Anything else (.numbers, images, .md) is skipped and listed.

Needs openpyxl for xlsx (`python3 -m pip install --user openpyxl`). On macOS nothing else is needed; on
Linux or Windows install poppler (`pdftotext`) and pandoc.
"""
import datetime
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEXTUTIL_EXTS = {".docx", ".doc", ".html", ".htm", ".rtf"}


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
		return run(["swift", str(HERE / "pdf_text.swift"), str(path)])
	if shutil.which("pdftotext"):
		pages = run(["pdftotext", "-layout", str(path), "-"]).split("\f")
		return "\n".join("=== page %d ===\n%s" % (n, page) for n, page in enumerate(pages, 1) if page.strip())
	raise RuntimeError("no PDF extractor: install poppler (pdftotext)")


def textutil_text(path):
	if shutil.which("textutil"):
		return run(["textutil", "-convert", "txt", "-stdout", str(path)])
	if shutil.which("pandoc") and path.suffix.lower() != ".doc":
		return run(["pandoc", "-t", "plain", "--wrap=none", str(path)])
	raise RuntimeError("no extractor for %s: install pandoc (legacy .doc needs macOS textutil or LibreOffice)" % path.name)


def extract(path):
	ext = path.suffix.lower()
	if ext == ".xlsx":
		return xlsx_text(path)
	if ext == ".pdf":
		return pdf_text(path)
	if ext in TEXTUTIL_EXTS:
		return textutil_text(path)
	return None


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
	if not args:
		print(__doc__)
		return 2
	today = datetime.date.today().isoformat()
	skipped = []
	for src in sources(args):
		if src.suffix == ".txt":
			continue
		try:
			text = extract(src)
		except (RuntimeError, subprocess.CalledProcessError) as e:
			print("failed %s: %s" % (src, e))
			continue
		if text is None:
			skipped.append(src.name)
			continue
		dest = src.with_name(src.name + ".txt")
		header = "source: %s · extracted %s by scripts/asset_text.py\n\n" % (src.name, today)
		dest.write_text(header + text.rstrip() + "\n", encoding="utf-8")
		print("wrote %s (%d KB)" % (dest, dest.stat().st_size // 1024))
	if skipped:
		print("skipped (no extractor): " + ", ".join(skipped))
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
