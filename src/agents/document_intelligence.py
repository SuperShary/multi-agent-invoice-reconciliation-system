"""Document Intelligence Agent - Extracts structured data from invoice PDFs."""

import time
import base64
import json
from pathlib import Path
from typing import Tuple, Optional
import google.generativeai as genai

from src.core.config import GOOGLE_API_KEY, GEMINI_MODEL
from src.core.state import AgentState
from src.models.schemas import ExtractedInvoice, LineItem


# Configure Gemini
genai.configure(api_key=GOOGLE_API_KEY)


EXTRACTION_PROMPT = """You are an expert invoice data extraction agent. Extract all structured data from this invoice image/document.

IMPORTANT: Extract EXACTLY what you see. Do not make up or assume values.

Return a JSON object with this exact structure:
{
    "invoice_number": "string",
    "invoice_date": "YYYY-MM-DD format",
    "supplier_name": "string",
    "supplier_address": "string or null",
    "supplier_vat": "string or null",
    "po_reference": "string or null (the Purchase Order reference if present)",
    "payment_terms": "string or null",
    "bill_to": {"company": "string", "address": "string"} or null,
    "line_items": [
        {
            "item_code": "string or null",
            "description": "string (product name/description)",
            "quantity": number,
            "unit": "string (kg, L, units, etc.)",
            "unit_price": number,
            "line_total": number
        }
    ],
    "subtotal": number,
    "vat_rate": number (as decimal, e.g., 0.20 for 20%),
    "vat_amount": number,
    "total": number,
    "currency": "string (GBP, EUR, USD, etc.)"
}

CRITICAL RULES:
1. If a field is not visible or unclear, use null
2. Extract ALL line items from the invoice table
3. Prices should be numeric values only (no currency symbols)
4. Dates should be in YYYY-MM-DD format
5. If PO reference exists, extract it exactly as shown (e.g., "PO-2024-001")

Return ONLY the JSON object, no additional text or markdown formatting."""


def get_mime_type(file_path: Path) -> str:
    """Get MIME type based on file extension."""
    suffix = file_path.suffix.lower()
    mime_types = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp"
    }
    return mime_types.get(suffix, "application/pdf")


def assess_document_quality(confidence: float, extracted_data: dict) -> str:
    """Assess overall document quality based on extraction results."""
    critical_fields = ["invoice_number", "supplier_name", "line_items", "total"]
    missing_critical = sum(1 for f in critical_fields if not extracted_data.get(f))
    
    if missing_critical == 0 and confidence >= 0.90:
        return "excellent"
    elif missing_critical <= 1 and confidence >= 0.75:
        return "good"
    elif missing_critical <= 2 and confidence >= 0.60:
        return "acceptable"
    else:
        return "poor"


def extract_with_gemini(file_path: Path, max_retries: int = 3) -> Tuple[Optional[dict], float, str]:
    """
    Extract invoice data using Gemini Vision with retry logic.
    Returns: (extracted_data_dict, confidence, reasoning)
    """
    for attempt in range(max_retries):
        try:
            # Upload the file using Gemini File API
            uploaded_file = genai.upload_file(str(file_path))
            
            # Wait for file to be processed
            while uploaded_file.state.name == "PROCESSING":
                time.sleep(1)
                uploaded_file = genai.get_file(uploaded_file.name)
            
            model = genai.GenerativeModel(GEMINI_MODEL)
            
            # Generate content with the uploaded file
            response = model.generate_content([
                EXTRACTION_PROMPT,
                uploaded_file
            ])
            
            # Clean up uploaded file
            try:
                genai.delete_file(uploaded_file.name)
            except:
                pass
            
            # Parse the response
            response_text = response.text.strip()
            
            # Clean up response if it has markdown code blocks
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                # Find the closing ``` and remove both
                if lines[-1].strip() == "```":
                    response_text = "\n".join(lines[1:-1])
                else:
                    response_text = "\n".join(lines[1:])
            
            # Also handle ```json prefix
            if response_text.startswith("json"):
                response_text = response_text[4:].strip()
            
            extracted_data = json.loads(response_text)
            
            # Calculate confidence based on extracted fields
            total_fields = 12
            present_fields = sum(1 for v in [
                extracted_data.get("invoice_number"),
                extracted_data.get("invoice_date"),
                extracted_data.get("supplier_name"),
                extracted_data.get("po_reference"),
                extracted_data.get("line_items"),
                extracted_data.get("subtotal"),
                extracted_data.get("vat_amount"),
                extracted_data.get("total"),
                extracted_data.get("currency"),
                extracted_data.get("payment_terms"),
                extracted_data.get("supplier_address"),
                extracted_data.get("bill_to")
            ] if v is not None and v != "" and v != [])
            
            # Base confidence from field presence
            confidence = 0.70 + (present_fields / total_fields) * 0.25
            
            # Boost confidence if critical fields are present
            if all([
                extracted_data.get("invoice_number"),
                extracted_data.get("supplier_name"),
                extracted_data.get("line_items"),
                extracted_data.get("total")
            ]):
                confidence = min(confidence + 0.05, 0.98)
            
            reasoning = f"Successfully extracted invoice data using Gemini Vision. Found {len(extracted_data.get('line_items', []))} line items. "
            reasoning += f"Critical fields present: invoice_number={bool(extracted_data.get('invoice_number'))}, "
            reasoning += f"supplier={bool(extracted_data.get('supplier_name'))}, "
            reasoning += f"PO_ref={bool(extracted_data.get('po_reference'))}, "
            reasoning += f"total={bool(extracted_data.get('total'))}."
            
            return extracted_data, confidence, reasoning
            
        except json.JSONDecodeError as e:
            return None, 0.0, f"Failed to parse Gemini response as JSON: {str(e)}"
        except Exception as e:
            error_msg = str(e)
            # Check if it's a rate limit error
            if "429" in error_msg or "quota" in error_msg.lower() or "rate" in error_msg.lower():
                if attempt < max_retries - 1:
                    # Wait and retry with exponential backoff
                    wait_time = (attempt + 1) * 30  # 30s, 60s, 90s
                    print(f"Rate limited, waiting {wait_time}s before retry {attempt + 2}/{max_retries}...")
                    time.sleep(wait_time)
                    continue
            return None, 0.0, f"Gemini extraction failed: {error_msg}"
    
    return None, 0.0, "Extraction failed after all retries"


