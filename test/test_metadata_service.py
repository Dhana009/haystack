"""
Unit tests for metadata_service module.

Tests: build_metadata_schema, validate_metadata, query_by_file_path,
query_by_content_hash, query_by_doc_id.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime
from haystack.dataclasses.document import Document
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore

from metadata_service import (
    build_metadata_schema,
    validate_metadata,
    query_by_file_path,
    query_by_content_hash,
    query_by_doc_id,
    VALID_CATEGORIES,
    VALID_SOURCES,
    VALID_STATUSES,
    REQUIRED_METADATA_FIELDS,
)


class TestBuildMetadataSchema:
    """Test build_metadata_schema function."""
    
    def test_build_metadata_basic(self):
        """Test basic metadata schema building."""
        content = "Test content"
        doc_id = "test_doc_1"
        category = "user_rule"
        hash_content = "abc123def456"
        
        metadata = build_metadata_schema(
            content=content,
            doc_id=doc_id,
            category=category,
            hash_content=hash_content
        )
        
        assert metadata["doc_id"] == doc_id
        assert metadata["category"] == category
        assert metadata["hash_content"] == hash_content
        assert metadata["content_hash"] == hash_content  # Alias
        assert metadata["source"] == "manual"
        assert metadata["repo"] == "qdrant_haystack"
        assert metadata["status"] == "active"
        assert "version" in metadata
        assert "created_at" in metadata
        assert "updated_at" in metadata
        assert "metadata_hash" in metadata
        assert isinstance(metadata["tags"], list)
    
    def test_build_metadata_required_fields(self):
        """Test that all required fields are present."""
        metadata = build_metadata_schema(
            content="Test",
            doc_id="test1",
            category="user_rule",
            hash_content="hash123"
        )
        
        for field in REQUIRED_METADATA_FIELDS:
            assert field in metadata, f"Required field {field} missing"
    
    def test_build_metadata_validation_errors(self):
        """Test validation errors for invalid inputs."""
        # Missing doc_id
        with pytest.raises(ValueError, match="doc_id is required"):
            build_metadata_schema("content", "", "user_rule", "hash")
        
        # Missing category
        with pytest.raises(ValueError, match="category is required"):
            build_metadata_schema("content", "doc1", "", "hash")
        
        # Invalid category
        with pytest.raises(ValueError, match="category must be one of"):
            build_metadata_schema("content", "doc1", "invalid_category", "hash")
        
        # Missing hash_content
        with pytest.raises(ValueError, match="hash_content is required"):
            build_metadata_schema("content", "doc1", "user_rule", "")
        
        # Invalid source
        with pytest.raises(ValueError, match="source must be one of"):
            build_metadata_schema("content", "doc1", "user_rule", "hash", source="invalid")
        
        # Invalid status
        with pytest.raises(ValueError, match="status must be one of"):
            build_metadata_schema("content", "doc1", "user_rule", "hash", status="invalid")
    
    def test_build_metadata_with_file_path(self):
        """Test metadata with file_path."""
        metadata = build_metadata_schema(
            content="Test",
            doc_id="test1",
            category="user_rule",
            hash_content="hash123",
            file_path="/path/to/file.txt"
        )
        
        assert metadata["file_path"] == "/path/to/file.txt"
        assert metadata["path"] == "/path/to/file.txt"
    
    def test_build_metadata_with_version(self):
        """Test metadata with custom version."""
        version = "v1.0"
        metadata = build_metadata_schema(
            content="Test",
            doc_id="test1",
            category="user_rule",
            hash_content="hash123",
            version=version
        )
        
        assert metadata["version"] == version
    
    def test_build_metadata_with_tags(self):
        """Test metadata with tags."""
        tags = ["tag1", "tag2", "tag3"]
        metadata = build_metadata_schema(
            content="Test",
            doc_id="test1",
            category="user_rule",
            hash_content="hash123",
            tags=tags
        )
        
        assert metadata["tags"] == tags
    
    def test_build_metadata_with_additional_metadata(self):
        """Test metadata with additional fields."""
        additional = {"custom_field": "custom_value", "another": 123}
        metadata = build_metadata_schema(
            content="Test",
            doc_id="test1",
            category="user_rule",
            hash_content="hash123",
            additional_metadata=additional
        )
        
        assert metadata["custom_field"] == "custom_value"
        assert metadata["another"] == 123
    
    def test_build_metadata_metadata_hash_consistency(self):
        """Test that metadata_hash is consistent for same metadata."""
        metadata1 = build_metadata_schema(
            content="Test",
            doc_id="test1",
            category="user_rule",
            hash_content="hash123",
            version="v1.0"
        )
        
        metadata2 = build_metadata_schema(
            content="Test",
            doc_id="test1",
            category="user_rule",
            hash_content="hash123",
            version="v1.0"
        )
        
        # Metadata hash should be same (excluding timestamps)
        assert metadata1["metadata_hash"] == metadata2["metadata_hash"]
    
    def test_build_metadata_all_valid_categories(self):
        """Test that all valid categories work."""
        for category in VALID_CATEGORIES:
            metadata = build_metadata_schema(
                content="Test",
                doc_id=f"test_{category}",
                category=category,
                hash_content="hash123"
            )
            assert metadata["category"] == category


class TestValidateMetadata:
    """Test validate_metadata function."""
    
    def test_validate_metadata_valid(self):
        """Test validation of valid metadata."""
        metadata = {
            "doc_id": "test1",
            "version": "v1.0",
            "category": "user_rule",
            "hash_content": "hash123"
        }
        
        is_valid, error_message = validate_metadata(metadata)
        assert is_valid is True
        assert error_message is None
    
    def test_validate_metadata_missing_required_fields(self):
        """Test validation with missing required fields."""
        metadata = {
            "doc_id": "test1",
            # Missing version, category, hash_content
        }
        
        is_valid, error_message = validate_metadata(metadata)
        assert is_valid is False
        assert error_message is not None
        assert "required" in error_message.lower() or "missing" in error_message.lower()
    
    def test_validate_metadata_invalid_category(self):
        """Test validation with invalid category."""
        metadata = {
            "doc_id": "test1",
            "version": "v1.0",
            "category": "invalid_category",
            "hash_content": "hash123"
        }
        
        is_valid, error_message = validate_metadata(metadata)
        assert is_valid is False
        assert "category" in error_message.lower()
    
    def test_validate_metadata_invalid_source(self):
        """Test validation with invalid source."""
        metadata = {
            "doc_id": "test1",
            "version": "v1.0",
            "category": "user_rule",
            "hash_content": "hash123",
            "source": "invalid_source"
        }
        
        is_valid, error_message = validate_metadata(metadata)
        assert is_valid is False
        assert "source" in error_message.lower()


class TestQueryByFilePath:
    """Test query_by_file_path function."""
    
    @patch('metadata_service.QdrantDocumentStore')
    def test_query_by_file_path_found(self, mock_document_store_class):
        """Test querying by file path when document exists."""
        # Setup mock
        mock_doc = Document(
            content="Test content",
            meta={"file_path": "/path/to/file.txt", "doc_id": "test1"}
        )
        mock_document_store = Mock()
        mock_document_store.filter_documents.return_value = [mock_doc]
        mock_document_store_class.return_value = mock_document_store
        
        # Create actual document store instance
        document_store = QdrantDocumentStore(
            url="http://localhost:6333",
            index="test",
            embedding_dim=384
        )
        document_store.filter_documents = Mock(return_value=[mock_doc])
        
        result = query_by_file_path(document_store, "/path/to/file.txt")
        
        assert len(result) == 1
        assert result[0] == mock_doc
        document_store.filter_documents.assert_called_once()
    
    @patch('metadata_service.QdrantDocumentStore')
    def test_query_by_file_path_not_found(self, mock_document_store_class):
        """Test querying by file path when document doesn't exist."""
        document_store = QdrantDocumentStore(
            url="http://localhost:6333",
            index="test",
            embedding_dim=384
        )
        document_store.filter_documents = Mock(return_value=[])
        
        result = query_by_file_path(document_store, "/nonexistent/path.txt")
        
        assert len(result) == 0
    
    @patch('metadata_service.QdrantDocumentStore')
    def test_query_by_file_path_with_status(self, mock_document_store_class):
        """Test querying by file path with status filter."""
        mock_doc = Document(
            content="Test",
            meta={"file_path": "/path/to/file.txt", "status": "active"}
        )
        document_store = QdrantDocumentStore(
            url="http://localhost:6333",
            index="test",
            embedding_dim=384
        )
        document_store.filter_documents = Mock(return_value=[mock_doc])
        
        result = query_by_file_path(document_store, "/path/to/file.txt", status="active")
        
        assert len(result) == 1
        # Verify filter was called with status
        call_args = document_store.filter_documents.call_args
        assert call_args is not None


