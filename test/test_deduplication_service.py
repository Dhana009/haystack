"""
Unit tests for deduplication_service module.

Tests all functions: normalize_content, generate_content_fingerprint,
check_duplicate_level (all 4 levels), and decide_storage_action logic.
"""
import pytest
from haystack.dataclasses.document import Document

from deduplication_service import (
    normalize_content,
    generate_content_fingerprint,
    check_duplicate_level,
    decide_storage_action,
    DUPLICATE_LEVEL_EXACT,
    DUPLICATE_LEVEL_UPDATE,
    DUPLICATE_LEVEL_SIMILAR,
    DUPLICATE_LEVEL_NEW,
    ACTION_SKIP,
    ACTION_UPDATE,
    ACTION_WARN,
    ACTION_STORE,
)


class TestNormalizeContent:
    """Test normalize_content function."""
    
    def test_normalize_empty_string(self):
        """Test normalization of empty string."""
        result = normalize_content("")
        assert result == ""
    
    def test_normalize_strips_trailing_whitespace(self):
        """Test that trailing whitespace is stripped."""
        result = normalize_content("Hello World   \n\t  ")
        assert result == "hello world"
    
    def test_normalize_newlines_windows(self):
        """Test Windows newline normalization."""
        result = normalize_content("Line 1\r\nLine 2\r\nLine 3")
        assert result == "line 1\nline 2\nline 3"
    
    def test_normalize_newlines_mac(self):
        """Test Mac newline normalization."""
        result = normalize_content("Line 1\rLine 2\rLine 3")
        assert result == "line 1\nline 2\nline 3"
    
    def test_normalize_removes_placeholders(self):
        """Test that placeholder patterns are removed."""
        content = "This is content [Full content from file...] with [TODO: fix this] placeholder"
        result = normalize_content(content)
        assert "[full content from file...]" not in result
        assert "[todo: fix this]" not in result
        assert "this is content" in result
        assert "with" in result
        assert "placeholder" in result
    
    def test_normalize_lowercase(self):
        """Test that content is lowercased."""
        result = normalize_content("Hello WORLD Test")
        assert result == "hello world test"
    
    def test_normalize_preserves_structure(self):
        """Test that content structure is preserved."""
        content = "Line 1\nLine 2\nLine 3"
        result = normalize_content(content)
        assert "\n" in result
        assert result.count("\n") == 2


class TestGenerateContentFingerprint:
    """Test generate_content_fingerprint function."""
    
    def test_fingerprint_basic(self):
        """Test basic fingerprint generation."""
        content = "Test content"
        metadata = {"category": "test", "version": "1.0"}
        result = generate_content_fingerprint(content, metadata)
        
        assert "content_hash" in result
        assert "metadata_hash" in result
        assert "composite_key" in result
        assert len(result["content_hash"]) == 64  # SHA256 hex length
        assert len(result["metadata_hash"]) == 64
        assert ":" in result["composite_key"]
    
    def test_fingerprint_deterministic(self):
        """Test that same content and metadata produce same fingerprint."""
        content = "Test content"
        metadata = {"category": "test", "version": "1.0"}
        
        result1 = generate_content_fingerprint(content, metadata)
        result2 = generate_content_fingerprint(content, metadata)
        
        assert result1 == result2
    
    def test_fingerprint_different_content(self):
        """Test that different content produces different hash."""
        metadata = {"category": "test"}
        
        result1 = generate_content_fingerprint("Content 1", metadata)
        result2 = generate_content_fingerprint("Content 2", metadata)
        
        assert result1["content_hash"] != result2["content_hash"]
        assert result1["metadata_hash"] == result2["metadata_hash"]
    
    def test_fingerprint_different_metadata(self):
        """Test that different metadata produces different hash."""
        content = "Test content"
        
        result1 = generate_content_fingerprint(content, {"category": "test1"})
        result2 = generate_content_fingerprint(content, {"category": "test2"})
        
        assert result1["content_hash"] == result2["content_hash"]
        assert result1["metadata_hash"] != result2["metadata_hash"]
    
    def test_fingerprint_metadata_order_independent(self):
        """Test that metadata key order doesn't affect hash."""
        content = "Test content"
        
        result1 = generate_content_fingerprint(content, {"a": 1, "b": 2})
        result2 = generate_content_fingerprint(content, {"b": 2, "a": 1})
        
        assert result1["metadata_hash"] == result2["metadata_hash"]
    
    def test_fingerprint_empty_metadata(self):
        """Test fingerprint with empty metadata."""
        content = "Test content"
        result = generate_content_fingerprint(content, {})
        
        assert "content_hash" in result
        assert "metadata_hash" in result
        assert len(result["metadata_hash"]) == 64
    
    def test_fingerprint_composite_key_format(self):
        """Test composite key format."""
        content = "Test"
        metadata = {"test": "value"}
        result = generate_content_fingerprint(content, metadata)
        
        assert result["composite_key"] == f"{result['content_hash']}:{result['metadata_hash']}"


