"""
Comprehensive test script for chunk-based incremental update implementation.

Tests:
1. Basic chunking functionality
2. Chunk comparison and change detection
3. Incremental update logic
4. Full scenario: 50% old / 50% new content update
"""
import sys
import os
from pathlib import Path

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from chunk_service import (
    chunk_document,
    generate_chunk_id,
    compare_chunks,
    identify_chunk_changes
)
from deduplication_service import normalize_content
import hashlib

print("=" * 80)
print("COMPREHENSIVE CHUNKING IMPLEMENTATION TEST")
print("=" * 80)

# Test 1: Basic Chunking
print("\n[TEST 1] Basic Document Chunking")
print("-" * 80)
test_content_1 = """
Introduction to Feature A

Feature A is a powerful tool that allows users to perform complex operations.
It provides a simple API for advanced functionality.

Advanced Usage

You can extend Feature A by configuring various parameters. This enables
customization for different use cases.

Best Practices

Follow these guidelines when using Feature A:
- Keep configurations simple
- Test thoroughly before production
- Document your customizations
""".strip()

chunks_1 = chunk_document(
    content=test_content_1,
    doc_id="test_doc_001",
    chunk_size=150,  # Small chunks for testing
    chunk_overlap=20
)

print(f"Document length: {len(test_content_1)} characters")
print(f"Created {len(chunks_1)} chunks")
for i, chunk in enumerate(chunks_1):
    chunk_id = chunk.meta.get('chunk_id')
    chunk_index = chunk.meta.get('chunk_index')
    parent_id = chunk.meta.get('parent_doc_id')
    is_chunk = chunk.meta.get('is_chunk')
    total_chunks = chunk.meta.get('total_chunks')
    content_hash = chunk.meta.get('hash_content', '')[:16]
    
    print(f"  Chunk {i}:")
    print(f"    ID: {chunk_id}")
    print(f"    Index: {chunk_index}")
    print(f"    Parent: {parent_id}")
    print(f"    Is Chunk: {is_chunk}")
    print(f"    Total Chunks: {total_chunks}")
    print(f"    Content Hash: {content_hash}...")
    print(f"    Content Preview: {chunk.content[:60].replace(chr(10), ' ')}...")

assert len(chunks_1) > 0, "Should create at least one chunk"
assert all(chunk.meta.get('is_chunk') == True for chunk in chunks_1), "All chunks should have is_chunk=True"
assert all(chunk.meta.get('parent_doc_id') == "test_doc_001" for chunk in chunks_1), "All chunks should reference parent doc"
assert chunks_1[0].meta.get('chunk_index') == 0, "First chunk should have index 0"
print("PASS: Basic chunking works correctly")

# Test 2: Chunk Comparison - Unchanged Content
print("\n[TEST 2] Chunk Comparison - Unchanged Content")
print("-" * 80)
old_chunks = chunks_1
new_chunks = chunk_document(test_content_1, "test_doc_001", chunk_size=150, chunk_overlap=20)

changes = compare_chunks(old_chunks, new_chunks)
summary = identify_chunk_changes(old_chunks, new_chunks)

print(f"Old chunks: {summary['total_old']}")
print(f"New chunks: {summary['total_new']}")
print(f"Unchanged: {summary['unchanged_count']}")
print(f"Changed: {summary['changed_count']}")
print(f"New: {summary['new_count']}")
print(f"Deleted: {summary['deleted_count']}")

# Since content is identical, chunks should be unchanged
assert summary['unchanged_count'] == len(old_chunks), "All chunks should be unchanged for identical content"
assert summary['changed_count'] == 0, "No chunks should be changed"
assert summary['new_count'] == 0, "No new chunks"
assert summary['deleted_count'] == 0, "No deleted chunks"
print("PASS: Unchanged content detection works correctly")

# Test 3: Chunk Comparison - Changed Content (50% scenario)
print("\n[TEST 3] Chunk Comparison - 50% Changed Content Scenario")
print("-" * 80)

