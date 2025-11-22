"""
Unit tests for bulk_operations_service module.

Tests: _convert_haystack_filter_to_qdrant (all operators), delete_by_filter,
delete_by_ids, update_metadata_by_filter, export_documents, import_documents.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from haystack.dataclasses.document import Document
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny, Range

from bulk_operations_service import (
    _convert_haystack_filter_to_qdrant,
    delete_by_filter,
    delete_by_ids,
    update_metadata_by_filter,
    export_documents,
    import_documents,
)


class TestConvertHaystackFilterToQdrant:
    """Test _convert_haystack_filter_to_qdrant function with all operators."""
    
    def test_convert_simple_equals(self):
        """Test conversion of simple == operator."""
        haystack_filter = {
            "field": "meta.category",
            "operator": "==",
            "value": "user_rule"
        }
        
        result = _convert_haystack_filter_to_qdrant(haystack_filter)
        
        assert result is not None
        assert isinstance(result, Filter)
        assert hasattr(result, 'must')
        assert len(result.must) == 1
        assert isinstance(result.must[0], FieldCondition)
    
    def test_convert_removes_meta_prefix(self):
        """Test that meta. prefix is removed from field names."""
        haystack_filter = {
            "field": "meta.category",
            "operator": "==",
            "value": "user_rule"
        }
        
        result = _convert_haystack_filter_to_qdrant(haystack_filter)
        
        assert result.must[0].key == "category"  # meta. prefix removed
    
    def test_convert_not_equals(self):
        """Test conversion of != operator."""
        haystack_filter = {
            "field": "meta.category",
            "operator": "!=",
            "value": "user_rule"
        }
        
        result = _convert_haystack_filter_to_qdrant(haystack_filter)
        
        assert result is not None
        assert hasattr(result, 'must_not')
        assert len(result.must_not) == 1
    
    def test_convert_greater_than(self):
        """Test conversion of > operator."""
        haystack_filter = {
            "field": "meta.version",
            "operator": ">",
            "value": "1.0"
        }
        
        result = _convert_haystack_filter_to_qdrant(haystack_filter)
        
        assert result is not None
        assert hasattr(result, 'must')
        assert isinstance(result.must[0].range, Range)
        assert result.must[0].range.gt == "1.0"
    
    def test_convert_greater_than_equal(self):
        """Test conversion of >= operator."""
        haystack_filter = {
            "field": "meta.version",
            "operator": ">=",
            "value": "1.0"
        }
        
        result = _convert_haystack_filter_to_qdrant(haystack_filter)
        
        assert result is not None
        assert result.must[0].range.gte == "1.0"
    
    def test_convert_less_than(self):
        """Test conversion of < operator."""
        haystack_filter = {
            "field": "meta.version",
            "operator": "<",
            "value": "2.0"
        }
        
        result = _convert_haystack_filter_to_qdrant(haystack_filter)
        
        assert result is not None
        assert result.must[0].range.lt == "2.0"
    
    def test_convert_less_than_equal(self):
        """Test conversion of <= operator."""
        haystack_filter = {
            "field": "meta.version",
            "operator": "<=",
            "value": "2.0"
        }
        
        result = _convert_haystack_filter_to_qdrant(haystack_filter)
        
        assert result is not None
        assert result.must[0].range.lte == "2.0"
    
    def test_convert_in_operator(self):
        """Test conversion of 'in' operator."""
        haystack_filter = {
            "field": "meta.category",
            "operator": "in",
            "value": ["user_rule", "project_rule"]
        }
        
        result = _convert_haystack_filter_to_qdrant(haystack_filter)
        
        assert result is not None
        assert isinstance(result.must[0].match, MatchAny)
        assert result.must[0].match.any == ["user_rule", "project_rule"]
    
    def test_convert_in_operator_single_value(self):
        """Test 'in' operator with single value (should convert to list)."""
        haystack_filter = {
            "field": "meta.category",
            "operator": "in",
            "value": "user_rule"  # Single value, not list
        }
        
        result = _convert_haystack_filter_to_qdrant(haystack_filter)
        
        assert result is not None
        assert isinstance(result.must[0].match, MatchAny)
        assert result.must[0].match.any == ["user_rule"]
    
    def test_convert_not_in_operator(self):
        """Test conversion of 'not in' operator."""
        haystack_filter = {
            "field": "meta.category",
            "operator": "not in",
            "value": ["other"]
        }
        
        result = _convert_haystack_filter_to_qdrant(haystack_filter)
        
        assert result is not None
        assert hasattr(result, 'must_not')
        assert isinstance(result.must_not[0].match, MatchAny)
    
    def test_convert_and_operator(self):
        """Test conversion of AND operator with multiple conditions."""
        haystack_filter = {
            "operator": "AND",
            "conditions": [
                {"field": "meta.category", "operator": "==", "value": "user_rule"},
                {"field": "meta.status", "operator": "==", "value": "active"}
            ]
        }
        
        result = _convert_haystack_filter_to_qdrant(haystack_filter)
        
        assert result is not None
        assert hasattr(result, 'must')
        assert len(result.must) == 2  # Both conditions in must array
    
    def test_convert_or_operator(self):
        """Test conversion of OR operator."""
        haystack_filter = {
            "operator": "OR",
            "conditions": [
                {"field": "meta.category", "operator": "==", "value": "user_rule"},
                {"field": "meta.category", "operator": "==", "value": "project_rule"}
            ]
        }
        
        result = _convert_haystack_filter_to_qdrant(haystack_filter)
        
        assert result is not None
        assert hasattr(result, 'should')
        assert len(result.should) == 2
    
    def test_convert_not_operator(self):
        """Test conversion of NOT operator."""
        haystack_filter = {
            "operator": "NOT",
            "conditions": [
                {"field": "meta.category", "operator": "==", "value": "other"}
            ]
        }
        
        result = _convert_haystack_filter_to_qdrant(haystack_filter)
        
        assert result is not None
        assert hasattr(result, 'must_not')
    
    def test_convert_empty_filter(self):
        """Test conversion of empty filter."""
        result = _convert_haystack_filter_to_qdrant({})
        assert result is None
    
    def test_convert_none_filter(self):
        """Test conversion of None filter."""
        result = _convert_haystack_filter_to_qdrant(None)
        assert result is None
    
    def test_convert_direct_field_no_meta_prefix(self):
        """Test conversion of field without meta. prefix."""
        haystack_filter = {
            "field": "content",
            "operator": "==",
            "value": "test"
        }
        
        result = _convert_haystack_filter_to_qdrant(haystack_filter)
        
        assert result is not None
        assert result.must[0].key == "content"  # No prefix removal


class TestDeleteByFilter:
    """Test delete_by_filter function."""
    
    @patch('bulk_operations_service._get_qdrant_client')
    def test_delete_by_filter_success(self, mock_get_client):
        """Test successful deletion by filter."""
        # Setup mocks
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # Mock scroll results
        from qdrant_client.models import ScoredPoint
        mock_points = [
            ScoredPoint(id=1, score=1.0, payload={}, vector=None),
            ScoredPoint(id=2, score=1.0, payload={}, vector=None),
        ]
        mock_client.scroll.return_value = (mock_points, None)
        mock_client.delete.return_value = None
        
        document_store = Mock()
        document_store.index = "test_collection"
        
        filters = {"field": "meta.category", "operator": "==", "value": "user_rule"}
        result = delete_by_filter(document_store, filters)
        
        assert result["status"] == "success"
        assert result["deleted_count"] == 2
        mock_client.delete.assert_called_once()
    
    @patch('bulk_operations_service._get_qdrant_client')
    def test_delete_by_filter_no_matches(self, mock_get_client):
        """Test deletion when no documents match filter."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.scroll.return_value = ([], None)
        
        document_store = Mock()
        document_store.index = "test_collection"
        
        filters = {"field": "meta.category", "operator": "==", "value": "nonexistent"}
        result = delete_by_filter(document_store, filters)
        
        assert result["status"] == "success"
        assert result["deleted_count"] == 0
        mock_client.delete.assert_not_called()
    
    @patch('bulk_operations_service._get_qdrant_client')
    def test_delete_by_filter_pagination(self, mock_get_client):
        """Test deletion with pagination (multiple scroll calls)."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        from qdrant_client.models import ScoredPoint
        # First scroll returns points with next_offset, second returns empty
        mock_points1 = [ScoredPoint(id=i, score=1.0, payload={}, vector=None) for i in range(100)]
        mock_points2 = []
        mock_client.scroll.side_effect = [
            (mock_points1, "next_offset_123"),
            (mock_points2, None)
        ]
        mock_client.delete.return_value = None
        
        document_store = Mock()
        document_store.index = "test_collection"
        
        filters = {"field": "meta.category", "operator": "==", "value": "user_rule"}
        result = delete_by_filter(document_store, filters)
        
        assert result["status"] == "success"
        assert result["deleted_count"] == 100
        assert mock_client.scroll.call_count == 2


class TestDeleteByIds:
    """Test delete_by_ids function."""
    
    def test_delete_by_ids_success(self):
        """Test successful deletion by IDs."""
        document_store = Mock()
        document_store.delete_documents = Mock(return_value=None)
        
        document_ids = ["doc1", "doc2", "doc3"]
        result = delete_by_ids(document_store, document_ids)
        
        assert result["status"] == "success"
        assert result["deleted_count"] == 3
        document_store.delete_documents.assert_called_once_with(document_ids)
    
    def test_delete_by_ids_empty_list(self):
        """Test deletion with empty ID list."""
        document_store = Mock()
        
        result = delete_by_ids(document_store, [])
        
        assert result["status"] == "success"
        assert result["deleted_count"] == 0
        document_store.delete_documents.assert_not_called()


class TestUpdateMetadataByFilter:
    """Test update_metadata_by_filter function."""
    
    @patch('bulk_operations_service._get_qdrant_client')
    def test_update_metadata_by_filter_success(self, mock_get_client):
        """Test successful metadata update by filter."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        from qdrant_client.models import ScoredPoint
        mock_point = ScoredPoint(
            id=1,
            score=1.0,
            payload={"meta": {"category": "user_rule", "status": "active"}},
            vector=[0.1, 0.2, 0.3]
        )
        mock_client.scroll.return_value = ([mock_point], None)
        mock_client.upsert.return_value = None
        
        document_store = Mock()
        document_store.index = "test_collection"
        
        filters = {"field": "meta.category", "operator": "==", "value": "user_rule"}
        metadata_updates = {"status": "deprecated", "updated_at": "2025-01-01T00:00:00Z"}
        
        result = update_metadata_by_filter(document_store, filters, metadata_updates)
        
        assert result["status"] == "success"
        assert result["updated_count"] == 1
        mock_client.upsert.assert_called_once()


