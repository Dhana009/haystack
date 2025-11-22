# qdrant-query-documents

Write your command content here.

This command will be available in chat with /qdrant-query-documents
COMMAND 4 – qdrant_query_documents
Purpose

Query Qdrant via Haystack with metadata filters and embeddings according to the retrieval contract.

Behavior

Accept:

user query text

optional category, tags, doc_id, status.

Use:

filters first (category, status = active, repo)

embedding search (top_k = sensible default).

Apply ranking:

primary: semantic score

secondary: recency (if versions differ)

tertiary: category relevance.

Return:

list of documents (id, version, category, score)

content snippets for context.

Rules

Must obey RULE 6.

Must not retrieve status = deprecated by default.

Must surface enough metadata for downstream reasoning.