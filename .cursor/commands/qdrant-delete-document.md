# qdrant-delete-document

Write your command content here.

This command will be available in chat with /qdrant-delete-document
COMMAND 3 – qdrant_delete_document
Purpose

Delete or deactivate a document (or all its versions) from Qdrant in a controlled way.

Behavior

Accept:

doc_id

optional category

mode: "soft" or "hard".

If soft:

set status = "deprecated" on all matching docs.

If hard:

call Haystack/Qdrant delete by filter:

filter by doc_id (and category if given).

Return count of affected docs.

Rules

Default MUST be soft delete unless user explicitly asks for hard.

Deleting without a doc_id is forbidden in this command.