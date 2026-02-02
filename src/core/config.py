"""Configuration for the multi-agent invoice reconciliation system."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# API Configuration
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = "gemini-flash-latest"

# Paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
PROVIDEDFILES_DIR = PROJECT_ROOT / "providedfiles"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

# PO Database
PO_DATABASE_PATH = PROVIDEDFILES_DIR / "purchase_orders.json"

# Reconciliation Rules (from Reconciliation_Rules.md)
class ReconciliationRules:
    """Thresholds and rules for invoice reconciliation."""
    
    # Price variance thresholds
    PRICE_VARIANCE_AUTO_APPROVE = 0.02  # ±2%
    PRICE_VARIANCE_FLAG_REVIEW = 0.15   # ≤15%
    PRICE_VARIANCE_ESCALATE = 0.15      # >15%
    
    # Total variance thresholds
    TOTAL_VARIANCE_AMOUNT = 5.0         # £5
    TOTAL_VARIANCE_PERCENT = 0.01       # 1%
    
    # Confidence thresholds
    CONFIDENCE_AUTO_APPROVE = 0.90      # ≥90%
    CONFIDENCE_FLAG_REVIEW_MIN = 0.70   # 70-89%
    CONFIDENCE_ESCALATE = 0.70          # <70%
    
    # Matching thresholds
    PO_MATCH_EXACT_CONFIDENCE = 0.95
    FUZZY_MATCH_SUPPLIER_MIN = 0.70
    FUZZY_MATCH_PRODUCT_MIN = 0.80
    
    # Date matching
    DATE_VARIANCE_DAYS = 14

# Agent names for tracing
AGENT_NAMES = {
    "document_intelligence": "Document Intelligence Agent",
    "matching": "Matching Agent",
    "discrepancy_detection": "Discrepancy Detection Agent",
    "resolution": "Resolution Agent",
    "human_reviewer": "Human Reviewer Agent"
}
