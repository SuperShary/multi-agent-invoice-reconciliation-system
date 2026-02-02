"""Resolution Agent - Recommends action based on all agent findings."""

import time
from typing import List, Optional

from src.core.state import AgentState
from src.core.config import ReconciliationRules
from src.models.schemas import Discrepancy, MatchingResult, ExtractedInvoice


def resolution_agent(state: AgentState) -> AgentState:
    """
    Resolution Agent node for LangGraph.
    Evaluates all findings and recommends: auto_approve, flag_for_review, or escalate_to_human.
    """
    start_time = time.time()
    
    extraction_confidence = state.get("extraction_confidence", 0.0)
    matching_results: Optional[MatchingResult] = state.get("matching_results")
    discrepancies: List[Discrepancy] = state.get("discrepancies", [])
    extracted_data: Optional[ExtractedInvoice] = state.get("extracted_data")
    matched_po_data = state.get("matched_po_data")
    
    # Initialize decision factors
    decision_factors = []
    risk_factors = []
    
    # Factor 1: Extraction confidence
    if extraction_confidence >= ReconciliationRules.CONFIDENCE_AUTO_APPROVE:
        decision_factors.append(("extraction_confidence", "high", extraction_confidence))
    elif extraction_confidence >= ReconciliationRules.CONFIDENCE_FLAG_REVIEW_MIN:
        decision_factors.append(("extraction_confidence", "medium", extraction_confidence))
        risk_factors.append("Low extraction confidence")
    else:
        decision_factors.append(("extraction_confidence", "low", extraction_confidence))
        risk_factors.append("Very low extraction confidence")
    
    # Factor 2: PO match confidence
    po_confidence = matching_results.po_match_confidence if matching_results else 0.0
    if po_confidence >= 0.95:
        decision_factors.append(("po_match", "high", po_confidence))
    elif po_confidence >= 0.70:
        decision_factors.append(("po_match", "medium", po_confidence))
        risk_factors.append(f"PO match confidence only {po_confidence:.0%}")
    elif po_confidence > 0:
        decision_factors.append(("po_match", "low", po_confidence))
        risk_factors.append("Low PO match confidence")
    else:
        decision_factors.append(("po_match", "none", 0.0))
        risk_factors.append("No PO match found")
    
    # Factor 3: Discrepancies
    high_severity_count = sum(1 for d in discrepancies if d.severity == "high")
    medium_severity_count = sum(1 for d in discrepancies if d.severity == "medium")
    
    if high_severity_count > 0:
        risk_factors.append(f"{high_severity_count} high-severity discrepancies")
    if medium_severity_count > 0:
        risk_factors.append(f"{medium_severity_count} medium-severity discrepancies")
    
    # Determine recommended action
    recommended_action = "auto_approve"
    
    # Escalate conditions
    escalate_conditions = [
        high_severity_count >= 1,
        len(discrepancies) >= 3,
        extraction_confidence < ReconciliationRules.CONFIDENCE_ESCALATE,
        po_confidence < 0.50 and matching_results is not None,
        matched_po_data is None and (matching_results is None or not matching_results.matched_po)
    ]
    
    # Flag for review conditions
    flag_conditions = [
        medium_severity_count >= 1,
        extraction_confidence < ReconciliationRules.CONFIDENCE_AUTO_APPROVE,
        po_confidence < 0.95 and po_confidence >= 0.50,
        matching_results and matching_results.match_method != "exact_po_reference",
        len(discrepancies) >= 1
    ]
    
    if any(escalate_conditions):
        recommended_action = "escalate_to_human"
        risk_level = "high"
    elif any(flag_conditions):
        recommended_action = "flag_for_review"
        risk_level = "medium"
    else:
        risk_level = "low"
    
    # Build comprehensive reasoning
    reasoning_parts = []
    
    # Invoice summary
    if extracted_data:
        reasoning_parts.append(
            f"Invoice {extracted_data.invoice_number} processed with {extraction_confidence:.0%} extraction confidence."
        )
    
    # Document quality
    doc_quality = state.get("document_quality", "unknown")
    reasoning_parts.append(f"Document quality assessed as '{doc_quality}'.")
    
    # PO matching summary
    if matching_results:
        if matching_results.matched_po:
            reasoning_parts.append(
                f"Matched to {matching_results.matched_po} via {matching_results.match_method.replace('_', ' ')} "
                f"({matching_results.po_match_confidence:.0%} confidence)."
            )
        else:
            reasoning_parts.append("Could not match to any purchase order in database.")
    
    # Discrepancy summary
    if discrepancies:
        reasoning_parts.append(f"Detected {len(discrepancies)} discrepancies:")
        for d in discrepancies:
            reasoning_parts.append(f"  - {d.type.replace('_', ' ').title()}: {d.details}")
    else:
        reasoning_parts.append("No discrepancies detected.")
    
    # Risk assessment
    if risk_factors:
        reasoning_parts.append(f"Risk factors: {', '.join(risk_factors)}.")
    else:
        reasoning_parts.append("No significant risk factors identified.")
    
    # Final decision
    action_explanations = {
        "auto_approve": "All criteria met for automatic approval. High confidence extraction, exact PO match, no discrepancies.",
        "flag_for_review": "Minor issues detected requiring human verification before approval.",
        "escalate_to_human": "Significant issues detected. Immediate human attention required before processing."
    }
    reasoning_parts.append(
        f"RECOMMENDATION: {recommended_action.upper()}. {action_explanations[recommended_action]}"
    )
    
    final_reasoning = " ".join(reasoning_parts)
    
    # Update state
    duration_ms = int((time.time() - start_time) * 1000)
    
    state["recommended_action"] = recommended_action
    state["resolution_reasoning"] = final_reasoning
    state["risk_level"] = risk_level
    state["agent_traces"] = state.get("agent_traces", {})
    state["agent_traces"]["resolution_recommendation_agent"] = {
        "duration_ms": duration_ms,
        "confidence": 0.95,
        "status": "success",
        "reasoning": f"Recommended {recommended_action} based on {len(decision_factors)} factors"
    }
    state["current_agent"] = "complete"
    
    return state
