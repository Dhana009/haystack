"""
Chunk Service for Qdrant/Haystack MCP Server.

Implements document chunking and chunk management for incremental updates.
Enables partial document updates by splitting documents into chunks and tracking changes at chunk level.
"""
import hashlib
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from haystack.dataclasses.document import Document
from haystack.components.preprocessors import RecursiveDocumentSplitter

from deduplication_service import normalize_content, generate_content_fingerprint


# Default chunking parameters
DEFAULT_CHUNK_SIZE = 512  # tokens (per RULE 2: 512-1024 tokens preferred)
DEFAULT_CHUNK_OVERLAP = 50  # tokens
DEFAULT_SEPARATORS = ["\n\n", "\n", ". ", " "]  # Natural boundaries: paragraphs, lines, sentences, words


def generate_chunk_id(doc_id: str, chunk_index: int) -> str:
    """
    Generate stable chunk ID for a document chunk.
    
    Format: {doc_id}_chunk_{chunk_index}
    This ensures chunks can be uniquely identified and tracked across updates.
    
    Args:
        doc_id: Parent document ID
        chunk_index: Zero-based index of the chunk within the document
        
    Returns:
        Stable chunk ID string
    """
    return f"{doc_id}_chunk_{chunk_index}"


def chunk_document(
    content: str,
    doc_id: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    separators: Optional[List[str]] = None,
    parent_metadata: Optional[Dict] = None
) -> List[Document]:
    """
    Split a document into chunks using Haystack's RecursiveDocumentSplitter.
    
    Creates chunk documents with metadata including:
    - chunk_id: Unique identifier for the chunk
    - chunk_index: Position within the parent document
    - parent_doc_id: Reference to parent document
    - is_chunk: Flag indicating this is a chunk
    - total_chunks: Total number of chunks in the parent document
    
    Args:
        content: Document content to chunk
        doc_id: Parent document ID
        chunk_size: Maximum chunk size in tokens (default: 512)
        chunk_overlap: Overlap between chunks in tokens (default: 50)
        separators: List of separators to use for splitting (default: ["\\n\\n", "\\n", ". ", " "])
        parent_metadata: Optional parent document metadata to copy to chunks
        
    Returns:
        List of Document objects, each representing a chunk with chunk metadata
    """
    if not content:
        return []
    
    # Use default separators if not provided
    if separators is None:
        separators = DEFAULT_SEPARATORS.copy()
    
    # Initialize splitter
    splitter = RecursiveDocumentSplitter(
        split_length=chunk_size,
        split_overlap=chunk_overlap,
        split_unit="token",  # Use tokens for accurate size control
        separators=separators
    )
    
    # Warm up splitter (required for RecursiveDocumentSplitter)
    splitter.warm_up()
    
    # Create temporary document for splitting
    temp_doc = Document(content=content)
    
    # Split document into chunks
    result = splitter.run([temp_doc])
    chunk_docs = result["documents"]
    
    # Enrich chunks with chunk metadata
    enriched_chunks = []
    total_chunks = len(chunk_docs)
    
    for index, chunk_doc in enumerate(chunk_docs):
        # Generate chunk ID
        chunk_id = generate_chunk_id(doc_id, index)
        
        # Generate content hash for the chunk
        chunk_content_hash = hashlib.sha256(
            normalize_content(chunk_doc.content).encode('utf-8')
        ).hexdigest()
        
        # Build chunk metadata
        chunk_metadata = {
            'doc_id': chunk_id,  # Chunk uses chunk_id as its doc_id for storage
            'chunk_id': chunk_id,
            'chunk_index': index,
            'parent_doc_id': doc_id,
            'is_chunk': True,
            'total_chunks': total_chunks,
            'hash_content': chunk_content_hash,
            'content_hash': chunk_content_hash,  # Alias for backward compatibility
        }
        
        # Copy parent metadata if provided (excluding conflicting fields)
        if parent_metadata:
            excluded_fields = {'doc_id', 'chunk_id', 'chunk_index', 'parent_doc_id', 
                             'is_chunk', 'total_chunks', 'hash_content', 'content_hash'}
            for key, value in parent_metadata.items():
                if key not in excluded_fields and key not in chunk_metadata:
                    chunk_metadata[key] = value
        
        # Create enriched chunk document
        enriched_chunk = Document(
            content=chunk_doc.content,
            meta=chunk_metadata
        )
        
        enriched_chunks.append(enriched_chunk)
    
    return enriched_chunks


