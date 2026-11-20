"""Turn validated extraction results into grounded fact drafts."""
from app.domain.enums import FactType
from app.extraction.grounding import FactBuilder
from app.extraction.schemas import (
    AmountFact,
    BankStatementExtraction,
    DateFact,
    DeclarationExtraction,
    LiabilityExtraction,
    PercentFact,
    PortfolioExtraction,
    SaleAgreementExtraction,
    TaxSummaryExtraction,
    TextFact,
)


def _text(b: FactBuilder, fact_type: FactType, f: TextFact | None, **extra) -> None:
    if f is not None:
        b.add(
            fact_type.value,
            f,
            original=f.value,
            normalized={"value": f.value, **extra},
            texts=(f.value,),
        )


def _date(b: FactBuilder, fact_type: FactType, f: DateFact | None) -> None:
    if f is not None:
        b.add(
            fact_type.value,
            f,
            original=f.value.isoformat(),
            normalized={"value": f.value.isoformat()},
            effective_date=f.value,
        )


def _amount(b: FactBuilder, fact_type: FactType, f: AmountFact | None, default_date=None, **extra) -> None:
    if f is not None:
        b.add(
            fact_type.value,
            f,
            original=str(f.amount),
            amount=f.amount,
            currency=f.currency,
            effective_date=f.as_of or default_date,
            normalized=dict(extra),
        )


def _percent(b: FactBuilder, fact_type: FactType, f: PercentFact | None) -> None:
    if f is not None:
        b.add(
            fact_type.value,
            f,
            original=str(f.value),
            normalized={"percent": str(f.value)},
            numbers=(f.value,),
        )


def flatten_declaration(ex: DeclarationExtraction, b: FactBuilder) -> None:
    _text(b, FactType.PARTY_NAME, ex.customer_name, role="customer")
    _text(b, FactType.PARTY_PAN, ex.customer_pan, role="customer")
    _date(b, FactType.DECLARATION_DATE, ex.declaration_date)
    on = ex.declaration_date.value if ex.declaration_date else None
    _amount(b, FactType.DECLARED_NET_WORTH, ex.declared_net_worth, on)
    _amount(b, FactType.DECLARED_SALE_VALUE, ex.declared_sale_value, on)
    _amount(b, FactType.DECLARED_INTENDED_INVESTMENT, ex.intended_investment, on)
    _amount(b, FactType.DECLARED_INVESTMENTS, ex.existing_investments, on)
    _amount(b, FactType.DECLARED_BANK_DEPOSITS, ex.bank_deposits, on)
    _amount(b, FactType.DECLARED_LOAN, ex.outstanding_loan, on)
    _amount(b, FactType.DECLARED_PROPERTY, ex.additional_property, on)
    _text(b, FactType.DECLARED_SOURCE_OF_WEALTH, ex.source_of_wealth)
    _text(b, FactType.DECLARED_SOURCE_OF_FUNDS, ex.source_of_funds)


def flatten_bank(ex: BankStatementExtraction, b: FactBuilder) -> None:
    _text(b, FactType.PARTY_NAME, ex.account_holder_name, role="account_holder")
    _text(b, FactType.ORGANIZATION_NAME, ex.bank_name, role="bank")
    _text(b, FactType.ACCOUNT_IDENTIFIER, ex.account_number_suffix, kind="account_suffix")
    _amount(b, FactType.BANK_OPENING_BALANCE, ex.opening_balance)
    _amount(b, FactType.BANK_CLOSING_BALANCE, ex.closing_balance)
    for t in ex.transactions:
        amount = t.credit if t.credit is not None else t.debit
        b.add(
            FactType.BANK_TRANSACTION.value,
            t,
            original=str(amount),
            amount=amount,
            currency=t.currency,
            effective_date=t.txn_date,
            normalized={
                "direction": "CREDIT" if t.credit is not None else "DEBIT",
                "narration": t.narration,
                "reference": t.reference,
                "balance": str(t.balance) if t.balance is not None else None,
            },
            numbers=(t.balance,) if t.balance is not None else (),
            texts=tuple(x for x in (t.narration, t.reference) if x),
        )


