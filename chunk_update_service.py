"""
Chunk Update Service for Qdrant/Haystack MCP Server.

Implements incremental update logic for chunk-based documents.
Handles partial document updates by updating only changed chunks and preserving unchanged chunks.
"""
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime

from haystack.dataclasses.document import Document
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore

from chunk_service import (
    chunk_document,
    compare_chunks,
    identify_chunk_changes,
    get_chunks_by_parent_doc_id,
    generate_chunk_id
)
from deduplication_service import (
    check_duplicate_level,
    decide_storage_action,
    generate_content_fingerprint,
    ACTION_SKIP,
    ACTION_UPDATE,
    ACTION_STORE
)
from metadata_service import build_chunk_metadata
from update_service import deprecate_version


def update_chunked_document(
    document_store: QdrantDocumentStore,
    content: str,
    doc_id: str,
    category: str,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    version: Optional[str] = None,
    file_path: Optional[str] = None,
    source: str = 'manual',
    tags: Optional[List[str]] = None,
    parent_metadata: Optional[Dict] = None,
    embedder=None
) -> Dict[str, Any]:
    """
    Update a chunked document incrementally, updating only changed chunks.
    
    Process:
    1. Retrieve existing chunks for the document
    2. Chunk the new document version
    3. Compare old chunks vs new chunks
    4. Update only changed chunks (re-embed and update)
    5. Keep unchanged chunks (preserve old embeddings)
    6. Add new chunks (embed and add)
    7. Deprecate deleted chunks
    
    Args:
        document_store: QdrantDocumentStore instance
        content: New document content
        doc_id: Document ID (same as parent document)
        category: Document category
        chunk_size: Chunk size in tokens (default: 512)
        chunk_overlap: Overlap between chunks in tokens (default: 50)
        version: Optional version string (default: auto-generated)
        file_path: Optional file path
        source: Source type (default: 'manual')
        tags: Optional tags list
        parent_metadata: Optional parent document metadata to copy to chunks
        embedder: Optional embedder for generating embeddings
        
    Returns:
        Dictionary with update results:
        - status: "success" | "error"
        - total_chunks: Total number of chunks
        - unchanged_count: Number of unchanged chunks (preserved)
        - changed_count: Number of changed chunks (updated)
        - new_count: Number of new chunks (added)
        - deleted_count: Number of deleted chunks (deprecated)
        - chunk_ids: List of all chunk IDs (new and updated)
        - message: Summary message
    """
    try:
        # Step 1: Retrieve existing chunks
        existing_chunks = get_chunks_by_parent_doc_id(document_store, doc_id, status='active')
        
        # Step 2: Chunk the new document version
        new_chunks = chunk_document(
            content=content,
            doc_id=doc_id,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            parent_metadata=parent_metadata
        )
        
        if not new_chunks:
            return {
                "status": "error",
                "error": "Failed to chunk document",
                "error_type": "ChunkingError"
            }
        
        # Step 3: Compare old chunks vs new chunks
        changes = compare_chunks(existing_chunks, new_chunks)
        
        unchanged_chunks = changes['unchanged']
        changed_chunks = changes['changed']
        new_chunks_list = changes['new']
        deleted_chunks = changes['deleted']
        
        # Step 4: Process unchanged chunks (preserve - no action needed)
        unchanged_count = len(unchanged_chunks)
        
        # Step 5: Process changed chunks (update - re-embed and update)
        changed_count = 0
        updated_chunk_ids = []
        
        for new_chunk in changed_chunks:
            chunk_id = new_chunk.meta.get('chunk_id')
            chunk_index = new_chunk.meta.get('chunk_index')
            
            # Find matching old chunk to deprecate
            old_chunk = None
            for old in existing_chunks:
                if old.meta.get('chunk_index') == chunk_index:
                    old_chunk = old
                    break
            
            # Deprecate old chunk version
            if old_chunk and old_chunk.id:
                try:
                    # Extract content_hash from old_chunk.meta to avoid ID format validation
                    content_hash = None
                    if old_chunk.meta:
                        content_hash = old_chunk.meta.get('hash_content') or old_chunk.meta.get('content_hash')
                    
                    deprecate_version(document_store, old_chunk.id, content_hash=content_hash)
                except Exception as e:
                    # Log error but continue
                    pass
            
            # Generate fingerprint for new chunk
            chunk_fingerprint = generate_content_fingerprint(
                new_chunk.content,
                new_chunk.meta
            )
            chunk_fingerprint['metadata_hash'] = new_chunk.meta.get('metadata_hash', chunk_fingerprint['metadata_hash'])
            chunk_fingerprint['composite_key'] = f"{chunk_fingerprint['content_hash']}:{chunk_fingerprint['metadata_hash']}"
            
            # Build full metadata for chunk
            chunk_metadata = build_chunk_metadata(
                content=new_chunk.content,
                doc_id=chunk_id,
                chunk_id=chunk_id,
                chunk_index=chunk_index,
                parent_doc_id=doc_id,
                total_chunks=len(new_chunks),
                category=category,
                hash_content=chunk_fingerprint['content_hash'],
                version=version,
                file_path=file_path,
                source=source,
                tags=tags,
                status='active',
                parent_metadata=parent_metadata
            )
            
            # Create chunk document
            chunk_doc = Document(content=new_chunk.content, meta=chunk_metadata)
            
            # Embed and store new chunk version
            if embedder:
                result = embedder.run(documents=[chunk_doc])
                embedded_chunk = result["documents"][0]
            else:
                embedded_chunk = chunk_doc
            
            document_store.write_documents([embedded_chunk])
            changed_count += 1
            updated_chunk_ids.append(chunk_id)
        
        # Step 6: Process new chunks (add - embed and add)
        new_count = 0
        
        for new_chunk in new_chunks_list:
            chunk_id = new_chunk.meta.get('chunk_id')
            chunk_index = new_chunk.meta.get('chunk_index')
            
            # Generate fingerprint for new chunk
            chunk_fingerprint = generate_content_fingerprint(
                new_chunk.content,
                new_chunk.meta
            )
            chunk_fingerprint['metadata_hash'] = new_chunk.meta.get('metadata_hash', chunk_fingerprint['metadata_hash'])
            chunk_fingerprint['composite_key'] = f"{chunk_fingerprint['content_hash']}:{chunk_fingerprint['metadata_hash']}"
            
            # Build full metadata for chunk
            chunk_metadata = build_chunk_metadata(
                content=new_chunk.content,
                doc_id=chunk_id,
                chunk_id=chunk_id,
                chunk_index=chunk_index,
                parent_doc_id=doc_id,
                total_chunks=len(new_chunks),
                category=category,
                hash_content=chunk_fingerprint['content_hash'],
                version=version,
                file_path=file_path,
                source=source,
                tags=tags,
                status='active',
                parent_metadata=parent_metadata
            )
            
            # Create chunk document
            chunk_doc = Document(content=new_chunk.content, meta=chunk_metadata)
            
            # Embed and store new chunk
            if embedder:
                result = embedder.run(documents=[chunk_doc])
                embedded_chunk = result["documents"][0]
            else:
                embedded_chunk = chunk_doc
            
            document_store.write_documents([embedded_chunk])
            new_count += 1
            updated_chunk_ids.append(chunk_id)
        
        # Step 7: Process deleted chunks (deprecate)
        deleted_count = 0
        
        for deleted_chunk in deleted_chunks:
            if deleted_chunk.id:
                try:
                    # Extract content_hash from deleted_chunk.meta to avoid ID format validation
                    content_hash = None
                    if deleted_chunk.meta:
                        content_hash = deleted_chunk.meta.get('hash_content') or deleted_chunk.meta.get('content_hash')
                    
                    deprecate_version(document_store, deleted_chunk.id, content_hash=content_hash)
                    deleted_count += 1
                except Exception as e:
                    # Log error but continue
                    pass
        
        # Generate summary message
        total_chunks = len(new_chunks)
        message = (
            f"Incremental update completed. "
            f"Total chunks: {total_chunks}, "
            f"Unchanged: {unchanged_count} (preserved), "
            f"Changed: {changed_count} (updated), "
            f"New: {new_count} (added), "
            f"Deleted: {deleted_count} (deprecated)"
        )
        
        return {
            "status": "success",
            "total_chunks": total_chunks,
            "unchanged_count": unchanged_count,
            "changed_count": changed_count,
            "new_count": new_count,
            "deleted_count": deleted_count,
            "chunk_ids": updated_chunk_ids,
            "message": message
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__
        }


