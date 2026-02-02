"""FastAPI Dashboard for Invoice Reconciliation System."""

import json
import time
from pathlib import Path
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, File, UploadFile, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from src.core.config import PROVIDEDFILES_DIR, OUTPUT_DIR
from src.core.workflow import run_invoice_processing


# Create FastAPI app
app = FastAPI(
    title="Invoice Reconciliation Dashboard",
    description="Multi-Agent AI System for Invoice Processing",
    version="1.0.0"
)

# Setup templates and static files
DASHBOARD_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(DASHBOARD_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Render the main dashboard."""
    # Load existing results
    results = []
    output_files = list(OUTPUT_DIR.glob("*.json")) if OUTPUT_DIR.exists() else []
    
    for f in sorted(output_files):
        try:
            with open(f) as file:
                data = json.load(file)
                results.append(data)
        except:
            pass
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "results": results,
        "total_invoices": len(results)
    })


@app.get("/api/results")
async def get_results():
    """Get all processing results as JSON."""
    results = []
    output_files = list(OUTPUT_DIR.glob("*.json")) if OUTPUT_DIR.exists() else []
    
    for f in sorted(output_files):
        try:
            with open(f) as file:
                data = json.load(file)
                results.append(data)
        except:
            pass
    
    return {"results": results, "count": len(results)}


@app.get("/api/result/{invoice_id}")
async def get_result(invoice_id: str):
    """Get a specific processing result."""
    output_files = list(OUTPUT_DIR.glob("*.json")) if OUTPUT_DIR.exists() else []
    
    for f in output_files:
        try:
            with open(f) as file:
                data = json.load(file)
                if data.get("invoice_id") == invoice_id:
                    return data
        except:
            pass
    
    raise HTTPException(status_code=404, detail="Invoice not found")


@app.post("/api/process")
async def process_invoice(file: UploadFile = File(...)):
    """Process an uploaded invoice."""
    # Save uploaded file temporarily
    temp_path = PROVIDEDFILES_DIR / f"temp_{file.filename}"
    
    try:
        contents = await file.read()
        with open(temp_path, "wb") as f:
            f.write(contents)
        
        # Process the invoice
        start_time = time.time()
        final_state = run_invoice_processing(str(temp_path))
        processing_time = time.time() - start_time
        
        # Build result
        extracted_data = final_state.get("extracted_data")
        matching_results = final_state.get("matching_results")
        discrepancies = final_state.get("discrepancies", [])
        
        result = {
            "invoice_id": extracted_data.invoice_number if extracted_data else "UNKNOWN",
            "processing_timestamp": datetime.utcnow().isoformat() + "Z",
            "processing_duration_seconds": round(processing_time, 2),
            "document_info": {
                "filename": file.filename,
                "document_quality": final_state.get("document_quality", "unknown")
            },
            "processing_results": {
                "extraction_confidence": final_state.get("extraction_confidence", 0.0),
                "matching_results": matching_results.model_dump() if matching_results else None,
                "discrepancies": [d.model_dump() for d in discrepancies] if discrepancies else [],
                "recommended_action": final_state.get("recommended_action", "escalate_to_human"),
                "risk_level": final_state.get("risk_level", "high")
            },
            "agent_execution_trace": final_state.get("agent_traces", {})
        }
        
        # Save result
        output_file = OUTPUT_DIR / f"{Path(file.filename).stem}.json"
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2, default=str)
        
        return result
        
    finally:
        # Cleanup temp file
        if temp_path.exists():
            temp_path.unlink()


@app.get("/api/stats")
async def get_stats():
    """Get processing statistics."""
    results = []
    output_files = list(OUTPUT_DIR.glob("*.json")) if OUTPUT_DIR.exists() else []
    
    for f in output_files:
        try:
            with open(f) as file:
                data = json.load(file)
                results.append(data)
        except:
            pass
    
    if not results:
        return {
            "total_invoices": 0,
            "auto_approved": 0,
            "flagged_for_review": 0,
            "escalated": 0,
            "avg_processing_time": 0,
            "avg_confidence": 0
        }
    
    actions = [r.get("processing_results", {}).get("recommended_action", "") for r in results]
    times = [r.get("processing_duration_seconds", 0) for r in results]
    confidences = [r.get("processing_results", {}).get("extraction_confidence", 0) for r in results]
    
    return {
        "total_invoices": len(results),
        "auto_approved": actions.count("auto_approve"),
        "flagged_for_review": actions.count("flag_for_review"),
        "escalated": actions.count("escalate_to_human"),
        "avg_processing_time": round(sum(times) / len(times), 2) if times else 0,
        "avg_confidence": round(sum(confidences) / len(confidences) * 100, 1) if confidences else 0
    }


def run_dashboard(host: str = "127.0.0.1", port: int = 8000):
    """Run the dashboard server."""
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_dashboard()
