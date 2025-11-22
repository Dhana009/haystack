"""
Metadata Service for Qdrant/Haystack MCP Server.

Implements metadata schema building and query functions following RULE 3.
Provides functions for building compliant metadata and querying documents by metadata fields.
"""
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from haystack.dataclasses.document import Document
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore


# Required metadata fields per RULE 3
REQUIRED_METADATA_FIELDS = ['doc_id', 'version', 'category', 'hash_content']

# Valid category values per RULE 3
VALID_CATEGORIES = [
    'user_rule',
    'project_rule',
    'project_command',
    'design_doc',
    'debug_summary',
    'test_pattern',
    'other'
]

# Valid source values per RULE 3
VALID_SOURCES = ['manual', 'generated', 'imported']

# Valid status values per RULE 3
VALID_STATUSES = ['active', 'deprecated', 'draft']


def build_metadata_schema(
    content: str,
    doc_id: str,
    category: str,
    hash_content: str,
    version: Optional[str] = None,
    file_path: Optional[str] = None,
    source: str = 'manual',
    repo: str = 'qdrant_haystack',
    tags: Optional[List[str]] = None,
    hash_file: Optional[str] = None,
    status: str = 'active',
    additional_metadata: Optional[Dict] = None
) -> Dict:
    """
    Build RULE 3 compliant metadata schema.
    
    Required fields:
    - doc_id: Stable logical ID (e.g., path or slug)
    - version: Version string (e.g., "v1", "v1.1", "2025-11-22T10:30Z")
    - category: One of the valid categories
    - hash_content: Hash of normalized content
    
    Optional fields:
    - source: "manual" | "generated" | "imported" (default: "manual")
    - repo: Repository identifier (default: "qdrant_haystack")
    - path: Logical or physical path if exists
    - hash_file: Hash of original file (optional)
    - created_at: ISO timestamp (auto-generated)
    - updated_at: ISO timestamp (auto-generated)
    - status: "active" | "deprecated" | "draft" (default: "active")
    - tags: List of free-form tags
    
    Args:
        content: Document content (for generating file hash if file_path provided)
        doc_id: Stable logical document ID (required)
        category: Document category (required, must be valid)
        hash_content: Hash of normalized content (required)
        version: Version string (default: auto-generated timestamp)
        file_path: File path if document comes from a file
        source: Source type (default: "manual")
        repo: Repository identifier (default: "qdrant_haystack")
        tags: List of tags (default: empty list)
        hash_file: Hash of original file (optional, auto-generated if file_path provided)
        status: Document status (default: "active")
        additional_metadata: Additional metadata fields to include
        
    Returns:
        Dictionary with RULE 3 compliant metadata
        
    Raises:
        ValueError: If required fields are missing or invalid values provided
    """
    # Validate required fields
    if not doc_id:
        raise ValueError("doc_id is required and cannot be empty")
    if not category:
        raise ValueError("category is required and cannot be empty")
    if category not in VALID_CATEGORIES:
        raise ValueError(f"category must be one of {VALID_CATEGORIES}, got: {category}")
    if not hash_content:
        raise ValueError("hash_content is required and cannot be empty")
    
    # Validate optional fields
    if source not in VALID_SOURCES:
        raise ValueError(f"source must be one of {VALID_SOURCES}, got: {source}")
    if status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {VALID_STATUSES}, got: {status}")
    
    # Generate version if not provided (use ISO timestamp)
    if not version:
        version = datetime.utcnow().isoformat() + 'Z'
    
    # Generate timestamps
    now = datetime.utcnow().isoformat() + 'Z'
    
    # Generate file hash if file_path provided and hash_file not provided
    if file_path and not hash_file:
        try:
            path = Path(file_path)
            if path.exists() and path.is_file():
                file_content = path.read_bytes()
                hash_file = hashlib.sha256(file_content).hexdigest()
        except Exception:
            # If file read fails, leave hash_file as None
            pass
    
    # Build base metadata
    metadata = {
        'doc_id': doc_id,
        'version': version,
        'category': category,
        'hash_content': hash_content,
        'source': source,
        'repo': repo,
        'status': status,
        'created_at': now,
        'updated_at': now,
        'tags': tags or []
    }
    
    # Add optional fields
    if file_path:
        metadata['file_path'] = file_path
        metadata['path'] = file_path  # Also add to 'path' field for compatibility
    
    if hash_file:
        metadata['hash_file'] = hash_file
    
    # Add metadata_hash for deduplication (hash of metadata itself)
    # Exclude timestamps and status from metadata hash for version comparison
    metadata_for_hash = {k: v for k, v in metadata.items() 
                        if k not in ['created_at', 'updated_at', 'status', 'version']}
    import json
    metadata_json = json.dumps(metadata_for_hash, sort_keys=True, default=str)
    metadata['metadata_hash'] = hashlib.sha256(metadata_json.encode('utf-8')).hexdigest()
    
    # Add content_hash alias for backward compatibility
    metadata['content_hash'] = hash_content
    
    # Merge additional metadata if provided
    if additional_metadata:
        metadata.update(additional_metadata)
    
    return metadata


