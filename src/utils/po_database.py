"""Purchase Order database utilities."""

import json
from typing import List, Optional, Tuple
from pathlib import Path
from rapidfuzz import fuzz, process
from src.core.config import PO_DATABASE_PATH
from src.models.schemas import PurchaseOrder, LineItem


class PODatabase:
    """Purchase Order database with fuzzy search capabilities."""
    
    def __init__(self, db_path: Path = PO_DATABASE_PATH):
        self.db_path = db_path
        self.purchase_orders: List[PurchaseOrder] = []
        self._load_database()
    
    def _load_database(self):
        """Load PO database from JSON file."""
        with open(self.db_path, 'r') as f:
            data = json.load(f)
        
        for po_data in data.get("purchase_orders", []):
            line_items = [
                LineItem(
                    item_code=item.get("item_id"),
                    description=item["description"],
                    quantity=item["quantity"],
                    unit=item.get("unit", "kg"),
                    unit_price=item["unit_price"],
                    line_total=item["line_total"]
                )
                for item in po_data.get("line_items", [])
            ]
            
            po = PurchaseOrder(
                po_number=po_data["po_number"],
                supplier=po_data["supplier"],
                date=po_data["date"],
                total=po_data["total"],
                currency=po_data.get("currency", "GBP"),
                line_items=line_items
            )
            self.purchase_orders.append(po)
    
    def get_by_po_number(self, po_number: str) -> Optional[PurchaseOrder]:
        """Get PO by exact PO number match."""
        for po in self.purchase_orders:
            if po.po_number.upper() == po_number.upper():
                return po
        return None
    
    def fuzzy_match_supplier(self, supplier_name: str, threshold: float = 70) -> List[Tuple[PurchaseOrder, float]]:
        """Find POs by fuzzy supplier name matching."""
        results = []
        for po in self.purchase_orders:
            # Try multiple fuzzy matching strategies
            ratio = fuzz.ratio(supplier_name.lower(), po.supplier.lower())
            partial_ratio = fuzz.partial_ratio(supplier_name.lower(), po.supplier.lower())
            token_sort = fuzz.token_sort_ratio(supplier_name.lower(), po.supplier.lower())
            
            # Use best score
            score = max(ratio, partial_ratio, token_sort)
            
            if score >= threshold:
                results.append((po, score / 100.0))
        
        # Sort by score descending
        return sorted(results, key=lambda x: x[1], reverse=True)
    
    def fuzzy_match_products(self, product_descriptions: List[str], threshold: float = 70) -> List[Tuple[PurchaseOrder, float, int]]:
        """Find POs by fuzzy product description matching."""
        results = []
        
        for po in self.purchase_orders:
            po_descriptions = [item.description.lower() for item in po.line_items]
            matched_count = 0
            total_score = 0
            
            for desc in product_descriptions:
                desc_lower = desc.lower()
                best_match = process.extractOne(
                    desc_lower, 
                    po_descriptions,
                    scorer=fuzz.token_sort_ratio
                )
                
                if best_match and best_match[1] >= threshold:
                    matched_count += 1
                    total_score += best_match[1]
            
            if matched_count > 0:
                avg_score = total_score / len(product_descriptions)
                match_rate = matched_count / len(product_descriptions)
                # Combined score: weighted average of match rate and similarity
                combined_score = (match_rate * 0.6 + (avg_score / 100) * 0.4)
                results.append((po, combined_score, matched_count))
        
        return sorted(results, key=lambda x: (x[2], x[1]), reverse=True)
    
    def find_best_match(
        self, 
        po_reference: Optional[str],
        supplier_name: str,
        product_descriptions: List[str],
        invoice_total: float
    ) -> Tuple[Optional[PurchaseOrder], str, float]:
        """
        Find best matching PO using 3-tier strategy.
        Returns: (matched_po, match_method, confidence)
        """
        # Tier 1: Exact PO reference match
        if po_reference:
            po = self.get_by_po_number(po_reference)
            if po:
                return (po, "exact_po_reference", 0.98)
        
        # Tier 2: Supplier + Products match
        supplier_matches = self.fuzzy_match_supplier(supplier_name, threshold=60)
        if supplier_matches:
            for po, supplier_score in supplier_matches:
                po_descriptions = [item.description for item in po.line_items]
                product_matches = self.fuzzy_match_products(product_descriptions, threshold=65)
                
                for matched_po, prod_score, matched_count in product_matches:
                    if matched_po.po_number == po.po_number:
                        # Check total similarity
                        total_diff = abs(matched_po.total - invoice_total) / matched_po.total
                        if total_diff < 0.15:  # Within 15% total variance
                            combined = (supplier_score * 0.4 + prod_score * 0.4 + (1 - total_diff) * 0.2)
                            return (matched_po, "fuzzy_supplier_product_match", min(combined, 0.90))
        
        # Tier 3: Product-only match
        product_matches = self.fuzzy_match_products(product_descriptions, threshold=70)
        if product_matches:
            best_po, score, matched_count = product_matches[0]
            match_rate = matched_count / len(product_descriptions)
            if match_rate >= 0.7:
                confidence = score * 0.7  # Lower confidence for product-only match
                return (best_po, "product_only_match", min(confidence, 0.70))
        
        return (None, "no_match", 0.0)
    
    def get_all_pos(self) -> List[PurchaseOrder]:
        """Get all purchase orders."""
        return self.purchase_orders
    
    def to_dict_list(self) -> List[dict]:
        """Convert all POs to list of dicts for state."""
        return [po.model_dump() for po in self.purchase_orders]
