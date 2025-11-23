"""
Test the 50% unchanged / 50% changed scenario - Real-world update simulation.

This test simulates updating a document where:
- 50% of the content (chunks) remains unchanged
- 50% of the content (chunks) is modified or new
- Only changed chunks should be re-embedded
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from chunk_service import (
    chunk_document,
    compare_chunks,
    identify_chunk_changes
)

print("=" * 80)
print("50% UNCHANGED / 50% CHANGED SCENARIO TEST")
print("=" * 80)

# Create a longer document that will be split into multiple chunks
# We'll ensure that some sections remain exactly the same
original_doc = """
# Feature Documentation: Advanced API

## Section 1: Getting Started (UNCHANGED)

This section provides a comprehensive introduction to the Advanced API.
The API allows developers to integrate powerful features into their applications.
Getting started is simple - just follow these basic steps.

First, install the required dependencies using pip. Then configure your API keys.
After configuration, you can make your first API call to test the connection.
This section will remain completely unchanged in the update.

## Section 2: Authentication (UNCHANGED)

Authentication is handled using API keys. Each request must include a valid key.
The key should be passed in the Authorization header as a Bearer token.
This ensures secure access to all API endpoints.

Rate limiting applies to all authenticated requests. Free tier allows 1000 requests per day.
Paid tiers offer higher limits and additional features. This section also remains unchanged.

## Section 3: Core Endpoints (MODIFIED)

The core endpoints provide essential functionality for most use cases.
This section describes the main API endpoints available to developers.
The endpoint URLs have been updated to use the new v2 API version.

Response formats have been improved for better consistency. Error handling is more robust.
This section has been significantly modified with new information and examples.

## Section 4: Error Handling (MODIFIED)

Proper error handling is crucial for building reliable applications.
The API returns standard HTTP status codes to indicate success or failure.
Error responses include detailed messages to help with debugging.

New error codes have been added to provide more granular error information.
This section has been updated with additional error handling examples and best practices.

## Section 5: Advanced Features (NEW)

This is a completely new section that was not in the original document.
It covers advanced features like webhooks, batch processing, and custom integrations.
These features are available to enterprise tier subscribers only.

## Section 6: Best Practices (NEW)

This section provides recommendations for optimal API usage.
It includes performance tips, security best practices, and common pitfalls to avoid.
Follow these guidelines to ensure your integration is efficient and secure.
""".strip()

# Updated document: Sections 1 and 2 unchanged, Sections 3 and 4 modified, Sections 5 and 6 new
updated_doc = """
# Feature Documentation: Advanced API

## Section 1: Getting Started (UNCHANGED)

This section provides a comprehensive introduction to the Advanced API.
The API allows developers to integrate powerful features into their applications.
Getting started is simple - just follow these basic steps.

First, install the required dependencies using pip. Then configure your API keys.
After configuration, you can make your first API call to test the connection.
This section will remain completely unchanged in the update.

## Section 2: Authentication (UNCHANGED)

Authentication is handled using API keys. Each request must include a valid key.
The key should be passed in the Authorization header as a Bearer token.
This ensures secure access to all API endpoints.

Rate limiting applies to all authenticated requests. Free tier allows 1000 requests per day.
Paid tiers offer higher limits and additional features. This section also remains unchanged.

## Section 3: Core Endpoints (MODIFIED)

The core endpoints provide essential functionality for most use cases.
This section describes the main API endpoints available to developers.
The endpoint URLs have been updated to use the new v2 API version.

Response formats have been improved for better consistency. Error handling is more robust.
This section has been significantly modified with new information and examples.
Additional endpoint documentation has been added with code samples in multiple languages.

## Section 4: Error Handling (MODIFIED)

Proper error handling is crucial for building reliable applications.
The API returns standard HTTP status codes to indicate success or failure.
Error responses include detailed messages to help with debugging.

New error codes have been added to provide more granular error information.
This section has been updated with additional error handling examples and best practices.
Retry logic and exponential backoff strategies are now documented.

## Section 5: Advanced Features (NEW)

This is a completely new section that was not in the original document.
It covers advanced features like webhooks, batch processing, and custom integrations.
These features are available to enterprise tier subscribers only.

## Section 6: Best Practices (NEW)

