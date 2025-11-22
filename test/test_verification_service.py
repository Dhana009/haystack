"""
Unit tests for verification_service module.

Tests: detect_placeholders, verify_hash_integrity, verify_content_quality, bulk_verify_category.
"""
import pytest
from unittest.mock import Mock, patch
from haystack.dataclasses.document import Document
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore

from verification_service import (
    detect_placeholders,
    verify_hash_integrity,
    verify_content_quality,
    bulk_verify_category,
    MIN_CONTENT_LENGTH,
    REQUIRED_METADATA_FIELDS,
)
from deduplication_service import normalize_content
import hashlib


class TestDetectPlaceholders:
    """Test detect_placeholders function."""
    
    def test_detect_placeholders_empty_content(self):
        """Test placeholder detection with empty content."""
        result = detect_placeholders("")
        
        assert result["has_placeholder"] is False
        assert result["placeholder_count"] == 0
        assert result["placeholder_types"] == []
        assert result["placeholder_positions"] == []
    
    def test_detect_placeholders_no_placeholders(self):
        """Test with content that has no placeholders."""
        content = "This is normal content without any placeholders."
        result = detect_placeholders(content)
        
        assert result["has_placeholder"] is False
        assert result["placeholder_count"] == 0
    
    def test_detect_placeholders_full_content_placeholder(self):
        """Test detection of [Full content from file...] placeholder."""
        content = "This is content [Full content from file...] with placeholder"
        result = detect_placeholders(content)
        
        assert result["has_placeholder"] is True
        assert result["placeholder_count"] > 0
        assert len(result["placeholder_types"]) > 0
    
    def test_detect_placeholders_todo_placeholder(self):
        """Test detection of [TODO: ...] placeholder."""
        content = "This has [TODO: fix this] a todo placeholder"
        result = detect_placeholders(content)
        
        assert result["has_placeholder"] is True
        assert result["placeholder_count"] > 0
    
    def test_detect_placeholders_multiple_placeholders(self):
        """Test detection of multiple placeholders."""
        content = "[TODO: task1] Some content [TBD: task2] more content [Full content from file...]"
        result = detect_placeholders(content)
        
        assert result["has_placeholder"] is True
        assert result["placeholder_count"] >= 3
    
    def test_detect_placeholders_case_insensitive(self):
        """Test that placeholder detection is case-insensitive."""
        content = "This has [todo: test] and [TBD: test] placeholders"
        result = detect_placeholders(content)
        
        assert result["has_placeholder"] is True


class TestVerifyHashIntegrity:
    """Test verify_hash_integrity function."""
    
    def test_verify_hash_integrity_no_stored_hash(self):
        """Test hash verification when no stored hash exists."""
        result = verify_hash_integrity("Test content", None)
        
        assert result["hash_valid"] is False
        assert result["match"] is False
        assert "error" in result
        assert "No stored hash" in result["error"]
    
    def test_verify_hash_integrity_valid_hash(self):
        """Test hash verification with valid matching hash."""
        content = "Test content"
        normalized = normalize_content(content)
        computed_hash = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
        
        result = verify_hash_integrity(content, computed_hash)
        
        assert result["hash_valid"] is True
        assert result["match"] is True
        assert result["computed_hash"] == computed_hash
        assert result["stored_hash"] == computed_hash
    
    def test_verify_hash_integrity_invalid_hash(self):
        """Test hash verification with mismatched hash."""
        content = "Test content"
        wrong_hash = "wrong_hash_value_12345"
        
        result = verify_hash_integrity(content, wrong_hash)
        
        assert result["hash_valid"] is False
        assert result["match"] is False
        assert result["computed_hash"] != wrong_hash
        assert result["stored_hash"] == wrong_hash
    
    def test_verify_hash_integrity_normalizes_content(self):
        """Test that content is normalized before hashing."""
        content1 = "Test Content"
        content2 = "test content"  # Different case
        normalized = normalize_content(content1)
        hash1 = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
        
        # Both should produce same hash after normalization
        result1 = verify_hash_integrity(content1, hash1)
        result2 = verify_hash_integrity(content2, hash1)
        
        assert result1["hash_valid"] is True
        assert result2["hash_valid"] is True


