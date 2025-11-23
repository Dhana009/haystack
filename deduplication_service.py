"""
Deduplication Service for Qdrant/Haystack MCP Server.

Implements multi-factor duplicate detection with 4 levels:
1. Exact Duplicate (Skip) - Same content_hash AND metadata_hash
2. Content Update (Replace) - Same metadata_hash BUT different content_hash
3. Semantic Similarity (Warn, Allow) - High similarity BUT different hashes
4. New Content (Store) - Low similarity OR different metadata
"""
import hashlib
import json
import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from haystack.dataclasses.document import Document


# Duplicate detection levels
DUPLICATE_LEVEL_EXACT = 1  # Exact duplicate - skip
DUPLICATE_LEVEL_UPDATE = 2  # Content update - replace
DUPLICATE_LEVEL_SIMILAR = 3  # Semantic similarity - warn but allow
DUPLICATE_LEVEL_NEW = 4  # New content - store normally

# Storage actions
ACTION_SKIP = "skip"
ACTION_UPDATE = "update"
ACTION_WARN = "warn"
ACTION_STORE = "store"

# Semantic similarity threshold for Level 3 detection
SEMANTIC_SIMILARITY_THRESHOLD = 0.85


def normalize_content(content: str) -> str:
    """
    Normalize content for consistent hashing.
    
    Normalization steps:
    - Strip trailing whitespace
    - Normalize newlines to \n
    - Remove obvious placeholders if they're not meaningful
    - Lowercase for hash comparison (optional, but ensures consistency)
    
    Args:
        content: Raw content string
        
    Returns:
        Normalized content string
    """
    if not content:
        return ""
    
    # Strip trailing spaces
    normalized = content.rstrip()
    
    # Normalize newlines (Windows \r\n -> \n, Mac \r -> \n)
    normalized = normalized.replace('\r\n', '\n').replace('\r', '\n')
    
    # Remove obvious placeholder markers that aren't meaningful
    # These are common placeholders that should be normalized
    placeholder_patterns = [
        r'\[Full content from file\.\.\.\]',
        r'\[\.\.\.\]',
        r'\[TODO:.*?\]',
        r'\[TBD:.*?\]',
    ]
    
    for pattern in placeholder_patterns:
        normalized = re.sub(pattern, '', normalized, flags=re.IGNORECASE)
    
    # Lowercase for hash consistency (ensures case-insensitive duplicate detection)
    normalized = normalized.lower()
    
    return normalized


def generate_content_fingerprint(content: str, metadata: Dict) -> Dict[str, str]:
    """
    Generate unique fingerprint based on content and metadata.
    
    Creates:
    1. Content hash (SHA256 of normalized content)
    2. Metadata hash (SHA256 of sorted metadata JSON)
    3. Composite key (content_hash:metadata_hash)
    
    Args:
        content: Document content
        metadata: Document metadata dictionary
        
    Returns:
        Dictionary with:
        - content_hash: SHA256 hash of normalized content
        - metadata_hash: SHA256 hash of normalized metadata
        - composite_key: Combined key for exact duplicate detection
    """
    # Normalize content
    normalized_content = normalize_content(content)
    
    # Generate content hash
    content_hash = hashlib.sha256(normalized_content.encode('utf-8')).hexdigest()
    
    # Normalize metadata for hashing (sort keys for consistency)
    # Create a copy to avoid modifying original
    metadata_copy = dict(metadata)
    
    # Sort keys and create JSON string
    # Use sort_keys=True for consistent ordering
    metadata_json = json.dumps(metadata_copy, sort_keys=True, default=str)
    metadata_hash = hashlib.sha256(metadata_json.encode('utf-8')).hexdigest()
    
    # Create composite key
    composite_key = f"{content_hash}:{metadata_hash}"
    
    return {
        'content_hash': content_hash,
        'metadata_hash': metadata_hash,
        'composite_key': composite_key
    }


