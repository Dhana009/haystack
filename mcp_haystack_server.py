"""
MCP Server for Haystack RAG operations.
Exposes Haystack functions as MCP tools for indexing, searching, and managing documents.
"""
import asyncio
import hashlib
import os
import json
import sys
from typing import Any, Sequence
from pathlib import Path

from haystack.dataclasses.document import Document
from haystack.components.embedders import SentenceTransformersDocumentEmbedder, SentenceTransformersTextEmbedder
from haystack.utils import Secret
from haystack import Pipeline

# Import deduplication and metadata services
from deduplication_service import (
    generate_content_fingerprint,
    check_duplicate_level,
    decide_storage_action,
    ACTION_SKIP,
    ACTION_UPDATE,
    ACTION_WARN,
    ACTION_STORE
)
from metadata_service import (
    build_metadata_schema,
    query_by_doc_id,
    query_by_content_hash,
    validate_metadata
)
from verification_service import (
    verify_content_quality,
    bulk_verify_category,
    audit_storage_integrity
)
from bulk_operations_service import (
    delete_by_filter,
    delete_by_ids,
    update_metadata_by_filter,
    export_documents,
    import_documents
)
from query_service import (
    get_document_by_path,
    search_with_metadata_filters,
    get_metadata_stats
)
from update_service import (
    update_document_content,
    update_document_metadata,
    deprecate_version,
    get_version_history
)
from backup_restore_service import (
    create_backup,
    restore_backup,
    list_backups
)

# Qdrant integration
try:
    from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
    from haystack_integrations.components.retrievers.qdrant import QdrantEmbeddingRetriever
    from qdrant_client import QdrantClient
    from qdrant_client.models import Filter, FieldCondition, MatchValue
except ImportError:
    print("Error: qdrant-haystack package not installed.", file=sys.stderr)
    print("Install it with: pip install qdrant-haystack", file=sys.stderr)
    raise

# MCP SDK
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print("Error: mcp package not installed.", file=sys.stderr)
    print("Install it with: pip install mcp", file=sys.stderr)
    raise


# Global Haystack components (initialized on startup)
document_store: QdrantDocumentStore | None = None  # For documentation
code_document_store: QdrantDocumentStore | None = None  # For code
doc_embedder: SentenceTransformersDocumentEmbedder | None = None  # For documentation
code_embedder: SentenceTransformersDocumentEmbedder | None = None  # For code
text_embedder: SentenceTransformersTextEmbedder | None = None  # For search queries (docs)
code_text_embedder: SentenceTransformersTextEmbedder | None = None  # For search queries (code)
search_pipeline: Pipeline | None = None  # For documentation search
code_search_pipeline: Pipeline | None = None  # For code search