class TestVerifyContentQuality:
    """Test verify_content_quality function."""
    
    def test_verify_content_quality_perfect_document(self):
        """Test verification of a perfect document."""
        content = "This is a test document with sufficient content length to pass all checks."
        normalized = normalize_content(content)
        content_hash = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
        
        doc = Document(
            content=content,
            meta={
                "doc_id": "test1",
                "version": "v1.0",
                "category": "user_rule",
                "hash_content": content_hash,
                "status": "active"
            },
            id="doc1"
        )
        
        result = verify_content_quality(doc)
        
        assert result["status"] == "pass"
        assert result["quality_score"] >= 0.8
        assert len(result["issues"]) == 0
        assert result["document_id"] == "doc1"
        assert result["doc_id"] == "test1"
    
    def test_verify_content_quality_no_content(self):
        """Test verification of document with no content."""
        doc = Document(
            content="",
            meta={"doc_id": "test1"},
            id="doc1"
        )
        
        result = verify_content_quality(doc)
        
        assert result["status"] == "fail"
        assert result["quality_score"] < 0.8
        assert any("no content" in issue.lower() for issue in result["issues"])
    
    def test_verify_content_quality_short_content(self):
        """Test verification of document with content too short."""
        content = "Short"  # Less than MIN_CONTENT_LENGTH
        doc = Document(
            content=content,
            meta={"doc_id": "test1"},
            id="doc1"
        )
        
        result = verify_content_quality(doc)
        
        assert result["status"] == "fail"
        assert any("too short" in issue.lower() for issue in result["issues"])
        assert result["checks"]["min_length"] is False
    
    def test_verify_content_quality_with_placeholders(self):
        """Test verification of document with placeholders."""
        content = "This is content [TODO: fix this] with placeholder"
        normalized = normalize_content(content)
        content_hash = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
        
        doc = Document(
            content=content,
            meta={
                "doc_id": "test1",
                "version": "v1.0",
                "category": "user_rule",
                "hash_content": content_hash,
                "status": "active"
            },
            id="doc1"
        )
        
        result = verify_content_quality(doc)
        
        assert result["checks"]["no_placeholders"] is False
        assert any("placeholder" in issue.lower() for issue in result["issues"])
    
    def test_verify_content_quality_missing_metadata(self):
        """Test verification of document with missing required metadata."""
        content = "This is a test document with sufficient content length."
        doc = Document(
            content=content,
            meta={},  # Missing required fields
            id="doc1"
        )
        
        result = verify_content_quality(doc)
        
        assert result["status"] == "fail"
        assert any("missing required metadata" in issue.lower() for issue in result["issues"])
        assert result["checks"]["has_required_metadata"] is False
    
    def test_verify_content_quality_hash_mismatch(self):
        """Test verification of document with hash mismatch."""
        content = "This is a test document with sufficient content length."
        wrong_hash = "wrong_hash_12345"
        
        doc = Document(
            content=content,
            meta={
                "doc_id": "test1",
                "version": "v1.0",
                "category": "user_rule",
                "hash_content": wrong_hash,
                "status": "active"
            },
            id="doc1"
        )
        
        result = verify_content_quality(doc)
        
        assert result["checks"]["hash_valid"] is False
        assert any("hash" in issue.lower() for issue in result["issues"])
    
    def test_verify_content_quality_invalid_status(self):
        """Test verification of document with invalid status."""
        content = "This is a test document with sufficient content length."
        normalized = normalize_content(content)
        content_hash = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
        
        doc = Document(
            content=content,
            meta={
                "doc_id": "test1",
                "version": "v1.0",
                "category": "user_rule",
                "hash_content": content_hash,
                "status": "invalid_status"
            },
            id="doc1"
        )
        
        result = verify_content_quality(doc)
        
        assert any("invalid status" in issue.lower() for issue in result["issues"])
    
    def test_verify_content_quality_missing_file_path(self):
        """Test verification when file_path is expected but missing."""
        content = "This is a test document with sufficient content length."
        normalized = normalize_content(content)
        content_hash = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
        
        doc = Document(
            content=content,
            meta={
                "doc_id": "test1",
                "version": "v1.0",
                "category": "user_rule",  # Categories that should have file_path
                "hash_content": content_hash,
                "status": "active"
                # Missing file_path
            },
            id="doc1"
        )
        
        result = verify_content_quality(doc)
        
        # Should warn about missing file_path for these categories
        assert result["checks"]["has_file_path"] is False


