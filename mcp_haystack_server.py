"""
MCP Server for Haystack RAG operations.
Exposes Haystack functions as MCP tools for indexing, searching, and managing documents.
"""
import asyncio
import os
import json
import sys
from typing import Any, Sequence
from pathlib import Path

from haystack.dataclasses.document import Document
from haystack.components.embedders import SentenceTransformersDocumentEmbedder, SentenceTransformersTextEmbedder
from haystack.utils import Secret
from haystack import Pipeline

# Qdrant integration
try:
    from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
    from haystack_integrations.components.retrievers.qdrant import QdrantEmbeddingRetriever
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
            description="Search for documents and code using semantic similarity. Use for finding relevant documents, code snippets, or content based on meaning. Can search documentation, code, or both.",
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
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Handle tool calls."""
    global document_store, code_document_store, doc_embedder, code_embedder, search_pipeline, code_search_pipeline
    
    # Check initialization based on tool type
    if name in ["add_document", "add_file", "search_documents", "get_stats", "delete_document"]:
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
            
            # Create document
            doc = Document(content=content, meta=metadata)
            
            # Embed and store
            result = doc_embedder.run(documents=[doc])
            documents_with_embeddings = result["documents"]
            document_store.write_documents(documents_with_embeddings)
            
            doc_id = documents_with_embeddings[0].id
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "message": "Document indexed successfully",
                    "document_id": doc_id
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
            
            # Add file path to metadata
            file_metadata = {**metadata, "file_path": str(path), "file_name": path.name}
            
            # Create and index document
            doc = Document(content=content, meta=file_metadata)
            result = doc_embedder.run(documents=[doc])
            documents_with_embeddings = result["documents"]
            document_store.write_documents(documents_with_embeddings)
            
            doc_id = documents_with_embeddings[0].id
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "message": "File indexed successfully",
                    "document_id": doc_id,
                    "file_path": str(path)
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
            
            # Create code-specific metadata
            code_metadata = {
                **metadata,
                "file_path": str(path),
                "file_name": path.name,
                "file_extension": path.suffix,
                "language": language,
                "content_type": "code",
                "file_size": path.stat().st_size
            }
            
            # Create and index document using CODE embedder and CODE document store
            doc = Document(content=content, meta=code_metadata)
            result = code_embedder.run(documents=[doc])
            documents_with_embeddings = result["documents"]
            code_document_store.write_documents(documents_with_embeddings)
            
            doc_id = documents_with_embeddings[0].id
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "message": "Code file indexed successfully",
                    "document_id": doc_id,
                    "file_path": str(path),
                    "language": language,
                    "collection": "code"
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
            
            if not query:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "query is required"}, indent=2)
                )]
            
            all_results = []
            
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
            
            # Delete document
            document_store.delete_documents([document_id])
            
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "message": f"Document {document_id} deleted successfully"
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

