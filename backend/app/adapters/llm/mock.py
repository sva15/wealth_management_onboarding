"""Deterministic stand-in for Bedrock (USE_MOCK_BEDROCK=true).

It parses the synthetic documents with regular expressions and returns the same JSON a real model
must produce. Provenance fields are filled from the matched text. Results are labelled with the
model id "mock-rules-v1" so they can never be mistaken for real model output.
"""
import json
import re
from datetime import datetime
from decimal import Decimal

from app.extraction import tasks
from app.extraction.pages import split_pages
from app.ports.llm import LlmError, LlmRequest, LlmResponse

MOCK_MODEL_ID = "mock-rules-v1"
_AMT = r"INR\s*([\d,]+(?:\.\d{1,2})?)"
_DATE = r"(\d{1,2} [A-Za-z]+ \d{4})"
_PAN = r"([A-Z]{5}\d{4}[A-Z])"
_CONFIDENCE = 0.95


def _money(raw: str) -> str:
    return str(Decimal(raw.replace(",", "")))


def _iso(raw: str) -> str | None:
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


class _Doc:
    def __init__(self, pages: dict[int, str]) -> None:
        self.pages = pages

    def find(self, pattern: str, flat: bool = False):
        for number in sorted(self.pages):
            text = " ".join(self.pages[number].split()) if flat else self.pages[number]
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                return number, match, " ".join(match.group(0).split())
        return None

    def find_all(self, pattern: str):
        for number in sorted(self.pages):
            for match in re.finditer(pattern, self.pages[number], re.MULTILINE):
                yield number, match, " ".join(match.group(0).split())


def _src(page: int, quote: str) -> dict:
    return {"source_page": page, "source_text": quote, "confidence": _CONFIDENCE}


def _text(doc: _Doc, pattern: str, group: int = 1, flat: bool = False) -> dict | None:
    hit = doc.find(pattern, flat)
    if not hit:
        return None
    page, match, quote = hit
    return {"value": " ".join(match.group(group).split()), **_src(page, quote)}


def _date(doc: _Doc, pattern: str, group: int = 1, flat: bool = False) -> dict | None:
    hit = doc.find(pattern, flat)
    if not hit:
        return None
    page, match, quote = hit
    value = _iso(match.group(group))
    return {"value": value, **_src(page, quote)} if value else None


def _amount(doc: _Doc, pattern: str, date_group: int | None = None, flat: bool = False) -> dict | None:
    hit = doc.find(pattern, flat)
    if not hit:
        return None
    page, match, quote = hit
    as_of = _iso(match.group(date_group)) if date_group else None
    return {"amount": _money(match.group(1)), "currency": "INR", "as_of": as_of, **_src(page, quote)}


def _declaration(doc: _Doc) -> dict:
    def row(label: str) -> dict | None:
        return _amount(doc, rf"^{label}\s+{_AMT}")

    return {
        "customer_name": _text(doc, r"^Customer name:\s*(.+)$"),
        "customer_pan": _text(doc, rf"PAN:\s*{_PAN}"),
        "declaration_date": _date(doc, rf"^Declaration date:\s*{_DATE}"),
        "declared_net_worth": row("Declared net worth"),
        "source_of_wealth": _text(doc, r"^Source of wealth\s+(.+)$"),
        "declared_sale_value": row("Declared company-sale value"),
        "source_of_funds": _text(doc, r"^Source of funds\s+(.+)$"),
        "intended_investment": row("Intended investment amount"),
        "existing_investments": row("Existing investments"),
        "bank_deposits": row("Bank deposits"),
        "outstanding_loan": row("Outstanding loan"),
        "additional_property": row(r"Additional property \(residential\)"),
    }


_TXN = (
    r"^(?P<date>\d{1,2} [A-Za-z]{3} \d{4}) (?P<narr>.+?) (?P<ref>[A-Z]{3,5}\d{6,}) "
    r"INR (?P<amt>[\d,]+\.\d{2}) INR (?P<bal>[\d,]+\.\d{2})\s*$"
)


def _bank(doc: _Doc) -> dict:
    opening = _amount(doc, rf"^Opening balance:\s*{_AMT}")
    transactions = []
    previous = Decimal(opening["amount"]) if opening else None
    for page, match, quote in doc.find_all(_TXN):
        amount, balance = Decimal(_money(match["amt"])), Decimal(_money(match["bal"]))
        # The statement does not mark debit vs credit, so infer it from the running balance.
        if previous is not None and previous + amount == balance:
            debit, credit = None, amount
        elif previous is not None and previous - amount == balance:
            debit, credit = amount, None
        else:
            previous = balance
            continue  # direction cannot be established; omit rather than guess
        previous = balance
        transactions.append(
            {
                "txn_date": _iso(match["date"]),
                "narration": match["narr"],
                "reference": match["ref"],
                "debit": str(debit) if debit is not None else None,
                "credit": str(credit) if credit is not None else None,
                "balance": str(balance),
                "currency": "INR",
                **_src(page, quote),
            }
        )
    return {
        "account_holder_name": _text(doc, r"^Account holder:\s*(.+)$"),
        "bank_name": _text(doc, r"^(.*\bBank\b.*)$"),
        "account_number_suffix": _text(doc, r"^Account number:\s*X*(\d+)"),
        "opening_balance": opening,
        "closing_balance": _amount(doc, rf"^Closing balance:\s*{_AMT}\s+as at\s+{_DATE}", date_group=2),
        "transactions": transactions,
    }