def dict_to_extracted_invoice(data: dict) -> ExtractedInvoice:
    """Convert extracted dict to Pydantic model."""
    line_items = []
    for item in data.get("line_items", []):
        line_items.append(LineItem(
            item_code=item.get("item_code"),
            description=item.get("description", "Unknown"),
            quantity=float(item.get("quantity", 0)),
            unit=item.get("unit", "kg"),
            unit_price=float(item.get("unit_price", 0)),
            line_total=float(item.get("line_total", 0)),
            extraction_confidence=0.95
        ))
    
    return ExtractedInvoice(
        invoice_number=data.get("invoice_number", "UNKNOWN"),
        invoice_date=data.get("invoice_date", ""),
        supplier_name=data.get("supplier_name", "Unknown Supplier"),
        supplier_address=data.get("supplier_address"),
        supplier_vat=data.get("supplier_vat"),
        po_reference=data.get("po_reference"),
        payment_terms=data.get("payment_terms"),
        bill_to=data.get("bill_to"),
        line_items=line_items,
        subtotal=float(data.get("subtotal", 0)),
        vat_rate=float(data.get("vat_rate", 0.20)),
        vat_amount=float(data.get("vat_amount", 0)),
        total=float(data.get("total", 0)),
        currency=data.get("currency", "GBP")
    )


def document_intelligence_agent(state: AgentState) -> AgentState:
    """
    Document Intelligence Agent node for LangGraph.
    Extracts structured data from invoice PDF/image.
    """
    start_time = time.time()
    
    invoice_path = Path(state["invoice_path"])
    
    # Extract using Gemini with retry logic
    extracted_dict, confidence, reasoning = extract_with_gemini(invoice_path)
    
    if extracted_dict is None:
        # Extraction failed
        duration_ms = int((time.time() - start_time) * 1000)
        state["errors"] = state.get("errors", []) + [reasoning]
        state["extraction_confidence"] = 0.0
        state["document_quality"] = "poor"
        state["extraction_reasoning"] = reasoning
        state["agent_traces"] = state.get("agent_traces", {})
        state["agent_traces"]["document_intelligence_agent"] = {
            "duration_ms": duration_ms,
            "confidence": 0.0,
            "status": "failed",
            "reasoning": reasoning
        }
        return state
    
    # Convert to Pydantic model
    extracted_invoice = dict_to_extracted_invoice(extracted_dict)
    document_quality = assess_document_quality(confidence, extracted_dict)
    
    # Update state
    duration_ms = int((time.time() - start_time) * 1000)
    
    state["extracted_data"] = extracted_invoice
    state["extraction_confidence"] = confidence
    state["document_quality"] = document_quality
    state["extraction_reasoning"] = reasoning
    state["agent_traces"] = state.get("agent_traces", {})
    state["agent_traces"]["document_intelligence_agent"] = {
        "duration_ms": duration_ms,
        "confidence": confidence,
        "status": "success",
        "reasoning": reasoning
    }
    state["current_agent"] = "matching"
    
    return state