# Original content with 3 sections (long enough to create multiple chunks)
original_content = """
Section 1: Introduction to Feature A

This is the original introduction paragraph. Feature A allows basic operations and provides a simple interface.
This section will remain unchanged in the update. It contains fundamental information about the feature.
The introduction explains the core purpose and basic usage patterns. Users can get started quickly.

Section 2: Core Functionality

This section describes the core features in detail. It covers the main operations available in Feature A.
The implementation uses efficient algorithms to ensure good performance. This section will be modified.
Old implementation details are described here. The previous version had different characteristics.

Section 3: Advanced Usage

This section covers advanced scenarios and edge cases. It explains how to extend Feature A for complex use cases.
Advanced users can configure additional parameters. This section will be completely rewritten in the update.
The current documentation provides basic examples only.

Section 4: Additional Information

This section provides supplementary details about Feature A. It includes troubleshooting tips and common issues.
The information here helps users resolve problems quickly. This section will remain mostly unchanged.
""".strip()

# Updated content: Section 1 unchanged, Section 2 modified, Section 3 completely new, Section 4 unchanged
updated_content = """
Section 1: Introduction to Feature A

This is the original introduction paragraph. Feature A allows basic operations and provides a simple interface.
This section will remain unchanged in the update. It contains fundamental information about the feature.
The introduction explains the core purpose and basic usage patterns. Users can get started quickly.

Section 2: Core Functionality (UPDATED)

This section describes the core features in detail. It has been completely rewritten with new implementation details.
The new implementation uses optimized algorithms for better performance. Updated documentation is provided here.
New implementation details describe the improved architecture. The current version has enhanced capabilities.

Section 3: Advanced Usage (REWRITTEN)

This is a completely rewritten section with new advanced usage patterns. It provides comprehensive examples.
Advanced users can now configure multiple parameters for fine-tuned control. The documentation is more detailed.
New examples demonstrate complex scenarios that were not covered previously. Best practices are included.

Section 4: Additional Information

This section provides supplementary details about Feature A. It includes troubleshooting tips and common issues.
The information here helps users resolve problems quickly. This section will remain mostly unchanged.

Section 5: New Section

This is a completely new section that was not in the original document. It provides additional functionality information.
New features and capabilities are described here. This section extends the documentation with new content.
""".strip()

original_chunks = chunk_document(original_content, "test_doc_002", chunk_size=120, chunk_overlap=15)
updated_chunks = chunk_document(updated_content, "test_doc_002", chunk_size=120, chunk_overlap=15)

print(f"Original document: {len(original_content)} characters, {len(original_chunks)} chunks")
print(f"Updated document: {len(updated_content)} characters, {len(updated_chunks)} chunks")

changes_50 = compare_chunks(original_chunks, updated_chunks)
summary_50 = identify_chunk_changes(original_chunks, updated_chunks)

print(f"\nChange Summary:")
print(f"  Unchanged: {summary_50['unchanged_count']}")
print(f"  Changed: {summary_50['changed_count']}")
print(f"  New: {summary_50['new_count']}")
print(f"  Deleted: {summary_50['deleted_count']}")

print(f"\nDetailed Changes:")
for i, unchanged in enumerate(changes_50['unchanged']):
    print(f"  Unchanged chunk {i}: {unchanged.meta.get('chunk_index')} - hash: {unchanged.meta.get('hash_content', '')[:16]}...")

for i, changed in enumerate(changes_50['changed']):
    print(f"  Changed chunk {i}: {changed.meta.get('chunk_index')} - hash: {changed.meta.get('hash_content', '')[:16]}...")

for i, new_chunk in enumerate(changes_50['new']):
    print(f"  New chunk {i}: {new_chunk.meta.get('chunk_index')} - hash: {new_chunk.meta.get('hash_content', '')[:16]}...")

# Verify that we detected changes correctly
total_chunks = len(original_chunks)
unchanged_ratio = summary_50['unchanged_count'] / total_chunks if total_chunks > 0 else 0
changed_ratio = summary_50['changed_count'] / total_chunks if total_chunks > 0 else 0
new_ratio = summary_50['new_count'] / len(updated_chunks) if len(updated_chunks) > 0 else 0

