"""Database-free tests for the company profile helpers (alpha v1.2.6): firm de-duplication, amounts, dates,
expiry badges, the PDF writer and the .xlsx reader."""
import io
import re
import zipfile
import zlib
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.pdf_simple import SimplePDF, wrap
from backend.profile_api import (STANDARD_ITEMS, completeness, expiry_state, firm_key, flatten, format_inr, parse_date,
                                 parse_inr, parse_rate, profile_pdf, yna)
from backend.xlsx_read import read_xlsx_rows

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("a,b", [
    ("Example Assurance & Sells LLP", "example assurance and sells"),
    ("HDFC Bank Ltd.", "HDFC BANK"),
    ("Example Technologies Private Limited", "Example Technologies Pvt. Ltd"),
    ("Sample Audit & Co LLP", "Sample Audit"),
])
def test_differently_written_firm_names_are_the_same_firm(a, b):
    assert firm_key(a) == firm_key(b)


def test_bank_of_india_keeps_its_name():
    assert firm_key("Bank of India") == "bank of india"
    assert firm_key("State Bank of India") != firm_key("Bank of India")


def test_the_browser_uses_the_same_firm_rule_as_the_server():
    js = (ROOT / "company-profile.js").read_text(encoding="utf-8")
    from backend import profile_api

    listed = re.search(r"const SUFFIXES = \[(.*?)\];", js).group(1)
    assert [s.strip().strip('"') for s in listed.split(",")] == list(profile_api.SUFFIXES)


@pytest.mark.parametrize("text,rupees", [
    ("5 crore", 50_000_000), ("5 crores", 50_000_000), ("75 cr", 750_000_000), ("50 lakh", 5_000_000), ("50L", 5_000_000),
    ("5,00,00,000", 50_000_000), ("Rs 2.5 Cr", 25_000_000), ("₹1.2 lakh", 120_000), ("25000", 25_000), ("10k", 10_000),
])
def test_rupee_amounts_as_people_write_them(text, rupees):
    assert parse_inr(text) == Decimal(rupees)


def test_amounts_are_shown_in_crore_and_lakh():
    assert format_inr(Decimal(50_000_000)) == "₹5 crore"
    assert format_inr(Decimal(2_500_000)) == "₹25 lakh"
    assert format_inr(Decimal(120_000)) == "₹1.2 lakh"
    assert format_inr(Decimal(99_000), rupee="Rs ") == "Rs 99000"


def test_bad_amounts_rates_and_answers_are_refused():
    for bad in ("lots", "5 million crore x"):
        with pytest.raises(HTTPException):
            parse_inr(bad)
    with pytest.raises(HTTPException):
        parse_rate("150")
    with pytest.raises(HTTPException):
        yna("maybe", "AOP")
    assert parse_rate("11.5%") == Decimal("11.5") and yna("N/A", "x") == "na" and yna("Y", "x") == "yes"


def test_dates_in_indian_iso_and_excel_form():
    assert parse_date("2026-10-29", "d") == date(2026, 10, 29)
    assert parse_date("29/10/2026", "d") == date(2026, 10, 29)
    assert parse_date("29 Oct 2026", "d") == date(2026, 10, 29)
    assert parse_date("46324", "d") == date(2026, 10, 29)  # Excel serial number
    with pytest.raises(HTTPException):
        parse_date("31/31/2026", "d")


def test_expiry_badges():
    today = date(2026, 10, 29)
    assert expiry_state(today - timedelta(days=1), today) == "red"
    assert expiry_state(today + timedelta(days=30), today) == "amber"
    assert expiry_state(today + timedelta(days=200), today) is None
    assert expiry_state(None, today) is None


