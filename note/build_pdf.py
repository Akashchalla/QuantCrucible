"""Build note/quant_note.pdf from note/quant_note.md.

    python note/build_pdf.py

Markdown -> HTML (python-markdown) -> PDF (headless Chrome/Chromium). 11 pt body,
1-inch margins, US Letter. Prints the page count of the main body (everything
before the References heading) so the 5-page limit is checked mechanically.
Fallback if no Chrome is found: the HTML is written next to the PDF and can be
printed from any browser, or use `pandoc quant_note.md -o quant_note.pdf`.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
MD = HERE / "quant_note.md"
HTML = HERE / "quant_note.html"
PDF = HERE / "quant_note.pdf"

CSS = """
@page { size: Letter; margin: 1in; }
html { font-size: 11pt; }
body { font-family: Georgia, 'Times New Roman', serif; font-size: 11pt; line-height: 1.2; color: #111; margin: 0; }
h1 { font-size: 20pt; margin: 0 0 2pt 0; letter-spacing: -0.01em; }
h2 { font-size: 12.5pt; margin: 7pt 0 3pt 0; border-bottom: 0.6pt solid #999; padding-bottom: 1pt; }
h3 { font-size: 11pt; margin: 6pt 0 2pt 0; font-style: italic; }
.title h2 { font-size: 12pt; border: none; font-weight: normal; color: #333; margin: 0 0 5pt 0; }
.meta { font-size: 9pt; color: #444; margin: 0 0 6pt 0; }
p { margin: 0 0 4pt 0; text-align: justify; }
table { border-collapse: collapse; width: 100%; font-size: 8.2pt; margin: 3pt 0 5pt 0; font-family: Helvetica, Arial, sans-serif; }
tr { page-break-inside: avoid; }
th, td { border-bottom: 0.4pt solid #bbb; padding: 1.6pt 3pt; text-align: right; vertical-align: top; }
th:first-child, td:first-child { text-align: left; }
th { border-bottom: 0.8pt solid #333; font-weight: 600; text-align: right; }
th:first-child { text-align: left; }
img.full { width: 90%; display: block; margin: 3pt auto 1pt auto; }
.row { display: flex; gap: 8pt; justify-content: center; }
img.half { width: 48%; display: block; margin: 4pt 0 2pt 0; }
.cap { font-size: 8.2pt; color: #333; margin: 0 0 6pt 0; text-align: left; }
code { font-family: Menlo, Consolas, monospace; font-size: 9pt; }
sub, sup { font-size: 75%; line-height: 0; }
.refs { page-break-before: always; font-size: 9.5pt; }
.refs p { text-align: left; }
"""


def build_html() -> str:
    body = markdown.markdown(MD.read_text(encoding="utf-8"), extensions=["tables", "md_in_html", "attr_list"])
    return f"<!doctype html><html><head><meta charset='utf-8'><title>Quant note</title><style>{CSS}</style></head><body>{body}</body></html>"


def find_chrome() -> str | None:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        if shutil.which(name):
            return shutil.which(name)
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    return mac if Path(mac).exists() else None


def page_count(pdf: Path) -> int | None:
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(pdf)).pages)
    except Exception:
        data = pdf.read_bytes()
        n = len(re.findall(rb"/Type\s*/Page[^s]", data))
        return n or None


def body_pages(pdf: Path) -> int | None:
    """Pages before the one that contains the References heading."""
    try:
        from pypdf import PdfReader
        for i, page in enumerate(PdfReader(str(pdf)).pages):
            if "References (outside the page limit)" in (page.extract_text() or ""):
                return i  # pages 0..i-1 are the body; the refs start a fresh page
    except Exception:
        return None
    return None


def main() -> int:
    HTML.write_text(build_html(), encoding="utf-8")
    chrome = find_chrome()
    if not chrome:
        print(f"No Chrome/Chromium found. Wrote {HTML}; print it to PDF from a browser, or run pandoc.")
        return 1
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
           f"--print-to-pdf={PDF}", HTML.as_uri()]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        if not PDF.exists():
            raise
        # some headless builds finish writing the PDF but never exit; the file is complete
    total, body = page_count(PDF), body_pages(PDF)
    print(f"wrote {PDF}  ({total} pages total; main body {body if body is not None else '?'} pages, references + appendix after)")
    if body is not None and body > 5:
        print("WARNING: main body exceeds 5 pages")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