def check_duplicate_level(
    fingerprint: Dict[str, str],
    existing_docs: List[Document],
    doc_id: Optional[str] = None,
    is_chunk: bool = False
) -> Tuple[int, Optional[Document], Optional[str]]:
    """
    Check duplicate level by comparing fingerprint with existing documents.
    
    Supports both document-level and chunk-level duplicate detection.
    
    Levels:
    1. Exact Duplicate: Same content_hash AND metadata_hash
    2. Content Update: Same doc_id (or chunk_id) OR same metadata_hash BUT different content_hash
    3. Semantic Similarity: High similarity (>0.85) BUT different hashes
    4. New Content: Low similarity OR different metadata
    
    Args:
        fingerprint: Fingerprint dict with content_hash, metadata_hash, composite_key
        existing_docs: List of existing Document objects to compare against
        doc_id: Optional document ID (or chunk_id) to check for same-document updates
        is_chunk: Whether this is a chunk-level comparison (default: False)
        
    Returns:
        Tuple of:
        - level: Duplicate level (1-4)
        - matching_doc: Matching document if found, None otherwise
        - reason: Human-readable reason for the level
    """
    if not existing_docs:
        return (DUPLICATE_LEVEL_NEW, None, "No existing documents found")
    
    content_hash = fingerprint['content_hash']
    metadata_hash = fingerprint['metadata_hash']
    composite_key = fingerprint['composite_key']
    
    # Level 1: Check for exact duplicate (same content_hash AND metadata_hash)
    # Works for both documents and chunks
    for doc in existing_docs:
        doc_meta = doc.meta or {}
        doc_content_hash = doc_meta.get('hash_content') or doc_meta.get('content_hash')
        doc_metadata_hash = doc_meta.get('metadata_hash')
        
        if doc_content_hash == content_hash and doc_metadata_hash == metadata_hash:
            entity_type = "chunk" if is_chunk else "document"
            return (
                DUPLICATE_LEVEL_EXACT,
                doc,
                f"Exact duplicate {entity_type}: same content_hash ({content_hash[:8]}...) and metadata_hash"
            )
    
    # Level 2: Check for content update
    # For chunks: Check by chunk_id (or chunk_index + parent_doc_id)
    # For documents: Check by doc_id (or metadata_hash)
    for doc in existing_docs:
        doc_meta = doc.meta or {}
        doc_metadata_hash = doc_meta.get('metadata_hash')
        doc_content_hash = doc_meta.get('hash_content') or doc_meta.get('content_hash')
        doc_doc_id = doc_meta.get('doc_id')
        doc_chunk_id = doc_meta.get('chunk_id')
        doc_chunk_index = doc_meta.get('chunk_index')
        doc_parent_doc_id = doc_meta.get('parent_doc_id')
        
        if is_chunk:
            # Chunk-level duplicate detection
            # Case 1: Same chunk_id + different content_hash → Level 2 (update)
            if doc_id and doc_chunk_id and doc_chunk_id == doc_id and doc_content_hash != content_hash:
                return (
                    DUPLICATE_LEVEL_UPDATE,
                    doc,
                    f"Chunk update: same chunk_id ({doc_id}) but different content_hash"
                )
            
            # Case 2: Same parent_doc_id + same chunk_index + different content_hash → Level 2 (update)
            # This handles cases where chunk_id might not be set but index is available
            if doc_parent_doc_id and doc_chunk_index is not None:
                # Need to check if we have parent_doc_id and chunk_index from new chunk
                # This will be handled by the caller providing proper doc_id or additional context
                pass
        
        # Document-level duplicate detection (original logic)
        # Case 1: Same doc_id + different content_hash → Level 2 (update)
        if doc_id and doc_doc_id and doc_doc_id == doc_id and doc_content_hash != content_hash:
            return (
                DUPLICATE_LEVEL_UPDATE,
                doc,
                f"Content update: same doc_id ({doc_id}) but different content_hash"
            )
        
        # Case 2: Same metadata_hash + different content_hash → Level 2 (update)
        if doc_metadata_hash == metadata_hash and doc_content_hash != content_hash:
            return (
                DUPLICATE_LEVEL_UPDATE,
                doc,
                f"Content update: same metadata_hash ({metadata_hash[:8]}...) but different content_hash"
            )
    
    # Level 3: Semantic similarity check
    # For now, we'll skip semantic similarity (requires embedding comparison)
    # This will be implemented in Phase 2 when we have embedding comparison
    # For Phase 1, we'll treat this as Level 4 (new content)
    
    # Level 4: New content (default)
    entity_type = "chunk" if is_chunk else "document"
    return (
        DUPLICATE_LEVEL_NEW,
        None,
        f"New {entity_type}: different content_hash and/or metadata_hash"
    )


