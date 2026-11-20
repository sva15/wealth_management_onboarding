"""Document-specific extraction schemas. Every extracted item carries its own source reference."""
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Confidence = Annotated[float, Field(ge=0, le=1)]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Quote = Annotated[str, StringConstraints(min_length=1, max_length=500)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Money = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=2)]
Quantity = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=6)]
Isin = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Sourced(_Strict):
    source_page: int = Field(ge=1, description="1-based page number where the value appears")
    source_text: Quote = Field(description="Exact text copied from that page that contains the value")
    confidence: Confidence = Field(description="Your confidence from 0 to 1 that the value is correct")


class TextFact(Sourced):
    value: ShortText


class DateFact(Sourced):
    value: date


class AmountFact(Sourced):
    amount: Money
    currency: Currency = "INR"
    as_of: date | None = None


class PercentFact(Sourced):
    value: Annotated[Decimal, Field(ge=0, le=100)]


# --- customer declaration -------------------------------------------------
class DeclarationExtraction(_Strict):
    customer_name: TextFact | None = None
    customer_pan: TextFact | None = None
    declaration_date: DateFact | None = None
    declared_net_worth: AmountFact | None = None
    source_of_wealth: TextFact | None = None
    declared_sale_value: AmountFact | None = None
    source_of_funds: TextFact | None = None
    intended_investment: AmountFact | None = None
    existing_investments: AmountFact | None = None
    bank_deposits: AmountFact | None = None
    outstanding_loan: AmountFact | None = None
    additional_property: AmountFact | None = None


# --- bank statement -------------------------------------------------------
class BankTransaction(Sourced):
    txn_date: date
    narration: ShortText
    reference: ShortText | None = None
    debit: Money | None = None
    credit: Money | None = None
    balance: Money | None = None
    currency: Currency = "INR"

    @model_validator(mode="after")
    def _exactly_one_direction(self) -> "BankTransaction":
        if (self.debit is None) == (self.credit is None):
            raise ValueError("exactly one of debit or credit must be set")
        return self


class BankStatementExtraction(_Strict):
    account_holder_name: TextFact | None = None
    bank_name: TextFact | None = None
    account_number_suffix: TextFact | None = None
    opening_balance: AmountFact | None = None
    closing_balance: AmountFact | None = None
    transactions: list[BankTransaction] = Field(default_factory=list)


# --- portfolio / holdings statement ---------------------------------------
class Holding(Sourced):
    instrument_name: ShortText
    isin: Isin | None = None
    folio: ShortText | None = None
    units: Quantity
    price: Quantity | None = None
    market_value: Money
    currency: Currency = "INR"


class PortfolioExtraction(_Strict):
    investor_name: TextFact | None = None
    investor_pan: TextFact | None = None
    institution_name: TextFact | None = None
    valuation_date: DateFact | None = None
    holdings: list[Holding] = Field(default_factory=list)
    total_market_value: AmountFact | None = None


# --- company sale agreement -----------------------------------------------
class SaleAgreementExtraction(_Strict):
    agreement_date: DateFact | None = None
    reference: TextFact | None = None
    seller_name: TextFact | None = None
    seller_pan: TextFact | None = None
    purchaser_name: TextFact | None = None
    purchaser_registration_id: TextFact | None = None
    target_company_name: TextFact | None = None
    target_registration_id: TextFact | None = None
    consideration: AmountFact | None = None
    payment_date: DateFact | None = None
    settlement_account_suffix: TextFact | None = None


# --- tax summary ----------------------------------------------------------
class IncomeItem(Sourced):
    label: ShortText
    amount: Money
    currency: Currency = "INR"


class TaxSummaryExtraction(_Strict):
    taxpayer_name: TextFact | None = None
    taxpayer_pan: TextFact | None = None
    assessment_year: TextFact | None = None
    income_items: list[IncomeItem] = Field(default_factory=list)
    total_income: AmountFact | None = None
    tax_paid: AmountFact | None = None


# --- loan / liability statement -------------------------------------------
class LiabilityExtraction(_Strict):
    borrower_name: TextFact | None = None
    borrower_pan: TextFact | None = None
    lender_name: TextFact | None = None
    loan_account_number: TextFact | None = None
    sanctioned_amount: AmountFact | None = None
    outstanding_principal: AmountFact | None = None
    interest_rate_pct: PercentFact | None = None
    emi: AmountFact | None = None
