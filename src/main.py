#!/usr/bin/env python3
"""
Multi-Agent Invoice Reconciliation System
Main entry point for processing invoices.

Usage:
    python src/main.py --process-all                    # Process all 5 test invoices
    python src/main.py --invoice <path>                 # Process single invoice
    python src/main.py --demo                           # Run demo mode with visualization
"""

import argparse
import json
import time
import sys
from pathlib import Path
from datetime import datetime

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import print as rprint

from src.core.config import PROVIDEDFILES_DIR, OUTPUT_DIR, GOOGLE_API_KEY
from src.core.workflow import run_invoice_processing
from src.models.schemas import ReconciliationResult


console = Console()


def format_result_to_json(state: dict, invoice_path: Path, processing_time: float) -> dict:
    """Convert workflow state to expected output JSON format."""
    extracted_data = state.get("extracted_data")
    matching_results = state.get("matching_results")
    discrepancies = state.get("discrepancies", [])
    
    # Build final output matching expected schema
    output = {
        "invoice_id": extracted_data.invoice_number if extracted_data else "UNKNOWN",
        "processing_timestamp": datetime.utcnow().isoformat() + "Z",
        "processing_duration_seconds": round(processing_time, 2),
        "document_info": {
            "filename": invoice_path.name,
            "file_size_kb": round(invoice_path.stat().st_size / 1024, 1),
            "document_quality": state.get("document_quality", "unknown")
        },
        "processing_results": {
            "extraction_confidence": state.get("extraction_confidence", 0.0),
            "document_quality": state.get("document_quality", "unknown"),
            "extracted_data": extracted_data.model_dump() if extracted_data else None,
            "matching_results": matching_results.model_dump() if matching_results else None,
            "discrepancies": [d.model_dump() for d in discrepancies] if discrepancies else [],
            "total_variance": calculate_total_variance(state),
            "recommended_action": state.get("recommended_action", "escalate_to_human"),
            "risk_level": state.get("risk_level", "high"),
            "confidence": calculate_overall_confidence(state),
            "agent_reasoning": build_agent_reasoning(state)
        },
        "agent_execution_trace": state.get("agent_traces", {}),
        "human_review_feedback": state.get("review_feedback")
    }
    
    return output


def calculate_total_variance(state: dict) -> dict:
    """Calculate total variance between invoice and PO."""
    extracted_data = state.get("extracted_data")
    matched_po_data = state.get("matched_po_data")
    
    if not extracted_data or not matched_po_data:
        return {"amount": 0, "percentage": 0, "within_tolerance": True}
    
    invoice_total = extracted_data.total
    po_total = matched_po_data.get("total", 0)
    
    if po_total == 0:
        return {"amount": 0, "percentage": 0, "within_tolerance": True}
    
    variance = invoice_total - po_total
    variance_pct = (variance / po_total) * 100
    within_tolerance = abs(variance) <= 5 or abs(variance_pct) <= 1
    
    return {
        "amount": round(variance, 2),
        "percentage": round(variance_pct, 2),
        "within_tolerance": within_tolerance
    }


def calculate_overall_confidence(state: dict) -> float:
    """Calculate overall processing confidence."""
    extraction_conf = state.get("extraction_confidence", 0.0)
    matching_results = state.get("matching_results")
    match_conf = matching_results.po_match_confidence if matching_results else 0.0
    
    # Weighted average
    overall = (extraction_conf * 0.4 + match_conf * 0.6)
    return round(overall, 2)


def build_agent_reasoning(state: dict) -> str:
    """Build comprehensive agent reasoning from all agents."""
    parts = []
    
    # Extraction reasoning
    if state.get("extraction_reasoning"):
        parts.append(state["extraction_reasoning"])
    
    # Matching reasoning
    if state.get("matching_reasoning"):
        parts.append(state["matching_reasoning"])
    
    # Discrepancy reasoning
    if state.get("discrepancy_reasoning"):
        parts.append(state["discrepancy_reasoning"])
    
    # Resolution reasoning
    if state.get("resolution_reasoning"):
        parts.append(state["resolution_reasoning"])
    
    # Human review feedback
    if state.get("review_feedback"):
        parts.append(f"Human Reviewer: {state['review_feedback']}")
    
    return " ".join(parts)


def process_invoice(invoice_path: Path, show_progress: bool = True) -> dict:
    """Process a single invoice and return results."""
    start_time = time.time()
    
    if show_progress:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task(f"Processing {invoice_path.name}...", total=None)
            
            # Run the workflow
            final_state = run_invoice_processing(str(invoice_path))
            
            progress.update(task, completed=True)
    else:
        final_state = run_invoice_processing(str(invoice_path))
    
    processing_time = time.time() - start_time
    
    # Format to expected output
    result = format_result_to_json(final_state, invoice_path, processing_time)
    
    return result


