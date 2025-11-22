"""
Unit tests for migration script (migrate_existing_documents.py).

Tests metadata generation, document retrieval, and migration workflow.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from haystack.dataclasses.document import Document
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore

from migrate_existing_documents import (
    get_all_documents,
    generate_migration_metadata,
    migrate_documents,
    generate_migration_report
)
from deduplication_service import normalize_content
import hashlib


class TestGetAllDocuments:
    """Test get_all_documents function."""
    
    def test_get_all_documents_success(self):
        """Test retrieving all documents."""
        document_store = Mock()
        mock_docs = [
            Document(content="Doc 1", meta={}, id="doc1"),
            Document(content="Doc 2", meta={}, id="doc2")
        ]
        document_store.filter_documents = Mock(return_value=mock_docs)
        
        result = get_all_documents(document_store)
        
        assert len(result) == 2
        assert result[0].id == "doc1"
        assert result[1].id == "doc2"
    
    def test_get_all_documents_empty(self):
        """Test retrieving documents when collection is empty."""
        document_store = Mock()
        document_store.filter_documents = Mock(return_value=[])
        
        result = get_all_documents(document_store)
        
        assert len(result) == 0
    
    def test_get_all_documents_error_handling(self):
        """Test error handling when retrieval fails."""
        document_store = Mock()
        document_store.filter_documents = Mock(side_effect=Exception("Connection error"))
        
        result = get_all_documents(document_store)
        
        assert len(result) == 0


class TestGenerateMigrationMetadata:
    """Test generate_migration_metadata function."""
    
    def test_generate_metadata_basic(self):
        """Test basic metadata generation."""
        content = "Test document content with sufficient length."
        doc = Document(content=content, meta={}, id="doc1")
        
        metadata = generate_migration_metadata(doc, {})
        
        assert "hash_content" in metadata
        assert "doc_id" in metadata
        assert "category" in metadata
        assert "version" in metadata
        assert metadata["category"] == "other"  # Default category
    
    def test_generate_metadata_preserves_existing(self):
        """Test that existing metadata is preserved where possible."""
        content = "Test content"
        existing_meta = {
            "doc_id": "existing_doc_1",
            "category": "user_rule",
            "version": "v1.0",
            "source": "manual",
            "tags": ["tag1", "tag2"]
        }
        doc = Document(content=content, meta=existing_meta, id="doc1")
        
        metadata = generate_migration_metadata(doc, existing_meta)
        
        assert metadata["doc_id"] == "existing_doc_1"
        assert metadata["category"] == "user_rule"
        assert metadata["version"] == "v1.0"
        assert metadata["source"] == "manual"
        assert metadata["tags"] == ["tag1", "tag2"]
    
    def test_generate_metadata_with_file_path(self):
        """Test metadata generation with file_path."""
        content = "Test content"
        file_path = "/path/to/file.txt"
        existing_meta = {"file_path": file_path}
        doc = Document(content=content, meta=existing_meta, id="doc1")
        
        metadata = generate_migration_metadata(doc, existing_meta)
        
        assert metadata["file_path"] == file_path
        assert metadata["path"] == file_path  # Alias
    
    def test_generate_metadata_generates_doc_id(self):
        """Test that doc_id is generated if missing."""
        content = "Test content"
        doc = Document(content=content, meta={}, id="doc1")
        
        metadata = generate_migration_metadata(doc, {})
        
        assert "doc_id" in metadata
        assert metadata["doc_id"] is not None
        assert len(metadata["doc_id"]) > 0
    
    def test_generate_metadata_generates_version(self):
        """Test that version is generated if missing."""
        content = "Test content"
        doc = Document(content=content, meta={}, id="doc1")
        
        metadata = generate_migration_metadata(doc, {})
        
        assert "version" in metadata
        assert metadata["version"] is not None
    
    def test_generate_metadata_hash_consistency(self):
        """Test that hash_content matches normalized content."""
        content = "Test Content"  # Different case
        doc = Document(content=content, meta={}, id="doc1")
        
        metadata = generate_migration_metadata(doc, {})
        
        # Verify hash matches normalized content
        normalized = normalize_content(content)
        expected_hash = hashlib.sha256(normalized.encode()).hexdigest()
        
        assert metadata["hash_content"] == expected_hash
        assert metadata["content_hash"] == expected_hash  # Alias
    
    def test_generate_metadata_invalid_category(self):
        """Test that invalid category is replaced with default."""
        content = "Test content"
        existing_meta = {"category": "invalid_category"}
        doc = Document(content=content, meta=existing_meta, id="doc1")
        
        metadata = generate_migration_metadata(doc, existing_meta)
        
        # Should default to "other" or infer from context
        assert metadata["category"] in ["other", "project_rule"]  # May infer from file_path


class TestMigrateDocuments:
    """Test migrate_documents function."""
    
    def test_migrate_documents_dry_run(self):
        """Test migration in dry-run mode."""
        document_store = Mock()
        document_store.filter_documents = Mock(return_value=[
            Document(content="Test", meta={}, id="doc1")
        ])
        
        result = migrate_documents(
            document_store,
            dry_run=True,
            batch_size=10
        )
        
        assert result["status"] == "success"
        assert result["total_documents"] == 1
        assert result["migrated_count"] == 1  # Counted in dry run
        assert result["failed_count"] == 0
    
    @patch('update_service.update_document_metadata')
    def test_migrate_documents_success(self, mock_update_metadata):
        """Test successful migration."""
        document_store = Mock()
        document_store.filter_documents = Mock(return_value=[
            Document(content="Test content", meta={}, id="doc1")
        ])
        
        mock_update_metadata.return_value = {
            "status": "success",
            "document_id": "doc1"
        }
        
        result = migrate_documents(
            document_store,
            dry_run=False,
            batch_size=10
        )
        
        assert result["status"] == "success"
        assert result["migrated_count"] == 1
        assert result["failed_count"] == 0
        mock_update_metadata.assert_called_once()
    
    @patch('update_service.update_document_metadata')
    def test_migrate_documents_with_failures(self, mock_update_metadata):
        """Test migration with some failures."""
        document_store = Mock()
        document_store.filter_documents = Mock(return_value=[
            Document(content="Test 1", meta={}, id="doc1"),
            Document(content="Test 2", meta={}, id="doc2")
        ])
        
        # First succeeds, second fails
        mock_update_metadata.side_effect = [
            {"status": "success", "document_id": "doc1"},
            {"status": "error", "error": "Update failed"}
        ]
        
        result = migrate_documents(
            document_store,
            dry_run=False,
            batch_size=10
        )
        
        assert result["migrated_count"] == 1
        assert result["failed_count"] == 1
        assert len(result["errors"]) == 1
    
    def test_migrate_documents_with_code_collection(self):
        """Test migration with code collection."""
        document_store = Mock()
        code_document_store = Mock()
        
        document_store.filter_documents = Mock(return_value=[
            Document(content="Doc content", meta={}, id="doc1")
        ])
        code_document_store.filter_documents = Mock(return_value=[
            Document(content="Code content", meta={}, id="code1")
        ])
        
        result = migrate_documents(
            document_store,
            code_document_store=code_document_store,
            dry_run=True
        )
        
        assert result["total_documents"] == 2


class TestGenerateMigrationReport:
    """Test generate_migration_report function."""
    
    def test_generate_report_basic(self):
        """Test basic report generation."""
        results = {
            "total_documents": 100,
            "migrated_count": 95,
            "failed_count": 5,
            "categories": {
                "user_rule": {"total": 50, "migrated": 48, "failed": 2},
                "project_rule": {"total": 50, "migrated": 47, "failed": 3}
            },
            "errors": []
        }
        
        report = generate_migration_report(results)
        
        assert "MIGRATION REPORT" in report
        assert "100" in report
        assert "95" in report
        assert "5" in report
        assert "user_rule" in report
        assert "project_rule" in report
    
    def test_generate_report_with_errors(self):
        """Test report generation with errors."""
        results = {
            "total_documents": 10,
            "migrated_count": 8,
            "failed_count": 2,
            "categories": {},
            "errors": [
                {"document_id": "doc1", "error": "Update failed"},
                {"document_id": "doc2", "error": "Validation error"}
            ]
        }
        
        report = generate_migration_report(results)
        
        assert "ERRORS" in report
        assert "doc1" in report
        assert "doc2" in report
    
    def test_generate_report_saves_to_file(self):
        """Test that report can be saved to file."""
        import tempfile
        import os
        
        results = {
            "total_documents": 10,
            "migrated_count": 10,
            "failed_count": 0,
            "categories": {},
            "errors": []
        }
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            temp_file = f.name
        
        try:
            report = generate_migration_report(results, output_file=temp_file)
            
            assert os.path.exists(temp_file)
            with open(temp_file, 'r') as f:
                saved_content = f.read()
            assert "MIGRATION REPORT" in saved_content
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)

