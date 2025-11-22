"""
Bulk Operations Service for Qdrant/Haystack MCP Server.

Implements bulk delete, update, export, and import operations using QdrantClient
directly for operations not supported by Haystack's DocumentStore interface.
"""
import json
import os
from typing import Dict, List, Optional, Any
from pathlib import Path

from haystack.dataclasses.document import Document
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny, Range, PointStruct

from metadata_service import query_by_doc_id
from deduplication_service import generate_content_fingerprint
from metadata_service import build_metadata_schema


def _get_qdrant_client() -> QdrantClient:
    """
    Get QdrantClient instance using environment variables.
    
    Returns:
        QdrantClient instance
    """
    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    
    if not qdrant_url or not qdrant_api_key:
        raise ValueError(
            "QDRANT_URL and QDRANT_API_KEY environment variables must be set"
        )
    
    return QdrantClient(url=qdrant_url, api_key=qdrant_api_key)


def _convert_haystack_filter_to_qdrant(haystack_filter: Dict) -> Optional[Filter]:
    """
    Convert Haystack filter format to Qdrant Filter format.
    
    Haystack format: {"field": "meta.category", "operator": "==", "value": "user_rule"}
    Qdrant format: Filter(must=[FieldCondition(key="category", match=MatchValue(value="user_rule"))])
    
    Note: Qdrant stores Haystack metadata in payload["meta"], so we need to access fields
    as "meta.category" in Qdrant, not just "category". However, Haystack's filter_documents
    already handles this, so when using QdrantClient directly, we need to use the full path.
    
    Args:
        haystack_filter: Haystack filter dictionary
        
    Returns:
        Qdrant Filter object or None
    """
    if not haystack_filter:
        return None
    
    # Handle simple comparison filter
    if "field" in haystack_filter:
        field = haystack_filter["field"]
        operator = haystack_filter.get("operator", "==")
        value = haystack_filter.get("value")
        
        # Haystack stores metadata nested in payload["meta"], so when using QdrantClient
        # directly (not through Haystack's filter_documents), we need to use the full
        # nested path like "meta.category" not just "category".
        # 
        # However, when using QdrantClient.scroll() or .delete() with filters, Qdrant
        # requires payload indexes to be created on the fields first. Without indexes,
        # filtering operations will fail with "Index required but not found" error.
        #
        # IMPORTANT: Keep the "meta." prefix - don't remove it! Haystack stores metadata
        # nested under "meta" in the Qdrant payload structure.
        if field.startswith("meta."):
            # Keep the full nested path for Qdrant payload structure
            key = field  # e.g., "meta.category", "meta.status"
        else:
            # Direct payload field (e.g., "content", "id") - rare, usually Haystack uses "meta."
            key = field
        
        # Convert operator to Qdrant format
        if operator == "==":
            return Filter(
                must=[
                    FieldCondition(
                        key=key,
                        match=MatchValue(value=value)
                    )
                ]
            )
        elif operator == "!=":
            return Filter(
                must_not=[
                    FieldCondition(
                        key=key,
                        match=MatchValue(value=value)
                    )
                ]
            )
        elif operator == ">":
            return Filter(
                must=[
                    FieldCondition(
                        key=key,
                        range=Range(gt=value)
                    )
                ]
            )
        elif operator == ">=":
            return Filter(
                must=[
                    FieldCondition(
                        key=key,
                        range=Range(gte=value)
                    )
                ]
            )
        elif operator == "<":
            return Filter(
                must=[
                    FieldCondition(
                        key=key,
                        range=Range(lt=value)
                    )
                ]
            )
        elif operator == "<=":
            return Filter(
                must=[
                    FieldCondition(
                        key=key,
                        range=Range(lte=value)
                    )
                ]
            )
        elif operator == "in":
            # Qdrant supports "in" via MatchAny
            if not isinstance(value, list):
                value = [value]
            return Filter(
                must=[
                    FieldCondition(
                        key=key,
                        match=MatchAny(any=value)
                    )
                ]
            )
        elif operator == "not in":
            if not isinstance(value, list):
                value = [value]
            return Filter(
                must_not=[
                    FieldCondition(
                        key=key,
                        match=MatchAny(any=value)
                    )
                ]
            )
    
    # Handle logic filter (AND, OR, NOT)
    if "operator" in haystack_filter and "conditions" in haystack_filter:
        operator = haystack_filter["operator"]
        conditions = haystack_filter["conditions"]
        
        # Convert each condition recursively
        qdrant_conditions = []
        for condition in conditions:
            qdrant_condition = _convert_haystack_filter_to_qdrant(condition)
            if qdrant_condition:
                qdrant_conditions.append(qdrant_condition)
        
        if not qdrant_conditions:
            return None
        
        if operator == "AND":
            # Combine all conditions into must array
            must_conditions = []
            must_not_conditions = []
            should_conditions = []
            
            for cond in qdrant_conditions:
                if hasattr(cond, 'must') and cond.must:
                    must_conditions.extend(cond.must)
                if hasattr(cond, 'must_not') and cond.must_not:
                    must_not_conditions.extend(cond.must_not)
                if hasattr(cond, 'should') and cond.should:
                    should_conditions.extend(cond.should)
            
            filter_dict = {}
            if must_conditions:
                filter_dict['must'] = must_conditions
            if must_not_conditions:
                filter_dict['must_not'] = must_not_conditions
            if should_conditions:
                filter_dict['should'] = should_conditions
            
            return Filter(**filter_dict) if filter_dict else None
        
        elif operator == "OR":
            # For OR, we use should - any matching condition includes the point
            # Qdrant doesn't support min_should_match, so all should conditions are ORed
            return Filter(
                should=qdrant_conditions
            )
        
        elif operator == "NOT":
            # For NOT, we wrap the condition in must_not
            if len(qdrant_conditions) == 1:
                # Single condition - extract its must/must_not/should
                not_cond = qdrant_conditions[0]
                if hasattr(not_cond, 'must') and not_cond.must:
                    return Filter(must_not=not_cond.must)
                elif hasattr(not_cond, 'must_not') and not_cond.must_not:
                    # Double negation - convert must_not to must
                    return Filter(must=not_cond.must_not)
            # Multiple conditions in NOT - wrap all in must_not
            return Filter(must_not=qdrant_conditions)
    
    return None