_HOLDING = (
    r"^(?P<name>.+?) (?P<isin>[A-Z]{2}[A-Z0-9]{10}) (?P<folio>\d+/\d+) "
    r"(?P<units>[\d,]+(?:\.\d+)?) (?P<price>[\d,]+(?:\.\d+)?) INR (?P<mv>[\d,]+\.\d{2})\s*$"
)


def _portfolio(doc: _Doc) -> dict:
    holdings = [
        {
            "instrument_name": m["name"],
            "isin": m["isin"],
            "folio": m["folio"],
            "units": m["units"].replace(",", ""),
            "price": m["price"].replace(",", ""),
            "market_value": _money(m["mv"]),
            "currency": "INR",
            **_src(page, quote),
        }
        for page, m, quote in doc.find_all(_HOLDING)
    ]
    return {
        "investor_name": _text(doc, r"^(?:Investor|Holder):\s*(.+?)\s+PAN:"),
        "investor_pan": _text(doc, rf"PAN:\s*{_PAN}"),
        "institution_name": _text(doc, r"^(.+\(fictional\))\s*$"),
        "valuation_date": _date(doc, rf"^Valuation date:\s*{_DATE}"),
        "holdings": holdings,
        "total_market_value": _amount(doc, rf"^Total market value:\s*{_AMT}"),
    }


def _sale(doc: _Doc) -> dict:
    party = r"\(PAN " + _PAN + r"\)"
    return {
        "agreement_date": _date(doc, rf"Date of agreement:\s*{_DATE}", flat=True),
        "reference": _text(doc, r"Reference:\s*(\S+)", flat=True),
        "seller_name": _text(doc, rf"Seller:\s*(?:Mr\.|Ms\.|Mrs\.)?\s*(.+?)\s*{party}", flat=True),
        "seller_pan": _text(doc, rf"Seller:\s*.+?{party}", flat=True),
        "purchaser_name": _text(doc, r"Purchaser:\s*(.+?)\s*\(CIN \S+?\)", flat=True),
        "purchaser_registration_id": _text(doc, r"Purchaser:\s*.+?\(CIN (\S+?)\)", flat=True),
        "target_company_name": _text(doc, r"Target company:\s*(.+?)\s*\(CIN \S+?\)", flat=True),
        "target_registration_id": _text(doc, r"Target company:\s*.+?\(CIN (\S+?)\)", flat=True),
        "consideration": _amount(doc, rf"total consideration for the shares is\s*{_AMT}", flat=True),
        "payment_date": _date(doc, rf"on completion,\s*{_DATE}", flat=True),
        "settlement_account_suffix": _text(doc, r"account ending\s*(\d+)", flat=True),
    }


_TAX_ROW = r"^(?P<label>[A-Za-z][A-Za-z ]*?)\s+INR\s*(?P<amt>[\d,]+\.\d{2})\s*$"


def _tax(doc: _Doc) -> dict:
    items, total, paid = [], None, None
    for page, m, quote in doc.find_all(_TAX_ROW):
        label = m["label"].strip()
        amount = {"amount": _money(m["amt"]), "currency": "INR", "as_of": None, **_src(page, quote)}
        if label.lower().startswith("total income"):
            total = amount
        elif label.lower().startswith("tax paid"):
            paid = amount
        else:
            items.append({"label": label, "amount": amount["amount"], "currency": "INR", **_src(page, quote)})
    return {
        "taxpayer_name": _text(doc, r"^Name:\s*(.+?)\s+PAN:"),
        "taxpayer_pan": _text(doc, rf"PAN:\s*{_PAN}"),
        "assessment_year": _text(doc, r"^Assessment Year:\s*(\d{4}-\d{2,4})"),
        "income_items": items,
        "total_income": total,
        "tax_paid": paid,
    }


def _liability(doc: _Doc) -> dict:
    return {
        "borrower_name": _text(doc, r"^Borrower:\s*(.+?)\s+PAN:"),
        "borrower_pan": _text(doc, rf"PAN:\s*{_PAN}"),
        "lender_name": _text(doc, r"^(.+\(fictional\))\s*$"),
        "loan_account_number": _text(doc, r"^Loan account number:\s*(\S+)"),
        "sanctioned_amount": _amount(doc, rf"^Sanctioned amount:\s*{_AMT}"),
        "outstanding_principal": _amount(
            doc, rf"^Outstanding principal:\s*{_AMT}\s+as at\s+{_DATE}", date_group=2
        ),
        "interest_rate_pct": _text(doc, r"Interest rate:\s*([\d.]+)\s*%"),
        "emi": _amount(doc, rf"\bEMI:\s*{_AMT}"),
    }


def _classify(_doc: _Doc) -> dict:
    return {
        "document_type": "UNKNOWN",
        "confidence": 0.0,
        "explanation": "The mock model does not classify documents.",
    }


_HANDLERS = {
    tasks.DECLARATION: _declaration,
    tasks.BANK: _bank,
    tasks.PORTFOLIO: _portfolio,
    tasks.SALE: _sale,
    tasks.TAX: _tax,
    tasks.LIABILITY: _liability,
    tasks.CLASSIFY: _classify,
}


class MockLlmClient:
    model_id = MOCK_MODEL_ID

    def invoke(self, request: LlmRequest) -> LlmResponse:
        handler = _HANDLERS.get(request.task)
        if handler is None:
            raise LlmError("MOCK_UNSUPPORTED_TASK")
        result = handler(_Doc(split_pages(request.untrusted_text)))
        text = json.dumps(result)
        return LlmResponse(
            text=text,
            model_id=self.model_id,
            input_tokens=len(request.untrusted_text) // 4,
            output_tokens=len(text) // 4,
            latency_ms=0,
        )