def store_chunked_document(
    document_store: QdrantDocumentStore,
    content: str,
    doc_id: str,
    category: str,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    version: Optional[str] = None,
    file_path: Optional[str] = None,
    source: str = 'manual',
    tags: Optional[List[str]] = None,
    parent_metadata: Optional[Dict] = None,
    embedder=None
) -> Dict[str, Any]:
    """
    Store a new chunked document (all chunks are new).
    
    Args:
        document_store: QdrantDocumentStore instance
        content: Document content
        doc_id: Document ID
        category: Document category
        chunk_size: Chunk size in tokens (default: 512)
        chunk_overlap: Overlap between chunks in tokens (default: 50)
        version: Optional version string (default: auto-generated)
        file_path: Optional file path
        source: Source type (default: 'manual')
        tags: Optional tags list
        parent_metadata: Optional parent document metadata to copy to chunks
        embedder: Optional embedder for generating embeddings
        
    Returns:
        Dictionary with storage results:
        - status: "success" | "error"
        - total_chunks: Total number of chunks stored
        - chunk_ids: List of chunk IDs
        - message: Summary message
    """
    try:
        # Chunk the document
        chunks = chunk_document(
            content=content,
            doc_id=doc_id,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            parent_metadata=parent_metadata
        )
        
        if not chunks:
            return {
                "status": "error",
                "error": "Failed to chunk document",
                "error_type": "ChunkingError"
            }
        
        # Store all chunks
        chunk_ids = []
        stored_chunks = []
        
        for chunk in chunks:
            chunk_id = chunk.meta.get('chunk_id')
            chunk_index = chunk.meta.get('chunk_index')
            
            # Generate fingerprint
            chunk_fingerprint = generate_content_fingerprint(
                chunk.content,
                chunk.meta
            )
            chunk_fingerprint['metadata_hash'] = chunk.meta.get('metadata_hash', chunk_fingerprint['metadata_hash'])
            chunk_fingerprint['composite_key'] = f"{chunk_fingerprint['content_hash']}:{chunk_fingerprint['metadata_hash']}"
            
            # Build full metadata
            chunk_metadata = build_chunk_metadata(
                content=chunk.content,
                doc_id=chunk_id,
                chunk_id=chunk_id,
                chunk_index=chunk_index,
                parent_doc_id=doc_id,
                total_chunks=len(chunks),
                category=category,
                hash_content=chunk_fingerprint['content_hash'],
                version=version,
                file_path=file_path,
                source=source,
                tags=tags,
                status='active',
                parent_metadata=parent_metadata
            )
            
            # Create chunk document
            chunk_doc = Document(content=chunk.content, meta=chunk_metadata)
            
            # Embed and store
            if embedder:
                result = embedder.run(documents=[chunk_doc])
                embedded_chunk = result["documents"][0]
            else:
                embedded_chunk = chunk_doc
            
            stored_chunks.append(embedded_chunk)
            chunk_ids.append(chunk_id)
        
        # Batch write all chunks
        document_store.write_documents(stored_chunks)
        
        return {
            "status": "success",
            "total_chunks": len(chunks),
            "chunk_ids": chunk_ids,
            "message": f"Chunked document stored successfully with {len(chunks)} chunks"
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__
        }