def delete_by_filter(
    document_store: QdrantDocumentStore,
    filters: Dict[str, Any],
    collection_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Delete documents matching metadata filters using QdrantClient.scroll() + delete() pattern.
    
    Process:
    1. Use scroll() with filter to get all matching point IDs
    2. Delete points by IDs
    
    Args:
        document_store: QdrantDocumentStore instance
        filters: Haystack filter dictionary (e.g., {"field": "meta.category", "operator": "==", "value": "user_rule"})
        collection_name: Optional collection name (defaults to document_store's collection)
        
    Returns:
        Dictionary with deletion results:
        - deleted_count: Number of documents deleted
        - status: "success" or "error"
        - error: Error message if failed
    """
    try:
        client = _get_qdrant_client()
        
        # Get collection name
        if not collection_name:
            collection_name = document_store.index
        
        # Convert Haystack filter to Qdrant filter
        qdrant_filter = _convert_haystack_filter_to_qdrant(filters)
        
        # Scroll through all matching points and collect IDs
        offset = None
        all_point_ids = []
        batch_size = 100
        
        while True:
            scroll_result = client.scroll(
                collection_name=collection_name,
                scroll_filter=qdrant_filter,
                limit=batch_size,
                offset=offset,
                with_payload=False,
                with_vectors=False
            )
            
            points, next_offset = scroll_result
            
            if not points:
                break
            
            all_point_ids.extend([point.id for point in points])
            
            if next_offset is None:
                break
            
            offset = next_offset
        
        # Delete all collected point IDs
        deleted_count = 0
        if all_point_ids:
            # Delete in batches to avoid overwhelming the server
            batch_size = 100
            for i in range(0, len(all_point_ids), batch_size):
                batch_ids = all_point_ids[i:i + batch_size]
                client.delete(
                    collection_name=collection_name,
                    points_selector=batch_ids
                )
                deleted_count += len(batch_ids)
        
        return {
            "status": "success",
            "deleted_count": deleted_count,
            "message": f"Successfully deleted {deleted_count} documents"
        }
    
    except Exception as e:
        return {
            "status": "error",
            "deleted_count": 0,
            "error": str(e),
            "error_type": type(e).__name__
        }


def delete_by_ids(
    document_store: QdrantDocumentStore,
    document_ids: List[str],
    collection_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Delete documents by their IDs using document_store.delete_documents().
    
    Args:
        document_store: QdrantDocumentStore instance
        document_ids: List of document IDs to delete
        collection_name: Optional collection name (not used, kept for API consistency)
        
    Returns:
        Dictionary with deletion results
    """
    try:
        if not document_ids:
            return {
                "status": "success",
                "deleted_count": 0,
                "message": "No documents to delete"
            }
        
        # Use Haystack's delete_documents method
        document_store.delete_documents(document_ids)
        
        return {
            "status": "success",
            "deleted_count": len(document_ids),
            "message": f"Successfully deleted {len(document_ids)} documents"
        }
    
    except Exception as e:
        return {
            "status": "error",
            "deleted_count": 0,
            "error": str(e),
            "error_type": type(e).__name__
        }


def update_metadata_by_filter(
    document_store: QdrantDocumentStore,
    filters: Dict[str, Any],
    metadata_updates: Dict[str, Any],
    collection_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update metadata for multiple documents matching a filter using QdrantClient.set_payload().
    
    Uses set_payload() with Filter parameter for efficient bulk updates.
    
    Args:
        document_store: QdrantDocumentStore instance
        filters: Haystack filter dictionary to match documents
        metadata_updates: Dictionary of metadata fields to update
        collection_name: Optional collection name (defaults to document_store's collection)
        
    Returns:
        Dictionary with update results:
        - updated_count: Number of documents updated (estimated)
        - status: "success" or "error"
    """
    try:
        client = _get_qdrant_client()
        
        # Get collection name
        if not collection_name:
            collection_name = document_store.index
        
        # Convert Haystack filter to Qdrant filter
        qdrant_filter = _convert_haystack_filter_to_qdrant(filters)
        
        if not qdrant_filter:
            return {
                "status": "error",
                "updated_count": 0,
                "error": "Invalid filter provided"
            }
        
        # Use set_payload to update metadata for all matching points
        # Haystack stores metadata in payload["meta"] as a nested dictionary
        # We need to update each field in the meta dictionary
        
        # For each metadata field, we need to update payload["meta"][key]
        # Qdrant's set_payload supports nested updates, but we need to structure it correctly
        # Since set_payload merges with existing payload, we can update meta fields directly
        
        # Use scroll to get points, update payload, then upsert
        # This ensures we preserve the existing payload structure
        # Note: We scroll once, update, and count during the update process
        offset = None
        updated_count = 0
        batch_size = 100
        
        while True:
            scroll_result = client.scroll(
                collection_name=collection_name,
                scroll_filter=qdrant_filter,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=True
            )
            
            points, next_offset = scroll_result
            
            if not points:
                break
            
            # Update each point's payload
            points_to_upsert = []
            for point in points:
                # Get existing payload
                payload = dict(point.payload or {})
                
                # Handle both nested and flattened metadata structures
                # Haystack may store metadata nested under "meta" or flattened at top level
                if "meta" in payload and isinstance(payload["meta"], dict):
                    # Nested structure: payload["meta"] = {...}
                    meta = dict(payload["meta"])
                    meta.update(metadata_updates)
                    payload["meta"] = meta
                else:
                    # Flattened structure: metadata fields at top level
                    # Update metadata fields directly in payload
                    for key, value in metadata_updates.items():
                        payload[key] = value
                
                # Create PointStruct for upsert
                # Get vector from point - Qdrant returns vectors in different formats
                vector = None
                if hasattr(point, 'vector'):
                    if point.vector is not None:
                        # Handle both named vector and default vector
                        if isinstance(point.vector, dict):
                            # Named vectors: {"default": [0.1, 0.2, ...]}
                            vector = point.vector.get("default") or list(point.vector.values())[0] if point.vector else None
                        elif isinstance(point.vector, list):
                            vector = point.vector
                
                points_to_upsert.append(
                    PointStruct(
                        id=point.id,
                        vector=vector,
                        payload=payload
                    )
                )
            
            # Upsert updated points
            if points_to_upsert:
                client.upsert(
                    collection_name=collection_name,
                    points=points_to_upsert
                )
                updated_count += len(points_to_upsert)
            
            if next_offset is None:
                break
            
            offset = next_offset
        
        return {
            "status": "success",
            "updated_count": updated_count,
            "message": f"Successfully updated metadata for {updated_count} documents"
        }
    
    except Exception as e:
        return {
            "status": "error",
            "updated_count": 0,
            "error": str(e),
            "error_type": type(e).__name__
        }


def export_documents(
    document_store: QdrantDocumentStore,
    filters: Optional[Dict[str, Any]] = None,
    include_embeddings: bool = False,
    collection_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Export documents with metadata to JSON-serializable format.
    
    Uses filter_documents() to retrieve documents, then serializes them.
    
    Args:
        document_store: QdrantDocumentStore instance
        filters: Optional Haystack filter dictionary
        include_embeddings: Whether to include embeddings in export
        collection_name: Optional collection name (not used, kept for API consistency)
        
    Returns:
        List of dictionaries representing documents
    """
    try:
        # Use Haystack's filter_documents
        documents = document_store.filter_documents(filters=filters)
        
        # Serialize documents
        exported = []
        for doc in documents:
            doc_dict = {
                "id": doc.id,
                "content": doc.content,
                "meta": doc.meta or {}
            }
            
            if include_embeddings and doc.embedding:
                doc_dict["embedding"] = doc.embedding
            
            exported.append(doc_dict)
        
        return exported
    
    except Exception as e:
        raise Exception(f"Failed to export documents: {str(e)}")


def import_documents(
    document_store: QdrantDocumentStore,
    documents_data: List[Dict[str, Any]],
    duplicate_strategy: str = "skip",
    batch_size: int = 100,
    embedder=None
) -> Dict[str, Any]:
    """
    Import documents with duplicate handling strategy.
    
    Strategies:
    - "skip": Skip documents that already exist (by doc_id)
    - "update": Update existing documents
    - "error": Raise error if duplicates found
    
    Args:
        document_store: QdrantDocumentStore instance
        documents_data: List of document dictionaries with content, meta, etc.
        duplicate_strategy: How to handle duplicates ("skip", "update", "error")
        batch_size: Number of documents to process per batch
        embedder: Optional embedder for generating embeddings (required for new documents)
        
    Returns:
        Dictionary with import results:
        - imported_count: Number of documents imported
        - skipped_count: Number of documents skipped
        - updated_count: Number of documents updated
        - errors: List of errors encountered
    """
    imported_count = 0
    skipped_count = 0
    updated_count = 0
    errors = []
    
    try:
        for i in range(0, len(documents_data), batch_size):
            batch = documents_data[i:i + batch_size]
            batch_documents = []
            
            for doc_data in batch:
                try:
                    content = doc_data.get("content", "")
                    meta = doc_data.get("meta", {})
                    doc_id = meta.get("doc_id") or meta.get("id")
                    
                    if not doc_id:
                        errors.append({
                            "document": doc_data,
                            "error": "Missing doc_id in metadata"
                        })
                        continue
                    
                    # Check for existing document
                    category = meta.get("category", "other")
                    existing_docs = query_by_doc_id(document_store, doc_id, category, status=None)
                    
                    if existing_docs:
                        if duplicate_strategy == "skip":
                            skipped_count += 1
                            continue
                        elif duplicate_strategy == "error":
                            errors.append({
                                "document": doc_data,
                                "error": f"Duplicate document found: {doc_id}"
                            })
                            continue
                        elif duplicate_strategy == "update":
                            # For update, we'll create a new document (actual update in Phase 2 update_service)
                            updated_count += 1
                    
                    # Create Document object
                    doc = Document(content=content, meta=meta)
                    batch_documents.append(doc)
                
                except Exception as e:
                    errors.append({
                        "document": doc_data,
                        "error": str(e)
                    })
            
            # Write batch if we have documents
            if batch_documents:
                if embedder:
                    # Embed documents
                    result = embedder.run(documents=batch_documents)
                    documents_with_embeddings = result["documents"]
                else:
                    documents_with_embeddings = batch_documents
                
                document_store.write_documents(documents_with_embeddings)
                imported_count += len(documents_with_embeddings)
        
        return {
            "status": "success",
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "updated_count": updated_count,
            "errors": errors,
            "total_processed": len(documents_data)
        }
    
    except Exception as e:
        return {
            "status": "error",
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "updated_count": updated_count,
            "errors": errors + [{"error": str(e)}],
            "total_processed": len(documents_data)
        }

