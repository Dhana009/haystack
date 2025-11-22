# qdrant-store-document

Write your command content here.

This command will be available in chat with /qdrant-store-document
COMMAND 1 – qdrant_store_document
Purpose

Safely insert or version a document into Qdrant with full metadata, deduplication, and verification.

Behavior

Understand input:

document text

logical doc_id

category

optional path, tags, source.

Normalize & hash content.

Build metadata according to RULE 3.

Check for existing docs (by doc_id + category).

Decide:

skip insert (exact same hash)

insert as new version (change status of previous to deprecated)

insert as new doc.

Call Haystack’s write_documents.

Run verification (RULE 7).

Return:

final doc_id

version

status

summary of operation.

Rules

Must obey RULE 2–5–7.

Must never rely only on embedding similarity for dedup.

Must fail loudly on missing required metadata.