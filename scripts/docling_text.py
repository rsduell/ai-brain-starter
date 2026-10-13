"""Convert documents to Markdown via docling, with `=== page N ===` before each page.

asset_text.py runs this with docling's own Python (the `uv tool install docling` env), so don't run it
with the system python3. Usage: <docling python> -I docling_text.py <file>...
Prints a JSON list with one {"path", "text"} or {"path", "error"} per file, in order. The models load
once for the whole batch.

Paged formats (pdf, pptx, images) get a marker per page, so nodes can cite `p.12`. Formats without
pages (docx, html) come out as one Markdown body, with no markers. Tables come out as Markdown tables,
images as `<!-- image -->` placeholders, and scanned pages are OCR'd.
"""
import json
import sys

from docling.document_converter import DocumentConverter
from docling_core.types.doc import ImageRefMode


def markdown(doc):
	if not doc.pages:
		return doc.export_to_markdown(image_mode=ImageRefMode.PLACEHOLDER)
	out = []
	for n in sorted(doc.pages):
		out.append("=== page %d ===" % n)
		out.append(doc.export_to_markdown(page_no=n, image_mode=ImageRefMode.PLACEHOLDER))
	return "\n\n".join(out)


def main(paths):
	converter = DocumentConverter()
	results = []
	for path in paths:
		try:
			results.append({"path": path, "text": markdown(converter.convert(path).document)})
		except Exception as e:
			results.append({"path": path, "error": "%s: %s" % (type(e).__name__, e)})
	json.dump(results, sys.stdout)


if __name__ == "__main__":
	main(sys.argv[1:])
