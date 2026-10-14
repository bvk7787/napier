"""A small HTML to markdown converter for manuals published as web pages.

Keeps headings, paragraphs, list items and table rows; drops scripts, styles, navigation,
headers, footers and SVG. Deterministic and stdlib only, so it runs without Docling."""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

SKIP = {"title", "script", "style", "nav", "header", "footer", "svg", "noscript", "template", "button", "form"}
BLOCK = {"p", "div", "section", "article", "main", "ul", "ol", "table", "blockquote", "figure",
         "figcaption", "dl", "dt", "dd", "pre", "aside"}


class _MD(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.buf: list[str] = []
        self.skip = 0
        self.prefix = ""
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.rows_in_table = 0
        self.pre = 0
        self.heading = False

    def flush(self):
        text = "".join(self.buf)
        text = text if self.pre else re.sub(r"\s+", " ", text).strip()
        self.buf = []
        if text:
            self.out.append(self.prefix + text)
        self.prefix = ""
        self.heading = False

    def handle_starttag(self, tag, attrs):
        if self.skip or tag in SKIP:
            if tag in SKIP:
                self.skip += 1
            return
        if re.fullmatch(r"h[1-6]", tag):
            self.flush()
            self.prefix = "#" * int(tag[1]) + " "
            self.heading = True
        elif tag == "li":
            self.flush()
            self.prefix = "- "
        elif tag == "br":
            self.buf.append("\n" if self.pre else " ")
        elif tag == "pre":
            self.flush()
            self.pre += 1
        elif tag == "table":
            self.flush()
            self.rows_in_table = 0
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag in BLOCK:
            self.flush()

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip().replace("|", "/"))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if any(self.row):
                self.out.append("| " + " | ".join(self.row) + " |")
                if self.rows_in_table == 0:
                    self.out.append("|" + " --- |" * len(self.row))
                self.rows_in_table += 1
            self.row = None
        elif tag == "pre":
            self.flush()
            self.pre = max(0, self.pre - 1)
        elif re.fullmatch(r"h[1-6]", tag) or tag == "li" or tag in BLOCK:
            self.flush()

    def handle_data(self, data):
        if self.skip:
            return
        if self.cell is not None:
            self.cell.append(data)
            return
        if self.heading and self.buf and data.strip() and not self.buf[-1][-1:].isspace():
            self.buf.append(" ")  # heading numbers and titles often sit in separate spans
        self.buf.append(data)


def html_to_md(text: str) -> str:
    p = _MD()
    p.feed(text)
    p.close()
    p.flush()
    lines, prev = [], None
    for ln in p.out:
        if ln.startswith("#") and lines and lines[-1] != "":
            lines.append("")
        if ln != prev:
            lines.append(ln)
        prev = ln
        if ln.startswith("#"):
            lines.append("")
    return html.unescape("\n".join(lines)).strip() + "\n"
