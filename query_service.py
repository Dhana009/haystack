"""
Query Service for Qdrant/Haystack MCP Server.

Implements enhanced metadata querying capabilities including path-based retrieval,
metadata filtering in search, and statistics aggregation.
"""
from typing import Dict, List, Optional, Any

from haystack.dataclasses.document import Document
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from haystack_integrations.components.retrievers.qdrant import QdrantEmbeddingRetriever
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

from metadata_service import query_by_file_path


def get_document_by_path(
    document_store: QdrantDocumentStore,
    file_path: str,
    status: Optional[str] = 'active'
) -> Optional[Document]:
    """
    Retrieve a document by file path using filter_documents().
    
    Args:
        document_store: QdrantDocumentStore instance
        file_path: File path to search for
        status: Optional status filter (default: 'active')
        
    Returns:
        Document object if found, None otherwise
    """
    docs = query_by_file_path(document_store, file_path, status)
    if docs:
        return docs[0]  # Return first match
    return None


def search_with_metadata_filters(
    document_store: QdrantDocumentStore,
    query: str,
    text_embedder,
    retriever: Optional[QdrantEmbeddingRetriever] = None,
    metadata_filters: Optional[Dict[str, Any]] = None,
    top_k: int = 5
) -> List[Document]:
    """
    Perform semantic search with metadata filtering.
    
    Uses QdrantEmbeddingRetriever with filters parameter for hybrid search.
    
    Args:
        document_store: QdrantDocumentStore instance
        query: Search query text
        text_embedder: Text embedder for generating query embedding
        retriever: Optional QdrantEmbeddingRetriever instance (created if not provided)
        metadata_filters: Optional metadata filters (Haystack filter format)
        top_k: Number of results to return
        
    Returns:
        List of Document objects matching the query and filters
    """
    # Generate query embedding
    embedding_result = text_embedder.run(text=query)
    query_embedding = embedding_result["embedding"]
    
    # Create retriever if not provided
    if not retriever:
        retriever = QdrantEmbeddingRetriever(document_store=document_store, top_k=top_k)
    
    # Convert Haystack filters to Qdrant filters if needed
    # QdrantEmbeddingRetriever accepts both Haystack dict filters and Qdrant Filter objects
    qdrant_filters = None
    if metadata_filters:
        # QdrantEmbeddingRetriever can accept Haystack filter format directly
        # But we may need to convert to Qdrant Filter for better performance
        # For now, pass Haystack format and let the retriever handle it
        qdrant_filters = metadata_filters
    
    # Perform retrieval with filters
    result = retriever.run(
        query_embedding=query_embedding,
        filters=qdrant_filters,
        top_k=top_k
    )
    
    return result.get("documents", [])


def get_metadata_stats(
    document_store: QdrantDocumentStore,
    filters: Optional[Dict[str, Any]] = None,
    group_by_fields: Optional[List[str]] = None,
    collection_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get statistics aggregated by metadata fields.
    
    Uses QdrantClient.scroll() to retrieve documents and perform manual aggregation,
    as Qdrant's facet API may not be available in all versions.
    
    Args:
        document_store: QdrantDocumentStore instance
        filters: Optional Haystack filter dictionary
        group_by_fields: List of metadata fields to group by (e.g., ["category", "status"])
        collection_name: Optional collection name (defaults to document_store's collection)
        
    Returns:
        Dictionary with statistics:
        - total_documents: Total count
        - by_field: Aggregated counts by each field
        - field_values: Unique values and counts for each field
    """
    try:
        # Get all documents matching filters
        documents = document_store.filter_documents(filters=filters)
        
        total = len(documents)
        
        # Aggregate statistics
        stats = {
            "total_documents": total,
            "by_field": {},
            "field_values": {}
        }
        
        if not group_by_fields:
            group_by_fields = ["category", "status", "source"]
        
        # Aggregate by each field
        for field in group_by_fields:
            field_counts = {}
            for doc in documents:
                meta = doc.meta or {}
                value = meta.get(field, "unknown")
                field_counts[value] = field_counts.get(value, 0) + 1
            
            stats["by_field"][field] = field_counts
            stats["field_values"][field] = {
                "unique_count": len(field_counts),
                "values": sorted(field_counts.items(), key=lambda x: x[1], reverse=True)
            }
        
        # Additional statistics
        stats["categories"] = stats["by_field"].get("category", {})
        stats["statuses"] = stats["by_field"].get("status", {})
        stats["sources"] = stats["by_field"].get("source", {})
        
        return stats
    
    except Exception as e:
        return {
            "error": str(e),
            "error_type": type(e).__name__,
            "total_documents": 0
        }