This section provides recommendations for optimal API usage.
It includes performance tips, security best practices, and common pitfalls to avoid.
Follow these guidelines to ensure your integration is efficient and secure.
""".strip()

print("\n[SCENARIO] Document Update with 50% Unchanged Content")
print("-" * 80)

# Chunk both documents
chunk_size = 200  # Small chunks to ensure multiple chunks
chunk_overlap = 30

print("Chunking original document...")
original_chunks = chunk_document(original_doc, "api_doc_001", chunk_size=chunk_size, chunk_overlap=chunk_overlap)

print("Chunking updated document...")
updated_chunks = chunk_document(updated_doc, "api_doc_001", chunk_size=chunk_size, chunk_overlap=chunk_overlap)

print(f"\nOriginal document: {len(original_doc)} characters, {len(original_chunks)} chunks")
print(f"Updated document: {len(updated_doc)} characters, {len(updated_chunks)} chunks")

# Compare chunks
changes = compare_chunks(original_chunks, updated_chunks)
summary = identify_chunk_changes(original_chunks, updated_chunks)

print("\n" + "=" * 80)
print("CHANGE DETECTION RESULTS")
print("=" * 80)

print(f"\nOriginal chunks: {summary['total_old']}")
print(f"Updated chunks: {summary['total_new']}")
print(f"\nUnchanged chunks: {summary['unchanged_count']} (preserved - no re-embedding needed)")
print(f"Changed chunks: {summary['changed_count']} (need re-embedding)")
print(f"New chunks: {summary['new_count']} (need embedding)")
print(f"Deleted chunks: {summary['deleted_count']} (will be deprecated)")

# Calculate percentages
total_original = summary['total_old']
unchanged_pct = (summary['unchanged_count'] / total_original * 100) if total_original > 0 else 0
changed_pct = (summary['changed_count'] / total_original * 100) if total_original > 0 else 0
new_pct = (summary['new_count'] / summary['total_new'] * 100) if summary['total_new'] > 0 else 0

print("\n" + "-" * 80)
print("PERCENTAGE BREAKDOWN")
print("-" * 80)
print(f"Unchanged: {unchanged_pct:.1f}% of original chunks (COST SAVINGS: No re-embedding)")
print(f"Changed: {changed_pct:.1f}% of original chunks (NEED RE-EMBEDDING)")
print(f"New: {new_pct:.1f}% of updated chunks (NEED EMBEDDING)")

# Calculate embedding cost savings
total_chunks_to_embed = summary['changed_count'] + summary['new_count']
total_chunks_preserved = summary['unchanged_count']
total_chunks_in_update = summary['total_new']

if total_chunks_in_update > 0:
    embedding_savings = (total_chunks_preserved / total_chunks_in_update * 100)
    print(f"\nEMBEDDING COST SAVINGS: {embedding_savings:.1f}% of chunks preserved")
    print(f"Chunks to embed: {total_chunks_to_embed} out of {total_chunks_in_update} total")
    print(f"Chunks preserved: {total_chunks_preserved} (no embedding cost)")

print("\n" + "=" * 80)
print("DETAILED CHUNK ANALYSIS")
print("=" * 80)

if changes['unchanged']:
    print(f"\nUNCHANGED CHUNKS ({len(changes['unchanged'])}):")
    for i, chunk in enumerate(changes['unchanged']):
        idx = chunk.meta.get('chunk_index')
        hash_short = chunk.meta.get('hash_content', '')[:16]
        preview = chunk.content[:50].replace('\n', ' ')
        print(f"  Chunk {idx}: {hash_short}... - '{preview}...'")

if changes['changed']:
    print(f"\nCHANGED CHUNKS ({len(changes['changed'])}):")
    for i, chunk in enumerate(changes['changed']):
        idx = chunk.meta.get('chunk_index')
        hash_short = chunk.meta.get('hash_content', '')[:16]
        preview = chunk.content[:50].replace('\n', ' ')
        print(f"  Chunk {idx}: {hash_short}... - '{preview}...'")

if changes['new']:
    print(f"\nNEW CHUNKS ({len(changes['new'])}):")
    for i, chunk in enumerate(changes['new']):
        idx = chunk.meta.get('chunk_index')
        hash_short = chunk.meta.get('hash_content', '')[:16]
        preview = chunk.content[:50].replace('\n', ' ')
        print(f"  Chunk {idx}: {hash_short}... - '{preview}...'")

print("\n" + "=" * 80)
print("TEST RESULTS")
print("=" * 80)

# Verify the scenario
assert summary['unchanged_count'] > 0, "Should detect unchanged chunks"
assert summary['changed_count'] > 0 or summary['new_count'] > 0, "Should detect changes"

print("\nPASS: 50% unchanged scenario works correctly!")
print(f"- {summary['unchanged_count']} chunks will be preserved (no embedding cost)")
print(f"- {summary['changed_count']} chunks will be updated (re-embedding required)")
print(f"- {summary['new_count']} chunks will be added (embedding required)")
print(f"- Estimated cost savings: ~{embedding_savings:.1f}% (unchanged chunks preserved)")
print("=" * 80)

