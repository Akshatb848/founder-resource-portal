"""Read the first worksheet of an .xlsx file as rows of text, using only the standard library and defusedxml.

Enough for importing a company spreadsheet: shared strings, inline strings, numbers and booleans. Formulas give
their last saved value. Dates come through as Excel serial numbers; profile_api.parse_date turns them into dates.
"""
from __future__ import annotations

import io
import posixpath
import re
import zipfile

from defusedxml import ElementTree as ET
from fastapi import HTTPException

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
MAX_UNPACKED = 20_000_000  # refuse files that expand to more than 20 MB


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def _number(text: str) -> str:
    try:
        f = float(text)
    except ValueError:
        return text
    return str(int(f)) if f.is_integer() else repr(f)


def read_xlsx_rows(data: bytes, max_rows: int = 5000) -> list[list[str]]:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=422, detail="This is not a valid .xlsx file. Save it as Excel Workbook or CSV.") from None
    if sum(i.file_size for i in z.infolist()) > MAX_UNPACKED:
        raise HTTPException(status_code=413, detail="The spreadsheet is too large")
    try:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        first = wb.find("m:sheets/m:sheet", NS)
        rid = first.get(f"{{{NS['r']}}}id")
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = next(r.get("Target") for r in rels.findall("rel:Relationship", NS) if r.get("Id") == rid)
        path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        sheet = ET.fromstring(z.read(path))
    except (KeyError, StopIteration, AttributeError, ET.ParseError):
        raise HTTPException(status_code=422, detail="Could not read this .xlsx file. Save it as CSV and try again.") from None
    rows: list[list[str]] = []
    for row in sheet.iterfind("m:sheetData/m:row", NS):
        cells: dict[int, str] = {}
        for c in row.findall("m:c", NS):
            ref, kind = c.get("r"), c.get("t")
            v = c.find("m:v", NS)
            if kind == "inlineStr":
                val = "".join(t.text or "" for t in c.iter(f"{{{NS['m']}}}t"))
            elif v is None or v.text is None:
                continue
            elif kind == "s":
                val = shared[int(v.text)]
            elif kind == "b":
                val = "TRUE" if v.text == "1" else "FALSE"
            elif kind in ("str", "e"):
                val = v.text
            else:
                val = _number(v.text)
            cells[_col_index(ref) if ref else len(cells)] = val
        if cells:
            width = max(cells) + 1
            rows.append([cells.get(i, "") for i in range(width)])
        if len(rows) > max_rows:
            raise HTTPException(status_code=413, detail=f"The spreadsheet has more than {max_rows} rows")
    if rows:
        # Every row as wide as the widest one: a short title row above the column names (the portfolio tracker's
        # "Professional Services ... Custodian" row) must not cut off the columns after it.
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
    return rows
