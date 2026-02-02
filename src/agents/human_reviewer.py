"""Human Reviewer Agent - BONUS: Simulates feedback loop for iterative improvement."""

import time
from typing import Optional
import google.generativeai as genai

from src.core.state import AgentState
from src.core.config import GOOGLE_API_KEY, GEMINI_MODEL
from src.models.schemas import ExtractedInvoice


# Configure Gemini
genai.configure(api_key=GOOGLE_API_KEY)


REVIEW_PROMPT = """You are a Human Reviewer Agent simulating an experienced accounts payable specialist reviewing an invoice reconciliation result.

Review the following processed invoice and provide feedback:

INVOICE DATA:
{invoice_data}

MATCHED PO:
{matched_po}

DISCREPANCIES FOUND:
{discrepancies}

CURRENT RECOMMENDATION: {recommendation}

YOUR TASK:
1. Identify any obvious OCR/extraction errors (e.g., prices that look wrong, descriptions that seem incomplete)
2. Check if the matching logic makes sense
3. Evaluate if the recommendation is appropriate

Respond in JSON format:
{{
    "approval_status": "approved" | "needs_correction" | "rejected",
    "corrections": [
        {{
            "field": "field_name",
            "current_value": "value",
            "suggested_value": "corrected_value",
            "reason": "why this correction is needed"
        }}
    ],
    "feedback": "Overall feedback about the processing quality",
    "confidence": 0.0-1.0
}}

If everything looks correct, return:
{{
    "approval_status": "approved",
    "corrections": [],
    "feedback": "Processing appears accurate and recommendation is appropriate.",
    "confidence": 0.95
}}

Return ONLY the JSON object."""


def human_reviewer_agent(state: AgentState) -> AgentState:
    """
    Human Reviewer Agent node for LangGraph.
    BONUS: Simulates human review feedback loop for iterative improvement.
    """
    start_time = time.time()
    
    extracted_data: Optional[ExtractedInvoice] = state.get("extracted_data")
    matched_po_data = state.get("matched_po_data")
    discrepancies = state.get("discrepancies", [])
    recommendation = state.get("recommended_action", "unknown")
    
    # Only review if flagged or escalated
    if recommendation == "auto_approve":
        # Skip review for auto-approved invoices
        state["review_feedback"] = "Auto-approved invoices do not require human review simulation."
        state["needs_reprocessing"] = False
        duration_ms = int((time.time() - start_time) * 1000)
        state["agent_traces"] = state.get("agent_traces", {})
        state["agent_traces"]["human_reviewer_agent"] = {
            "duration_ms": duration_ms,
            "confidence": 1.0,
            "status": "skipped",
            "reasoning": "Auto-approved invoice, no review needed"
        }
        return state
    
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        
        # Prepare data for review
        invoice_str = extracted_data.model_dump_json(indent=2) if extracted_data else "No data"
        po_str = str(matched_po_data) if matched_po_data else "No matched PO"
        discrepancy_str = "\n".join([d.details for d in discrepancies]) if discrepancies else "None"
        
        prompt = REVIEW_PROMPT.format(
            invoice_data=invoice_str,
            matched_po=po_str,
            discrepancies=discrepancy_str,
            recommendation=recommendation
        )
        
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        # Clean up response
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1])
        
        import json
        review_result = json.loads(response_text)
        
        approval_status = review_result.get("approval_status", "approved")
        corrections = review_result.get("corrections", [])
        feedback = review_result.get("feedback", "")
        review_confidence = review_result.get("confidence", 0.90)
        
        state["review_feedback"] = feedback
        state["corrections"] = corrections if corrections else None
        state["needs_reprocessing"] = approval_status == "needs_correction" and len(corrections) > 0
        
        reasoning = f"Human Reviewer simulation: {approval_status}. {feedback}"
        if corrections:
            reasoning += f" Suggested {len(corrections)} corrections."
        
    except Exception as e:
        # Handle errors gracefully
        state["review_feedback"] = f"Human review simulation failed: {str(e)}"
        state["needs_reprocessing"] = False
        reasoning = f"Review simulation error: {str(e)}"
        review_confidence = 0.5
    
    duration_ms = int((time.time() - start_time) * 1000)
    state["agent_traces"] = state.get("agent_traces", {})
    state["agent_traces"]["human_reviewer_agent"] = {
        "duration_ms": duration_ms,
        "confidence": review_confidence,
        "status": "success",
        "reasoning": reasoning
    }
    
    return state
