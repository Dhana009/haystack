"""
Unit tests for update_service module.

Tests: update_document_content, update_document_metadata, deprecate_version, get_version_history.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from haystack.dataclasses.document import Document
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from haystack.components.embedders import SentenceTransformersDocumentEmbedder

from update_service import (
    update_document_content,
    update_document_metadata,
    deprecate_version,
    get_version_history,
)


class TestUpdateDocumentContent:
    """Test update_document_content function."""
    
    @patch('update_service._get_qdrant_client')
    def test_update_document_content_success(self, mock_get_client):
        """Test successful document content update."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        from qdrant_client.models import ScoredPoint
        existing_point = ScoredPoint(
            id="doc1",
            score=1.0,
            payload={
                "content": "Old content",
                "meta": {
                    "doc_id": "test1",
                    "category": "user_rule",
                    "hash_content": "old_hash"
                }
            },
            vector=[0.1, 0.2, 0.3]
        )
        mock_client.retrieve.return_value = [existing_point]
        mock_client.upsert.return_value = None
        
        embedder = Mock()
        embedder.run.return_value = {
            "documents": [Document(content="New content", embedding=[0.4, 0.5, 0.6])]
        }
        
        document_store = Mock()
        document_store.index = "test_collection"
        
        result = update_document_content(
            document_store,
            "doc1",
            "New content",
            embedder
        )
        
        assert result["status"] == "success"
        assert result["document_id"] == "doc1"
        mock_client.upsert.assert_called_once()
    
    @patch('update_service._get_qdrant_client')
    def test_update_document_content_not_found(self, mock_get_client):
        """Test update when document doesn't exist."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.retrieve.return_value = []
        
        document_store = Mock()
        document_store.index = "test_collection"
        
        embedder = Mock()
        result = update_document_content(
            document_store,
            "nonexistent_doc",
            "New content",
            embedder
        )
        
        assert result["status"] == "error"
        assert "not found" in result["error"].lower()
    
    @patch('update_service._get_qdrant_client')
    def test_update_document_content_with_metadata_updates(self, mock_get_client):
        """Test content update with additional metadata updates."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        from qdrant_client.models import ScoredPoint
        existing_point = ScoredPoint(
            id="doc1",
            score=1.0,
            payload={
                "content": "Old content",
                "meta": {"doc_id": "test1", "category": "user_rule", "hash_content": "old_hash"}
            },
            vector=[0.1, 0.2, 0.3]
        )
        mock_client.retrieve.return_value = [existing_point]
        mock_client.upsert.return_value = None
        
        embedder = Mock()
        embedder.run.return_value = {
            "documents": [Document(content="New content", embedding=[0.4, 0.5, 0.6])]
        }
        
        document_store = Mock()
        document_store.index = "test_collection"
        
        metadata_updates = {"tags": ["updated", "new"]}
        result = update_document_content(
            document_store,
            "doc1",
            "New content",
            embedder,
            metadata_updates=metadata_updates
        )
        
        assert result["status"] == "success"
        assert "tags" in result["updated_fields"]


class TestUpdateDocumentMetadata:
    """Test update_document_metadata function."""
    
    @patch('update_service._get_qdrant_client')
    def test_update_document_metadata_success(self, mock_get_client):
        """Test successful metadata update."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        from qdrant_client.models import ScoredPoint
        existing_point = ScoredPoint(
            id="doc1",
            score=1.0,
            payload={
                "content": "Test content",
                "meta": {"doc_id": "test1", "category": "user_rule", "status": "active"}
            },
            vector=[0.1, 0.2, 0.3]
        )
        mock_client.retrieve.return_value = [existing_point]
        mock_client.upsert.return_value = None
        
        document_store = Mock()
        document_store.index = "test_collection"
        
        metadata_updates = {"status": "deprecated", "tags": ["archived"]}
        result = update_document_metadata(
            document_store,
            "doc1",
            metadata_updates
        )
        
        assert result["status"] == "success"
        assert result["document_id"] == "doc1"
        assert "status" in result["updated_fields"]
        mock_client.upsert.assert_called_once()
    
    @patch('update_service._get_qdrant_client')
    def test_update_document_metadata_not_found(self, mock_get_client):
        """Test metadata update when document doesn't exist."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.retrieve.return_value = []
        
        document_store = Mock()
        document_store.index = "test_collection"
        
        result = update_document_metadata(
            document_store,
            "nonexistent_doc",
            {"status": "deprecated"}
        )
        
        assert result["status"] == "error"
        assert "not found" in result["error"].lower()


class TestDeprecateVersion:
    """Test deprecate_version function."""
    
    @patch('update_service.update_document_metadata')
    def test_deprecate_version(self, mock_update_metadata):
        """Test deprecating a document version."""
        mock_update_metadata.return_value = {
            "status": "success",
            "document_id": "doc1",
            "message": "Document metadata updated successfully",
            "updated_fields": ["status"]
        }
        
        document_store = Mock()
        result = deprecate_version(document_store, "doc1")
        
        assert result["status"] == "success"
        mock_update_metadata.assert_called_once_with(
            document_store,
            "doc1",
            {"status": "deprecated"},
            collection_name=None
        )


class TestGetVersionHistory:
    """Test get_version_history function."""
    
    @patch('update_service.query_by_doc_id')
    def test_get_version_history_success(self, mock_query):
        """Test retrieving version history."""
        mock_docs = [
            Document(
                content="Version 1",
                meta={"doc_id": "test1", "version": "v1.0", "created_at": "2025-01-01T00:00:00Z"},
                id="doc1"
            ),
            Document(
                content="Version 2",
                meta={"doc_id": "test1", "version": "v2.0", "created_at": "2025-01-02T00:00:00Z"},
                id="doc2"
            )
        ]
        mock_query.return_value = mock_docs
        
        document_store = Mock()
        result = get_version_history(document_store, "test1")
        
        assert len(result) == 2
        assert result[0].meta["version"] == "v1.0"
        assert result[1].meta["version"] == "v2.0"
        mock_query.assert_called_once()
    
    @patch('update_service.query_by_doc_id')
    def test_get_version_history_with_category(self, mock_query):
        """Test retrieving version history with category filter."""
        mock_docs = [Document(content="Test", meta={"doc_id": "test1", "version": "v1.0"}, id="doc1")]
        mock_query.return_value = mock_docs
        
        document_store = Mock()
        result = get_version_history(document_store, "test1", category="user_rule")
        
        assert len(result) == 1
        call_kwargs = mock_query.call_args[1]
        assert call_kwargs["category"] == "user_rule"
    
    @patch('update_service.query_by_doc_id')
    def test_get_version_history_exclude_deprecated(self, mock_query):
        """Test retrieving version history excluding deprecated versions."""
        mock_docs = [
            Document(content="Active", meta={"doc_id": "test1", "version": "v1.0", "status": "active"}, id="doc1"),
            Document(content="Deprecated", meta={"doc_id": "test1", "version": "v2.0", "status": "deprecated"}, id="doc2")
        ]
        mock_query.return_value = mock_docs
        
        document_store = Mock()
        result = get_version_history(document_store, "test1", include_deprecated=False)
        
        call_kwargs = mock_query.call_args[1]
        assert call_kwargs["status"] == "active"