def _profile(**over):
    prof = {
        "company": {"id": 1, "brand_name": "Meepo", "legal_name": "Pebble Robotics Private Limited (test)", "slug": "meepo",
                    "sector": "SaaS", "stage": "Series B", "city": "Bengaluru", "fund": "Fund II", "website": None},
        "governance": {"auditor": "Example & Co LLP", "auditor_appointed_on": "2015-06-30", "company_secretary": None,
                       "legal_counsel": None, "bankers": ["Example Bank"], "board": [{"full_name": "Leela Das", "role_note": "Chair"}],
                       "advisory": [], "independent": [], "secretary_engaged_on": None, "board_nominee": None,
                       "infosec_policy": "yes", "cos_name": None, "cos_joined_on": None},
        "services": {"accounts_signed_on": None, "investment_bank": None, "tax_advisor": "Example Tax LLP", "cloud_provider": "AWS"},
        "patents": {"filed": 0, "granted": 0},
        "compliance": [{"item": i, "standard": True, "status": None, "certificate_no": None, "issued_on": None,
                        "expires_on": None, "note": None, "alert": None} for i in STANDARD_ITEMS],
        "agreements": {"sha_custody": None, "aop_status": "yes", "aop_note": None, "share_cert_custody": None, "demat_status": None},
        "dpdp": {"consent": None, "consent_duration": None, "renewal": None, "sha_annexure": None},
        "credit": {"credit_line": [{"lender": "Granite Venture Debt (test)", "instrument": "Venture debt", "amount_inr": 750_000_000.0,
                                    "amount_label": "₹75 crore", "interest_rate": 14.0, "note": None}], "credit_card": []},
        "confirmed_at": None, "confirmed_by": None, "confirm_due": True, "alerts": [],
    }
    prof.update(over)
    prof["completeness"] = completeness(prof)
    return prof


def test_completeness_lists_what_is_missing():
    comp = _profile()["completeness"]
    assert "Company secretary" in comp["missing"] and "Statutory auditor" not in comp["missing"]
    assert comp["total"] == 18 + len(STANDARD_ITEMS) and 0 < comp["pct"] < 100
    # 0 patents is an answer, not a gap; the tracker's other fields are listed while empty
    assert "Patents filed" not in comp["missing"] and "Demat status" in comp["missing"] and "Cloud service provider" not in comp["missing"]


def test_change_history_text_includes_credit_lines():
    flat = flatten(_profile())
    assert flat["Credit lines"] == "Granite Venture Debt (test), Venture debt, ₹75 crore, 14%"
    assert flat["Board members"] == "Leela Das (Chair)"


def _pdf_text(data: bytes) -> str:
    streams = re.findall(rb"stream\n(.*?)\nendstream", data, re.S)
    return "\n".join(zlib.decompress(s).decode("cp1252") for s in streams)


def test_profile_pdf_is_valid_and_has_the_legal_name_in_every_footer():
    data = profile_pdf(_profile(), "Test Analyst")
    assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")
    xref = int(re.search(rb"startxref\n(\d+)", data).group(1))
    assert data[xref:xref + 4] == b"xref"
    text = _pdf_text(data)
    assert "(Meepo) Tj" in text and "Rs 75 crore" in text
    pages = int(re.search(rb"/Count (\d+)", data).group(1))
    assert text.count("Pebble Robotics Private Limited \\(test\\)") >= pages + 1  # subtitle + one footer per page
    assert f"Page {pages} of {pages}" in text


def test_long_pdfs_break_onto_new_pages():
    pdf = SimplePDF(footer_left="Legal Name Pvt Ltd")
    pdf.title("Long")
    for i in range(120):
        pdf.row(f"Row {i}", "value " * 30)
    data = pdf.output()
    assert int(re.search(rb"/Count (\d+)", data).group(1)) > 3
    assert all(len(line) > 0 for line in wrap("x" * 400, 10, 100))


