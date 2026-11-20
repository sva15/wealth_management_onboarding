"""Builders for in-memory fact views that mirror the extracted demo case."""
from datetime import date
from decimal import Decimal

from app.domain.facts import FactView


def fact(fid, doc, fact_type, *, amount=None, normalized=None, on=None, page=1, conf=0.95, currency=None, name=None, quote=None):
    return FactView(
        id=fid,
        document_id=doc,
        document_name=name or doc,
        fact_type=fact_type,
        page=page,
        confidence=conf,
        amount=Decimal(amount) if amount is not None else None,
        currency=currency or ("INR" if amount is not None else None),
        effective_date=on,
        normalized=normalized or {},
        source_text=quote or f"quote for {fid}",
    )


def person(fid, doc, role, name, pan=None):
    out = [fact(f"{fid}-n", doc, "PARTY_NAME", normalized={"value": name, "role": role})]
    if pan:
        out.append(fact(f"{fid}-p", doc, "PARTY_PAN", normalized={"value": pan, "role": role}))
    return out


def org(fid, doc, role, name, reg=None):
    out = [fact(f"{fid}-n", doc, "ORGANIZATION_NAME", normalized={"value": name, "role": role})]
    if reg:
        out.append(fact(f"{fid}-r", doc, "REGISTRATION_ID", normalized={"value": reg, "role": role}))
    return out


def sale_facts(seller_name="Aarav K. Mehta"):
    d = "d-sale"
    return [
        *person("sale-seller", d, "seller", seller_name, "ABCDE1234F"),
        *org("sale-buyer", d, "purchaser", "Orbit Capital Holdings Private Limited", "U74999KA2015PTC000123"),
        *org("sale-target", d, "target_company", "TechNova Solutions Private Limited", "U72900KA2015PTC000456"),
        fact("sale-ref", d, "DOCUMENT_REFERENCE", normalized={"value": "SPA-2026-0112"}),
        fact("sale-date", d, "SALE_AGREEMENT_DATE", normalized={"value": "2026-01-12"}, on=date(2026, 1, 12)),
        fact("sale-amt", d, "SALE_CONSIDERATION", amount="52000000.00", on=date(2026, 1, 12), page=2,
             quote="total consideration for the shares is INR 5,20,00,000.00"),
        fact("sale-acct", d, "ACCOUNT_IDENTIFIER", normalized={"value": "4821", "kind": "settlement_account_suffix"}),
    ]


def bank_facts(holder="Aarav Mehta"):
    d = "d-bank"
    txn = lambda fid, amt, direction, ref, narr, on: fact(  # noqa: E731
        fid, d, "BANK_TRANSACTION", amount=amt, on=on, page=2,
        normalized={"direction": direction, "reference": ref, "narration": narr, "balance": None},
        quote=f"{narr} {ref} INR {amt}",
    )
    return [
        *person("bank-holder", d, "account_holder", holder),
        *org("bank-org", d, "bank", "First Indus Bank Limited (fictional)"),
        fact("bank-acct", d, "ACCOUNT_IDENTIFIER", normalized={"value": "4821", "kind": "account_suffix"}),
        fact("bank-open", d, "BANK_OPENING_BALANCE", amount="500000.00"),
        fact("bank-close", d, "BANK_CLOSING_BALANCE", amount="11000000.00", on=date(2026, 3, 31)),
        txn("bank-t1", "50400000.00", "CREDIT", "UTR260115001", "RTGS CR ORBIT CAPITAL SPA-2026-0112", date(2026, 1, 15)),
        txn("bank-t2", "17000000.00", "DEBIT", "NEFT260120077", "NEFT DR ZENITH WEALTH INVESTMENT", date(2026, 1, 20)),
        txn("bank-t3", "6000000.00", "DEBIT", "TAX260310015", "ADVANCE TAX PAYMENT CHALLAN 280", date(2026, 3, 10)),
        txn("bank-t4", "16900000.00", "DEBIT", "IMPS260325044", "TRANSFER TO OWN ACCT ENDING 7733", date(2026, 3, 25)),
    ]


def holding(fid, doc, isin, folio, amount, name="Zenith Bluechip Fund - Growth"):
    return fact(
        fid, doc, "PORTFOLIO_HOLDING", amount=amount, on=date(2026, 3, 31),
        normalized={"instrument_name": name, "isin": isin, "folio": folio, "units": "1", "price": None},
    )


def portfolio_facts():
    d = "d-pf"
    return [
        *person("pf-inv", d, "investor", "Aarav Kumar Mehta", "ABCDE1234F"),
        *org("pf-inst", d, "institution", "Zenith Wealth Services (fictional)"),
        holding("pf-h1", d, "INF000Z01AB1", "11223344/01", "10000000.00"),
        holding("pf-h2", d, "INF000Z01CD2", "55667788/02", "7000000.00", "Zenith Debt Fund - Growth"),
        fact("pf-total", d, "PORTFOLIO_TOTAL_VALUE", amount="17000000.00", on=date(2026, 3, 31)),
    ]


def consolidated_facts():
    d = "d-cons"
    return [
        *person("cn-inv", d, "investor", "Mehta Aarav Kumar", "ABCDE1234F"),
        *org("cn-inst", d, "institution", "Nova Registrar and Transfer Agents (fictional)"),
        holding("cn-h1", d, "INF000Z01AB1", "11223344 / 01", "10000000.00"),
    ]


def tax_facts():
    d = "d-tax"
    return [
        *person("tax-p", d, "taxpayer", "Aarav Mehta", "ABCDE1234F"),
        fact("tax-total", d, "TAX_TOTAL_INCOME", amount="12000000.00"),
    ]


def loan_facts():
    d = "d-loan"
    return [
        *person("ln-b", d, "borrower", "Aarav Kumar Mehta", "ABCDE1234F"),
        *org("ln-l", d, "lender", "Meridian Finance Limited (fictional)"),
        fact("ln-acct", d, "ACCOUNT_IDENTIFIER", normalized={"value": "LN-77881234", "kind": "loan_account"}),
        fact("ln-sanc", d, "LIABILITY_SANCTIONED", amount="15000000.00"),
        fact("ln-out", d, "LIABILITY_OUTSTANDING", amount="9000000.00", on=date(2026, 3, 31)),
        fact("ln-emi", d, "LIABILITY_EMI", amount="240000.00"),
    ]


def demo_facts():
    return sale_facts() + bank_facts() + portfolio_facts() + consolidated_facts() + tax_facts() + loan_facts()