class TestExportDocuments:
    """Test export_documents function."""
    
    def test_export_documents_success(self):
        """Test successful document export."""
        document_store = Mock()
        mock_docs = [
            Document(
                content="Content 1",
                meta={"doc_id": "doc1", "category": "user_rule"},
                id="id1"
            ),
            Document(
                content="Content 2",
                meta={"doc_id": "doc2", "category": "project_rule"},
                id="id2"
            )
        ]
        document_store.filter_documents = Mock(return_value=mock_docs)
        
        filters = {"field": "meta.category", "operator": "==", "value": "user_rule"}
        result = export_documents(document_store, filters)
        
        assert result["status"] == "success"
        assert result["exported_count"] == 2
        assert "documents" in result
        assert len(result["documents"]) == 2
    
    def test_export_documents_no_filters(self):
        """Test export with no filters (exports all)."""
        document_store = Mock()
        mock_docs = [Document(content="Test", meta={}, id="id1")]
        document_store.filter_documents = Mock(return_value=mock_docs)
        
        result = export_documents(document_store, None)
        
        assert result["status"] == "success"
        assert result["exported_count"] == 1


class TestImportDocuments:
    """Test import_documents function."""
    
    def test_import_documents_skip_strategy(self):
        """Test import with skip duplicate strategy."""
        document_store = Mock()
        document_store.write_documents = Mock(return_value=None)
        
        from metadata_service import query_by_doc_id
        with patch('bulk_operations_service.query_by_doc_id') as mock_query:
            mock_query.return_value = [Document(content="Existing", meta={"doc_id": "doc1"}, id="id1")]
            
            documents_data = [
                {
                    "content": "New content",
                    "meta": {"doc_id": "doc1", "category": "user_rule"}
                },
                {
                    "content": "Another content",
                    "meta": {"doc_id": "doc2", "category": "user_rule"}
                }
            ]
            
            result = import_documents(
                document_store,
                documents_data,
                duplicate_strategy="skip",
                embedder=None
            )
            
            assert result["status"] == "success"
            assert result["skipped_count"] == 1
            assert result["imported_count"] == 1
    
    def test_import_documents_error_strategy(self):
        """Test import with error on duplicate strategy."""
        document_store = Mock()
        
        with patch('bulk_operations_service.query_by_doc_id') as mock_query:
            mock_query.return_value = [Document(content="Existing", meta={"doc_id": "doc1"}, id="id1")]
            
            documents_data = [
                {
                    "content": "New content",
                    "meta": {"doc_id": "doc1", "category": "user_rule"}
                }
            ]
            
            result = import_documents(
                document_store,
                documents_data,
                duplicate_strategy="error",
                embedder=None
            )
            
            assert result["status"] == "success"  # Returns success but with errors
            assert len(result["errors"]) > 0
            assert result["imported_count"] == 0
    
    def test_import_documents_missing_doc_id(self):
        """Test import with missing doc_id in metadata."""
        document_store = Mock()
        
        documents_data = [
            {
                "content": "Content without doc_id",
                "meta": {"category": "user_rule"}  # Missing doc_id
            }
        ]
        
        result = import_documents(
            document_store,
            documents_data,
            duplicate_strategy="skip",
            embedder=None
        )
        
        assert len(result["errors"]) > 0
        assert any("doc_id" in str(error).lower() for error in result["errors"])

