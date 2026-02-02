"""Pydantic models for invoice reconciliation system."""

from typing import Optional, List, Literal
from pydantic import BaseModel, Field
from datetime import datetime


class LineItem(BaseModel):
    """A line item from an invoice or PO."""
    item_code: Optional[str] = None
    description: str
    quantity: float
    unit: str = "kg"
    unit_price: float
    line_total: float
    extraction_confidence: float = Field(default=0.95, ge=0.0, le=1.0)


class ExtractedInvoice(BaseModel):
    """Structured data extracted from an invoice."""
    invoice_number: str
    invoice_date: str
    supplier_name: str
    supplier_address: Optional[str] = None
    supplier_vat: Optional[str] = None
    po_reference: Optional[str] = None
    payment_terms: Optional[str] = None
    bill_to: Optional[dict] = None
    line_items: List[LineItem]
    subtotal: float
    vat_rate: Optional[float] = 0.20
    vat_amount: Optional[float] = None
    total: float
    currency: str = "GBP"


class PurchaseOrder(BaseModel):
    """A purchase order from the database."""
    po_number: str
    supplier: str
    date: str
    total: float
    currency: str = "GBP"
    line_items: List[LineItem]


class Discrepancy(BaseModel):
    """A detected discrepancy between invoice and PO."""
    type: Literal["price_mismatch", "quantity_mismatch", "missing_po_reference", 
                  "supplier_mismatch", "total_variance", "missing_item", "extra_item"]
    severity: Literal["low", "medium", "high"]
    line_item_index: Optional[int] = None
    field: Optional[str] = None
    invoice_value: Optional[float] = None
    po_value: Optional[float] = None
    variance_percentage: Optional[float] = None
    details: str
    recommended_action: Literal["auto_approve", "flag_for_review", "escalate_to_human"]
    confidence: float = Field(default=0.95, ge=0.0, le=1.0)


class MatchingResult(BaseModel):
    """Results from PO matching."""
    po_match_confidence: float = Field(ge=0.0, le=1.0)
    matched_po: Optional[str] = None
    match_method: Literal["exact_po_reference", "fuzzy_supplier_product_match", 
                          "product_only_match", "no_match"]
    supplier_match: bool = False
    date_variance_days: Optional[int] = None
    line_items_matched: int = 0
    line_items_total: int = 0
    match_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    alternative_matches: List[dict] = Field(default_factory=list)


class AgentExecutionTrace(BaseModel):
    """Execution trace for a single agent."""
    duration_ms: int
    confidence: float = Field(ge=0.0, le=1.0)
    status: Literal["success", "partial", "failed"]
    reasoning: Optional[str] = None


class ReconciliationResult(BaseModel):
    """Final output for a processed invoice."""
    invoice_id: str
    processing_timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    processing_duration_seconds: Optional[float] = None
    document_info: dict = Field(default_factory=dict)
    processing_results: dict = Field(default_factory=dict)
    agent_execution_trace: dict = Field(default_factory=dict)
    
    @classmethod
    def create(
        cls,
        invoice_id: str,
        extraction_confidence: float,
        document_quality: str,
        extracted_data: ExtractedInvoice,
        matching_results: MatchingResult,
        discrepancies: List[Discrepancy],
        recommended_action: str,
        agent_reasoning: str,
        execution_traces: dict
    ) -> "ReconciliationResult":
        """Create a properly formatted reconciliation result."""
        return cls(
            invoice_id=invoice_id,
            processing_results={
                "extraction_confidence": extraction_confidence,
                "document_quality": document_quality,
                "extracted_data": extracted_data.model_dump(),
                "matching_results": matching_results.model_dump(),
                "discrepancies": [d.model_dump() for d in discrepancies],
                "recommended_action": recommended_action,
                "agent_reasoning": agent_reasoning
            },
            agent_execution_trace=execution_traces
        )
