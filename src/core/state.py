"""LangGraph state management for agent workflow."""

from typing import TypedDict, Optional, List, Any
from src.models.schemas import ExtractedInvoice, MatchingResult, Discrepancy


class AgentState(TypedDict, total=False):
    """State passed between agents in the workflow."""
    
    # Input
    invoice_path: str
    po_database: List[dict]
    
    # Document Intelligence Agent outputs
    raw_text: str
    extracted_data: Optional[ExtractedInvoice]
    extraction_confidence: float
    document_quality: str
    extraction_reasoning: str
    
    # Matching Agent outputs
    matching_results: Optional[MatchingResult]
    matched_po_data: Optional[dict]
    matching_reasoning: str
    
    # Discrepancy Detection Agent outputs
    discrepancies: List[Discrepancy]
    discrepancy_reasoning: str
    
    # Resolution Agent outputs
    recommended_action: str
    resolution_reasoning: str
    risk_level: str
    
    # Human Reviewer Agent outputs (bonus)
    review_feedback: Optional[str]
    corrections: Optional[dict]
    needs_reprocessing: bool
    
    # Metadata
    agent_traces: dict
    errors: List[str]
    current_agent: str
    processing_start_time: float