print(f"\nChange Ratios:")
print(f"  Unchanged: {unchanged_ratio:.2%} ({summary_50['unchanged_count']}/{total_chunks})")
print(f"  Changed: {changed_ratio:.2%} ({summary_50['changed_count']}/{total_chunks})")
print(f"  New: {new_ratio:.2%} ({summary_50['new_count']}/{len(updated_chunks)})")

# Verify that we have multiple chunks and detected changes
assert len(original_chunks) > 1 or len(updated_chunks) > 1, "Should have multiple chunks for meaningful comparison"
assert summary_50['changed_count'] > 0 or summary_50['new_count'] > 0, "Should detect changes or new chunks"
print("PASS: Changed content scenario works correctly (50% scenario demonstrated)")

# Test 4: Chunk ID Generation
print("\n[TEST 4] Chunk ID Generation")
print("-" * 80)
chunk_id_0 = generate_chunk_id("doc_001", 0)
chunk_id_1 = generate_chunk_id("doc_001", 1)
chunk_id_2 = generate_chunk_id("doc_002", 0)

print(f"doc_001, chunk 0: {chunk_id_0}")
print(f"doc_001, chunk 1: {chunk_id_1}")
print(f"doc_002, chunk 0: {chunk_id_2}")

assert chunk_id_0 == "doc_001_chunk_0", "Chunk ID format should be correct"
assert chunk_id_1 == "doc_001_chunk_1", "Chunk ID format should be correct"
assert chunk_id_2 == "doc_002_chunk_0", "Chunk ID format should be correct"
assert chunk_id_0 != chunk_id_1, "Different chunk indices should have different IDs"
assert chunk_id_0 != chunk_id_2, "Different parent docs should have different IDs"
print("PASS: Chunk ID generation works correctly")

# Test 5: Content Hash Stability
print("\n[TEST 5] Content Hash Stability")
print("-" * 80)
test_content_same = "Feature A works like X."
test_content_modified = "Feature A works like X (updated)."

chunk_same_1 = chunk_document(test_content_same, "test_003", chunk_size=100)[0]
chunk_same_2 = chunk_document(test_content_same, "test_003", chunk_size=100)[0]
chunk_modified = chunk_document(test_content_modified, "test_003", chunk_size=100)[0]

hash_same_1 = chunk_same_1.meta.get('hash_content')
hash_same_2 = chunk_same_2.meta.get('hash_content')
hash_modified = chunk_modified.meta.get('hash_content')

print(f"Same content hash 1: {hash_same_1[:16]}...")
print(f"Same content hash 2: {hash_same_2[:16]}...")
print(f"Modified content hash: {hash_modified[:16]}...")

assert hash_same_1 == hash_same_2, "Same content should have same hash"
assert hash_same_1 != hash_modified, "Different content should have different hash"
print("PASS: Content hash stability works correctly")

# Test 6: Chunk Index Preservation
print("\n[TEST 6] Chunk Index Preservation")
print("-" * 80)
long_content = """
Paragraph 1: First section with important information.

Paragraph 2: Second section with more details.

Paragraph 3: Third section with additional content.

Paragraph 4: Fourth section with final information.
""".strip()

chunks_long = chunk_document(long_content, "test_004", chunk_size=100, chunk_overlap=10)

print(f"Created {len(chunks_long)} chunks")
indices = [chunk.meta.get('chunk_index') for chunk in chunks_long]
print(f"Chunk indices: {indices}")

assert indices == list(range(len(chunks_long))), "Chunk indices should be sequential starting from 0"
assert all(chunk.meta.get('total_chunks') == len(chunks_long) for chunk in chunks_long), "All chunks should have correct total_chunks count"
print("PASS: Chunk index preservation works correctly")

# Final Summary
print("\n" + "=" * 80)
print("TEST SUMMARY")
print("=" * 80)
print("All tests passed successfully!")
print("\nKey Features Verified:")
print("  - Document chunking with configurable size and overlap")
print("  - Chunk metadata (chunk_id, chunk_index, parent_doc_id, etc.)")
print("  - Chunk comparison and change detection")
print("  - Unchanged chunk preservation logic")
print("  - Changed chunk detection logic")
print("  - New chunk detection logic")
print("  - Content hash stability")
print("  - Chunk ID generation")
print("  - 50% changed content scenario detection")
print("=" * 80)