class TestQueryByContentHash:
    """Test query_by_content_hash function."""
    
    @patch('metadata_service.QdrantDocumentStore')
    def test_query_by_content_hash_found(self, mock_document_store_class):
        """Test querying by content hash when document exists."""
        mock_doc = Document(
            content="Test content",
            meta={"hash_content": "abc123", "doc_id": "test1"}
        )
        document_store = QdrantDocumentStore(
            url="http://localhost:6333",
            index="test",
            embedding_dim=384
        )
        document_store.filter_documents = Mock(return_value=[mock_doc])
        
        result = query_by_content_hash(document_store, "abc123")
        
        assert len(result) == 1
        assert result[0] == mock_doc
    
    @patch('metadata_service.QdrantDocumentStore')
    def test_query_by_content_hash_fallback(self, mock_document_store_class):
        """Test querying by content_hash alias when hash_content not found."""
        mock_doc = Document(
            content="Test content",
            meta={"content_hash": "abc123", "doc_id": "test1"}  # Using alias
        )
        document_store = QdrantDocumentStore(
            url="http://localhost:6333",
            index="test",
            embedding_dim=384
        )
        # First call returns empty, second call (fallback) returns doc
        document_store.filter_documents = Mock(side_effect=[[], [mock_doc]])
        
        result = query_by_content_hash(document_store, "abc123")
        
        assert len(result) == 1
        assert document_store.filter_documents.call_count == 2


