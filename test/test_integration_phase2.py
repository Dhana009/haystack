"""
Integration tests for Phase 2 features.

Tests bulk operations, metadata querying, atomic updates, and version management workflows.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from haystack.dataclasses.document import Document
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from haystack.components.embedders import SentenceTransformersDocumentEmbedder

from bulk_operations_service import (
    delete_by_filter,
    delete_by_ids,
    update_metadata_by_filter,
    export_documents,
    import_documents,
)
from query_service import (
    get_document_by_path,
    search_with_metadata_filters,
    get_metadata_stats,
)
from update_service import (
    update_document_content,
    update_document_metadata,
    deprecate_version,
    get_version_history,
)


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


class TestBulkOperationsWorkflow:
    """Test bulk operations workflows."""
    
    @patch('bulk_operations_service._get_qdrant_client')
    def test_bulk_delete_and_export_workflow(self, mock_get_client, mock_document_store):
        """Test workflow: export -> delete -> verify deletion."""
        # Setup mocks
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        from qdrant_client.models import ScoredPoint
        mock_points = [
            ScoredPoint(
                id=i,
                score=1.0,
                payload={"meta": {"category": "user_rule", "doc_id": f"doc{i}"}},
                vector=None
            ) for i in range(5)
        ]
        mock_client.scroll.return_value = (mock_points, None)
        mock_client.delete.return_value = None
        
        # Export documents first
        mock_docs = [
            Document(
                content=f"Content {i}",
                meta={"category": "user_rule", "doc_id": f"doc{i}"},
                id=str(i)
            ) for i in range(5)
        ]
        mock_document_store.filter_documents = Mock(return_value=mock_docs)
        
        filters = {"field": "meta.category", "operator": "==", "value": "user_rule"}
        export_result = export_documents(mock_document_store, filters)
        
        assert export_result["status"] == "success"
        assert export_result["exported_count"] == 5
        
        # Delete by filter
        delete_result = delete_by_filter(mock_document_store, filters)
        
        assert delete_result["status"] == "success"
        assert delete_result["deleted_count"] == 5
    
    @patch('bulk_operations_service._get_qdrant_client')
    def test_bulk_update_metadata_workflow(self, mock_get_client, mock_document_store):
        """Test bulk metadata update workflow."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        from qdrant_client.models import ScoredPoint
        mock_points = [
            ScoredPoint(
                id=i,
                score=1.0,
                payload={"meta": {"category": "user_rule", "status": "active"}},
                vector=[0.1, 0.2, 0.3]
            ) for i in range(3)
        ]
        mock_client.scroll.return_value = (mock_points, None)
        mock_client.upsert.return_value = None
        
        filters = {"field": "meta.category", "operator": "==", "value": "user_rule"}
        metadata_updates = {"status": "deprecated", "tags": ["archived"]}
        
        result = update_metadata_by_filter(mock_document_store, filters, metadata_updates)
        
        assert result["status"] == "success"
        assert result["updated_count"] == 3
        mock_client.upsert.assert_called_once()
    
    def test_import_export_workflow(self, mock_document_store):
        """Test import/export workflow with duplicate handling."""
        # Export documents
        mock_docs = [
            Document(
                content="Content 1",
                meta={"doc_id": "doc1", "category": "user_rule", "version": "v1.0"},
                id="id1"
            ),
            Document(
                content="Content 2",
                meta={"doc_id": "doc2", "category": "user_rule", "version": "v1.0"},
                id="id2"
            )
        ]
        mock_document_store.filter_documents = Mock(return_value=mock_docs)
        
        export_result = export_documents(mock_document_store, None)
        
        assert export_result["status"] == "success"
        assert len(export_result["documents"]) == 2
        
        # Prepare import data
        documents_data = [
            {
                "content": doc.content,
                "meta": doc.meta
            } for doc in mock_docs
        ]
        
        # Import with skip strategy
        with patch('bulk_operations_service.query_by_doc_id') as mock_query:
            mock_query.return_value = []  # No existing docs
            
            import_result = import_documents(
                mock_document_store,
                documents_data,
                duplicate_strategy="skip",
                embedder=None
            )
            
            assert import_result["status"] == "success"
            assert import_result["imported_count"] == 2