def _xlsx(rows):
    """A minimal .xlsx: shared strings for text, numbers inline."""
    strings, sheet_rows = [], []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, val in enumerate(row):
            ref = f"{chr(65 + c)}{r}"
            if isinstance(val, (int, float)):
                cells.append(f'<c r="{ref}"><v>{val}</v></c>')
            elif val is not None:
                strings.append(val)
                cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
        sheet_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                                      '<sheets><sheet name="Companies" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                                 '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", f'<sst {ns}>' + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>')
    return buf.getvalue()


def test_xlsx_reader_gives_text_rows_with_gaps_filled():
    data = _xlsx([["company", "legal_name", "auditor_appointed_on"], ["meepo", None, 42185], ["acme", "Acme Pvt Ltd", 45000.5]])
    rows = read_xlsx_rows(data)
    assert rows == [["company", "legal_name", "auditor_appointed_on"], ["meepo", "", "42185"], ["acme", "Acme Pvt Ltd", "45000.5"]]
    assert parse_date(rows[1][2], "d") == date(2015, 6, 30)


def test_xlsx_reader_refuses_a_file_that_is_not_a_workbook():
    with pytest.raises(HTTPException):
        read_xlsx_rows(b"not a zip")


def test_tracker_sheet_columns_and_cells():
    from backend import profile_api as pa
    assert pa._tracker_header("Company Name") == "company" and pa._tracker_header("Particulars") == "legal_name"
    assert pa._tracker_header("FY25 AOP received") == "aop" and pa._tracker_header("FY 2027 AOP received") == "aop"
    assert pa._tracker_header("Credit History \n(CC limit/ Corporate Credit Card)") == "credit_history"
    assert pa._tracker_header("Founders\u2019 KYC (PAN Aadhar & Passport)") == "kyc_received"
    assert pa._register_cell("Yes, valid till 31/03/2027", "x") == ("yes", "2027-03-31", "Yes, valid till 31/03/2027")
    assert pa._register_cell("Applied", "x")[0] == "no" and pa._register_cell("NA", "x")[0] == "na" and pa._register_cell("", "x") == (None, None, None)
    lookup = {"nimbus mobility": 1, "nimbus-mobility": 1, "ledgerly fintech": 2, "the orchard (formerly skyforge)": 3, "tempo ai": 4, "orbit-health": 5}
    assert [pa._find_company(lookup, n) for n in ("Nimbus", "Ledger", "Skyforge", "Tempo", "Orbit Health", "Zephyr", "ai")] == [1, 2, 3, 4, 5, None, None]


def test_tracker_never_stores_identity_numbers():
    from backend import profile_api as pa
    for text in ("PAN ABCDE1234F", "aadhaar 1234 5678 9012", "Passport K1234567"):
        assert pa.ID_NUMBER.search(text.upper()), text
    for text in ("Series B in Q3 FY27", "Call on 12/10/2026 with 3 partners", "KYC received for both founders"):
        assert not pa.ID_NUMBER.search(text.upper()), text


def test_every_tracker_company_matches_one_portfolio_company():
    """The tracker writes short names (Nimbus, Ledgerly, Orbit); each must find exactly one company."""
    import json
    from pathlib import Path
    from backend import profile_api as pa

    root = Path(__file__).resolve().parents[1]
    sheet = [{"sheet_name": n} for n in ("Nimbus", "Ledgerly", "Kirana", "Orbit", "Greenrow", "Ringly", "Voltara")]
    portfolio = json.loads((root / "backend/data/demo_portfolio.json").read_text(encoding="utf-8"))["companies"]
    lookup = {}
    for i, c in enumerate(portfolio):
        lookup.setdefault(c["name"].lower(), i)
    found = {e["sheet_name"]: pa._find_company(lookup, e["sheet_name"]) for e in sheet}
    assert None not in found.values(), [k for k, v in found.items() if v is None]
    assert len(set(found.values())) == len(found)  # no two sheet rows land on the same company
    assert portfolio[found["Nimbus"]]["name"] == "Nimbus Mobility" and portfolio[found["Voltara"]]["fund"] == "Fund IV"
