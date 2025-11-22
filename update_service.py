"""
Update Service for Qdrant/Haystack MCP Server.

Implements atomic update operations for document content and metadata using QdrantClient.
Since Haystack doesn't have native update methods, we use QdrantClient directly.
"""
import os
from typing import Dict, List, Optional, Any
from datetime import datetime

from haystack.dataclasses.document import Document
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from haystack.components.embedders import SentenceTransformersDocumentEmbedder
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue

from deduplication_service import generate_content_fingerprint
from metadata_service import build_metadata_schema, query_by_doc_id


def _get_qdrant_client() -> QdrantClient:
    """Get QdrantClient instance using environment variables."""
    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    
    if not qdrant_url or not qdrant_api_key:
        raise ValueError(
            "QDRANT_URL and QDRANT_API_KEY environment variables must be set"
        )
    
    return QdrantClient(url=qdrant_url, api_key=qdrant_api_key)


def update_document_content(
    document_store: QdrantDocumentStore,
    document_id: str,
    new_content: str,
    embedder: SentenceTransformersDocumentEmbedder,
    metadata_updates: Optional[Dict[str, Any]] = None,
    collection_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Atomically update document content and optionally metadata using QdrantClient.upsert().
    
    Process:
    1. Retrieve existing document
    2. Generate new embedding for new content
    3. Update metadata (including hash_content, updated_at)
    4. Use upsert() to atomically update vector and payload
    
    Args:
        document_store: QdrantDocumentStore instance
        document_id: Document ID (Qdrant point ID)
        new_content: New document content
        embedder: Document embedder for generating new embedding
        metadata_updates: Optional metadata fields to update
        collection_name: Optional collection name (defaults to document_store's collection)
        
    Returns:
        Dictionary with update results
    """
    try:
        client = _get_qdrant_client()
        
        # Get collection name
        if not collection_name:
            collection_name = document_store.index
        
        # Retrieve existing point
        points = client.retrieve(
            collection_name=collection_name,
            ids=[document_id],
            with_payload=True,
            with_vectors=True
        )
        
        if not points or len(points) == 0:
            return {
                "status": "error",
                "error": f"Document not found: {document_id}"
            }
        
        existing_point = points[0]
        existing_payload = dict(existing_point.payload or {})
        
        # Handle both nested and flattened metadata structures
        if "meta" in existing_payload and isinstance(existing_payload["meta"], dict):
            # Nested structure: payload["meta"] = {...}
            existing_meta = dict(existing_payload["meta"])
            
            # Generate new fingerprint for new content
            fingerprint = generate_content_fingerprint(new_content, existing_meta)
            
            # Prepare updated metadata
            updated_meta = dict(existing_meta)
            updated_meta["hash_content"] = fingerprint["content_hash"]
            updated_meta["content_hash"] = fingerprint["content_hash"]  # Alias
            updated_meta["updated_at"] = datetime.utcnow().isoformat() + 'Z'
            
            # Apply metadata updates if provided
            if metadata_updates:
                updated_meta.update(metadata_updates)
            
            # Regenerate metadata_hash
            import json
            import hashlib
            metadata_for_hash = {k: v for k, v in updated_meta.items() 
                                if k not in ['created_at', 'updated_at', 'status', 'version']}
            metadata_json = json.dumps(metadata_for_hash, sort_keys=True, default=str)
            updated_meta["metadata_hash"] = hashlib.sha256(metadata_json.encode('utf-8')).hexdigest()
            
            # Generate new embedding
            doc_for_embedding = Document(content=new_content, meta=updated_meta)
            embedding_result = embedder.run(documents=[doc_for_embedding])
            new_embedding = embedding_result["documents"][0].embedding
            
            # Update payload
            updated_payload = dict(existing_payload)
            updated_payload["content"] = new_content
            updated_payload["meta"] = updated_meta
        else:
            # Flattened structure: metadata fields at top level
            # Extract metadata fields for fingerprint generation
            metadata_fields = {k: v for k, v in existing_payload.items() 
                             if k not in ['content', 'id']}
            
            # Generate new fingerprint for new content
            fingerprint = generate_content_fingerprint(new_content, metadata_fields)
            
            # Update payload directly
            updated_payload = dict(existing_payload)
            updated_payload["content"] = new_content
            updated_payload["hash_content"] = fingerprint["content_hash"]
            updated_payload["content_hash"] = fingerprint["content_hash"]  # Alias
            updated_payload["updated_at"] = datetime.utcnow().isoformat() + 'Z'
            
            # Apply metadata updates if provided
            if metadata_updates:
                updated_payload.update(metadata_updates)
            
            # Regenerate metadata_hash
            import json
            import hashlib
            metadata_for_hash = {k: v for k, v in updated_payload.items() 
                                if k not in ['content', 'id', 'created_at', 'updated_at', 'status', 'version', 'metadata_hash']}
            metadata_json = json.dumps(metadata_for_hash, sort_keys=True, default=str)
            updated_payload["metadata_hash"] = hashlib.sha256(metadata_json.encode('utf-8')).hexdigest()
            
            # Generate new embedding (need to reconstruct meta dict for Document)
            meta_for_embedding = {k: v for k, v in updated_payload.items() 
                                 if k not in ['content', 'id']}
            doc_for_embedding = Document(content=new_content, meta=meta_for_embedding)
            embedding_result = embedder.run(documents=[doc_for_embedding])
            new_embedding = embedding_result["documents"][0].embedding
        
        # Atomically update using upsert
        client.upsert(
            collection_name=collection_name,
            points=[
                PointStruct(
                    id=document_id,
                    vector=new_embedding,
                    payload=updated_payload
                )
            ]
        )
        
        return {
            "status": "success",
            "document_id": document_id,
            "message": "Document content updated successfully",
            "updated_fields": ["content", "hash_content", "updated_at"] + (list(metadata_updates.keys()) if metadata_updates else [])
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__
        }


def update_document_metadata(
    document_store: QdrantDocumentStore,
    document_id: str,
    metadata_updates: Dict[str, Any],
    collection_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update only metadata fields without changing content using QdrantClient.set_payload().
    
    Args:
        document_store: QdrantDocumentStore instance
        document_id: Document ID (Qdrant point ID)
        metadata_updates: Dictionary of metadata fields to update
        collection_name: Optional collection name (defaults to document_store's collection)
        
    Returns:
        Dictionary with update results
    """
    try:
        client = _get_qdrant_client()
        
        # Get collection name
        if not collection_name:
            collection_name = document_store.index
        
        # Retrieve existing point to get current payload
        points = client.retrieve(
            collection_name=collection_name,
            ids=[document_id],
            with_payload=True,
            with_vectors=False
        )
        
        if not points or len(points) == 0:
            return {
                "status": "error",
                "error": f"Document not found: {document_id}"
            }
        
        existing_point = points[0]
        existing_payload = dict(existing_point.payload or {})
        
        # Handle both nested and flattened metadata structures
        # Haystack may store metadata nested under "meta" or flattened at top level
        if "meta" in existing_payload and isinstance(existing_payload["meta"], dict):
            # Nested structure: payload["meta"] = {...}
            existing_meta = dict(existing_payload["meta"])
            updated_meta = dict(existing_meta)
            updated_meta.update(metadata_updates)
            updated_meta["updated_at"] = datetime.utcnow().isoformat() + 'Z'
            
            # Regenerate metadata_hash if metadata changed
            import json
            import hashlib
            metadata_for_hash = {k: v for k, v in updated_meta.items() 
                                if k not in ['created_at', 'updated_at', 'status', 'version']}
            metadata_json = json.dumps(metadata_for_hash, sort_keys=True, default=str)
            updated_meta["metadata_hash"] = hashlib.sha256(metadata_json.encode('utf-8')).hexdigest()
            
            updated_payload["meta"] = updated_meta
        else:
            # Flattened structure: metadata fields at top level
            # Update metadata fields directly in payload
            for key, value in metadata_updates.items():
                existing_payload[key] = value
            existing_payload["updated_at"] = datetime.utcnow().isoformat() + 'Z'
            
            # Regenerate metadata_hash (collect all metadata fields)
            import json
            import hashlib
            # Extract metadata fields (exclude content, id, and dynamic fields)
            metadata_fields = {k: v for k, v in existing_payload.items() 
                             if k not in ['content', 'id', 'created_at', 'updated_at', 'status', 'version', 'metadata_hash']}
            metadata_json = json.dumps(metadata_fields, sort_keys=True, default=str)
            existing_payload["metadata_hash"] = hashlib.sha256(metadata_json.encode('utf-8')).hexdigest()
            updated_payload = existing_payload
        
        # Get vector from existing point - handle different vector formats
        vector = None
        if hasattr(existing_point, 'vector') and existing_point.vector is not None:
            if isinstance(existing_point.vector, dict):
                # Named vectors: {"default": [0.1, 0.2, ...]}
                vector = existing_point.vector.get("default") or list(existing_point.vector.values())[0] if existing_point.vector else None
            elif isinstance(existing_point.vector, list):
                vector = existing_point.vector
        
        client.upsert(
            collection_name=collection_name,
            points=[
                PointStruct(
                    id=document_id,
                    vector=vector,
                    payload=updated_payload
                )
            ]
        )
        
        return {
            "status": "success",
            "document_id": document_id,
            "message": "Document metadata updated successfully",
            "updated_fields": list(metadata_updates.keys())
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__
        }


def deprecate_version(
    document_store: QdrantDocumentStore,
    document_id: str,
    collection_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Mark a document version as deprecated using QdrantClient.set_payload().
    
    Args:
        document_store: QdrantDocumentStore instance
        document_id: Document ID (Qdrant point ID)
        collection_name: Optional collection name (defaults to document_store's collection)
        
    Returns:
        Dictionary with deprecation results
    """
    return update_document_metadata(
        document_store=document_store,
        document_id=document_id,
        metadata_updates={"status": "deprecated"},
        collection_name=collection_name
    )


def get_version_history(
    document_store: QdrantDocumentStore,
    doc_id: str,
    category: Optional[str] = None,
    include_deprecated: bool = True
) -> List[Document]:
    """
    Retrieve version history for a document by doc_id.
    
    Args:
        document_store: QdrantDocumentStore instance
        doc_id: Logical document ID (not Qdrant point ID)
        category: Optional category filter
        include_deprecated: Whether to include deprecated versions
        
    Returns:
        List of Document objects representing all versions, sorted by version/created_at
    """
    # Query by doc_id
    status_filter = None if include_deprecated else 'active'
    documents = query_by_doc_id(document_store, doc_id, category, status=status_filter)
    
    # Sort by version or created_at
    def sort_key(doc):
        meta = doc.meta or {}
        # Try to sort by version first, then by created_at
        version = meta.get("version", "")
        created_at = meta.get("created_at", "")
        return (version, created_at)
    
    documents.sort(key=sort_key)
    
    return documents