class TestCheckDuplicateLevel:
    """Test check_duplicate_level function for all 4 levels."""
    
    def test_level_4_no_existing_docs(self):
        """Test Level 4: No existing documents."""
        fingerprint = {
            "content_hash": "abc123",
            "metadata_hash": "def456",
            "composite_key": "abc123:def456"
        }
        level, doc, reason = check_duplicate_level(fingerprint, [])
        
        assert level == DUPLICATE_LEVEL_NEW
        assert doc is None
        assert "No existing documents" in reason
    
    def test_level_1_exact_duplicate(self):
        """Test Level 1: Exact duplicate (same content_hash and metadata_hash)."""
        fingerprint = {
            "content_hash": "abc123",
            "metadata_hash": "def456",
            "composite_key": "abc123:def456"
        }
        
        existing_doc = Document(
            content="Test content",
            meta={
                "hash_content": "abc123",
                "metadata_hash": "def456"
            }
        )
        
        level, doc, reason = check_duplicate_level(fingerprint, [existing_doc])
        
        assert level == DUPLICATE_LEVEL_EXACT
        assert doc == existing_doc
        assert "Exact duplicate" in reason
        assert "abc123" in reason
    
    def test_level_1_exact_duplicate_content_hash_alias(self):
        """Test Level 1 with content_hash alias."""
        fingerprint = {
            "content_hash": "abc123",
            "metadata_hash": "def456",
            "composite_key": "abc123:def456"
        }
        
        existing_doc = Document(
            content="Test content",
            meta={
                "content_hash": "abc123",  # Using alias
                "metadata_hash": "def456"
            }
        )
        
        level, doc, reason = check_duplicate_level(fingerprint, [existing_doc])
        
        assert level == DUPLICATE_LEVEL_EXACT
    
    def test_level_2_content_update(self):
        """Test Level 2: Content update (same metadata_hash, different content_hash)."""
        fingerprint = {
            "content_hash": "new_content_hash",
            "metadata_hash": "same_metadata_hash",
            "composite_key": "new_content_hash:same_metadata_hash"
        }
        
        existing_doc = Document(
            content="Old content",
            meta={
                "hash_content": "old_content_hash",
                "metadata_hash": "same_metadata_hash"
            }
        )
        
        level, doc, reason = check_duplicate_level(fingerprint, [existing_doc])
        
        assert level == DUPLICATE_LEVEL_UPDATE
        assert doc == existing_doc
        assert "Content update" in reason
        assert "same_metadata_hash" in reason
    
    def test_level_4_new_content_different_hashes(self):
        """Test Level 4: New content (different content_hash and metadata_hash)."""
        fingerprint = {
            "content_hash": "new_content_hash",
            "metadata_hash": "new_metadata_hash",
            "composite_key": "new_content_hash:new_metadata_hash"
        }
        
        existing_doc = Document(
            content="Old content",
            meta={
                "hash_content": "old_content_hash",
                "metadata_hash": "old_metadata_hash"
            }
        )
        
        level, doc, reason = check_duplicate_level(fingerprint, [existing_doc])
        
        assert level == DUPLICATE_LEVEL_NEW
        assert doc is None
        assert "New content" in reason
    
    def test_level_4_new_content_same_content_different_metadata(self):
        """Test Level 4: Same content but different metadata."""
        fingerprint = {
            "content_hash": "same_content_hash",
            "metadata_hash": "different_metadata_hash",
            "composite_key": "same_content_hash:different_metadata_hash"
        }
        
        existing_doc = Document(
            content="Same content",
            meta={
                "hash_content": "same_content_hash",
                "metadata_hash": "old_metadata_hash"
            }
        )
        
        level, doc, reason = check_duplicate_level(fingerprint, [existing_doc])
        
        assert level == DUPLICATE_LEVEL_NEW
    
    def test_level_4_new_content_missing_hashes(self):
        """Test Level 4: Existing doc missing hashes."""
        fingerprint = {
            "content_hash": "abc123",
            "metadata_hash": "def456",
            "composite_key": "abc123:def456"
        }
        
        existing_doc = Document(
            content="Old content",
            meta={}  # No hashes
        )
        
        level, doc, reason = check_duplicate_level(fingerprint, [existing_doc])
        
        assert level == DUPLICATE_LEVEL_NEW
    
    def test_multiple_existing_docs_exact_match(self):
        """Test with multiple existing docs, finding exact match."""
        fingerprint = {
            "content_hash": "abc123",
            "metadata_hash": "def456",
            "composite_key": "abc123:def456"
        }
        
        existing_docs = [
            Document(content="Doc 1", meta={"hash_content": "hash1", "metadata_hash": "meta1"}),
            Document(content="Doc 2", meta={"hash_content": "abc123", "metadata_hash": "def456"}),
            Document(content="Doc 3", meta={"hash_content": "hash3", "metadata_hash": "meta3"}),
        ]
        
        level, doc, reason = check_duplicate_level(fingerprint, existing_docs)
        
        assert level == DUPLICATE_LEVEL_EXACT
        assert doc == existing_docs[1]