def display_result_summary(result: dict):
    """Display a nice summary of the processing result."""
    proc_results = result.get("processing_results", {})
    
    # Action color coding
    action = proc_results.get("recommended_action", "unknown")
    action_colors = {
        "auto_approve": "green",
        "flag_for_review": "yellow",
        "escalate_to_human": "red"
    }
    action_color = action_colors.get(action, "white")
    
    # Create summary table
    table = Table(title=f"Invoice: {result.get('invoice_id', 'Unknown')}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white")
    
    table.add_row("Document Quality", proc_results.get("document_quality", "N/A"))
    table.add_row("Extraction Confidence", f"{proc_results.get('extraction_confidence', 0):.0%}")
    
    matching = proc_results.get("matching_results", {})
    if matching:
        table.add_row("Matched PO", matching.get("matched_po", "None"))
        table.add_row("Match Confidence", f"{matching.get('po_match_confidence', 0):.0%}")
        table.add_row("Match Method", matching.get("match_method", "N/A").replace("_", " "))
    
    discrepancies = proc_results.get("discrepancies", [])
    table.add_row("Discrepancies Found", str(len(discrepancies)))
    
    table.add_row(
        "Recommended Action", 
        f"[{action_color}]{action.upper().replace('_', ' ')}[/{action_color}]"
    )
    table.add_row("Processing Time", f"{result.get('processing_duration_seconds', 0):.2f}s")
    
    console.print(table)
    
    # Show discrepancies if any
    if discrepancies:
        console.print("\n[yellow]Discrepancies:[/yellow]")
        for d in discrepancies:
            console.print(f"  • [{d.get('severity', 'medium')}] {d.get('details', 'No details')}")


def process_all_invoices():
    """Process all 5 test invoices."""
    invoice_files = [
        PROVIDEDFILES_DIR / "Invoice_1_Baseline.pdf",
        PROVIDEDFILES_DIR / "Invoice_2_Scanned.pdf",
        PROVIDEDFILES_DIR / "Invoice_3_Different_Format.pdf",
        PROVIDEDFILES_DIR / "Invoice_4_Price_Trap.pdf",
        PROVIDEDFILES_DIR / "Invoice_5_Missing_PO.pdf"
    ]
    
    console.print(Panel.fit(
        "[bold blue]Multi-Agent Invoice Reconciliation System[/bold blue]\n"
        "Processing 5 test invoices...",
        title="🚀 Starting"
    ))
    
    total_start = time.time()
    results = []
    
    for invoice_path in invoice_files:
        if not invoice_path.exists():
            console.print(f"[red]ERROR: {invoice_path.name} not found![/red]")
            continue
        
        console.print(f"\n[cyan]━━━ Processing: {invoice_path.name} ━━━[/cyan]")
        
        result = process_invoice(invoice_path)
        results.append(result)
        
        # Save individual result
        output_file = OUTPUT_DIR / f"{invoice_path.stem}.json"
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2, default=str)
        
        display_result_summary(result)
        console.print(f"[green]✓ Saved to: {output_file}[/green]")
    
    total_time = time.time() - total_start
    
    # Final summary
    console.print(Panel.fit(
        f"[bold green]Processing Complete![/bold green]\n\n"
        f"Total Invoices: {len(results)}\n"
        f"Total Time: {total_time:.2f} seconds\n"
        f"Target: <300 seconds ({'✓ PASS' if total_time < 300 else '✗ FAIL'})\n\n"
        f"Results saved to: {OUTPUT_DIR}",
        title="📊 Summary"
    ))
    
    # Check critical tests
    console.print("\n[bold]Critical Test Results:[/bold]")
    
    # Invoice 4 - Price Trap
    inv4_result = next((r for r in results if "Invoice_4" in r.get("document_info", {}).get("filename", "")), None)
    if inv4_result:
        discrepancies = inv4_result.get("processing_results", {}).get("discrepancies", [])
        price_issue = any(d.get("type") == "price_mismatch" for d in discrepancies)
        console.print(f"  Invoice 4 (Price Trap): {'[green]✓ DETECTED[/green]' if price_issue else '[red]✗ MISSED[/red]'}")
    
    # Invoice 5 - Missing PO
    inv5_result = next((r for r in results if "Invoice_5" in r.get("document_info", {}).get("filename", "")), None)
    if inv5_result:
        matching = inv5_result.get("processing_results", {}).get("matching_results", {})
        matched_po = matching.get("matched_po", "")
        console.print(f"  Invoice 5 (Missing PO): {'[green]✓ Matched to ' + matched_po + '[/green]' if matched_po else '[red]✗ NO MATCH[/red]'}")
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Multi-Agent Invoice Reconciliation System"
    )
    parser.add_argument(
        "--process-all", 
        action="store_true", 
        help="Process all 5 test invoices"
    )
    parser.add_argument(
        "--invoice", 
        type=str, 
        help="Path to a single invoice to process"
    )
    parser.add_argument(
        "--output", 
        type=str, 
        default=str(OUTPUT_DIR),
        help="Output directory for results"
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run in demo mode with extra visualization"
    )
    
    args = parser.parse_args()
    
    # Check API key
    if not GOOGLE_API_KEY:
        console.print("[red]ERROR: GOOGLE_API_KEY environment variable not set![/red]")
        console.print("Please set it with: export GOOGLE_API_KEY=your_api_key")
        sys.exit(1)
    
    if args.process_all or args.demo:
        process_all_invoices()
    elif args.invoice:
        invoice_path = Path(args.invoice)
        if not invoice_path.exists():
            console.print(f"[red]ERROR: Invoice file not found: {invoice_path}[/red]")
            sys.exit(1)
        
        result = process_invoice(invoice_path)
        display_result_summary(result)
        
        # Save result
        output_file = Path(args.output) / f"{invoice_path.stem}.json"
        output_file.parent.mkdir(exist_ok=True)
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2, default=str)
        console.print(f"[green]✓ Saved to: {output_file}[/green]")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
