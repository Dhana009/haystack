"""
Index Management Service for Qdrant/Haystack MCP Server.

Creates and manages payload indexes on Qdrant collections for efficient metadata filtering.
Required for bulk operations, metadata queries, and filtering operations.
"""
import os
from typing import List, Optional

import os
from typing import List, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import PayloadSchemaType


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


# Metadata fields that require payload indexes per RULE 9
REQUIRED_INDEX_FIELDS = [
    ("meta.doc_id", PayloadSchemaType.KEYWORD),
    ("meta.category", PayloadSchemaType.KEYWORD),
    ("meta.status", PayloadSchemaType.KEYWORD),
    ("meta.repo", PayloadSchemaType.KEYWORD),
    ("meta.version", PayloadSchemaType.KEYWORD),
    ("meta.file_path", PayloadSchemaType.KEYWORD),
    ("meta.hash_content", PayloadSchemaType.KEYWORD),
    ("meta.content_hash", PayloadSchemaType.KEYWORD),
    ("meta.metadata_hash", PayloadSchemaType.KEYWORD),
]


def create_payload_indexes(
    collection_name: str,
    fields: Optional[List[tuple]] = None,
    client: Optional[QdrantClient] = None
) -> dict:
    """
    Create payload indexes on a Qdrant collection for efficient filtering.
    
    Per RULE 9, the following fields MUST have indexes:
    - doc_id
    - category
    - status
    - repo
    - version
    
    Args:
        collection_name: Name of the Qdrant collection
        fields: Optional list of (field_name, schema_type) tuples. 
                If None, uses REQUIRED_INDEX_FIELDS
        client: Optional QdrantClient instance. If None, creates one.
        
    Returns:
        Dictionary with:
        - status: "success" or "error"
        - created_indexes: List of indexes that were created
        - existing_indexes: List of indexes that already existed
        - errors: List of errors encountered
    """
    if client is None:
        client = _get_qdrant_client()
    
    if fields is None:
        fields = REQUIRED_INDEX_FIELDS
    
    created_indexes = []
    existing_indexes = []
    errors = []
    
    # Get existing collection info to check current indexes
    try:
        collection_info = client.get_collection(collection_name)
        existing_payload_schema = collection_info.payload_schema or {}
    except Exception as e:
        return {
            "status": "error",
            "error": f"Failed to get collection info: {str(e)}",
            "created_indexes": [],
            "existing_indexes": [],
            "errors": [str(e)]
        }
    
    # Create indexes for each field
    for field_name, schema_type in fields:
        try:
            # Check if index already exists
            field_exists = field_name in existing_payload_schema
            
            if field_exists:
                existing_indexes.append(field_name)
                continue
            
            # Create the payload index
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=schema_type
            )
            
            created_indexes.append(field_name)
            
        except Exception as e:
            error_msg = f"Failed to create index for {field_name}: {str(e)}"
            errors.append(error_msg)
    
    return {
        "status": "success" if len(errors) == 0 else "partial_success",
        "created_indexes": created_indexes,
        "existing_indexes": existing_indexes,
        "errors": errors,
        "total_fields": len(fields),
        "successfully_indexed": len(created_indexes) + len(existing_indexes)
    }


def ensure_payload_indexes(
    collection_name: str,
    client: Optional[QdrantClient] = None
) -> dict:
    """
    Ensure all required payload indexes exist on a collection.
    
    This is a convenience function that creates all required indexes
    from REQUIRED_INDEX_FIELDS if they don't exist.
    
    Args:
        collection_name: Name of the Qdrant collection
        client: Optional QdrantClient instance
        
    Returns:
        Dictionary with index creation results
    """
    return create_payload_indexes(
        collection_name=collection_name,
        fields=REQUIRED_INDEX_FIELDS,
        client=client
    )


def list_payload_indexes(
    collection_name: str,
    client: Optional[QdrantClient] = None
) -> dict:
    """
    List all existing payload indexes on a collection.
    
    Args:
        collection_name: Name of the Qdrant collection
        client: Optional QdrantClient instance
        
    Returns:
        Dictionary with:
        - status: "success" or "error"
        - indexes: Dictionary of field_name -> schema_type
        - total: Total number of indexes
    """
    if client is None:
        client = _get_qdrant_client()
    
    try:
        collection_info = client.get_collection(collection_name)
        payload_schema = collection_info.payload_schema or {}
        
        # Convert to readable format
        indexes = {}
        for field_name, schema_info in payload_schema.items():
            if hasattr(schema_info, 'data_type'):
                indexes[field_name] = str(schema_info.data_type)
            else:
                indexes[field_name] = str(schema_info)
        
        return {
            "status": "success",
            "indexes": indexes,
            "total": len(indexes)
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "indexes": {},
            "total": 0
        }