class TestQueryByDocId:
    """Test query_by_doc_id function."""
    
    @patch('metadata_service.QdrantDocumentStore')
    def test_query_by_doc_id_found(self, mock_document_store_class):
        """Test querying by doc_id when document exists."""
        mock_doc = Document(
            content="Test content",
            meta={"doc_id": "test_doc_1", "category": "user_rule"}
        )
        document_store = QdrantDocumentStore(
            url="http://localhost:6333",
            index="test",
            embedding_dim=384
        )
        document_store.filter_documents = Mock(return_value=[mock_doc])
        
        result = query_by_doc_id(document_store, "test_doc_1")
        
        assert len(result) == 1
        assert result[0] == mock_doc
    
    @patch('metadata_service.QdrantDocumentStore')
    def test_query_by_doc_id_with_category(self, mock_document_store_class):
        """Test querying by doc_id with category filter."""
        mock_doc = Document(
            content="Test",
            meta={"doc_id": "test1", "category": "user_rule"}
        )
        document_store = QdrantDocumentStore(
            url="http://localhost:6333",
            index="test",
            embedding_dim=384
        )
        document_store.filter_documents = Mock(return_value=[mock_doc])
        
        result = query_by_doc_id(document_store, "test1", category="user_rule")
        
        assert len(result) == 1
    
    @patch('metadata_service.QdrantDocumentStore')
    def test_query_by_doc_id_with_status(self, mock_document_store_class):
        """Test querying by doc_id with status filter."""
        mock_doc = Document(
            content="Test",
            meta={"doc_id": "test1", "status": "active"}
        )
        document_store = QdrantDocumentStore(
            url="http://localhost:6333",
            index="test",
            embedding_dim=384
        )
        document_store.filter_documents = Mock(return_value=[mock_doc])
        
        result = query_by_doc_id(document_store, "test1", status="active")
        
        assert len(result) == 1
    
    @patch('metadata_service.QdrantDocumentStore')
    def test_query_by_doc_id_not_found(self, mock_document_store_class):
        """Test querying by doc_id when document doesn't exist."""
        document_store = QdrantDocumentStore(
            url="http://localhost:6333",
            index="test",
            embedding_dim=384
        )
        document_store.filter_documents = Mock(return_value=[])
        
        result = query_by_doc_id(document_store, "nonexistent_doc")
        
        assert len(result) == 0