def decide_storage_action(
    level: int,
    fingerprint: Dict[str, str],
    matching_doc: Optional[Document] = None
) -> Tuple[str, Dict]:
    """
    Decide storage action based on duplicate detection level.
    
    Actions:
    - skip: Level 1 - Exact duplicate, skip storage
    - update: Level 2 - Content update, mark old as deprecated, store new
    - warn: Level 3 - Semantic similarity, store with warning flag
    - store: Level 4 - New content, store normally
    
    Args:
        level: Duplicate detection level (1-4)
        fingerprint: Fingerprint dictionary
        matching_doc: Matching document if found (for update action)
        
    Returns:
        Tuple of:
        - action: Storage action string (skip/update/warn/store)
        - action_data: Dictionary with action-specific data
    """
    action_data = {
        'level': level,
        'fingerprint': fingerprint,
        'matching_doc_id': matching_doc.id if matching_doc else None
    }
    
    if level == DUPLICATE_LEVEL_EXACT:
        return (ACTION_SKIP, {
            **action_data,
            'reason': 'Exact duplicate detected - skipping storage',
            'existing_doc_id': matching_doc.id if matching_doc else None
        })
    
    elif level == DUPLICATE_LEVEL_UPDATE:
        return (ACTION_UPDATE, {
            **action_data,
            'reason': 'Content update detected - will deprecate old version',
            'old_doc_id': matching_doc.id if matching_doc else None,
            'old_version': matching_doc.meta.get('version') if matching_doc and matching_doc.meta else None
        })
    
    elif level == DUPLICATE_LEVEL_SIMILAR:
        return (ACTION_WARN, {
            **action_data,
            'reason': 'High semantic similarity detected - storing with warning flag',
            'warning': 'Content is semantically similar to existing documents'
        })
    
    else:  # DUPLICATE_LEVEL_NEW
        return (ACTION_STORE, {
            **action_data,
            'reason': 'New content - storing normally'
        })


def get_duplicate_check_filters(fingerprint: Dict[str, str], file_path: Optional[str] = None) -> Dict:
    """
    Generate filters for checking duplicates in Qdrant.
    
    Creates filter conditions for:
    1. Exact duplicate check (content_hash AND metadata_hash)
    2. Content update check (metadata_hash match)
    3. File path check (if file_path provided)
    
    Args:
        fingerprint: Fingerprint dictionary
        file_path: Optional file path for file-based deduplication
        
    Returns:
        Dictionary with filter conditions for Qdrant query
    """
    filters = {}
    
    # Add content_hash filter if available
    if fingerprint.get('content_hash'):
        filters['hash_content'] = fingerprint['content_hash']
        # Also check 'content_hash' key for backward compatibility
        filters['content_hash'] = fingerprint['content_hash']
    
    # Add metadata_hash filter if available
    if fingerprint.get('metadata_hash'):
        filters['metadata_hash'] = fingerprint['metadata_hash']
    
    # Add file_path filter if provided
    if file_path:
        filters['file_path'] = file_path
    
    return filters

