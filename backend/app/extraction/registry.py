"""Maps each supported document type to its schema, task and flattening function."""
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from app.domain.enums import DocumentType
from app.extraction import facts, tasks
from app.extraction.grounding import FactBuilder
from app.extraction.schemas import (
    BankStatementExtraction,
    DeclarationExtraction,
    LiabilityExtraction,
    PortfolioExtraction,
    SaleAgreementExtraction,
    TaxSummaryExtraction,
)


@dataclass(frozen=True)
class ExtractorSpec:
    task: str
    schema: type[BaseModel]
    flatten: Callable[[BaseModel, FactBuilder], None]


EXTRACTORS: dict[str, ExtractorSpec] = {
    DocumentType.CUSTOMER_DECLARATION.value: ExtractorSpec(
        tasks.DECLARATION, DeclarationExtraction, facts.flatten_declaration
    ),
    DocumentType.BANK_STATEMENT.value: ExtractorSpec(tasks.BANK, BankStatementExtraction, facts.flatten_bank),
    DocumentType.PORTFOLIO_STATEMENT.value: ExtractorSpec(
        tasks.PORTFOLIO, PortfolioExtraction, facts.flatten_portfolio
    ),
    DocumentType.COMPANY_SALE_AGREEMENT.value: ExtractorSpec(
        tasks.SALE, SaleAgreementExtraction, facts.flatten_sale
    ),
    DocumentType.TAX_SUMMARY.value: ExtractorSpec(tasks.TAX, TaxSummaryExtraction, facts.flatten_tax),
    DocumentType.LIABILITY_STATEMENT.value: ExtractorSpec(
        tasks.LIABILITY, LiabilityExtraction, facts.flatten_liability
    ),
}
