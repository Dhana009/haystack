"""
Unit tests for enhanced audit_storage_integrity function.

Tests file comparison, missing file detection, content mismatch detection, and integrity scoring.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from haystack.dataclasses.document import Document
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore

from verification_service import audit_storage_integrity
from deduplication_service import normalize_content
import hashlib
import tempfile
import os


class TestAuditStorageIntegrity:
    """Test enhanced audit_storage_integrity function."""
    
    def test_audit_without_source_directory(self):
        """Test audit without source directory (quality checks only)."""
        document_store = Mock()
        document_store.filter_documents = Mock(return_value=[
            Document(
                content="Test content",
                meta={"doc_id": "test1", "category": "user_rule"},
                id="doc1"
            )
        ])
        
        result = audit_storage_integrity(document_store, source_directory=None)
        
        assert result["total_documents"] == 1
        assert "integrity_score" in result
        assert result["total_files"] is None
        assert "missing_files" in result
        assert "content_mismatches" in result
    
    def test_audit_with_source_directory_missing_files(self):
        """Test audit detects missing files."""
        # Create temporary directory with test files
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create test files
            (temp_path / "file1.md").write_text("Content 1")
            (temp_path / "file2.md").write_text("Content 2")
            
            # Mock document store with only one file stored
            document_store = Mock()
            stored_doc = Document(
                content="Content 1",
                meta={
                    "file_path": str(temp_path / "file1.md"),
                    "hash_content": hashlib.sha256(normalize_content("Content 1").encode()).hexdigest()
                },
                id="doc1"
            )
            document_store.filter_documents = Mock(return_value=[stored_doc])
            
            result = audit_storage_integrity(
                document_store,
                source_directory=str(temp_path),
                recursive=False
            )
            
            assert result["total_files"] == 2
            assert len(result["missing_files"]) == 1
            assert result["missing_files"][0]["file_path"] == str(temp_path / "file2.md")
            assert result["missing_files"][0]["severity"] == "high"
    
    def test_audit_with_content_mismatch(self):
        """Test audit detects content mismatches."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_file = temp_path / "test.md"
            test_file.write_text("Updated content")
            
            # Mock document store with old content hash
            document_store = Mock()
            stored_doc = Document(
                content="Old content",
                meta={
                    "file_path": str(test_file),
                    "hash_content": "old_hash_12345"  # Wrong hash
                },
                id="doc1"
            )
            document_store.filter_documents = Mock(return_value=[stored_doc])
            
            result = audit_storage_integrity(
                document_store,
                source_directory=str(temp_path),
                recursive=False
            )
            
            assert len(result["content_mismatches"]) == 1
            assert result["content_mismatches"][0]["file_path"] == str(test_file)
            assert result["content_mismatches"][0]["severity"] == "high"
            assert "stored_hash" in result["content_mismatches"][0]
            assert "source_hash" in result["content_mismatches"][0]
    
    def test_audit_with_matching_content(self):
        """Test audit when content matches."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_file = temp_path / "test.md"
            content = "Test content"
            test_file.write_text(content)
            
            # Generate correct hash
            normalized = normalize_content(content)
            correct_hash = hashlib.sha256(normalized.encode()).hexdigest()
            
            document_store = Mock()
            stored_doc = Document(
                content=content,
                meta={
                    "file_path": str(test_file),
                    "hash_content": correct_hash
                },
                id="doc1"
            )
            document_store.filter_documents = Mock(return_value=[stored_doc])
            
            result = audit_storage_integrity(
                document_store,
                source_directory=str(temp_dir),
                recursive=False
            )
            
            assert len(result["content_mismatches"]) == 0
            assert len(result["missing_files"]) == 0
            assert result["integrity_score"] == 1.0
    
    def test_audit_integrity_score_calculation(self):
        """Test integrity score calculation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create 10 files
            for i in range(10):
                (temp_path / f"file{i}.md").write_text(f"Content {i}")
            
            # Store only 8 files, 2 with mismatches
            stored_docs = []
            for i in range(8):
                content = f"Content {i}"
                normalized = normalize_content(content)
                hash_content = hashlib.sha256(normalized.encode()).hexdigest()
                
                stored_docs.append(Document(
                    content=content,
                    meta={
                        "file_path": str(temp_path / f"file{i}.md"),
                        "hash_content": hash_content if i < 6 else "wrong_hash"  # 2 mismatches
                    },
                    id=f"doc{i}"
                ))
            
            document_store = Mock()
            document_store.filter_documents = Mock(return_value=stored_docs)
            
            result = audit_storage_integrity(
                document_store,
                source_directory=str(temp_path),
                recursive=False
            )
            
            assert result["total_files"] == 10
            assert len(result["missing_files"]) == 2  # file8.md and file9.md
            assert len(result["content_mismatches"]) == 2  # file6.md and file7.md
            # Score = (10 - 2 missing - 2 mismatches) / 10 = 0.6
            assert result["integrity_score"] == 0.6
    
    def test_audit_recursive_scanning(self):
        """Test recursive directory scanning."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create nested structure
            (temp_path / "file1.md").write_text("Content 1")
            (temp_path / "subdir").mkdir()
            (temp_path / "subdir" / "file2.md").write_text("Content 2")
            
            document_store = Mock()
            document_store.filter_documents = Mock(return_value=[])
            
            result = audit_storage_integrity(
                document_store,
                source_directory=str(temp_path),
                recursive=True
            )
            
            assert result["total_files"] == 2
            assert len(result["missing_files"]) == 2
    
    def test_audit_file_extensions_filter(self):
        """Test filtering by file extensions."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            (temp_path / "file1.md").write_text("Content 1")
            (temp_path / "file2.txt").write_text("Content 2")
            (temp_path / "file3.py").write_text("Content 3")
            
            document_store = Mock()
            document_store.filter_documents = Mock(return_value=[])
            
            result = audit_storage_integrity(
                document_store,
                source_directory=str(temp_path),
                recursive=False,
                file_extensions=[".md", ".txt"]
            )
            
            assert result["total_files"] == 2  # Only .md and .txt
            assert len(result["missing_files"]) == 2
    
    def test_audit_path_normalization(self):
        """Test that path normalization works for matching."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_file = temp_path / "test.md"
            test_file.write_text("Content")
            
            # Store with absolute path
            normalized = normalize_content("Content")
            hash_content = hashlib.sha256(normalized.encode()).hexdigest()
            
            document_store = Mock()
            stored_doc = Document(
                content="Content",
                meta={
                    "file_path": str(test_file.resolve()),  # Absolute path
                    "hash_content": hash_content
                },
                id="doc1"
            )
            document_store.filter_documents = Mock(return_value=[stored_doc])
            
            result = audit_storage_integrity(
                document_store,
                source_directory=str(temp_path),
                recursive=False
            )
            
            # Should match despite path format differences
            assert len(result["missing_files"]) == 0
            assert len(result["content_mismatches"]) == 0
    
    def test_audit_with_code_collection(self):
        """Test audit with both main and code collections."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_file = temp_path / "test.py"
            test_file.write_text("code content")
            
            document_store = Mock()
            code_document_store = Mock()
            
            normalized = normalize_content("code content")
            hash_content = hashlib.sha256(normalized.encode()).hexdigest()
            
            code_doc = Document(
                content="code content",
                meta={
                    "file_path": str(test_file),
                    "hash_content": hash_content
                },
                id="code_doc1"
            )
            
            document_store.filter_documents = Mock(return_value=[])
            code_document_store.filter_documents = Mock(return_value=[code_doc])
            
            result = audit_storage_integrity(
                document_store,
                source_directory=str(temp_path),
                code_document_store=code_document_store,
                recursive=False,
                file_extensions=[".py"]
            )
            
            assert result["total_files"] == 1
            assert len(result["missing_files"]) == 0
            assert len(result["content_mismatches"]) == 0
    
    def test_audit_nonexistent_source_directory(self):
        """Test audit with nonexistent source directory."""
        document_store = Mock()
        document_store.filter_documents = Mock(return_value=[])
        
        result = audit_storage_integrity(
            document_store,
            source_directory="/nonexistent/path"
        )
        
        assert len(result["issues"]) > 0
        assert any("source_directory_not_found" in str(issue.get("type", "")) for issue in result["issues"])
    
    def test_audit_issues_grouped_by_type(self):
        """Test that issues are properly grouped by type."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            (temp_path / "file1.md").write_text("Content 1")
            (temp_path / "file2.md").write_text("Content 2")
            
            document_store = Mock()
            stored_doc = Document(
                content="Wrong content",
                meta={
                    "file_path": str(temp_path / "file1.md"),
                    "hash_content": "wrong_hash"
                },
                id="doc1"
            )
            document_store.filter_documents = Mock(return_value=[stored_doc])
            
            result = audit_storage_integrity(
                document_store,
                source_directory=str(temp_path),
                recursive=False
            )
            
            assert "issues_by_type" in result
            assert "missing_file" in result["issues_by_type"]
            assert "content_mismatch" in result["issues_by_type"]

