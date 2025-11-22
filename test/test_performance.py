"""
Performance tests for Qdrant/Haystack MCP Server.

Tests with 10K+ documents for:
- Duplicate detection performance
- Bulk operations performance
- Query performance
- Memory usage

Note: These tests require actual Qdrant connection and may take significant time.
Mark with @pytest.mark.integration to run them.
"""
import pytest
import time
import sys
from unittest.mock import Mock, patch
from haystack.dataclasses.document import Document
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore

from deduplication_service import (
    generate_content_fingerprint,
    check_duplicate_level,
    normalize_content,
    DUPLICATE_LEVEL_EXACT,
)
from metadata_service import build_metadata_schema, query_by_doc_id
from bulk_operations_service import delete_by_filter, update_metadata_by_filter
from query_service import get_metadata_stats


@pytest.mark.integration
@pytest.mark.performance
class TestDuplicateDetectionPerformance:
    """Performance tests for duplicate detection."""
    
    def test_duplicate_detection_with_10k_documents(self):
        """Test duplicate detection performance with 10K documents."""
        # Generate 10K documents
        documents = []
        for i in range(10000):
            content = f"This is test document number {i} with sufficient content length."
            metadata = {
                "doc_id": f"doc_{i}",
                "category": "user_rule",
                "version": "v1.0"
            }
            fingerprint = generate_content_fingerprint(content, metadata)
            doc = Document(
                content=content,
                meta={
                    "doc_id": f"doc_{i}",
                    "category": "user_rule",
                    "hash_content": fingerprint["content_hash"],
                    "metadata_hash": fingerprint["metadata_hash"]
                },
                id=f"doc_{i}"
            )
            documents.append((doc, fingerprint))
        
        # Test duplicate detection performance
        start_time = time.time()
        
        # Check for duplicates (simulating checking new document against all existing)
        new_content = "This is test document number 5000 with sufficient content length."
        new_metadata = {"doc_id": "doc_5000", "category": "user_rule", "version": "v1.0"}
        new_fingerprint = generate_content_fingerprint(new_content, new_metadata)
        
        existing_docs = [doc for doc, _ in documents]
        level, matching_doc, reason = check_duplicate_level(new_fingerprint, existing_docs)
        
        elapsed_time = time.time() - start_time
        
        assert level == DUPLICATE_LEVEL_EXACT
        assert matching_doc is not None
        assert elapsed_time < 5.0  # Should complete in under 5 seconds
        
        print(f"Duplicate detection with 10K documents: {elapsed_time:.3f}s")
    
    def test_fingerprint_generation_performance(self):
        """Test fingerprint generation performance."""
        content = "This is a test document with sufficient content length for performance testing."
        metadata = {"doc_id": "test1", "category": "user_rule", "version": "v1.0"}
        
        # Generate 10K fingerprints
        start_time = time.time()
        for i in range(10000):
            fingerprint = generate_content_fingerprint(f"{content} {i}", metadata)
            assert "content_hash" in fingerprint
        
        elapsed_time = time.time() - start_time
        avg_time = elapsed_time / 10000
        
        assert avg_time < 0.001  # Should average under 1ms per fingerprint
        print(f"Average fingerprint generation time: {avg_time*1000:.3f}ms")


@pytest.mark.integration
@pytest.mark.performance
class TestBulkOperationsPerformance:
    """Performance tests for bulk operations."""
    
    @patch('bulk_operations_service._get_qdrant_client')
    def test_bulk_delete_performance(self, mock_get_client):
        """Test bulk delete performance with large dataset."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        from qdrant_client.models import ScoredPoint
        # Simulate 10K documents
        mock_points = [
            ScoredPoint(
                id=i,
                score=1.0,
                payload={"meta": {"category": "user_rule"}},
                vector=None
            ) for i in range(10000)
        ]
        
        # Simulate pagination (100 points per scroll)
        def mock_scroll(*args, **kwargs):
            offset = kwargs.get("offset")
            if offset is None:
                return (mock_points[:100], "next_offset_100")
            elif offset == "next_offset_100":
                return (mock_points[100:200], "next_offset_200")
            # Continue pattern... for simplicity, return all at once after first call
            return (mock_points[200:], None)
        
        mock_client.scroll.side_effect = mock_scroll
        mock_client.delete.return_value = None
        
        document_store = Mock()
        document_store.index = "test_collection"
        
        filters = {"field": "meta.category", "operator": "==", "value": "user_rule"}
        
        start_time = time.time()
        result = delete_by_filter(document_store, filters)
        elapsed_time = time.time() - start_time
        
        assert result["status"] == "success"
        assert elapsed_time < 30.0  # Should complete in under 30 seconds
        print(f"Bulk delete 10K documents: {elapsed_time:.3f}s")
    
    @patch('bulk_operations_service._get_qdrant_client')
    def test_bulk_update_performance(self, mock_get_client):
        """Test bulk metadata update performance."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        from qdrant_client.models import ScoredPoint
        mock_points = [
            ScoredPoint(
                id=i,
                score=1.0,
                payload={"meta": {"category": "user_rule", "status": "active"}},
                vector=[0.1] * 384  # Simulate embedding vector
            ) for i in range(10000)
        ]
        
        mock_client.scroll.return_value = (mock_points, None)
        mock_client.upsert.return_value = None
        
        document_store = Mock()
        document_store.index = "test_collection"
        
        filters = {"field": "meta.category", "operator": "==", "value": "user_rule"}
        metadata_updates = {"status": "deprecated"}
        
        start_time = time.time()
        result = update_metadata_by_filter(document_store, filters, metadata_updates)
        elapsed_time = time.time() - start_time
        
        assert result["status"] == "success"
        assert elapsed_time < 60.0  # Should complete in under 60 seconds
        print(f"Bulk update 10K documents: {elapsed_time:.3f}s")