def flatten_portfolio(ex: PortfolioExtraction, b: FactBuilder) -> None:
    _text(b, FactType.PARTY_NAME, ex.investor_name, role="investor")
    _text(b, FactType.PARTY_PAN, ex.investor_pan, role="investor")
    _text(b, FactType.ORGANIZATION_NAME, ex.institution_name, role="institution")
    valuation = None
    if ex.valuation_date and b.verify("VALUATION_DATE", ex.valuation_date):
        valuation = ex.valuation_date.value  # carried on each holding as its effective date
    for h in ex.holdings:
        numbers = tuple(n for n in (h.units, h.price) if n is not None)
        b.add(
            FactType.PORTFOLIO_HOLDING.value,
            h,
            original=str(h.market_value),
            amount=h.market_value,
            currency=h.currency,
            effective_date=valuation,
            normalized={
                "instrument_name": h.instrument_name,
                "isin": h.isin,
                "folio": h.folio,
                "units": str(h.units),
                "price": str(h.price) if h.price is not None else None,
            },
            numbers=numbers,
            texts=tuple(x for x in (h.isin, h.folio) if x),
        )
    _amount(b, FactType.PORTFOLIO_TOTAL_VALUE, ex.total_market_value, valuation)


def flatten_sale(ex: SaleAgreementExtraction, b: FactBuilder) -> None:
    _date(b, FactType.SALE_AGREEMENT_DATE, ex.agreement_date)
    agreed = ex.agreement_date.value if ex.agreement_date else None
    _text(b, FactType.DOCUMENT_REFERENCE, ex.reference)
    _text(b, FactType.PARTY_NAME, ex.seller_name, role="seller")
    _text(b, FactType.PARTY_PAN, ex.seller_pan, role="seller")
    _text(b, FactType.ORGANIZATION_NAME, ex.purchaser_name, role="purchaser")
    _text(b, FactType.REGISTRATION_ID, ex.purchaser_registration_id, role="purchaser")
    _text(b, FactType.ORGANIZATION_NAME, ex.target_company_name, role="target_company")
    _text(b, FactType.REGISTRATION_ID, ex.target_registration_id, role="target_company")
    _amount(b, FactType.SALE_CONSIDERATION, ex.consideration, agreed)
    _date(b, FactType.SALE_PAYMENT_DATE, ex.payment_date)
    _text(b, FactType.ACCOUNT_IDENTIFIER, ex.settlement_account_suffix, kind="settlement_account_suffix")


def flatten_tax(ex: TaxSummaryExtraction, b: FactBuilder) -> None:
    _text(b, FactType.PARTY_NAME, ex.taxpayer_name, role="taxpayer")
    _text(b, FactType.PARTY_PAN, ex.taxpayer_pan, role="taxpayer")
    _text(b, FactType.TAX_ASSESSMENT_YEAR, ex.assessment_year)
    for item in ex.income_items:
        b.add(
            FactType.TAX_INCOME_ITEM.value,
            item,
            original=str(item.amount),
            amount=item.amount,
            currency=item.currency,
            normalized={"label": item.label},
            texts=(item.label,),
        )
    _amount(b, FactType.TAX_TOTAL_INCOME, ex.total_income)
    _amount(b, FactType.TAX_PAID, ex.tax_paid)


def flatten_liability(ex: LiabilityExtraction, b: FactBuilder) -> None:
    _text(b, FactType.PARTY_NAME, ex.borrower_name, role="borrower")
    _text(b, FactType.PARTY_PAN, ex.borrower_pan, role="borrower")
    _text(b, FactType.ORGANIZATION_NAME, ex.lender_name, role="lender")
    _text(b, FactType.ACCOUNT_IDENTIFIER, ex.loan_account_number, kind="loan_account")
    _amount(b, FactType.LIABILITY_SANCTIONED, ex.sanctioned_amount)
    _amount(b, FactType.LIABILITY_OUTSTANDING, ex.outstanding_principal)
    _percent(b, FactType.LIABILITY_INTEREST_RATE, ex.interest_rate_pct)
    _amount(b, FactType.LIABILITY_EMI, ex.emi)
