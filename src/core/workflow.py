"""LangGraph workflow for invoice reconciliation multi-agent system."""

import time
from typing import Literal
from langgraph.graph import StateGraph, END

from src.core.state import AgentState
from src.agents.document_intelligence import document_intelligence_agent
from src.agents.matching_agent import matching_agent
from src.agents.discrepancy_detection import discrepancy_detection_agent
from src.agents.resolution_agent import resolution_agent
from src.agents.human_reviewer import human_reviewer_agent


def should_continue_to_matching(state: AgentState) -> Literal["matching", "error"]:
    """Determine if we should continue to matching or handle error."""
    if state.get("extracted_data") is None:
        return "error"
    return "matching"


def should_continue_to_discrepancy(state: AgentState) -> Literal["discrepancy", "error"]:
    """Determine if we should continue to discrepancy detection."""
    # Always continue even without match - we'll report no match as an issue
    return "discrepancy"


def should_run_human_review(state: AgentState) -> Literal["human_review", "complete"]:
    """Determine if human review agent should be invoked."""
    recommendation = state.get("recommended_action", "")
    # Only run human review for flagged or escalated invoices
    if recommendation in ["flag_for_review", "escalate_to_human"]:
        return "human_review"
    return "complete"


def error_handler(state: AgentState) -> AgentState:
    """Handle errors in the workflow."""
    errors = state.get("errors", [])
    state["recommended_action"] = "escalate_to_human"
    state["resolution_reasoning"] = (
        f"Processing failed with errors: {'; '.join(errors)}. "
        "Manual review required."
    )
    state["risk_level"] = "high"
    return state


def create_workflow() -> StateGraph:
    """Create the LangGraph workflow for invoice processing."""
    
    # Initialize the graph with our state type
    workflow = StateGraph(AgentState)
    
    # Add nodes for each agent
    workflow.add_node("document_intelligence", document_intelligence_agent)
    workflow.add_node("matching", matching_agent)
    workflow.add_node("discrepancy_detection", discrepancy_detection_agent)
    workflow.add_node("resolution", resolution_agent)
    workflow.add_node("human_review", human_reviewer_agent)
    workflow.add_node("error_handler", error_handler)
    
    # Set the entry point
    workflow.set_entry_point("document_intelligence")
    
    # Add conditional edges for intelligent routing
    workflow.add_conditional_edges(
        "document_intelligence",
        should_continue_to_matching,
        {
            "matching": "matching",
            "error": "error_handler"
        }
    )
    
    workflow.add_conditional_edges(
        "matching",
        should_continue_to_discrepancy,
        {
            "discrepancy": "discrepancy_detection",
            "error": "error_handler"
        }
    )
    
    # Discrepancy detection always goes to resolution
    workflow.add_edge("discrepancy_detection", "resolution")
    
    # Resolution conditionally goes to human review or ends
    workflow.add_conditional_edges(
        "resolution",
        should_run_human_review,
        {
            "human_review": "human_review",
            "complete": END
        }
    )
    
    # Human review ends the workflow
    workflow.add_edge("human_review", END)
    
    # Error handler ends the workflow
    workflow.add_edge("error_handler", END)
    
    return workflow


def compile_workflow():
    """Compile and return the workflow."""
    workflow = create_workflow()
    return workflow.compile()


def run_invoice_processing(invoice_path: str, po_database: list = None) -> dict:
    """
    Run the complete invoice processing workflow.
    
    Args:
        invoice_path: Path to the invoice PDF/image
        po_database: Optional pre-loaded PO database
        
    Returns:
        Final state dict with all processing results
    """
    from src.utils.po_database import PODatabase
    
    # Initialize state
    initial_state: AgentState = {
        "invoice_path": invoice_path,
        "po_database": po_database or PODatabase().to_dict_list(),
        "errors": [],
        "agent_traces": {},
        "processing_start_time": time.time(),
        "discrepancies": [],
        "needs_reprocessing": False
    }
    
    # Compile and run workflow
    app = compile_workflow()
    
    # Run the workflow
    final_state = app.invoke(initial_state)
    
    return final_state