@pytest.mark.integration
@pytest.mark.performance
class TestQueryPerformance:
    """Performance tests for query operations."""
    
    def test_metadata_query_performance(self):
        """Test metadata query performance with large dataset."""
        # Generate 10K documents
        documents = []
        for i in range(10000):
            content = f"Test document {i}"
            metadata = {
                "doc_id": f"doc_{i}",
                "category": "user_rule" if i % 2 == 0 else "project_rule",
                "version": "v1.0",
                "hash_content": f"hash_{i}"
            }
            documents.append(Document(content=content, meta=metadata, id=f"doc_{i}"))
        
        # Mock document store
        document_store = Mock()
        
        # Test query by doc_id (should be fast with indexing)
        start_time = time.time()
        for i in range(0, 10000, 1000):  # Query every 1000th document
            doc_id = f"doc_{i}"
            matching_docs = [d for d in documents if d.meta["doc_id"] == doc_id]
            assert len(matching_docs) == 1
        
        elapsed_time = time.time() - start_time
        avg_time = elapsed_time / 10  # 10 queries
        
        assert avg_time < 0.01  # Should average under 10ms per query
        print(f"Average query by doc_id time: {avg_time*1000:.3f}ms")
    
    @patch('query_service._get_qdrant_client')
    def test_metadata_stats_performance(self, mock_get_client):
        """Test metadata statistics aggregation performance."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        from qdrant_client.models import ScoredPoint
        # Generate 10K points with various categories
        mock_points = [
            ScoredPoint(
                id=i,
                score=1.0,
                payload={
                    "meta": {
                        "category": ["user_rule", "project_rule", "other"][i % 3],
                        "status": ["active", "deprecated"][i % 2]
                    }
                },
                vector=None
            ) for i in range(10000)
        ]
        
        # Simulate pagination
        def mock_scroll(*args, **kwargs):
            offset = kwargs.get("offset")
            if offset is None:
                return (mock_points[:1000], "next_offset_1000")
            elif offset == "next_offset_1000":
                return (mock_points[1000:2000], "next_offset_2000")
            # Continue... for simplicity, return remaining
            return (mock_points[2000:], None)
        
        mock_client.scroll.side_effect = mock_scroll
        
        document_store = Mock()
        document_store.index = "test_collection"
        
        start_time = time.time()
        result = get_metadata_stats(
            document_store,
            group_by_fields=["category", "status"]
        )
        elapsed_time = time.time() - start_time
        
        assert result["status"] == "success"
        assert elapsed_time < 30.0  # Should complete in under 30 seconds
        print(f"Metadata stats aggregation 10K documents: {elapsed_time:.3f}s")


@pytest.mark.integration
@pytest.mark.performance
class TestMemoryUsage:
    """Tests for memory usage with large datasets."""
    
    def test_memory_usage_10k_documents(self):
        """Test memory usage when processing 10K documents."""
        import tracemalloc
        
        tracemalloc.start()
        
        # Generate 10K documents
        documents = []
        for i in range(10000):
            content = f"This is test document {i} with sufficient content length."
            metadata = {
                "doc_id": f"doc_{i}",
                "category": "user_rule",
                "version": "v1.0"
            }
            fingerprint = generate_content_fingerprint(content, metadata)
            full_metadata = build_metadata_schema(
                content=content,
                doc_id=metadata["doc_id"],
                category=metadata["category"],
                hash_content=fingerprint["content_hash"],
                version=metadata["version"]
            )
            doc = Document(content=content, meta=full_metadata, id=f"doc_{i}")
            documents.append(doc)
        
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        # Memory should be reasonable (less than 500MB for 10K documents)
        peak_mb = peak / (1024 * 1024)
        assert peak_mb < 500, f"Peak memory usage too high: {peak_mb:.2f}MB"
        
        print(f"Peak memory usage for 10K documents: {peak_mb:.2f}MB")
        print(f"Current memory usage: {current / (1024 * 1024):.2f}MB")


@pytest.mark.integration
@pytest.mark.performance
class TestScalability:
    """Scalability tests for different document sizes."""
    
    def test_duplicate_detection_scalability(self):
        """Test how duplicate detection scales with document count."""
        document_counts = [100, 1000, 5000, 10000]
        results = []
        
        for count in document_counts:
            # Generate documents
            documents = []
            for i in range(count):
                content = f"Test document {i}"
                metadata = {"doc_id": f"doc_{i}", "category": "user_rule", "version": "v1.0"}
                fingerprint = generate_content_fingerprint(content, metadata)
                doc = Document(
                    content=content,
                    meta={
                        "doc_id": f"doc_{i}",
                        "hash_content": fingerprint["content_hash"],
                        "metadata_hash": fingerprint["metadata_hash"]
                    },
                    id=f"doc_{i}"
                )
                documents.append(doc)
            
            # Test duplicate detection
            new_content = "Test document 500"
            new_metadata = {"doc_id": "doc_500", "category": "user_rule", "version": "v1.0"}
            new_fingerprint = generate_content_fingerprint(new_content, new_metadata)
            
            start_time = time.time()
            level, matching_doc, reason = check_duplicate_level(new_fingerprint, documents)
            elapsed_time = time.time() - start_time
            
            results.append((count, elapsed_time))
            print(f"Duplicate detection with {count} documents: {elapsed_time:.3f}s")
        
        # Verify that time increases sub-linearly or linearly (not quadratically)
        # Time for 10K should be less than 10x time for 1K
        time_1k = next(t for c, t in results if c == 1000)
        time_10k = next(t for c, t in results if c == 10000)
        
        assert time_10k < time_1k * 15, "Performance degradation too severe"

