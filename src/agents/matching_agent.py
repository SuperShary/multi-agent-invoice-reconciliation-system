"""Matching Agent - Matches invoices to PO database with fuzzy logic."""

import time
from typing import Optional

from src.core.state import AgentState
from src.core.config import ReconciliationRules
from src.utils.po_database import PODatabase
from src.models.schemas import MatchingResult, ExtractedInvoice


def matching_agent(state: AgentState) -> AgentState:
    """
    Matching Agent node for LangGraph.
    Matches extracted invoice data to purchase orders using 3-tier strategy.
    """
    start_time = time.time()
    
    extracted_data: Optional[ExtractedInvoice] = state.get("extracted_data")
    
    if extracted_data is None:
        # No data to match
        duration_ms = int((time.time() - start_time) * 1000)
        state["matching_results"] = MatchingResult(
            po_match_confidence=0.0,
            matched_po=None,
            match_method="no_match",
            supplier_match=False
        )
        state["matching_reasoning"] = "No extracted invoice data available for matching."
        state["agent_traces"] = state.get("agent_traces", {})
        state["agent_traces"]["matching_agent"] = {
            "duration_ms": duration_ms,
            "confidence": 0.0,
            "status": "failed",
            "reasoning": "No extracted data"
        }
        return state
    
    # Initialize PO database
    po_db = PODatabase()
    
    # Get product descriptions for fuzzy matching
    product_descriptions = [item.description for item in extracted_data.line_items]
    
    # Use 3-tier matching strategy
    matched_po, match_method, confidence = po_db.find_best_match(
        po_reference=extracted_data.po_reference,
        supplier_name=extracted_data.supplier_name,
        product_descriptions=product_descriptions,
        invoice_total=extracted_data.total
    )
    
    # Build detailed reasoning
    reasoning_parts = []
    
    if match_method == "exact_po_reference":
        reasoning_parts.append(
            f"Found exact PO reference match: '{extracted_data.po_reference}' exists in database."
        )
    elif match_method == "fuzzy_supplier_product_match":
        reasoning_parts.append(
            f"No exact PO reference found. Used fuzzy matching on supplier '{extracted_data.supplier_name}' "
            f"and product descriptions."
        )
    elif match_method == "product_only_match":
        reasoning_parts.append(
            f"Matched based on product descriptions only. Supplier could not be verified."
        )
    else:
        reasoning_parts.append(
            f"Could not match invoice to any purchase order in database. "
            f"Searched {len(po_db.get_all_pos())} POs."
        )
    
    # Calculate line item matching stats
    line_items_matched = 0
    if matched_po:
        po_descriptions = [item.description.lower() for item in matched_po.line_items]
        for item in extracted_data.line_items:
            for po_desc in po_descriptions:
                from rapidfuzz import fuzz
                if fuzz.token_sort_ratio(item.description.lower(), po_desc) >= 70:
                    line_items_matched += 1
                    break
        
        # Check supplier name match
        from rapidfuzz import fuzz
        supplier_score = fuzz.token_sort_ratio(
            extracted_data.supplier_name.lower(),
            matched_po.supplier.lower()
        )
        supplier_match = supplier_score >= 70
        
        reasoning_parts.append(
            f"Matched PO: {matched_po.po_number}. "
            f"Supplier match: {supplier_match} ({supplier_score:.0f}% similarity). "
            f"Line items matched: {line_items_matched}/{len(extracted_data.line_items)}."
        )
        
        # Store matched PO data for discrepancy detection
        state["matched_po_data"] = matched_po.model_dump()
    else:
        supplier_match = False
    
    # Create matching result
    matching_result = MatchingResult(
        po_match_confidence=confidence,
        matched_po=matched_po.po_number if matched_po else None,
        match_method=match_method,
        supplier_match=supplier_match if matched_po else False,
        line_items_matched=line_items_matched,
        line_items_total=len(extracted_data.line_items),
        match_rate=line_items_matched / len(extracted_data.line_items) if extracted_data.line_items else 0
    )
    
    # Look for alternative matches if confidence is low
    if confidence < 0.80 and matched_po:
        alt_matches = []
        product_matches = po_db.fuzzy_match_products(product_descriptions, threshold=60)
        for po, score, count in product_matches[:3]:
            if po.po_number != matched_po.po_number:
                alt_matches.append({
                    "po_number": po.po_number,
                    "supplier": po.supplier,
                    "confidence": score,
                    "matched_items": count
                })
        if alt_matches:
            matching_result.alternative_matches = alt_matches
            reasoning_parts.append(
                f"Found {len(alt_matches)} alternative PO candidates for human review."
            )
    
    reasoning = " ".join(reasoning_parts)
    
    # Update state
    duration_ms = int((time.time() - start_time) * 1000)
    
    state["matching_results"] = matching_result
    state["matching_reasoning"] = reasoning
    state["agent_traces"] = state.get("agent_traces", {})
    state["agent_traces"]["matching_agent"] = {
        "duration_ms": duration_ms,
        "confidence": confidence,
        "status": "success" if matched_po else "partial",
        "reasoning": reasoning
    }
    state["current_agent"] = "discrepancy_detection"
    
    return state
