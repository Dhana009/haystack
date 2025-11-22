"""
Unit tests for query_service module.

Tests: get_document_by_path, search_with_metadata_filters, get_metadata_stats.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from haystack.dataclasses.document import Document
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from haystack_integrations.components.retrievers.qdrant import QdrantEmbeddingRetriever

from query_service import (
    get_document_by_path,
    search_with_metadata_filters,
    get_metadata_stats,
)


class TestGetDocumentByPath:
    """Test get_document_by_path function."""
    
    @patch('query_service.query_by_file_path')
    def test_get_document_by_path_found(self, mock_query):
        """Test retrieving document by path when found."""
        mock_doc = Document(
            content="Test content",
            meta={"file_path": "/path/to/file.txt"},
            id="doc1"
        )
        mock_query.return_value = [mock_doc]
        
        document_store = Mock()
        result = get_document_by_path(document_store, "/path/to/file.txt")
        
        assert result == mock_doc
        mock_query.assert_called_once_with(document_store, "/path/to/file.txt", "active")
    
    @patch('query_service.query_by_file_path')
    def test_get_document_by_path_not_found(self, mock_query):
        """Test retrieving document by path when not found."""
        mock_query.return_value = []
        
        document_store = Mock()
        result = get_document_by_path(document_store, "/nonexistent/path.txt")
        
        assert result is None
    
    @patch('query_service.query_by_file_path')
    def test_get_document_by_path_with_status(self, mock_query):
        """Test retrieving document by path with custom status."""
        mock_doc = Document(content="Test", meta={"file_path": "/path.txt"}, id="doc1")
        mock_query.return_value = [mock_doc]
        
        document_store = Mock()
        result = get_document_by_path(document_store, "/path.txt", status="deprecated")
        
        assert result == mock_doc
        mock_query.assert_called_once_with(document_store, "/path.txt", "deprecated")


class TestSearchWithMetadataFilters:
    """Test search_with_metadata_filters function."""
    
    def test_search_with_metadata_filters_no_filters(self):
        """Test search without metadata filters."""
        document_store = Mock()
        text_embedder = Mock()
        text_embedder.run.return_value = {"embedding": [0.1, 0.2, 0.3]}
        
        retriever = Mock()
        retriever.run.return_value = {"documents": [
            Document(content="Result 1", meta={}, id="doc1"),
            Document(content="Result 2", meta={}, id="doc2")
        ]}
        
        result = search_with_metadata_filters(
            document_store,
            "test query",
            text_embedder,
            retriever=retriever,
            metadata_filters=None,
            top_k=5
        )
        
        assert len(result) == 2
        text_embedder.run.assert_called_once_with(text="test query")
        retriever.run.assert_called_once()
    
    def test_search_with_metadata_filters_with_filters(self):
        """Test search with metadata filters."""
        document_store = Mock()
        text_embedder = Mock()
        text_embedder.run.return_value = {"embedding": [0.1, 0.2, 0.3]}
        
        retriever = Mock()
        retriever.run.return_value = {"documents": [
            Document(content="Result", meta={"category": "user_rule"}, id="doc1")
        ]}
        
        metadata_filters = {
            "field": "meta.category",
            "operator": "==",
            "value": "user_rule"
        }
        
        result = search_with_metadata_filters(
            document_store,
            "test query",
            text_embedder,
            retriever=retriever,
            metadata_filters=metadata_filters,
            top_k=5
        )
        
        assert len(result) == 1
        call_kwargs = retriever.run.call_args[1]
        assert call_kwargs["filters"] == metadata_filters
    
    def test_search_with_metadata_filters_creates_retriever(self):
        """Test that retriever is created if not provided."""
        document_store = Mock()
        text_embedder = Mock()
        text_embedder.run.return_value = {"embedding": [0.1, 0.2, 0.3]}
        
        with patch('query_service.QdrantEmbeddingRetriever') as mock_retriever_class:
            mock_retriever = Mock()
            mock_retriever.run.return_value = {"documents": []}
            mock_retriever_class.return_value = mock_retriever
            
            result = search_with_metadata_filters(
                document_store,
                "test query",
                text_embedder,
                retriever=None,
                top_k=10
            )
            
            mock_retriever_class.assert_called_once_with(document_store=document_store, top_k=10)


class TestGetMetadataStats:
    """Test get_metadata_stats function."""
    
    @patch('query_service._get_qdrant_client')
    def test_get_metadata_stats_basic(self, mock_get_client):
        """Test basic metadata statistics."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        from qdrant_client.models import ScoredPoint
        mock_points = [
            ScoredPoint(
                id=1,
                score=1.0,
                payload={"meta": {"category": "user_rule", "status": "active"}},
                vector=None
            ),
            ScoredPoint(
                id=2,
                score=1.0,
                payload={"meta": {"category": "user_rule", "status": "active"}},
                vector=None
            ),
            ScoredPoint(
                id=3,
                score=1.0,
                payload={"meta": {"category": "project_rule", "status": "active"}},
                vector=None
            )
        ]
        mock_client.scroll.return_value = (mock_points, None)
        
        document_store = Mock()
        document_store.index = "test_collection"
        
        result = get_metadata_stats(document_store, group_by_fields=["category"])
        
        assert result["status"] == "success"
        assert "total_documents" in result
        assert "grouped_stats" in result
    
    @patch('query_service._get_qdrant_client')
    def test_get_metadata_stats_with_filters(self, mock_get_client):
        """Test metadata statistics with filters."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.scroll.return_value = ([], None)
        
        document_store = Mock()
        document_store.index = "test_collection"
        
        filters = {"field": "meta.category", "operator": "==", "value": "user_rule"}
        result = get_metadata_stats(document_store, filters=filters)
        
        assert result["status"] == "success"
        # Verify scroll was called with filter
        assert mock_client.scroll.called
    
    @patch('query_service._get_qdrant_client')
    def test_get_metadata_stats_multiple_group_by(self, mock_get_client):
        """Test metadata statistics with multiple group_by fields."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        from qdrant_client.models import ScoredPoint
        mock_points = [
            ScoredPoint(
                id=i,
                score=1.0,
                payload={"meta": {"category": "user_rule", "status": "active"}},
                vector=None
            ) for i in range(5)
        ]
        mock_client.scroll.return_value = (mock_points, None)
        
        document_store = Mock()
        document_store.index = "test_collection"
        
        result = get_metadata_stats(
            document_store,
            group_by_fields=["category", "status"]
        )
        
        assert result["status"] == "success"
        assert "grouped_stats" in result