class TestBulkVerifyCategory:
    """Test bulk_verify_category function."""
    
    @patch('verification_service.QdrantDocumentStore')
    def test_bulk_verify_category_success(self, mock_document_store_class):
        """Test bulk verification of a category."""
        # Create mock documents
        content = "This is a test document with sufficient content length."
        normalized = normalize_content(content)
        content_hash = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
        
        mock_docs = [
            Document(
                content=content,
                meta={
                    "doc_id": "test1",
                    "version": "v1.0",
                    "category": "user_rule",
                    "hash_content": content_hash,
                    "status": "active"
                },
                id="doc1"
            ),
            Document(
                content=content,
                meta={
                    "doc_id": "test2",
                    "version": "v1.0",
                    "category": "user_rule",
                    "hash_content": content_hash,
                    "status": "active"
                },
                id="doc2"
            )
        ]
        
        document_store = QdrantDocumentStore(
            url="http://localhost:6333",
            index="test",
            embedding_dim=384
        )
        document_store.filter_documents = Mock(return_value=mock_docs)
        
        result = bulk_verify_category(document_store, None, category="user_rule")
        
        assert result["category"] == "user_rule"
        assert result["total"] == 2
        assert result["passed"] >= 0
        assert result["failed"] >= 0
        assert "average_quality_score" in result
        assert "summary" in result
    
    @patch('verification_service.QdrantDocumentStore')
    def test_bulk_verify_category_empty(self, mock_document_store_class):
        """Test bulk verification with no documents in category."""
        document_store = QdrantDocumentStore(
            url="http://localhost:6333",
            index="test",
            embedding_dim=384
        )
        document_store.filter_documents = Mock(return_value=[])
        
        result = bulk_verify_category(document_store, None, category="user_rule")
        
        assert result["category"] == "user_rule"
        assert result["total"] == 0
        assert result["passed"] == 0
        assert result["failed"] == 0
    
    @patch('verification_service.QdrantDocumentStore')
    def test_bulk_verify_category_with_max_documents(self, mock_document_store_class):
        """Test bulk verification with max_documents limit."""
        mock_docs = [Document(content=f"Doc {i}", meta={"category": "user_rule"}, id=f"doc{i}") 
                     for i in range(10)]
        
        document_store = QdrantDocumentStore(
            url="http://localhost:6333",
            index="test",
            embedding_dim=384
        )
        document_store.filter_documents = Mock(return_value=mock_docs)
        
        result = bulk_verify_category(document_store, None, category="user_rule", max_documents=5)
        
        assert result["total"] == 5  # Should be limited to max_documents
    
    @patch('verification_service.QdrantDocumentStore')
    def test_bulk_verify_category_with_code_store(self, mock_document_store_class):
        """Test bulk verification with both document stores."""
        mock_docs_main = [Document(content="Doc 1", meta={"category": "user_rule"}, id="doc1")]
        mock_docs_code = [Document(content="Doc 2", meta={"category": "user_rule"}, id="doc2")]
        
        document_store = QdrantDocumentStore(
            url="http://localhost:6333",
            index="test",
            embedding_dim=384
        )
        document_store.filter_documents = Mock(return_value=mock_docs_main)
        
        code_document_store = QdrantDocumentStore(
            url="http://localhost:6333",
            index="test_code",
            embedding_dim=384
        )
        code_document_store.filter_documents = Mock(return_value=mock_docs_code)
        
        result = bulk_verify_category(document_store, code_document_store, category="user_rule")
        
        assert result["total"] == 2  # Should include docs from both stores