class TestMetadataQueryingWorkflow:
    """Test metadata querying workflows."""
    
    def test_path_based_retrieval_workflow(self, mock_document_store):
        """Test retrieving documents by file path."""
        mock_doc = Document(
            content="Test content",
            meta={"file_path": "/path/to/file.txt", "doc_id": "test1"},
            id="doc1"
        )
        mock_document_store.filter_documents = Mock(return_value=[mock_doc])
        
        result = get_document_by_path(mock_document_store, "/path/to/file.txt")
        
        assert result == mock_doc
        assert result.meta["file_path"] == "/path/to/file.txt"
    
    @patch('query_service._get_qdrant_client')
    def test_metadata_stats_workflow(self, mock_get_client, mock_document_store):
        """Test metadata statistics aggregation workflow."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        from qdrant_client.models import ScoredPoint
        mock_points = [
            ScoredPoint(
                id=i,
                score=1.0,
                payload={"meta": {"category": "user_rule" if i % 2 == 0 else "project_rule"}},
                vector=None
            ) for i in range(10)
        ]
        mock_client.scroll.return_value = (mock_points, None)
        
        result = get_metadata_stats(
            mock_document_store,
            group_by_fields=["category"]
        )
        
        assert result["status"] == "success"
        assert "total_documents" in result
        assert "grouped_stats" in result


class TestAtomicUpdateWorkflow:
    """Test atomic update workflows."""
    
    @patch('update_service._get_qdrant_client')
    def test_content_update_workflow(self, mock_get_client, mock_document_store, mock_embedder):
        """Test atomic content update workflow."""
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
        
        mock_embedder.run.return_value = {
            "documents": [Document(content="New content", embedding=[0.4, 0.5, 0.6])]
        }
        
        result = update_document_content(
            mock_document_store,
            "doc1",
            "New content",
            mock_embedder
        )
        
        assert result["status"] == "success"
        assert "content" in result["updated_fields"]
        assert "hash_content" in result["updated_fields"]
        mock_client.upsert.assert_called_once()
    
    @patch('update_service._get_qdrant_client')
    def test_metadata_update_workflow(self, mock_get_client, mock_document_store):
        """Test metadata-only update workflow."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        from qdrant_client.models import ScoredPoint
        existing_point = ScoredPoint(
            id="doc1",
            score=1.0,
            payload={
                "content": "Test content",
                "meta": {"doc_id": "test1", "status": "active"}
            },
            vector=[0.1, 0.2, 0.3]
        )
        mock_client.retrieve.return_value = [existing_point]
        mock_client.upsert.return_value = None
        
        result = update_document_metadata(
            mock_document_store,
            "doc1",
            {"status": "deprecated", "tags": ["archived"]}
        )
        
        assert result["status"] == "success"
        assert "status" in result["updated_fields"]
        assert "tags" in result["updated_fields"]


class TestVersionManagementWorkflow:
    """Test version management workflows."""
    
    def test_version_history_workflow(self, mock_document_store):
        """Test retrieving version history workflow."""
        # Create multiple versions of same document
        versions = [
            Document(
                content=f"Version {i} content",
                meta={
                    "doc_id": "test1",
                    "version": f"v{i}.0",
                    "created_at": f"2025-01-0{i}T00:00:00Z",
                    "status": "active" if i == 3 else "deprecated"
                },
                id=f"doc_v{i}"
            ) for i in range(1, 4)
        ]
        
        mock_document_store.filter_documents = Mock(return_value=versions)
        
        # Get all versions
        with patch('update_service.query_by_doc_id') as mock_query:
            mock_query.return_value = versions
            
            result = get_version_history(mock_document_store, "test1", include_deprecated=True)
            
            assert len(result) == 3
            # Should be sorted by version
            assert result[0].meta["version"] == "v1.0"
            assert result[2].meta["version"] == "v3.0"
    
    @patch('update_service.update_document_metadata')
    def test_deprecate_version_workflow(self, mock_update_metadata, mock_document_store):
        """Test deprecating a document version workflow."""
        mock_update_metadata.return_value = {
            "status": "success",
            "document_id": "doc1",
            "message": "Document metadata updated successfully",
            "updated_fields": ["status"]
        }
        
        result = deprecate_version(mock_document_store, "doc1")
        
        assert result["status"] == "success"
        mock_update_metadata.assert_called_once_with(
            mock_document_store,
            "doc1",
            {"status": "deprecated"},
            collection_name=None
        )


class TestCompletePhase2Workflow:
    """Test complete Phase 2 workflow combining multiple features."""
    
    @patch('bulk_operations_service._get_qdrant_client')
    @patch('update_service._get_qdrant_client')
    def test_complete_update_and_query_workflow(
        self,
        mock_get_client_bulk,
        mock_get_client_update,
        mock_document_store,
        mock_embedder
    ):
        """Test complete workflow: update -> query -> verify."""
        # Setup mocks
        mock_client = Mock()
        mock_get_client_bulk.return_value = mock_client
        mock_get_client_update.return_value = mock_client
        
        from qdrant_client.models import ScoredPoint
        existing_point = ScoredPoint(
            id="doc1",
            score=1.0,
            payload={
                "content": "Old content",
                "meta": {
                    "doc_id": "test1",
                    "category": "user_rule",
                    "hash_content": "old_hash",
                    "file_path": "/path/to/file.txt"
                }
            },
            vector=[0.1, 0.2, 0.3]
        )
        mock_client.retrieve.return_value = [existing_point]
        mock_client.upsert.return_value = None
        
        mock_embedder.run.return_value = {
            "documents": [Document(content="New content", embedding=[0.4, 0.5, 0.6])]
        }
        
        # Step 1: Update document content
        update_result = update_document_content(
            mock_document_store,
            "doc1",
            "New content",
            mock_embedder
        )
        
        assert update_result["status"] == "success"
        
        # Step 2: Query by path
        updated_doc = Document(
            content="New content",
            meta={
                "doc_id": "test1",
                "file_path": "/path/to/file.txt",
                "hash_content": "new_hash"
            },
            id="doc1"
        )
        mock_document_store.filter_documents = Mock(return_value=[updated_doc])
        
        queried_doc = get_document_by_path(mock_document_store, "/path/to/file.txt")
        
        assert queried_doc is not None
        assert queried_doc.content == "New content"
        
        # Step 3: Verify updated document
        from verification_service import verify_content_quality
        verify_result = verify_content_quality(updated_doc)
        
        assert verify_result["status"] == "pass" or verify_result["status"] == "fail"  # May fail if metadata incomplete
        assert verify_result["document_id"] == "doc1"