class TestDecideStorageAction:
    """Test decide_storage_action function."""
    
    def test_action_skip_exact_duplicate(self):
        """Test ACTION_SKIP for exact duplicate."""
        fingerprint = {"content_hash": "abc", "metadata_hash": "def", "composite_key": "abc:def"}
        matching_doc = Document(content="Test", meta={}, id="doc1")
        action, action_data = decide_storage_action(DUPLICATE_LEVEL_EXACT, fingerprint, matching_doc)
        
        assert action == ACTION_SKIP
        assert action_data["level"] == DUPLICATE_LEVEL_EXACT
        assert action_data["existing_doc_id"] == "doc1"
        assert "Exact duplicate detected" in action_data["reason"]
    
    def test_action_update_content_update(self):
        """Test ACTION_UPDATE for content update."""
        fingerprint = {"content_hash": "abc", "metadata_hash": "def", "composite_key": "abc:def"}
        matching_doc = Document(content="Test", meta={"version": "1.0"}, id="doc1")
        action, action_data = decide_storage_action(DUPLICATE_LEVEL_UPDATE, fingerprint, matching_doc)
        
        assert action == ACTION_UPDATE
        assert action_data["level"] == DUPLICATE_LEVEL_UPDATE
        assert action_data["old_doc_id"] == "doc1"
        assert action_data["old_version"] == "1.0"
        assert "Content update detected" in action_data["reason"]
    
    def test_action_warn_semantic_similarity(self):
        """Test ACTION_WARN for semantic similarity."""
        fingerprint = {"content_hash": "abc", "metadata_hash": "def", "composite_key": "abc:def"}
        action, action_data = decide_storage_action(DUPLICATE_LEVEL_SIMILAR, fingerprint, None)
        
        assert action == ACTION_WARN
        assert action_data["level"] == DUPLICATE_LEVEL_SIMILAR
        assert "High semantic similarity" in action_data["reason"]
        assert "warning" in action_data
    
    def test_action_store_new_content(self):
        """Test ACTION_STORE for new content."""
        fingerprint = {"content_hash": "abc", "metadata_hash": "def", "composite_key": "abc:def"}
        action, action_data = decide_storage_action(DUPLICATE_LEVEL_NEW, fingerprint, None)
        
        assert action == ACTION_STORE
        assert action_data["level"] == DUPLICATE_LEVEL_NEW
        assert "New content" in action_data["reason"]
    
    def test_action_invalid_level(self):
        """Test with invalid level (should default to STORE)."""
        fingerprint = {"content_hash": "abc", "metadata_hash": "def", "composite_key": "abc:def"}
        action, action_data = decide_storage_action(999, fingerprint, None)
        
        assert action == ACTION_STORE
        assert action_data["level"] == 999
    
    def test_action_skip_no_matching_doc(self):
        """Test ACTION_SKIP without matching doc."""
        fingerprint = {"content_hash": "abc", "metadata_hash": "def", "composite_key": "abc:def"}
        action, action_data = decide_storage_action(DUPLICATE_LEVEL_EXACT, fingerprint, None)
        
        assert action == ACTION_SKIP
        assert action_data["existing_doc_id"] is None