def compare_chunks(
    old_chunks: List[Document],
    new_chunks: List[Document]
) -> Dict[str, List[Document]]:
    """
    Compare old and new chunks to identify changes.
    
    Categorizes chunks into:
    - unchanged: Chunks with same chunk_index and content_hash
    - changed: Chunks with same chunk_index but different content_hash
    - new: Chunks that don't exist in old_chunks
    - deleted: Old chunks that don't exist in new_chunks
    
    Args:
        old_chunks: List of existing chunk documents
        new_chunks: List of new chunk documents
        
    Returns:
        Dictionary with keys:
        - 'unchanged': List of unchanged chunks (from old_chunks)
        - 'changed': List of changed chunks (from new_chunks)
        - 'new': List of new chunks (from new_chunks)
        - 'deleted': List of deleted chunks (from old_chunks)
    """
    # Create maps for efficient lookup
    old_chunks_by_index = {chunk.meta.get('chunk_index'): chunk for chunk in old_chunks}
    old_chunks_by_id = {chunk.meta.get('chunk_id'): chunk for chunk in old_chunks}
    
    # Initialize result categories
    unchanged = []
    changed = []
    new = []
    deleted_indices = set(old_chunks_by_index.keys())
    
    # Process new chunks
    for new_chunk in new_chunks:
        chunk_index = new_chunk.meta.get('chunk_index')
        chunk_id = new_chunk.meta.get('chunk_id')
        new_hash = new_chunk.meta.get('hash_content') or new_chunk.meta.get('content_hash')
        
        # Check if chunk exists in old chunks by index
        if chunk_index in old_chunks_by_index:
            old_chunk = old_chunks_by_index[chunk_index]
            old_hash = old_chunk.meta.get('hash_content') or old_chunk.meta.get('content_hash')
            
            # Compare hashes
            if new_hash == old_hash:
                # Chunk unchanged - keep old chunk
                unchanged.append(old_chunk)
                deleted_indices.discard(chunk_index)
            else:
                # Chunk changed - use new chunk
                changed.append(new_chunk)
                deleted_indices.discard(chunk_index)
        else:
            # New chunk (no matching index)
            new.append(new_chunk)
    
    # Find deleted chunks (old chunks not found in new chunks)
    deleted = [old_chunks_by_index[index] for index in deleted_indices]
    
    return {
        'unchanged': unchanged,
        'changed': changed,
        'new': new,
        'deleted': deleted
    }


def identify_chunk_changes(
    old_chunks: List[Document],
    new_chunks: List[Document]
) -> Dict[str, any]:
    """
    Identify changes between old and new chunks, returning summary statistics.
    
    Args:
        old_chunks: List of existing chunk documents
        new_chunks: List of new chunk documents
        
    Returns:
        Dictionary with change statistics:
        - total_old: Number of old chunks
        - total_new: Number of new chunks
        - unchanged_count: Number of unchanged chunks
        - changed_count: Number of changed chunks
        - new_count: Number of new chunks
        - deleted_count: Number of deleted chunks
        - changes: Detailed comparison result from compare_chunks()
    """
    changes = compare_chunks(old_chunks, new_chunks)
    
    return {
        'total_old': len(old_chunks),
        'total_new': len(new_chunks),
        'unchanged_count': len(changes['unchanged']),
        'changed_count': len(changes['changed']),
        'new_count': len(changes['new']),
        'deleted_count': len(changes['deleted']),
        'changes': changes
    }


def get_chunks_by_parent_doc_id(
    document_store,
    parent_doc_id: str,
    status: Optional[str] = 'active'
) -> List[Document]:
    """
    Retrieve all chunks for a parent document.
    
    Args:
        document_store: QdrantDocumentStore instance
        parent_doc_id: Parent document ID
        status: Optional status filter (default: 'active')
        
    Returns:
        List of chunk documents, sorted by chunk_index
    """
    from metadata_service import query_by_doc_id
    
    # Query chunks by parent_doc_id
    filters = {
        "field": "meta.parent_doc_id",
        "operator": "==",
        "value": parent_doc_id
    }
    
    if status:
        filters = {
            "operator": "AND",
            "conditions": [
                {"field": "meta.parent_doc_id", "operator": "==", "value": parent_doc_id},
                {"field": "meta.status", "operator": "==", "value": status}
            ]
        }
    
    try:
        chunks = document_store.filter_documents(filters=filters)
        # Sort by chunk_index
        chunks.sort(key=lambda doc: doc.meta.get('chunk_index', 0))
        return chunks
    except Exception:
        return []


def reconstruct_document_from_chunks(chunks: List[Document]) -> str:
    """
    Reconstruct full document content from chunks.
    
    Args:
        chunks: List of chunk documents (should be sorted by chunk_index)
        
    Returns:
        Reconstructed document content
    """
    # Sort chunks by index to ensure correct order
    sorted_chunks = sorted(chunks, key=lambda doc: doc.meta.get('chunk_index', 0))
    
    # Join chunk contents
    contents = [chunk.content for chunk in sorted_chunks]
    
    return "".join(contents)

