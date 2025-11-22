# qdrant-verify-collection

Write your command content here.

This command will be available in chat with /qdrant-verify-collection
COMMAND 5 – qdrant_verify_collection
Purpose

Run a health check on the Qdrant collection to detect structural and data issues.

Behavior

Sample documents across categories.

Check for:

missing required metadata fields

inconsistent status (active but old version, etc.)

hash mismatches (if original content available)

presence of placeholder-only documents.

Generate a summary report:

counts by category/status

obvious anomalies

suggested fixes (e.g., delete placeholder docs, re-ingest certain paths).

Rules

This command is read-only and must not modify the collection directly.

For fixes, it should suggest using qdrant_delete_document or qdrant_store_document.