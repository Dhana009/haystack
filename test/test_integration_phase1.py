"""
Integration tests for Phase 1 features.

Tests end-to-end document storage with deduplication, metadata generation, and verification.
"""
import pytest
import os
from unittest.mock import Mock, patch, MagicMock
from haystack.dataclasses.document import Document
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from haystack.components.embedders import SentenceTransformersDocumentEmbedder

from deduplication_service import (
    generate_content_fingerprint,
    check_duplicate_level,
    decide_storage_action,
    DUPLICATE_LEVEL_EXACT,
    DUPLICATE_LEVEL_UPDATE,
    DUPLICATE_LEVEL_NEW,
    ACTION_SKIP,
    ACTION_UPDATE,
    ACTION_STORE,
)
from metadata_service import build_metadata_schema, query_by_doc_id, query_by_content_hash
from verification_service import verify_content_quality, bulk_verify_category


@pytest.fixture
def mock_document_store():
    """Create a mock document store for testing."""
    store = Mock(spec=QdrantDocumentStore)
    store.index = "test_collection"
    store.filter_documents = Mock(return_value=[])
    store.write_documents = Mock(return_value=None)
    store.delete_documents = Mock(return_value=None)
    return store


@pytest.fixture
def mock_embedder():
    """Create a mock embedder for testing."""
    embedder = Mock(spec=SentenceTransformersDocumentEmbedder)
    embedder.run = Mock(return_value={
        "documents": [Document(content="Test", embedding=[0.1, 0.2, 0.3])]
    })
    return embedder


