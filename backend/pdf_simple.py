"""A small PDF writer for text documents (the company profile download), using only the standard library.

A4 pages, Helvetica and Helvetica-Bold (built into every PDF reader, so nothing is embedded), headings,
label/value rows with wrapped text, and a footer on every page (footer_left plus "Page n of N").
Text is encoded as Windows-1252 (the PDF's WinAnsiEncoding); characters outside it become "?", and the
rupee sign is written as "Rs ".
"""
from __future__ import annotations

import zlib

# Helvetica glyph widths (1/1000 em) for characters 32-126, from the standard AFM metrics.
_W = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556,
      556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833,
      722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556,
      556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334,
      260, 334, 584]

PAGE_W, PAGE_H = 595.28, 841.89
MARGIN = 50
LABEL_W = 165
INK, GREY, ACCENT = (0.13, 0.13, 0.13), (0.42, 0.42, 0.42), (0.05, 0.33, 0.45)


def _clean(text: str) -> str:
    text = str(text).replace("₹", "Rs ").replace("–", "-").replace("—", "-").replace(" ", " ")
    return text.encode("cp1252", errors="replace").decode("cp1252")


def text_width(text: str, size: float, bold: bool = False) -> float:
    w = sum(_W[ord(ch) - 32] if 32 <= ord(ch) <= 126 else 556 for ch in text)
    return w * size / 1000 * (1.07 if bold else 1.0)


def wrap(text: str, size: float, width: float, bold: bool = False) -> list[str]:
    lines: list[str] = []
    for para in _clean(text).split("\n"):
        line = ""
        for word in para.split(" "):
            trial = f"{line} {word}" if line else word
            if text_width(trial, size, bold) <= width:
                line = trial
                continue
            if line:
                lines.append(line)
            while text_width(word, size, bold) > width:  # a single word longer than the line
                cut = len(word)
                while cut > 1 and text_width(word[:cut], size, bold) > width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            line = word
        lines.append(line)
    return lines


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class SimplePDF:
    def __init__(self, footer_left: str = "") -> None:
        self.footer_left = _clean(footer_left)
        self.pages: list[list[str]] = []
        self.y = 0.0
        self._new_page()

    # ---- layout
    def _new_page(self) -> None:
        self.pages.append([])
        self.y = PAGE_H - MARGIN

    def _need(self, h: float) -> None:
        if self.y - h < MARGIN + 30:  # keep clear of the footer
            self._new_page()

    def _text(self, x: float, y: float, s: str, size: float, bold: bool = False, color=INK) -> None:
        r, g, b = color
        self.pages[-1].append(f"BT {r} {g} {b} rg /{'F2' if bold else 'F1'} {size} Tf {x:.2f} {y:.2f} Td ({_esc(s)}) Tj ET")

    def _rule(self, y: float) -> None:
        self.pages[-1].append(f"0.8 0.8 0.8 RG 0.6 w {MARGIN} {y:.2f} m {PAGE_W - MARGIN:.2f} {y:.2f} l S")

    def title(self, s: str) -> None:
        for line in wrap(s, 20, PAGE_W - 2 * MARGIN, bold=True):
            self._need(26)
            self.y -= 22
            self._text(MARGIN, self.y, line, 20, bold=True)
        self.y -= 4

    def subtitle(self, s: str) -> None:
        for line in wrap(s, 11, PAGE_W - 2 * MARGIN):
            self._need(15)
            self.y -= 14
            self._text(MARGIN, self.y, line, 11, color=GREY)

    def note(self, s: str) -> None:
        if not s:
            return
        for line in wrap(s, 9, PAGE_W - 2 * MARGIN):
            self._need(13)
            self.y -= 12
            self._text(MARGIN, self.y, line, 9, color=GREY)

    def heading(self, s: str) -> None:
        self._need(40)
        self.y -= 22
        self._text(MARGIN, self.y, _clean(s), 12.5, bold=True, color=ACCENT)
        self.y -= 5
        self._rule(self.y)
        self.y -= 2

    def row(self, label: str, value: str) -> None:
        size = 10
        labels = wrap(label, size, LABEL_W - 10, bold=True) if label else [""]
        values = wrap(value or "-", size, PAGE_W - 2 * MARGIN - LABEL_W)
        for i in range(max(len(labels), len(values))):
            self._need(15)
            self.y -= 14
            if i < len(labels) and labels[i]:
                self._text(MARGIN, self.y, labels[i], size, bold=True)
            if i < len(values):
                self._text(MARGIN + LABEL_W, self.y, values[i], size)
        self.y -= 3

    # ---- output
    def output(self) -> bytes:
        total = len(self.pages)
        for n, ops in enumerate(self.pages, start=1):
            right = f"Page {n} of {total}"
            left = self.footer_left
            max_left = PAGE_W - 2 * MARGIN - text_width(right, 8) - 20
            while left and text_width(left, 8) > max_left:
                left = left[:-2]
            ops.append(f"0.8 0.8 0.8 RG 0.6 w {MARGIN} {MARGIN:.2f} m {PAGE_W - MARGIN:.2f} {MARGIN:.2f} l S")
            r, g, b = GREY
            ops.append(f"BT {r} {g} {b} rg /F1 8 Tf {MARGIN} {MARGIN - 13} Td ({_esc(left)}) Tj ET")
            ops.append(f"BT {r} {g} {b} rg /F1 8 Tf {PAGE_W - MARGIN - text_width(right, 8):.2f} {MARGIN - 13} Td ({_esc(right)}) Tj ET")

        objs: list[bytes] = []
        objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        kids = " ".join(f"{5 + 2 * i} 0 R" for i in range(total))
        objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {total} >>".encode())
        objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        for i, ops in enumerate(self.pages):
            content = zlib.compress("\n".join(ops).encode("cp1252", errors="replace"))
            objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                        f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {6 + 2 * i} 0 R >>".encode())
            objs.append(f"<< /Length {len(content)} /Filter /FlateDecode >>\nstream\n".encode() + content + b"\nendstream")

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for n, body in enumerate(objs, start=1):
            offsets.append(len(out))
            out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
        out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
        out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        return bytes(out)