def query_by_file_path(
    document_store: QdrantDocumentStore,
    file_path: str,
    status: Optional[str] = 'active'
) -> List[Document]:
    """
    Query documents by file path using filter_documents().
    
    Uses Haystack filter format: {"field": "meta.file_path", "operator": "==", "value": ...}
    
    Args:
        document_store: QdrantDocumentStore instance
        file_path: File path to search for
        status: Optional status filter (default: 'active' to get only active documents)
        
    Returns:
        List of Document objects matching the file path
    """
    # Build Haystack-compliant filter format
    conditions = [
        {"field": "meta.file_path", "operator": "==", "value": file_path}
    ]
    
    if status:
        conditions.append({"field": "meta.status", "operator": "==", "value": status})
    
    if len(conditions) == 1:
        filters = conditions[0]
    else:
        filters = {
            "operator": "AND",
            "conditions": conditions
        }
    
    try:
        return document_store.filter_documents(filters=filters)
    except Exception as e:
        # Return empty list on error
        return []


def query_by_content_hash(
    document_store: QdrantDocumentStore,
    content_hash: str,
    status: Optional[str] = None
) -> List[Document]:
    """
    Query documents by content hash using filter_documents().
    
    Checks both 'hash_content' and 'content_hash' fields for backward compatibility.
    Uses Haystack filter format.
    
    Args:
        document_store: QdrantDocumentStore instance
        content_hash: Content hash to search for
        status: Optional status filter (None = all statuses)
        
    Returns:
        List of Document objects matching the content hash
    """
    # Try hash_content first (primary field)
    conditions = [
        {"field": "meta.hash_content", "operator": "==", "value": content_hash}
    ]
    
    if status:
        conditions.append({"field": "meta.status", "operator": "==", "value": status})
    
    if len(conditions) == 1:
        filters = conditions[0]
    else:
        filters = {
            "operator": "AND",
            "conditions": conditions
        }
    
    try:
        docs = document_store.filter_documents(filters=filters)
        if docs:
            return docs
    except Exception:
        pass
    
    # Fallback to content_hash (backward compatibility)
    conditions = [
        {"field": "meta.content_hash", "operator": "==", "value": content_hash}
    ]
    if status:
        conditions.append({"field": "meta.status", "operator": "==", "value": status})
    
    if len(conditions) == 1:
        filters = conditions[0]
    else:
        filters = {
            "operator": "AND",
            "conditions": conditions
        }
    
    try:
        return document_store.filter_documents(filters=filters)
    except Exception:
        return []


def query_by_doc_id(
    document_store: QdrantDocumentStore,
    doc_id: str,
    category: Optional[str] = None,
    status: Optional[str] = 'active'
) -> List[Document]:
    """
    Query documents by doc_id (and optionally category) using filter_documents().
    
    This is the primary method for checking if a document already exists per RULE 4.
    Uses Haystack filter format.
    
    Args:
        document_store: QdrantDocumentStore instance
        doc_id: Document ID to search for
        category: Optional category filter
        status: Optional status filter (default: 'active')
        
    Returns:
        List of Document objects matching the doc_id
    """
    # Build Haystack-compliant filter format
    conditions = [
        {"field": "meta.doc_id", "operator": "==", "value": doc_id}
    ]
    
    if category:
        conditions.append({"field": "meta.category", "operator": "==", "value": category})
    
    if status:
        conditions.append({"field": "meta.status", "operator": "==", "value": status})
    
    if len(conditions) == 1:
        filters = conditions[0]
    else:
        filters = {
            "operator": "AND",
            "conditions": conditions
        }
    
    try:
        return document_store.filter_documents(filters=filters)
    except Exception:
        return []


def validate_metadata(metadata: Dict) -> Tuple[bool, Optional[str]]:
    """
    Validate metadata against RULE 3 requirements.
    
    Args:
        metadata: Metadata dictionary to validate
        
    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if metadata is valid, False otherwise
        - error_message: Error message if invalid, None if valid
    """
    # Check required fields
    for field in REQUIRED_METADATA_FIELDS:
        if field not in metadata:
            return (False, f"Required field '{field}' is missing from metadata")
        if not metadata[field]:
            return (False, f"Required field '{field}' cannot be empty")
    
    # Validate category
    if metadata['category'] not in VALID_CATEGORIES:
        return (False, f"Invalid category: {metadata['category']}. Must be one of {VALID_CATEGORIES}")
    
    # Validate source if present
    if 'source' in metadata and metadata['source'] not in VALID_SOURCES:
        return (False, f"Invalid source: {metadata['source']}. Must be one of {VALID_SOURCES}")
    
    # Validate status if present
    if 'status' in metadata and metadata['status'] not in VALID_STATUSES:
        return (False, f"Invalid status: {metadata['status']}. Must be one of {VALID_STATUSES}")
    
    return (True, None)