class TestPhase1EndToEnd:
    """End-to-end integration tests for Phase 1 features."""
    
    def test_complete_document_storage_workflow(self, mock_document_store):
        """Test complete workflow: fingerprint -> deduplication -> metadata -> storage."""
        # Step 1: Generate fingerprint
        content = "This is a test document with sufficient content length for testing."
        metadata = {
            "doc_id": "test_doc_1",
            "category": "user_rule",
            "version": "v1.0"
        }
        
        fingerprint = generate_content_fingerprint(content, metadata)
        
        assert "content_hash" in fingerprint
        assert "metadata_hash" in fingerprint
        assert "composite_key" in fingerprint
        
        # Step 2: Check for duplicates (no existing docs)
        existing_docs = []
        level, matching_doc, reason = check_duplicate_level(fingerprint, existing_docs)
        
        assert level == DUPLICATE_LEVEL_NEW
        assert matching_doc is None
        
        # Step 3: Decide storage action
        action, action_data = decide_storage_action(level, fingerprint, matching_doc)
        
        assert action == ACTION_STORE
        
        # Step 4: Build metadata schema
        full_metadata = build_metadata_schema(
            content=content,
            doc_id=metadata["doc_id"],
            category=metadata["category"],
            hash_content=fingerprint["content_hash"],
            version=metadata["version"]
        )
        
        assert full_metadata["doc_id"] == metadata["doc_id"]
        assert full_metadata["category"] == metadata["category"]
        assert full_metadata["hash_content"] == fingerprint["content_hash"]
        assert "metadata_hash" in full_metadata
        
        # Step 5: Verify content quality
        doc = Document(content=content, meta=full_metadata, id="doc1")
        quality_result = verify_content_quality(doc)
        
        assert quality_result["status"] == "pass"
        assert quality_result["quality_score"] >= 0.8
    
    def test_duplicate_detection_workflow_exact_duplicate(self, mock_document_store):
        """Test workflow when exact duplicate is detected."""
        content = "Test content for duplicate detection."
        metadata = {"doc_id": "test1", "category": "user_rule", "version": "v1.0"}
        
        # Generate fingerprint
        fingerprint = generate_content_fingerprint(content, metadata)
        
        # Create existing document with same fingerprint
        existing_doc = Document(
            content=content,
            meta={
                "doc_id": "test1",
                "category": "user_rule",
                "hash_content": fingerprint["content_hash"],
                "metadata_hash": fingerprint["metadata_hash"]
            },
            id="existing_doc1"
        )
        
        # Check duplicate level
        level, matching_doc, reason = check_duplicate_level(fingerprint, [existing_doc])
        
        assert level == DUPLICATE_LEVEL_EXACT
        assert matching_doc == existing_doc
        
        # Decide action
        action, action_data = decide_storage_action(level, fingerprint, matching_doc)
        
        assert action == ACTION_SKIP
        assert action_data["existing_doc_id"] == "existing_doc1"
    
    def test_duplicate_detection_workflow_content_update(self, mock_document_store):
        """Test workflow when content update is detected."""
        old_content = "Old content version."
        new_content = "New content version with updates."
        metadata = {"doc_id": "test1", "category": "user_rule", "version": "v1.0"}
        
        # Generate fingerprints
        old_fingerprint = generate_content_fingerprint(old_content, metadata)
        new_fingerprint = generate_content_fingerprint(new_content, metadata)
        
        # Create existing document with same metadata_hash but different content_hash
        existing_doc = Document(
            content=old_content,
            meta={
                "doc_id": "test1",
                "category": "user_rule",
                "hash_content": old_fingerprint["content_hash"],
                "metadata_hash": old_fingerprint["metadata_hash"]  # Same metadata_hash
            },
            id="existing_doc1"
        )
        
        # Check duplicate level with new fingerprint
        level, matching_doc, reason = check_duplicate_level(new_fingerprint, [existing_doc])
        
        assert level == DUPLICATE_LEVEL_UPDATE
        assert matching_doc == existing_doc
        
        # Decide action
        action, action_data = decide_storage_action(level, new_fingerprint, matching_doc)
        
        assert action == ACTION_UPDATE
        assert action_data["old_doc_id"] == "existing_doc1"
    
    def test_metadata_query_workflow(self, mock_document_store):
        """Test querying documents by metadata fields."""
        # Setup mock to return documents
        mock_doc = Document(
            content="Test content",
            meta={
                "doc_id": "test1",
                "category": "user_rule",
                "file_path": "/path/to/file.txt",
                "hash_content": "abc123",
                "version": "v1.0",
                "status": "active"
            },
            id="doc1"
        )
        
        mock_document_store.filter_documents = Mock(return_value=[mock_doc])
        
        # Query by doc_id
        results = query_by_doc_id(mock_document_store, "test1")
        assert len(results) == 1
        assert results[0].meta["doc_id"] == "test1"
        
        # Query by content_hash
        results = query_by_content_hash(mock_document_store, "abc123")
        assert len(results) == 1
        assert results[0].meta["hash_content"] == "abc123"
    
    def test_verification_workflow(self, mock_document_store):
        """Test content verification workflow."""
        content = "This is a comprehensive test document with sufficient content length."
        metadata = {
            "doc_id": "test1",
            "category": "user_rule",
            "version": "v1.0",
            "hash_content": "abc123",
            "status": "active"
        }
        
        # Create document
        doc = Document(content=content, meta=metadata, id="doc1")
        
        # Verify quality
        result = verify_content_quality(doc)
        
        assert "quality_score" in result
        assert "checks" in result
        assert "status" in result
        assert result["document_id"] == "doc1"
        
        # Verify all checks passed
        checks = result["checks"]
        assert checks["has_content"] is True
        assert checks["min_length"] is True
        assert checks["has_metadata"] is True
    
    def test_bulk_verification_workflow(self, mock_document_store):
        """Test bulk verification workflow."""
        # Create multiple documents
        docs = []
        for i in range(3):
            content = f"This is test document {i} with sufficient content length."
            metadata = {
                "doc_id": f"test{i}",
                "category": "user_rule",
                "version": "v1.0",
                "hash_content": f"hash{i}",
                "status": "active"
            }
            docs.append(Document(content=content, meta=metadata, id=f"doc{i}"))
        
        mock_document_store.filter_documents = Mock(return_value=docs)
        
        # Bulk verify
        result = bulk_verify_category(mock_document_store, None, category="user_rule")
        
        assert result["category"] == "user_rule"
        assert result["total"] == 3
        assert "passed" in result
        assert "failed" in result
        assert "average_quality_score" in result
    
    def test_complete_workflow_with_duplicate_handling(self, mock_document_store):
        """Test complete workflow including duplicate handling."""
        content = "Test document content."
        metadata = {"doc_id": "test1", "category": "user_rule", "version": "v1.0"}
        
        # First document - should be stored
        fingerprint1 = generate_content_fingerprint(content, metadata)
        level1, doc1, reason1 = check_duplicate_level(fingerprint1, [])
        action1, _ = decide_storage_action(level1, fingerprint1, doc1)
        
        assert action1 == ACTION_STORE
        
        # Create existing document
        existing_doc = Document(
            content=content,
            meta={
                "doc_id": "test1",
                "category": "user_rule",
                "hash_content": fingerprint1["content_hash"],
                "metadata_hash": fingerprint1["metadata_hash"]
            },
            id="existing1"
        )
        
        # Second document - same content, should be skipped
        fingerprint2 = generate_content_fingerprint(content, metadata)
        level2, doc2, reason2 = check_duplicate_level(fingerprint2, [existing_doc])
        action2, _ = decide_storage_action(level2, fingerprint2, doc2)
        
        assert action2 == ACTION_SKIP
        
        # Third document - updated content, should be updated
        new_content = "Updated test document content."
        fingerprint3 = generate_content_fingerprint(new_content, metadata)
        level3, doc3, reason3 = check_duplicate_level(fingerprint3, [existing_doc])
        action3, _ = decide_storage_action(level3, fingerprint3, doc3)
        
        assert action3 == ACTION_UPDATE

