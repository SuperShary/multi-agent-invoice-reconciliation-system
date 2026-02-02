# Written Analysis - Multi-Agent Invoice Reconciliation System

## Where Does OCR/Extraction Fail? How Do Agents Compensate?

The Document Intelligence Agent faces several extraction challenges:

1. **Scanned/Rotated Documents**: Invoice 2 is a rotated scanned image. Gemini Vision handles this reasonably well, but confidence drops from 95%+ to 75-85%. The agent explicitly lowers confidence scores when document quality is poor, which triggers the Resolution Agent to flag for human review rather than auto-approve.

2. **Varied Templates**: Invoice 3 uses a different template format with items in different order. The extraction works, but line-item matching becomes harder. The Matching Agent compensates using fuzzy string matching with RapidFuzz, comparing product descriptions rather than relying on exact order or codes.

3. **Missing Critical Fields**: When PO references are missing (Invoice 5), the Document Intelligence Agent returns null for that field. The Matching Agent then falls back to Tier 2/3 matching (supplier + products, or products-only), accepting lower confidence but still finding the correct PO.

The key compensation pattern: **confidence scoring propagates through all agents**. Low extraction confidence → lower match confidence → triggers review/escalation path.

## How Would You Improve Accuracy from 70% to 95%?

1. **Fine-tuned Models**: Train a domain-specific model on pharmaceutical invoice patterns. Current Gemini is general-purpose; a fine-tuned model would better understand industry-specific terms, unit formats, and layout conventions.

2. **Multi-pass Extraction**: Run extraction twice with different prompts. If results differ significantly, flag for review. Currently using single-pass for speed.

3. **Template Recognition**: Build a template classifier that identifies known invoice formats before extraction. Each template could have custom extraction rules.

4. **Human-in-the-Loop Learning**: Capture human corrections and feed them back to improve future extractions. The Human Reviewer Agent demonstrates this pattern, but real implementation would require a persistent feedback store.

5. **Ensemble OCR**: Combine Gemini Vision with Tesseract and other OCR engines. Vote on extracted values to reduce errors.

## How Would You Validate at 10,000 Invoices/Day Scale?

1. **Parallel Processing**: Current sequential processing wouldn't scale. Would implement async processing with a job queue (e.g., Celery/Redis) to process multiple invoices concurrently. Target: 100 parallel workers.

2. **Caching**: Cache PO database in Redis with fuzzy index support. Current approach loads JSON repeatedly; caching reduces latency significantly.

3. **Sampling-Based Validation**: Can't manually verify 10,000 invoices. Instead:
   - Auto-approve high-confidence results (>95%)
   - Sample 5% of medium-confidence for human audit
   - Track accuracy metrics daily with alerts for degradation

4. **A/B Testing**: Run new model versions on shadow traffic, compare results before deployment.

5. **Monitoring Dashboard**: Track processing time, confidence distributions, discrepancy rates, and false positive/negative rates in real-time.

---

*Word count: 498*
