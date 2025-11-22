# qdrant-update-document

Write your command content here.

This command will be available in chat with /qdrant-update-document
COMMAND 2 – qdrant_update_document
Purpose

Update an existing logical document with new content (e.g., updated rules or commands) in a safe, versioned way.

Behavior

Locate document by:

doc_id

category.

Fetch current active version.

Compare current vs new hash_content.

If same → no-op.

If different:

mark old version status = "deprecated"

insert new version with status = "active".

Verify write.

Return old_version_id, new_version_id.

Rules

Must never overwrite existing content in-place without versioning.

Must use the same metadata schema as qdrant_store_document.

Must ensure that queries using status = "active" see only the new version.