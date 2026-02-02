"""Discrepancy Detection Agent - Flags price/quantity mismatches with confidence scores."""

import time
from typing import List, Optional
from rapidfuzz import fuzz

from src.core.state import AgentState
from src.core.config import ReconciliationRules
from src.models.schemas import Discrepancy, ExtractedInvoice, MatchingResult


def find_matching_po_item(invoice_item_desc: str, po_items: List[dict], threshold: float = 70) -> Optional[dict]:
    """Find the best matching PO line item for an invoice line item."""
    best_match = None
    best_score = 0
    
    for po_item in po_items:
        score = fuzz.token_sort_ratio(
            invoice_item_desc.lower(),
            po_item.get("description", "").lower()
        )
        if score > best_score and score >= threshold:
            best_score = score
            best_match = po_item
    
    return best_match


def discrepancy_detection_agent(state: AgentState) -> AgentState:
    """
    Discrepancy Detection Agent node for LangGraph.
    Identifies price, quantity, and total variances between invoice and PO.
    """
    start_time = time.time()
    
    extracted_data: Optional[ExtractedInvoice] = state.get("extracted_data")
    matching_results: Optional[MatchingResult] = state.get("matching_results")
    matched_po_data: Optional[dict] = state.get("matched_po_data")
    
    discrepancies: List[Discrepancy] = []
    reasoning_parts = []
    
    # Check if we have data to compare
    if extracted_data is None:
        reasoning = "No extracted invoice data available for discrepancy detection."
        state["discrepancies"] = discrepancies
        state["discrepancy_reasoning"] = reasoning
        duration_ms = int((time.time() - start_time) * 1000)
        state["agent_traces"] = state.get("agent_traces", {})
        state["agent_traces"]["discrepancy_detection_agent"] = {
            "duration_ms": duration_ms,
            "confidence": 0.0,
            "status": "failed",
            "reasoning": reasoning
        }
        return state
    
    # Check for missing PO reference
    if not extracted_data.po_reference:
        severity = "medium"
        if matching_results and matching_results.matched_po:
            details = (
                f"Invoice does not contain a PO reference. "
                f"Fuzzy matching by supplier and products suggests {matching_results.matched_po} "
                f"({matching_results.po_match_confidence:.0%} confidence)."
            )
        else:
            severity = "high"
            details = "Invoice does not contain a PO reference and could not be matched to any PO."
        
        discrepancies.append(Discrepancy(
            type="missing_po_reference",
            severity=severity,
            field="po_reference",
            details=details,
            recommended_action="flag_for_review" if matching_results and matching_results.matched_po else "escalate_to_human",
            confidence=0.95
        ))
        reasoning_parts.append(f"Missing PO reference detected (severity: {severity}).")
    
    # If no matched PO, we can't do detailed comparison
    if matched_po_data is None:
        reasoning = " ".join(reasoning_parts) if reasoning_parts else "No matched PO for detailed comparison."
        state["discrepancies"] = discrepancies
        state["discrepancy_reasoning"] = reasoning
        duration_ms = int((time.time() - start_time) * 1000)
        state["agent_traces"] = state.get("agent_traces", {})
        state["agent_traces"]["discrepancy_detection_agent"] = {
            "duration_ms": duration_ms,
            "confidence": 0.80,
            "status": "partial",
            "reasoning": reasoning
        }
        state["current_agent"] = "resolution"
        return state
    
    po_items = matched_po_data.get("line_items", [])
    po_total = matched_po_data.get("total", 0)
    
    # Compare each invoice line item to PO
    for idx, invoice_item in enumerate(extracted_data.line_items):
        matched_po_item = find_matching_po_item(invoice_item.description, po_items)
        
        if matched_po_item is None:
            # Extra item on invoice not in PO
            discrepancies.append(Discrepancy(
                type="extra_item",
                severity="medium",
                line_item_index=idx,
                field="description",
                details=f"Line item '{invoice_item.description}' not found in matched PO.",
                recommended_action="flag_for_review",
                confidence=0.85
            ))
            reasoning_parts.append(f"Extra item detected: '{invoice_item.description}'.")
            continue
        
        # Check price variance
        invoice_price = invoice_item.unit_price
        po_price = matched_po_item.get("unit_price", 0)
        
        if po_price > 0:
            price_variance = (invoice_price - po_price) / po_price
            price_variance_pct = abs(price_variance * 100)
            
            if abs(price_variance) > ReconciliationRules.PRICE_VARIANCE_ESCALATE:
                # Major price discrepancy (>15%)
                discrepancies.append(Discrepancy(
                    type="price_mismatch",
                    severity="high",
                    line_item_index=idx,
                    field="unit_price",
                    invoice_value=invoice_price,
                    po_value=po_price,
                    variance_percentage=round(price_variance * 100, 2),
                    details=f"Line item '{invoice_item.description}': Invoice unit price £{invoice_price:.2f} "
                            f"vs PO price £{po_price:.2f} ({price_variance_pct:.1f}% {'increase' if price_variance > 0 else 'decrease'})",
                    recommended_action="escalate_to_human",
                    confidence=0.99
                ))
                reasoning_parts.append(
                    f"CRITICAL: {price_variance_pct:.1f}% price variance on '{invoice_item.description}'."
                )
            elif abs(price_variance) > ReconciliationRules.PRICE_VARIANCE_AUTO_APPROVE:
                # Moderate price discrepancy (>2% but ≤15%)
                severity = "high" if abs(price_variance) > 0.05 else "medium"
                discrepancies.append(Discrepancy(
                    type="price_mismatch",
                    severity=severity,
                    line_item_index=idx,
                    field="unit_price",
                    invoice_value=invoice_price,
                    po_value=po_price,
                    variance_percentage=round(price_variance * 100, 2),
                    details=f"Line item '{invoice_item.description}': Invoice unit price £{invoice_price:.2f} "
                            f"vs PO price £{po_price:.2f} ({price_variance_pct:.1f}% {'increase' if price_variance > 0 else 'decrease'})",
                    recommended_action="flag_for_review",
                    confidence=0.99
                ))
                reasoning_parts.append(
                    f"Price variance detected: {price_variance_pct:.1f}% on '{invoice_item.description}'."
                )
        
        # Check quantity variance
        invoice_qty = invoice_item.quantity
        po_qty = matched_po_item.get("quantity", 0)
        
        if po_qty > 0 and invoice_qty != po_qty:
            qty_variance = (invoice_qty - po_qty) / po_qty
            discrepancies.append(Discrepancy(
                type="quantity_mismatch",
                severity="medium" if abs(qty_variance) <= 0.10 else "high",
                line_item_index=idx,
                field="quantity",
                invoice_value=invoice_qty,
                po_value=po_qty,
                variance_percentage=round(qty_variance * 100, 2),
                details=f"Line item '{invoice_item.description}': Invoice quantity {invoice_qty} "
                        f"vs PO quantity {po_qty}",
                recommended_action="flag_for_review",
                confidence=0.98
            ))
            reasoning_parts.append(f"Quantity mismatch on '{invoice_item.description}'.")
    
    # Check total variance
    invoice_total = extracted_data.total
    if po_total > 0:
        total_variance = invoice_total - po_total
        total_variance_pct = abs(total_variance / po_total) * 100
        
        # Check if within tolerance
        within_amount_tolerance = abs(total_variance) <= ReconciliationRules.TOTAL_VARIANCE_AMOUNT
        within_pct_tolerance = abs(total_variance / po_total) <= ReconciliationRules.TOTAL_VARIANCE_PERCENT
        
        if not (within_amount_tolerance or within_pct_tolerance):
            severity = "high" if total_variance_pct > 10 else "medium"
            discrepancies.append(Discrepancy(
                type="total_variance",
                severity=severity,
                field="total",
                invoice_value=invoice_total,
                po_value=po_total,
                variance_percentage=round(total_variance_pct, 2),
                details=f"Invoice total £{invoice_total:.2f} vs PO total £{po_total:.2f} "
                        f"(variance: £{total_variance:.2f}, {total_variance_pct:.1f}%)",
                recommended_action="flag_for_review" if severity == "medium" else "escalate_to_human",
                confidence=0.99
            ))
            reasoning_parts.append(f"Total variance: £{total_variance:.2f} ({total_variance_pct:.1f}%).")
    
    # Build final reasoning
    if not discrepancies:
        reasoning = "No discrepancies detected. All line items match PO prices and quantities within tolerance."
    else:
        reasoning = f"Detected {len(discrepancies)} discrepancies. " + " ".join(reasoning_parts)
    
    # Update state
    duration_ms = int((time.time() - start_time) * 1000)
    
    state["discrepancies"] = discrepancies
    state["discrepancy_reasoning"] = reasoning
    state["agent_traces"] = state.get("agent_traces", {})
    state["agent_traces"]["discrepancy_detection_agent"] = {
        "duration_ms": duration_ms,
        "confidence": 0.95,
        "status": "success",
        "reasoning": reasoning
    }
    state["current_agent"] = "resolution"
    
    return state
