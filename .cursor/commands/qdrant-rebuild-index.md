# qdrant-rebuild-index

Write your command content here.

This command will be available in chat with /qdrant-rebuild-index
COMMAND 6 – qdrant_rebuild_index (Optional / Admin-Level)
Purpose

Rebuild or migrate the Qdrant collection safely when:

embedding model changes

embedding dimension changes

large-scale corruption is detected.

Behavior

Export:

all documents + metadata.

Create:

new collection with correct schema.

Re-embed documents using new model.

Bulk insert with verification.

Swap collections (old → deprecated, new → active).

Rules

This is a heavy operation; must be explicit.

Must be confirmed by the user before running.

Must log a clear migration summary.