def initialize_haystack():
    """Initialize Haystack components with Qdrant connection.
    
    Supports separate embedding models and dimensions for code vs documentation:
    - Documentation: Uses fast text-focused models (default: all-MiniLM-L6-v2, 384 dims)
    - Code: Uses higher-quality models better for code understanding (default: all-mpnet-base-v2, 768 dims)
    
    The code model uses more dimensions (768 vs 384) for better semantic understanding of code structure,
    syntax, and meaning. This provides superior code search and retrieval performance.
    """
    global document_store, code_document_store, doc_embedder, code_embedder
    global text_embedder, code_text_embedder, search_pipeline, code_search_pipeline
    
    # Get Qdrant credentials from environment
    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    collection_name = os.getenv("QDRANT_COLLECTION", "haystack_mcp")
    code_collection_name = os.getenv("QDRANT_CODE_COLLECTION", "haystack_mcp_code")
    
    # Model configuration
    # Documentation: Fast, efficient model for text (384 dims)
    doc_model = os.getenv("DOC_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    # Code: Higher quality model better suited for code understanding (768 dims)
    code_model = os.getenv("CODE_EMBEDDING_MODEL", "sentence-transformers/all-mpnet-base-v2")
    
    # Embedding dimensions (defaults based on common models)
    doc_embedding_dim = int(os.getenv("DOC_EMBEDDING_DIM", "384"))  # all-MiniLM-L6-v2
    code_embedding_dim = int(os.getenv("CODE_EMBEDDING_DIM", "768"))  # all-mpnet-base-v2
    
    if not qdrant_url or not qdrant_api_key:
        raise ValueError(
            "QDRANT_URL and QDRANT_API_KEY environment variables must be set.\n"
            "Example:\n"
            "  export QDRANT_URL='https://xxx.qdrant.io:6333'\n"
            "  export QDRANT_API_KEY='your-api-key'"
        )
    
    # Log to stderr (not stdout) to avoid breaking MCP protocol
    # Use [info] prefix to indicate informational messages, not errors
    print("[info] Initializing Haystack with Qdrant...", file=sys.stderr)
    print(f"[info] URL: {qdrant_url}", file=sys.stderr)
    print(f"[info] Documentation collection: {collection_name}", file=sys.stderr)
    print(f"[info] Code collection: {code_collection_name}", file=sys.stderr)
    print(f"[info] Doc model: {doc_model} ({doc_embedding_dim} dims)", file=sys.stderr)
    print(f"[info] Code model: {code_model} ({code_embedding_dim} dims)", file=sys.stderr)
    
    # Initialize document store for documentation
    document_store = QdrantDocumentStore(
        url=qdrant_url,
        index=collection_name,
        embedding_dim=doc_embedding_dim,
        api_key=Secret.from_token(qdrant_api_key),
        recreate_index=False,
        return_embedding=True,
        wait_result_from_api=True,
    )
    
    # Initialize document store for code (separate collection)
    code_document_store = QdrantDocumentStore(
        url=qdrant_url,
        index=code_collection_name,
        embedding_dim=code_embedding_dim,
        api_key=Secret.from_token(qdrant_api_key),
        recreate_index=False,
        return_embedding=True,
        wait_result_from_api=True,
    )
    
    # Create payload indexes for efficient metadata filtering (per RULE 9)
    # Required for bulk operations that use QdrantClient directly (delete_by_filter,
    # bulk_update_metadata, etc.). These indexes are required when using filters
    # with QdrantClient.scroll(), .delete(), or .set_payload() operations.
    try:
        from index_management_service import ensure_payload_indexes, _get_qdrant_client
        client = _get_qdrant_client()
        
        # Create indexes for documentation collection
        doc_index_result = ensure_payload_indexes(collection_name, client)
        if doc_index_result.get("created_indexes"):
            print(f"[info] Created {len(doc_index_result['created_indexes'])} payload indexes for {collection_name}", file=sys.stderr)
        
        # Create indexes for code collection
        code_index_result = ensure_payload_indexes(code_collection_name, client)
        if code_index_result.get("created_indexes"):
            print(f"[info] Created {len(code_index_result['created_indexes'])} payload indexes for {code_collection_name}", file=sys.stderr)
            
    except Exception as e:
        # Log but don't fail initialization - indexes can be created later
        print(f"[warning] Failed to create payload indexes: {str(e)}", file=sys.stderr)
        print(f"[warning] Some filtering operations may fail. Use index_management_service to create indexes manually.", file=sys.stderr)
    
    # Initialize embedders for documentation
    doc_embedder = SentenceTransformersDocumentEmbedder(model=doc_model)
    doc_embedder.warm_up()
    
    text_embedder = SentenceTransformersTextEmbedder(model=doc_model)
    text_embedder.warm_up()
    
    # Initialize embedders for code
    code_embedder = SentenceTransformersDocumentEmbedder(model=code_model)
    code_embedder.warm_up()
    
    code_text_embedder = SentenceTransformersTextEmbedder(model=code_model)
    code_text_embedder.warm_up()
    
    # Create search pipeline for documentation
    retriever = QdrantEmbeddingRetriever(document_store=document_store, top_k=10)
    search_pipeline = Pipeline()
    search_pipeline.add_component("text_embedder", text_embedder)
    search_pipeline.add_component("retriever", retriever)
    search_pipeline.connect("text_embedder.embedding", "retriever.query_embedding")
    
    # Create search pipeline for code
    code_retriever = QdrantEmbeddingRetriever(document_store=code_document_store, top_k=10)
    code_search_pipeline = Pipeline()
    code_search_pipeline.add_component("text_embedder", code_text_embedder)
    code_search_pipeline.add_component("retriever", code_retriever)
    code_search_pipeline.connect("text_embedder.embedding", "retriever.query_embedding")
    
    print("[info] Haystack initialized successfully!", file=sys.stderr)


# Create MCP server with metadata
server = Server("haystack-rag-server")

# Set server info for better client compatibility
@server.list_resources()
async def list_resources() -> list:
    """List available resources (empty for this server)."""
    return []

@server.list_prompts()
async def list_prompts() -> list:
    """List available prompts (empty for this server)."""
    return []


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools."""
    return [
        Tool(
            name="add_document",
            description="Add a document to the Haystack RAG system. The document will be embedded and stored in Qdrant. Use for storing new documents or content for future search.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The text content of the document to index"
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Optional metadata for the document (e.g., file_path, source, etc.)",
                        "additionalProperties": True
                    }
                },
                "required": ["content"]
            }
        ),
        Tool(
            name="add_file",
            description="Add a file to the Haystack RAG system by reading its content. Use for storing new files for future search.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file to index"
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Optional additional metadata",
                        "additionalProperties": True
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="add_code",
            description="Add a code file to the Haystack RAG system with language detection and code-specific metadata. Automatically detects programming language from file extension. Use for storing code files for future search.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the code file to index"
                    },
                    "language": {
                        "type": "string",
                        "description": "Optional programming language (e.g., 'python', 'javascript', 'typescript'). Auto-detected from extension if not provided."
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Optional additional metadata",
                        "additionalProperties": True
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="add_code_directory",
            description="Add all code files from a directory recursively to the Haystack RAG system. Supports common code file extensions (.py, .js, .ts, .java, .cpp, .go, .rs, etc.). Use for storing multiple code files for future search.",
            inputSchema={
                "type": "object",
                "properties": {
                    "directory_path": {
                        "type": "string",
                        "description": "Path to the directory containing code files"
                    },
                    "extensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of file extensions to include (e.g., ['.py', '.js']). If not provided, uses common code extensions."
                    },
                    "exclude_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional patterns to exclude (e.g., ['__pycache__', 'node_modules', '.git'])"
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Optional additional metadata to add to all indexed files",
                        "additionalProperties": True
                    }
                },
                "required": ["directory_path"]
            }
        ),
        Tool(
            name="search_documents",
            description="Search for documents and code using semantic similarity. Use for finding relevant documents, code snippets, or content based on meaning. Can search documentation, code, or both. Supports metadata filtering.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return (default: 5)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 50
                    },
                    "content_type": {
                        "type": "string",
                        "description": "Type of content to search: 'all' (default), 'code', or 'docs'",
                        "enum": ["all", "code", "docs"],
                        "default": "all"
                    },
                    "metadata_filters": {
                        "type": "object",
                        "description": "Optional metadata filters (Haystack filter format). Example: {\"field\": \"meta.category\", \"operator\": \"==\", \"value\": \"user_rule\"}",
                        "additionalProperties": True
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_stats",
            description="Get statistics about indexed documents. Use for checking how many documents are stored, collection info, etc.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="delete_document",
            description="Delete a document from the vector store by ID. Use when user wants to remove a specific document.",
            inputSchema={
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "string",
                        "description": "The ID of the document to delete"
                    }
                },
                "required": ["document_id"]
            }
        ),
        Tool(
            name="clear_all",
            description="Delete all documents from both documentation and code collections. Use when user wants to clear all data from the Haystack RAG system.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="verify_document",
            description="Verify the quality and integrity of a single document. Checks for placeholders, validates hash, verifies metadata, and returns a quality score.",
            inputSchema={
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "string",
                        "description": "The ID of the document to verify"
                    }
                },
                "required": ["document_id"]
            }
        ),
        Tool(
            name="verify_category",
            description="Bulk verify all documents in a category. Returns statistics on quality scores, failed documents, and common issues.",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Category to verify (e.g., 'user_rule', 'project_rule', 'other')"
                    },
                    "max_documents": {
                        "type": "integer",
                        "description": "Maximum number of documents to verify (optional, defaults to all)",
                        "minimum": 1
                    }
                },
                "required": ["category"]
            }
        ),
        Tool(
            name="delete_by_filter",
            description="Delete documents matching metadata filters. Use for bulk deletion by category, status, file_path, etc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filters": {
                        "type": "object",
                        "description": "Haystack filter dictionary. Example: {\"field\": \"meta.category\", \"operator\": \"==\", \"value\": \"user_rule\"}",
                        "additionalProperties": True
                    }
                },
                "required": ["filters"]
            }
        ),
        Tool(
            name="bulk_update_metadata",
            description="Update metadata for multiple documents matching a filter. Efficient bulk metadata updates.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filters": {
                        "type": "object",
                        "description": "Haystack filter dictionary to match documents",
                        "additionalProperties": True
                    },
                    "metadata_updates": {
                        "type": "object",
                        "description": "Dictionary of metadata fields to update",
                        "additionalProperties": True
                    }
                },
                "required": ["filters", "metadata_updates"]
            }
        ),
        Tool(
            name="export_documents",
            description="Export documents with metadata to JSON format. Useful for backup and migration.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filters": {
                        "type": "object",
                        "description": "Optional Haystack filter dictionary to filter documents",
                        "additionalProperties": True
                    },
                    "include_embeddings": {
                        "type": "boolean",
                        "description": "Whether to include embeddings in export (default: false)",
                        "default": False
                    }
                }
            }
        ),
        Tool(
            name="import_documents",
            description="Bulk import documents with duplicate handling strategy (skip/update/error).",
            inputSchema={
                "type": "object",
                "properties": {
                    "documents_data": {
                        "type": "array",
                        "description": "Array of document dictionaries with content, meta, etc.",
                        "items": {"type": "object"}
                    },
                    "duplicate_strategy": {
                        "type": "string",
                        "description": "How to handle duplicates: 'skip', 'update', or 'error'",
                        "enum": ["skip", "update", "error"],
                        "default": "skip"
                    },
                    "batch_size": {
                        "type": "integer",
                        "description": "Number of documents to process per batch (default: 100)",
                        "default": 100,
                        "minimum": 1
                    }
                },
                "required": ["documents_data"]
            }
        ),
        Tool(
            name="get_document_by_path",
            description="Retrieve a document by file path using filter_documents().",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "File path to search for"
                    },
                    "status": {
                        "type": "string",
                        "description": "Optional status filter (default: 'active')",
                        "enum": ["active", "deprecated", "draft"],
                        "default": "active"
                    }
                },
                "required": ["file_path"]
            }
        ),
        Tool(
            name="get_metadata_stats",
            description="Get statistics aggregated by metadata fields. Returns counts by category, status, source, etc.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filters": {
                        "type": "object",
                        "description": "Optional Haystack filter dictionary",
                        "additionalProperties": True
                    },
                    "group_by_fields": {
                        "type": "array",
                        "description": "List of metadata fields to group by (e.g., ['category', 'status'])",
                        "items": {"type": "string"}
                    }
                }
            }
        ),
        Tool(
            name="update_document",
            description="Atomically update document content and optionally metadata. Regenerates embedding and updates hash.",
            inputSchema={
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "string",
                        "description": "Document ID (Qdrant point ID)"
                    },
                    "content": {
                        "type": "string",
                        "description": "New document content"
                    },
                    "metadata_updates": {
                        "type": "object",
                        "description": "Optional metadata fields to update",
                        "additionalProperties": True
                    }
                },
                "required": ["document_id", "content"]
            }
        ),
        Tool(
            name="update_metadata",
            description="Update only metadata fields without changing content. Efficient for metadata-only updates.",
            inputSchema={
                "type": "object",
                "properties": {
                    "document_id": {
                        "type": "string",
                        "description": "Document ID (Qdrant point ID)"
                    },
                    "metadata_updates": {
                        "type": "object",
                        "description": "Dictionary of metadata fields to update",
                        "additionalProperties": True
                    }
                },
                "required": ["document_id", "metadata_updates"]
            }
        ),
        Tool(
            name="get_version_history",
            description="Retrieve version history for a document by doc_id. Returns all versions sorted by version/created_at.",
            inputSchema={
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "Logical document ID (not Qdrant point ID)"
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional category filter"
                    },
                    "include_deprecated": {
                        "type": "boolean",
                        "description": "Whether to include deprecated versions (default: true)",
                        "default": True
                    }
                },
                "required": ["doc_id"]
            }
        ),
        Tool(
            name="create_backup",
            description="Create a local backup of a Qdrant collection. Backs up to timestamped directory with documents, metadata, and manifest files.",
            inputSchema={
                "type": "object",
                "properties": {
                    "backup_directory": {
                        "type": "string",
                        "description": "Directory to store backups (default: './backups')",
                        "default": "./backups"
                    },
                    "include_embeddings": {
                        "type": "boolean",
                        "description": "Whether to include embeddings in backup (default: false)",
                        "default": False
                    },
                    "filters": {
                        "type": "object",
                        "description": "Optional Haystack filter dictionary to filter documents for backup",
                        "additionalProperties": True
                    }
                }
            }
        ),
        Tool(
            name="restore_backup",
            description="Restore a collection from a local backup. Verifies backup integrity and optionally verifies restored documents.",
            inputSchema={
                "type": "object",
                "properties": {
                    "backup_path": {
                        "type": "string",
                        "description": "Path to backup directory"
                    },
                    "verify_after_restore": {
                        "type": "boolean",
                        "description": "Whether to verify documents after restore (default: true)",
                        "default": True
                    },
                    "duplicate_strategy": {
                        "type": "string",
                        "description": "How to handle duplicates: 'skip', 'update', or 'overwrite'",
                        "enum": ["skip", "update", "overwrite"],
                        "default": "skip"
                    }
                },
                "required": ["backup_path"]
            }
        ),
        Tool(
            name="list_backups",
            description="List all available backups in the backup directory with their metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "backup_directory": {
                        "type": "string",
                        "description": "Directory containing backups (default: './backups')",
                        "default": "./backups"
                    }
                }
            }
        ),
        Tool(
            name="audit_storage_integrity",
            description="Audit storage integrity by comparing stored documents with source files. Detects missing files, content mismatches, and quality issues.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_directory": {
                        "type": "string",
                        "description": "Optional source directory to compare against stored documents"
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "Whether to scan source directory recursively (default: true)",
                        "default": True
                    },
                    "file_extensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of file extensions to include (e.g., ['.md', '.txt'])"
                    }
                }
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Handle tool calls."""
    global document_store, code_document_store, doc_embedder, code_embedder, search_pipeline, code_search_pipeline
    
    # Check initialization based on tool type
    if name in ["add_document", "add_file", "search_documents", "get_stats", "delete_document", "clear_all", 
                "verify_document", "verify_category", "delete_by_filter", "bulk_update_metadata", 
                "export_documents", "import_documents", "get_document_by_path", "get_metadata_stats",
                "update_document", "update_metadata", "get_version_history", "create_backup", 
                "restore_backup", "list_backups", "audit_storage_integrity"]:
        if document_store is None or doc_embedder is None or search_pipeline is None:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": "Haystack not initialized. Please check QDRANT_URL and QDRANT_API_KEY environment variables."
                }, indent=2)
            )]
    elif name in ["add_code", "add_code_directory"]:
        if code_document_store is None or code_embedder is None:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": "Code indexing not initialized. Please check QDRANT_URL and QDRANT_API_KEY environment variables."
                }, indent=2)
            )]
    
    try:
        if name == "add_document":
            content = arguments.get("content", "")
            metadata = arguments.get("metadata", {})
            
            if not content:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "content is required"}, indent=2)
                )]
            
            try:
                # Step 1: Extract or generate required metadata fields
                doc_id = metadata.get('doc_id') or metadata.get('id') or f"doc_{hashlib.sha256(content.encode()).hexdigest()[:16]}"
                category = metadata.get('category', 'other')
                version = metadata.get('version')
                file_path = metadata.get('file_path') or metadata.get('path')
                source = metadata.get('source', 'manual')
                tags = metadata.get('tags', [])
                
                # Step 2: Generate initial content hash for duplicate checking
                # We'll generate the full fingerprint after building metadata
                initial_fingerprint = generate_content_fingerprint(content, metadata)
                
                # Step 3: Build RULE 3 compliant metadata
                try:
                    full_metadata = build_metadata_schema(
                        content=content,
                        doc_id=doc_id,
                        category=category,
                        hash_content=initial_fingerprint['content_hash'],
                        version=version,
                        file_path=file_path,
                        source=source,
                        tags=tags if isinstance(tags, list) else [],
                        additional_metadata=metadata
                    )
                except ValueError as e:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "error": f"Metadata validation failed: {str(e)}"
                        }, indent=2)
                    )]
                
                # Step 4: Generate fingerprint from full metadata (for accurate comparison)
                # This ensures metadata_hash matches what will be stored
                fingerprint = generate_content_fingerprint(content, full_metadata)
                # Update fingerprint with the metadata_hash from full_metadata (which excludes timestamps/status)
                fingerprint['metadata_hash'] = full_metadata.get('metadata_hash', fingerprint['metadata_hash'])
                fingerprint['composite_key'] = f"{fingerprint['content_hash']}:{fingerprint['metadata_hash']}"
                
                # Step 5: Check for duplicates using metadata-based query
                # First check by doc_id and category (per RULE 4)
                existing_docs = query_by_doc_id(document_store, doc_id, category, status='active')
                
                # Also check by content_hash for exact duplicates
                if not existing_docs:
                    existing_docs = query_by_content_hash(document_store, fingerprint['content_hash'], status='active')
                
                # Step 6: Determine duplicate level and action
                level, matching_doc, reason = check_duplicate_level(fingerprint, existing_docs)
                action, action_data = decide_storage_action(level, fingerprint, matching_doc)
                
                # Step 7: Handle action
                if action == ACTION_SKIP:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "status": "skipped",
                            "message": "Document is an exact duplicate - skipping storage",
                            "reason": reason,
                            "existing_document_id": matching_doc.id if matching_doc else None,
                            "action_data": action_data
                        }, indent=2)
                    )]
                
                elif action == ACTION_UPDATE:
                    # For Phase 1, we'll still store as new but mark old as deprecated
                    # Full update functionality will be in Phase 2
                    # For now, we'll store the new version and note that old should be deprecated
                    full_metadata['status'] = 'active'
                    # Note: Actual deprecation of old version will be handled in Phase 2
                    action_note = "New version stored. Old version should be deprecated (Phase 2 will handle this automatically)."
                
                elif action == ACTION_WARN:
                    full_metadata['status'] = 'active'
                    full_metadata['warning'] = action_data.get('warning', 'High semantic similarity detected')
                    action_note = "Document stored with warning flag due to semantic similarity."
                
                else:  # ACTION_STORE
                    full_metadata['status'] = 'active'
                    action_note = "New document stored successfully."
                
                # Step 7: Create document with full metadata
                doc = Document(content=content, meta=full_metadata)
                
                # Step 8: Embed and store
                result = doc_embedder.run(documents=[doc])
                documents_with_embeddings = result["documents"]
                document_store.write_documents(documents_with_embeddings)
                
                doc_id_stored = documents_with_embeddings[0].id
                
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "success",
                        "message": action_note,
                        "document_id": doc_id_stored,
                        "doc_id": doc_id,
                        "version": full_metadata.get('version'),
                        "category": category,
                        "action": action,
                        "duplicate_level": level,
                        "reason": reason,
                        "action_data": action_data
                    }, indent=2)
                )]
            
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to add document: {str(e)}",
                        "type": type(e).__name__
                    }, indent=2)
                )]
        
        elif name == "add_file":
            file_path = arguments.get("file_path", "")
            metadata = arguments.get("metadata", {})
            
            if not file_path:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "file_path is required"}, indent=2)
                )]
            
            path = Path(file_path)
            if not path.exists():
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": f"File not found: {file_path}"}, indent=2)
                )]
            
            # Read file content
            try:
                content = path.read_text(encoding="utf-8")
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": f"Failed to read file: {str(e)}"}, indent=2)
                )]
            
            try:
                # Step 1: Extract or generate required metadata fields
                # Use file path as doc_id if not provided
                doc_id = metadata.get('doc_id') or metadata.get('id') or str(path)
                category = metadata.get('category', 'other')
                version = metadata.get('version')
                source = metadata.get('source', 'manual')
                tags = metadata.get('tags', [])
                
                # Step 2: Generate initial content hash for duplicate checking
                file_metadata_for_fingerprint = {**metadata, "file_path": str(path), "file_name": path.name}
                initial_fingerprint = generate_content_fingerprint(content, file_metadata_for_fingerprint)
                
                # Step 3: Build RULE 3 compliant metadata with file-specific fields
                try:
                    full_metadata = build_metadata_schema(
                        content=content,
                        doc_id=doc_id,
                        category=category,
                        hash_content=initial_fingerprint['content_hash'],
                        version=version,
                        file_path=str(path),
                        source=source,
                        tags=tags if isinstance(tags, list) else [],
                        additional_metadata={**metadata, "file_name": path.name}
                    )
                except ValueError as e:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "error": f"Metadata validation failed: {str(e)}"
                        }, indent=2)
                    )]
                
                # Step 4: Generate fingerprint from full metadata (for accurate comparison)
                fingerprint = generate_content_fingerprint(content, full_metadata)
                fingerprint['metadata_hash'] = full_metadata.get('metadata_hash', fingerprint['metadata_hash'])
                fingerprint['composite_key'] = f"{fingerprint['content_hash']}:{fingerprint['metadata_hash']}"
                
                # Step 5: Check for duplicates using file_path (primary) and doc_id
                # First check by file_path (file-based deduplication)
                existing_docs = query_by_file_path(document_store, str(path), status='active')
                
                # Also check by doc_id and category
                if not existing_docs:
                    existing_docs = query_by_doc_id(document_store, doc_id, category, status='active')
                
                # Also check by content_hash for exact duplicates
                if not existing_docs:
                    existing_docs = query_by_content_hash(document_store, fingerprint['content_hash'], status='active')
                
                # Step 6: Determine duplicate level and action
                level, matching_doc, reason = check_duplicate_level(fingerprint, existing_docs)
                action, action_data = decide_storage_action(level, fingerprint, matching_doc)
                
                # Step 6: Handle action
                if action == ACTION_SKIP:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "status": "skipped",
                            "message": "File is an exact duplicate - skipping storage",
                            "reason": reason,
                            "existing_document_id": matching_doc.id if matching_doc else None,
                            "file_path": str(path),
                            "action_data": action_data
                        }, indent=2)
                    )]
                
                elif action == ACTION_UPDATE:
                    full_metadata['status'] = 'active'
                    action_note = "New version stored. Old version should be deprecated (Phase 2 will handle this automatically)."
                
                elif action == ACTION_WARN:
                    full_metadata['status'] = 'active'
                    full_metadata['warning'] = action_data.get('warning', 'High semantic similarity detected')
                    action_note = "File stored with warning flag due to semantic similarity."
                
                else:  # ACTION_STORE
                    full_metadata['status'] = 'active'
                    action_note = "New file indexed successfully."
                
                # Step 7: Create document with full metadata
                doc = Document(content=content, meta=full_metadata)
                
                # Step 8: Embed and store
                result = doc_embedder.run(documents=[doc])
                documents_with_embeddings = result["documents"]
                document_store.write_documents(documents_with_embeddings)
                
                doc_id_stored = documents_with_embeddings[0].id
                
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "success",
                        "message": action_note,
                        "document_id": doc_id_stored,
                        "doc_id": doc_id,
                        "file_path": str(path),
                        "file_name": path.name,
                        "version": full_metadata.get('version'),
                        "category": category,
                        "action": action,
                        "duplicate_level": level,
                        "reason": reason,
                        "action_data": action_data
                    }, indent=2)
                )]
            
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to add file: {str(e)}",
                        "type": type(e).__name__,
                        "file_path": str(path) if 'path' in locals() else file_path
                    }, indent=2)
                )]
        
        elif name == "add_code":
            file_path = arguments.get("file_path", "")
            language = arguments.get("language", "")
            metadata = arguments.get("metadata", {})
            
            if not file_path:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "file_path is required"}, indent=2)
                )]
            
            if code_document_store is None or code_embedder is None:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "Code indexing not initialized. Check CODE_EMBEDDING_MODEL and CODE_EMBEDDING_DIM."}, indent=2)
                )]
            
            path = Path(file_path)
            if not path.exists():
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": f"File not found: {file_path}"}, indent=2)
                )]
            
            # Detect language from extension if not provided
            if not language:
                ext_to_lang = {
                    ".py": "python",
                    ".js": "javascript",
                    ".ts": "typescript",
                    ".jsx": "javascript",
                    ".tsx": "typescript",
                    ".java": "java",
                    ".cpp": "cpp",
                    ".c": "c",
                    ".h": "c",
                    ".hpp": "cpp",
                    ".go": "go",
                    ".rs": "rust",
                    ".rb": "ruby",
                    ".php": "php",
                    ".swift": "swift",
                    ".kt": "kotlin",
                    ".scala": "scala",
                    ".r": "r",
                    ".m": "matlab",
                    ".sql": "sql",
                    ".sh": "bash",
                    ".bash": "bash",
                    ".zsh": "zsh",
                    ".ps1": "powershell",
                    ".yaml": "yaml",
                    ".yml": "yaml",
                    ".json": "json",
                    ".xml": "xml",
                    ".html": "html",
                    ".css": "css",
                    ".scss": "scss",
                    ".less": "less",
                    ".vue": "vue",
                    ".svelte": "svelte",
                }
                language = ext_to_lang.get(path.suffix.lower(), "unknown")
            
            # Read file content
            try:
                content = path.read_text(encoding="utf-8")
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": f"Failed to read file: {str(e)}"}, indent=2)
                )]
            
            try:
                # Step 1: Extract or generate required metadata fields
                # Use file path as doc_id if not provided
                doc_id = metadata.get('doc_id') or metadata.get('id') or str(path)
                category = metadata.get('category', 'other')
                version = metadata.get('version')
                source = metadata.get('source', 'manual')
                tags = metadata.get('tags', [])
                
                # Step 2: Generate initial content hash for duplicate checking
                code_metadata_for_fingerprint = {
                    **metadata,
                    "file_path": str(path),
                    "file_name": path.name,
                    "file_extension": path.suffix,
                    "language": language,
                    "content_type": "code"
                }
                initial_fingerprint = generate_content_fingerprint(content, code_metadata_for_fingerprint)
                
                # Step 3: Build RULE 3 compliant metadata with code-specific fields
                try:
                    full_metadata = build_metadata_schema(
                        content=content,
                        doc_id=doc_id,
                        category=category,
                        hash_content=initial_fingerprint['content_hash'],
                        version=version,
                        file_path=str(path),
                        source=source,
                        tags=tags if isinstance(tags, list) else [],
                        additional_metadata={
                            **metadata,
                            "file_name": path.name,
                            "file_extension": path.suffix,
                            "language": language,
                            "content_type": "code",
                            "file_size": path.stat().st_size
                        }
                    )
                except ValueError as e:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "error": f"Metadata validation failed: {str(e)}"
                        }, indent=2)
                    )]
                
                # Step 4: Generate fingerprint from full metadata (for accurate comparison)
                fingerprint = generate_content_fingerprint(content, full_metadata)
                fingerprint['metadata_hash'] = full_metadata.get('metadata_hash', fingerprint['metadata_hash'])
                fingerprint['composite_key'] = f"{fingerprint['content_hash']}:{fingerprint['metadata_hash']}"
                
                # Step 5: Check for duplicates using file_path (primary) and doc_id
                # First check by file_path (file-based deduplication)
                existing_docs = query_by_file_path(code_document_store, str(path), status='active')
                
                # Also check by doc_id and category
                if not existing_docs:
                    existing_docs = query_by_doc_id(code_document_store, doc_id, category, status='active')
                
                # Also check by content_hash for exact duplicates
                if not existing_docs:
                    existing_docs = query_by_content_hash(code_document_store, fingerprint['content_hash'], status='active')
                
                # Step 6: Determine duplicate level and action
                level, matching_doc, reason = check_duplicate_level(fingerprint, existing_docs)
                action, action_data = decide_storage_action(level, fingerprint, matching_doc)
                
                # Step 6: Handle action
                if action == ACTION_SKIP:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "status": "skipped",
                            "message": "Code file is an exact duplicate - skipping storage",
                            "reason": reason,
                            "existing_document_id": matching_doc.id if matching_doc else None,
                            "file_path": str(path),
                            "language": language,
                            "collection": "code",
                            "action_data": action_data
                        }, indent=2)
                    )]
                
                elif action == ACTION_UPDATE:
                    full_metadata['status'] = 'active'
                    action_note = "New version stored. Old version should be deprecated (Phase 2 will handle this automatically)."
                
                elif action == ACTION_WARN:
                    full_metadata['status'] = 'active'
                    full_metadata['warning'] = action_data.get('warning', 'High semantic similarity detected')
                    action_note = "Code file stored with warning flag due to semantic similarity."
                
                else:  # ACTION_STORE
                    full_metadata['status'] = 'active'
                    action_note = "New code file indexed successfully."
                
                # Step 7: Create document with full metadata
                doc = Document(content=content, meta=full_metadata)
                
                # Step 8: Embed and store using CODE embedder and CODE document store
                result = code_embedder.run(documents=[doc])
                documents_with_embeddings = result["documents"]
                code_document_store.write_documents(documents_with_embeddings)
                
                doc_id_stored = documents_with_embeddings[0].id
                
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "success",
                        "message": action_note,
                        "document_id": doc_id_stored,
                        "doc_id": doc_id,
                        "file_path": str(path),
                        "file_name": path.name,
                        "language": language,
                        "collection": "code",
                        "version": full_metadata.get('version'),
                        "category": category,
                        "action": action,
                        "duplicate_level": level,
                        "reason": reason,
                        "action_data": action_data
                    }, indent=2)
                )]
            
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to add code file: {str(e)}",
                        "type": type(e).__name__,
                        "file_path": str(path) if 'path' in locals() else file_path
                    }, indent=2)
                )]
        
        elif name == "add_code_directory":
            directory_path = arguments.get("directory_path", "")
            extensions = arguments.get("extensions", [])
            exclude_patterns = arguments.get("exclude_patterns", ["__pycache__", "node_modules", ".git", ".venv", "venv", "env", ".env", "dist", "build", ".pytest_cache", ".mypy_cache"])
            metadata = arguments.get("metadata", {})
            
            if not directory_path:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "directory_path is required"}, indent=2)
                )]
            
            dir_path = Path(directory_path)
            if not dir_path.exists() or not dir_path.is_dir():
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": f"Directory not found: {directory_path}"}, indent=2)
                )]
            
            # Default code extensions if not provided
            if not extensions:
                extensions = [".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".cpp", ".c", ".h", ".hpp", 
                             ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala", ".r", ".m", ".sql",
                             ".sh", ".bash", ".yaml", ".yml", ".json", ".xml", ".html", ".css", ".scss",
                             ".less", ".vue", ".svelte", ".ps1"]
            
            # Find all code files
            code_files = []
            for ext in extensions:
                for file_path in dir_path.rglob(f"*{ext}"):
                    # Check if file should be excluded
                    should_exclude = False
                    for pattern in exclude_patterns:
                        if pattern in str(file_path):
                            should_exclude = True
                            break
                    
                    if not should_exclude and file_path.is_file():
                        code_files.append(file_path)
            
            if not code_files:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "success",
                        "message": "No code files found to index",
                        "files_found": 0
                    }, indent=2)
                )]
            
            # Index all code files
            documents = []
            indexed_files = []
            failed_files = []
            
            for file_path in code_files:
                try:
                    content = file_path.read_text(encoding="utf-8")
                    
                    # Detect language
                    ext_to_lang = {
                        ".py": "python", ".js": "javascript", ".ts": "typescript",
                        ".jsx": "javascript", ".tsx": "typescript", ".java": "java",
                        ".cpp": "cpp", ".c": "c", ".h": "c", ".hpp": "cpp",
                        ".go": "go", ".rs": "rust", ".rb": "ruby", ".php": "php",
                        ".swift": "swift", ".kt": "kotlin", ".scala": "scala",
                        ".r": "r", ".m": "matlab", ".sql": "sql",
                        ".sh": "bash", ".bash": "bash", ".zsh": "zsh", ".ps1": "powershell",
                        ".yaml": "yaml", ".yml": "yaml", ".json": "json",
                        ".xml": "xml", ".html": "html", ".css": "css",
                        ".scss": "scss", ".less": "less", ".vue": "vue", ".svelte": "svelte",
                    }
                    language = ext_to_lang.get(file_path.suffix.lower(), "unknown")
                    
                    code_metadata = {
                        **metadata,
                        "file_path": str(file_path),
                        "file_name": file_path.name,
                        "file_extension": file_path.suffix,
                        "language": language,
                        "content_type": "code",
                        "file_size": file_path.stat().st_size
                    }
                    
                    doc = Document(content=content, meta=code_metadata)
                    documents.append(doc)
                    indexed_files.append(str(file_path))
                    
                except Exception as e:
                    failed_files.append({"file": str(file_path), "error": str(e)})
            
            if documents:
                # Embed and store all documents using CODE embedder and CODE document store
                if code_document_store is None or code_embedder is None:
                    return [TextContent(
                        type="text",
                        text=json.dumps({"error": "Code indexing not initialized. Check CODE_EMBEDDING_MODEL and CODE_EMBEDDING_DIM."}, indent=2)
                    )]
                result = code_embedder.run(documents=documents)
                documents_with_embeddings = result["documents"]
                code_document_store.write_documents(documents_with_embeddings)
            
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "message": f"Indexed {len(indexed_files)} code files",
                    "files_indexed": len(indexed_files),
                    "files_failed": len(failed_files),
                    "indexed_files": indexed_files[:10],  # Show first 10
                    "failed_files": failed_files[:10] if failed_files else []
                }, indent=2)
            )]
        
        elif name == "search_documents":
            query = arguments.get("query", "")
            top_k = arguments.get("top_k", 5)
            content_type = arguments.get("content_type", "all")  # "all", "code", "docs"
            metadata_filters = arguments.get("metadata_filters")
            
            if not query:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "query is required"}, indent=2)
                )]
            
            all_results = []
            
            # If metadata_filters provided, use search_with_metadata_filters
            if metadata_filters:
                # Search documentation if requested
                if content_type in ["all", "docs"]:
                    if document_store and text_embedder:
                        retriever = QdrantEmbeddingRetriever(document_store=document_store, top_k=top_k)
                        retrieved_docs = search_with_metadata_filters(
                            document_store=document_store,
                            query=query,
                            text_embedder=text_embedder,
                            retriever=retriever,
                            metadata_filters=metadata_filters,
                            top_k=top_k
                        )
                        
                        for doc in retrieved_docs:
                            score = getattr(doc, 'score', getattr(doc, 'relevance_score', None))
                            all_results.append({
                                "rank": len(all_results) + 1,
                                "score": float(score) if score is not None else None,
                                "content": doc.content,
                                "metadata": doc.meta,
                                "id": doc.id,
                                "source": "documentation"
                            })
                
                # Search code if requested
                if content_type in ["all", "code"]:
                    if code_document_store and code_text_embedder:
                        retriever = QdrantEmbeddingRetriever(document_store=code_document_store, top_k=top_k)
                        retrieved_docs = search_with_metadata_filters(
                            document_store=code_document_store,
                            query=query,
                            text_embedder=code_text_embedder,
                            retriever=retriever,
                            metadata_filters=metadata_filters,
                            top_k=top_k
                        )
                        
                        for doc in retrieved_docs:
                            score = getattr(doc, 'score', getattr(doc, 'relevance_score', None))
                            all_results.append({
                                "rank": len(all_results) + 1,
                                "score": float(score) if score is not None else None,
                                "content": doc.content,
                                "metadata": doc.meta,
                                "id": doc.id,
                                "source": "code"
                            })
            else:
                # Original pipeline-based search (no filters)
                # Search documentation if requested
                if content_type in ["all", "docs"]:
                    if search_pipeline:
                        retriever = search_pipeline.get_component("retriever")
                        if hasattr(retriever, "top_k"):
                            retriever.top_k = top_k
                        
                        result = search_pipeline.run({"text_embedder": {"text": query}})
                        retrieved_docs = result["retriever"]["documents"]
                        
                        for i, doc in enumerate(retrieved_docs, 1):
                            score = getattr(doc, 'score', getattr(doc, 'relevance_score', None))
                            all_results.append({
                                "rank": len(all_results) + 1,
                                "score": float(score) if score is not None else None,
                                "content": doc.content,
                                "metadata": doc.meta,
                                "id": doc.id,
                                "source": "documentation"
                            })
                
                # Search code if requested
                if content_type in ["all", "code"]:
                    if code_search_pipeline:
                        retriever = code_search_pipeline.get_component("retriever")
                        if hasattr(retriever, "top_k"):
                            retriever.top_k = top_k
                        
                        result = code_search_pipeline.run({"text_embedder": {"text": query}})
                        retrieved_docs = result["retriever"]["documents"]
                        
                        for i, doc in enumerate(retrieved_docs, 1):
                            score = getattr(doc, 'score', getattr(doc, 'relevance_score', None))
                            all_results.append({
                                "rank": len(all_results) + 1,
                                "score": float(score) if score is not None else None,
                                "content": doc.content,
                                "metadata": doc.meta,
                                "id": doc.id,
                                "source": "code"
                            })
            
            # Sort by score (descending) and limit to top_k
            all_results.sort(key=lambda x: x["score"] if x["score"] is not None else 0, reverse=True)
            all_results = all_results[:top_k]
            
            # Re-rank
            for i, result in enumerate(all_results, 1):
                result["rank"] = i
            
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "query": query,
                    "content_type": content_type,
                    "metadata_filters": metadata_filters,
                    "results_count": len(all_results),
                    "results": all_results
                }, indent=2)
            )]
        
        elif name == "get_stats":
            doc_count = document_store.count_documents() if document_store else 0
            code_count = code_document_store.count_documents() if code_document_store else 0
            
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "total_documents": doc_count + code_count,
                    "documentation_documents": doc_count,
                    "code_documents": code_count,
                    "documentation_collection": document_store.index if document_store else None,
                    "code_collection": code_document_store.index if code_document_store else None
                }, indent=2)
            )]
        
        elif name == "delete_document":
            document_id = arguments.get("document_id", "")
            
            if not document_id:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "document_id is required"}, indent=2)
                )]
            
            # Try to delete from both stores (document might be in either)
            deleted_from_docs = False
            deleted_from_code = False
            
            try:
                # Get all documents from docs store to check if ID exists
                docs = document_store.filter_documents(filters={"id": document_id})
                if docs:
                    document_store.delete_documents([document_id])
                    deleted_from_docs = True
            except Exception:
                pass
            
            try:
                # Get all documents from code store to check if ID exists
                if code_document_store:
                    code_docs = code_document_store.filter_documents(filters={"id": document_id})
                    if code_docs:
                        code_document_store.delete_documents([document_id])
                        deleted_from_code = True
            except Exception:
                pass
            
            if not deleted_from_docs and not deleted_from_code:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "error",
                        "message": f"Document {document_id} not found in any collection"
                    }, indent=2)
                )]
            
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "message": f"Document {document_id} deleted successfully",
                    "deleted_from": "documentation" if deleted_from_docs else "code"
                }, indent=2)
            )]
        
        elif name == "clear_all":
            # Get counts before deletion
            doc_count_before = document_store.count_documents() if document_store else 0
            code_count_before = code_document_store.count_documents() if code_document_store else 0
            
            # Use Qdrant client directly to delete all points from both collections
            qdrant_url = os.getenv("QDRANT_URL")
            qdrant_api_key = os.getenv("QDRANT_API_KEY")
            collection_name = os.getenv("QDRANT_COLLECTION", "haystack_mcp")
            code_collection_name = os.getenv("QDRANT_CODE_COLLECTION", "haystack_mcp_code")
            
            deleted_docs = 0
            deleted_code = 0
            
            try:
                # Create Qdrant client
                client = QdrantClient(
                    url=qdrant_url,
                    api_key=qdrant_api_key
                )
                
                # Delete all points from docs collection using scroll and delete
                if document_store:
                    collection = collection_name
                    # Scroll through all points and collect IDs
                    offset = None
                    all_point_ids = []
                    while True:
                        result = client.scroll(
                            collection_name=collection,
                            limit=100,
                            offset=offset,
                            with_payload=False,
                            with_vectors=False
                        )
                        points, next_offset = result
                        if not points:
                            break
                        all_point_ids.extend([point.id for point in points])
                        if next_offset is None:
                            break
                        offset = next_offset
                    
                    # Delete all points
                    if all_point_ids:
                        client.delete(
                            collection_name=collection,
                            points_selector=all_point_ids
                        )
                        deleted_docs = len(all_point_ids)
                
                # Delete all points from code collection
                if code_document_store:
                    collection = code_collection_name
                    # Scroll through all points and collect IDs
                    offset = None
                    all_point_ids = []
                    while True:
                        result = client.scroll(
                            collection_name=collection,
                            limit=100,
                            offset=offset,
                            with_payload=False,
                            with_vectors=False
                        )
                        points, next_offset = result
                        if not points:
                            break
                        all_point_ids.extend([point.id for point in points])
                        if next_offset is None:
                            break
                        offset = next_offset
                    
                    # Delete all points
                    if all_point_ids:
                        client.delete(
                            collection_name=collection,
                            points_selector=all_point_ids
                        )
                        deleted_code = len(all_point_ids)
                
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to clear collections: {str(e)}",
                        "type": type(e).__name__,
                        "deleted_so_far": {
                            "documentation_documents": deleted_docs,
                            "code_documents": deleted_code
                        }
                    }, indent=2)
                )]
            
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "message": "All documents cleared successfully",
                    "deleted": {
                        "documentation_documents": deleted_docs,
                        "code_documents": deleted_code,
                        "total": deleted_docs + deleted_code
                    },
                    "before": {
                        "documentation_documents": doc_count_before,
                        "code_documents": code_count_before,
                        "total": doc_count_before + code_count_before
                    }
                }, indent=2)
            )]
        
        elif name == "verify_document":
            document_id = arguments.get("document_id", "")
            
            if not document_id:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "document_id is required"}, indent=2)
                )]
            
            try:
                # Try to get document from docs store first
                # Use a workaround: get all documents and filter by ID
                # This is not efficient but works reliably
                all_docs = document_store.filter_documents(filters=None)
                matching_doc = None
                for doc in all_docs:
                    if doc.id == document_id:
                        matching_doc = doc
                        break
                
                if matching_doc:
                    result = verify_content_quality(matching_doc)
                    return [TextContent(
                        type="text",
                        text=json.dumps(result, indent=2)
                    )]
                
                # Try code collection
                if code_document_store:
                    all_code_docs = code_document_store.filter_documents(filters=None)
                    for doc in all_code_docs:
                        if doc.id == document_id:
                            matching_doc = doc
                            break
                    
                    if matching_doc:
                        result = verify_content_quality(matching_doc)
                        return [TextContent(
                            type="text",
                            text=json.dumps(result, indent=2)
                        )]
                
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Document not found: {document_id}"
                    }, indent=2)
                )]
            
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to verify document: {str(e)}",
                        "type": type(e).__name__
                    }, indent=2)
                )]
        
        elif name == "verify_category":
            category = arguments.get("category", "")
            max_documents = arguments.get("max_documents")
            
            if not category:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "category is required"}, indent=2)
                )]
            
            try:
                # Bulk verify category (pass both document stores)
                result = bulk_verify_category(document_store, code_document_store, category=category, max_documents=max_documents)
                
                return [TextContent(
                    type="text",
                    text=json.dumps(result, indent=2)
                )]
            
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to verify category: {str(e)}",
                        "type": type(e).__name__
                    }, indent=2)
                )]
        
        elif name == "delete_by_filter":
            filters = arguments.get("filters", {})
            
            if not filters:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "filters are required"}, indent=2)
                )]
            
            try:
                result = delete_by_filter(document_store, filters)
                return [TextContent(
                    type="text",
                    text=json.dumps(result, indent=2)
                )]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to delete by filter: {str(e)}",
                        "type": type(e).__name__
                    }, indent=2)
                )]
        
        elif name == "bulk_update_metadata":
            filters = arguments.get("filters", {})
            metadata_updates = arguments.get("metadata_updates", {})
            
            if not filters or not metadata_updates:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "filters and metadata_updates are required"}, indent=2)
                )]
            
            try:
                result = update_metadata_by_filter(document_store, filters, metadata_updates)
                return [TextContent(
                    type="text",
                    text=json.dumps(result, indent=2)
                )]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to update metadata: {str(e)}",
                        "type": type(e).__name__
                    }, indent=2)
                )]
        
        elif name == "export_documents":
            filters = arguments.get("filters")
            include_embeddings = arguments.get("include_embeddings", False)
            
            try:
                exported = export_documents(document_store, filters, include_embeddings)
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "success",
                        "count": len(exported),
                        "documents": exported
                    }, indent=2)
                )]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to export documents: {str(e)}",
                        "type": type(e).__name__
                    }, indent=2)
                )]
        
        elif name == "import_documents":
            documents_data = arguments.get("documents_data", [])
            duplicate_strategy = arguments.get("duplicate_strategy", "skip")
            batch_size = arguments.get("batch_size", 100)
            
            if not documents_data:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "documents_data is required"}, indent=2)
                )]
            
            try:
                result = import_documents(
                    document_store,
                    documents_data,
                    duplicate_strategy,
                    batch_size,
                    doc_embedder
                )
                return [TextContent(
                    type="text",
                    text=json.dumps(result, indent=2)
                )]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to import documents: {str(e)}",
                        "type": type(e).__name__
                    }, indent=2)
                )]
        
        elif name == "get_document_by_path":
            file_path = arguments.get("file_path", "")
            status = arguments.get("status", "active")
            
            if not file_path:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "file_path is required"}, indent=2)
                )]
            
            try:
                doc = get_document_by_path(document_store, file_path, status)
                if doc:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "status": "success",
                            "document": {
                                "id": doc.id,
                                "content": doc.content,
                                "meta": doc.meta
                            }
                        }, indent=2)
                    )]
                else:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "status": "not_found",
                            "message": f"Document not found: {file_path}"
                        }, indent=2)
                    )]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to get document: {str(e)}",
                        "type": type(e).__name__
                    }, indent=2)
                )]
        
        elif name == "get_metadata_stats":
            filters = arguments.get("filters")
            group_by_fields = arguments.get("group_by_fields")
            
            try:
                stats = get_metadata_stats(document_store, filters, group_by_fields)
                return [TextContent(
                    type="text",
                    text=json.dumps(stats, indent=2)
                )]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to get metadata stats: {str(e)}",
                        "type": type(e).__name__
                    }, indent=2)
                )]
        
        elif name == "update_document":
            document_id = arguments.get("document_id", "")
            content = arguments.get("content", "")
            metadata_updates = arguments.get("metadata_updates")
            
            if not document_id or not content:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "document_id and content are required"}, indent=2)
                )]
            
            try:
                result = update_document_content(
                    document_store,
                    document_id,
                    content,
                    doc_embedder,
                    metadata_updates
                )
                return [TextContent(
                    type="text",
                    text=json.dumps(result, indent=2)
                )]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to update document: {str(e)}",
                        "type": type(e).__name__
                    }, indent=2)
                )]
        
        elif name == "update_metadata":
            document_id = arguments.get("document_id", "")
            metadata_updates = arguments.get("metadata_updates", {})
            
            if not document_id or not metadata_updates:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "document_id and metadata_updates are required"}, indent=2)
                )]
            
            try:
                result = update_document_metadata(document_store, document_id, metadata_updates)
                return [TextContent(
                    type="text",
                    text=json.dumps(result, indent=2)
                )]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to update metadata: {str(e)}",
                        "type": type(e).__name__
                    }, indent=2)
                )]
        
        elif name == "get_version_history":
            doc_id = arguments.get("doc_id", "")
            category = arguments.get("category")
            include_deprecated = arguments.get("include_deprecated", True)
            
            if not doc_id:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "doc_id is required"}, indent=2)
                )]
            
            try:
                versions = get_version_history(document_store, doc_id, category, include_deprecated)
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "success",
                        "doc_id": doc_id,
                        "version_count": len(versions),
                        "versions": [
                            {
                                "id": doc.id,
                                "version": doc.meta.get("version") if doc.meta else None,
                                "status": doc.meta.get("status") if doc.meta else None,
                                "created_at": doc.meta.get("created_at") if doc.meta else None,
                                "updated_at": doc.meta.get("updated_at") if doc.meta else None
                            }
                            for doc in versions
                        ]
                    }, indent=2)
                )]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to get version history: {str(e)}",
                        "type": type(e).__name__
                    }, indent=2)
                )]
        
        elif name == "create_backup":
            backup_directory = arguments.get("backup_directory", "./backups")
            include_embeddings = arguments.get("include_embeddings", False)
            filters = arguments.get("filters")
            
            try:
                result = create_backup(
                    document_store=document_store,
                    backup_directory=backup_directory,
                    include_embeddings=include_embeddings,
                    filters=filters
                )
                return [TextContent(
                    type="text",
                    text=json.dumps(result, indent=2, default=str)
                )]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to create backup: {str(e)}",
                        "type": type(e).__name__
                    }, indent=2)
                )]
        
        elif name == "restore_backup":
            backup_path = arguments.get("backup_path", "")
            verify_after_restore = arguments.get("verify_after_restore", True)
            duplicate_strategy = arguments.get("duplicate_strategy", "skip")
            
            if not backup_path:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "backup_path is required"}, indent=2)
                )]
            
            try:
                result = restore_backup(
                    backup_path=backup_path,
                    document_store=document_store,
                    verify_after_restore=verify_after_restore,
                    duplicate_strategy=duplicate_strategy,
                    embedder=doc_embedder  # Pass embedder for automatic embedding regeneration
                )
                return [TextContent(
                    type="text",
                    text=json.dumps(result, indent=2, default=str)
                )]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to restore backup: {str(e)}",
                        "type": type(e).__name__
                    }, indent=2)
                )]
        
        elif name == "list_backups":
            backup_directory = arguments.get("backup_directory", "./backups")
            
            try:
                result = list_backups(backup_directory=backup_directory)
                return [TextContent(
                    type="text",
                    text=json.dumps(result, indent=2, default=str)
                )]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to list backups: {str(e)}",
                        "type": type(e).__name__
                    }, indent=2)
                )]
        
        elif name == "audit_storage_integrity":
            source_directory = arguments.get("source_directory")
            recursive = arguments.get("recursive", True)
            file_extensions = arguments.get("file_extensions")
            
            try:
                result = audit_storage_integrity(
                    document_store=document_store,
                    source_directory=source_directory,
                    code_document_store=code_document_store if 'code_document_store' in globals() else None,
                    recursive=recursive,
                    file_extensions=file_extensions
                )
                return [TextContent(
                    type="text",
                    text=json.dumps(result, indent=2, default=str)
                )]
            except Exception as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": f"Failed to audit storage integrity: {str(e)}",
                        "type": type(e).__name__
                    }, indent=2)
                )]
        
        else:
            return [TextContent(
                type="text",
                text=json.dumps({"error": f"Unknown tool: {name}"}, indent=2)
            )]
    
    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": str(e),
                "type": type(e).__name__
            }, indent=2)
        )]


async def main():
    """Main entry point for the MCP server."""
    # Log server startup
    print("[info] MCP Haystack RAG Server starting...", file=sys.stderr)
    
    # Initialize Haystack
    try:
        initialize_haystack()
        print("[info] Server ready and waiting for connections", file=sys.stderr)
    except Exception as e:
        print(f"[error] Error initializing Haystack: {e}", file=sys.stderr)
        print("[warn] Server will start but tools may return errors until initialization succeeds", file=sys.stderr)
        # Don't raise - let the server start but tools will return errors
        # This allows the MCP client to connect and see the error via tool calls
        pass
    
    # Run MCP server
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options()
            )
    except KeyboardInterrupt:
        print("[info] Server shutting down...", file=sys.stderr)
    except Exception as e:
        print(f"[error] Server error: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    asyncio.run(main())

