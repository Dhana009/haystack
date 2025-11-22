# Haystack MCP Server

MCP (Model Context Protocol) server that exposes Haystack RAG functions as tools with advanced duplicate detection, metadata management, bulk operations, and content verification.

## Features

### Core Indexing
- **Index Documents**: Add text documents to the RAG system with automatic duplicate detection
- **Index Files**: Index files from the filesystem with file-based deduplication
- **Index Code**: Index code files with language detection and code-specific metadata
- **Index Code Directory**: Index all code files from a directory recursively

### Search & Retrieval
- **Search**: Semantic search across indexed documents with metadata filtering
- **Get Document by Path**: Retrieve documents by file path
- **Get Metadata Stats**: View aggregated statistics by metadata fields

### Document Management
- **Delete Document**: Remove a document by ID
- **Delete by Filter**: Bulk delete documents matching metadata filters
- **Update Document**: Atomically update document content and metadata
- **Update Metadata**: Update only metadata fields without changing content
- **Bulk Update Metadata**: Update metadata for multiple documents matching a filter

### Verification & Quality
- **Verify Document**: Verify quality and integrity of a single document
- **Verify Category**: Bulk verify all documents in a category

### Import/Export
- **Export Documents**: Export documents with metadata to JSON format
- **Import Documents**: Bulk import documents with duplicate handling strategies

### Version Management
- **Get Version History**: Retrieve all versions of a document by doc_id

## Installation

```bash
pip install -r requirements_mcp.txt
```

## Configuration

Set environment variables for Qdrant connection:

```bash
export QDRANT_URL="https://your-cluster.qdrant.io:6333"
export QDRANT_API_KEY="your-api-key"
export QDRANT_COLLECTION="haystack_mcp"  # Optional, defaults to "haystack_mcp"
```

Or create a `.env` file:

```env
QDRANT_URL=https://your-cluster.qdrant.io:6333
QDRANT_API_KEY=your-api-key
QDRANT_COLLECTION=haystack_mcp
```

## Running the Server

### As stdio server (for MCP clients like Cursor):

```bash
python mcp_haystack_server.py
```

### Testing with MCP Inspector:

```bash
npx @modelcontextprotocol/inspector python mcp_haystack_server.py
```

## Available Tools

### Core Indexing Tools

#### 1. `add_document`
Add a text document to the RAG system with automatic duplicate detection and metadata management.

**Parameters:**
- `content` (string, required): The text content to index
- `metadata` (object, optional): Additional metadata (e.g., `{"doc_id": "doc1", "category": "user_rule", "file_path": "doc.txt", "source": "manual"}`)

**Features:**
- Automatic duplicate detection (4 levels: exact, update, similar, new)
- RULE 3 compliant metadata generation
- Content fingerprinting for deduplication
- Version management support

**Example:**
```json
{
  "content": "Haystack is a framework for building RAG applications with LLMs.",
  "metadata": {
    "doc_id": "haystack_intro",
    "category": "user_rule",
    "source": "documentation",
    "tags": ["rag", "framework"]
  }
}
```

**Response:**
```json
{
  "status": "success",
  "message": "New document stored successfully.",
  "document_id": "qdrant-point-id",
  "doc_id": "haystack_intro",
  "version": "2025-01-15T10:30:00Z",
  "category": "user_rule",
  "action": "store",
  "duplicate_level": 4
}
```

#### 2. `add_file`
Add a file to the RAG system by reading its content. Includes file-based duplicate detection.

**Parameters:**
- `file_path` (string, required): Path to the file to index
- `metadata` (object, optional): Additional metadata

**Example:**
```json
{
  "file_path": "/path/to/document.txt",
  "metadata": {
    "category": "docs",
    "source": "manual"
  }
}
```

#### 3. `add_code`
Add a code file with automatic language detection and code-specific metadata.

**Parameters:**
- `file_path` (string, required): Path to the code file to index
- `language` (string, optional): Programming language (auto-detected from extension if not provided)
- `metadata` (object, optional): Additional metadata

**Supported languages:** Python, JavaScript, TypeScript, Java, C/C++, Go, Rust, Ruby, PHP, Swift, Kotlin, Scala, R, SQL, Bash, PowerShell, YAML, JSON, XML, HTML, CSS, Vue, Svelte, and more.

**Example:**
```json
{
  "file_path": "/path/to/script.py",
  "language": "python",
  "metadata": {
    "project": "my-app",
    "category": "project_rule"
  }
}
```

#### 4. `add_code_directory`
Index all code files from a directory recursively.

**Parameters:**
- `directory_path` (string, required): Path to the directory containing code files
- `extensions` (array, optional): List of file extensions to include (e.g., `[".py", ".js"]`)
- `exclude_patterns` (array, optional): Patterns to exclude (e.g., `["__pycache__", "node_modules", ".git"]`)
- `metadata` (object, optional): Additional metadata to add to all indexed files

**Example:**
```json
{
  "directory_path": "/path/to/project",
  "extensions": [".py", ".js", ".ts"],
  "exclude_patterns": ["__pycache__", "node_modules", ".git"],
  "metadata": {
    "project": "my-app",
    "version": "1.0.0"
  }
}
```

### Search & Retrieval Tools

#### 5. `search_documents`
Search for documents using semantic similarity with optional metadata filtering.

**Parameters:**
- `query` (string, required): The search query
- `top_k` (integer, optional): Number of results (default: 5, max: 50)
- `content_type` (string, optional): Type of content to search: `"all"` (default), `"code"`, or `"docs"`
- `metadata_filters` (object, optional): Haystack filter format for metadata filtering

**Filter Format:**
```json
{
  "field": "meta.category",
  "operator": "==",
  "value": "user_rule"
}
```

**Supported Operators:** `==`, `!=`, `>`, `<`, `>=`, `<=`, `in`, `not in`

**Complex Filters (AND/OR/NOT):**
```json
{
  "operator": "AND",
  "conditions": [
    {"field": "meta.category", "operator": "==", "value": "user_rule"},
    {"field": "meta.status", "operator": "==", "value": "active"}
  ]
}
```

**Example:**
```json
{
  "query": "What is Haystack?",
  "top_k": 5,
  "metadata_filters": {
    "field": "meta.category",
    "operator": "==",
    "value": "user_rule"
  }
}
```

#### 6. `get_document_by_path`
Retrieve a document by its file path.

**Parameters:**
- `file_path` (string, required): File path to search for
- `status` (string, optional): Status filter - `"active"` (default), `"deprecated"`, or `"draft"`

**Example:**
```json
{
  "file_path": "/path/to/document.txt",
  "status": "active"
}
```

#### 7. `get_metadata_stats`
Get statistics aggregated by metadata fields.

**Parameters:**
- `filters` (object, optional): Haystack filter dictionary to filter documents
- `group_by_fields` (array, optional): List of metadata fields to group by (e.g., `["category", "status"]`)

**Example:**
```json
{
  "filters": {
    "field": "meta.status",
    "operator": "==",
    "value": "active"
  },
  "group_by_fields": ["category", "status"]
}
```

**Response:**
```json
{
  "status": "success",
  "total_documents": 150,
  "grouped_stats": {
    "category": {
      "user_rule": 50,
      "project_rule": 75,
      "other": 25
    },
    "status": {
      "active": 150
    }
  }
}
```

### Document Management Tools

#### 8. `delete_document`
Delete a document by its ID.

**Parameters:**
- `document_id` (string, required): The document ID (Qdrant point ID) to delete

**Example:**
```json
{
  "document_id": "doc-123"
}
```

#### 9. `delete_by_filter`
Bulk delete documents matching metadata filters.

**Parameters:**
- `filters` (object, required): Haystack filter dictionary

**Example:**
```json
{
  "filters": {
    "field": "meta.category",
    "operator": "==",
    "value": "deprecated_category"
  }
}
```

**Response:**
```json
{
  "status": "success",
  "deleted_count": 25,
  "message": "Successfully deleted 25 documents"
}
```

#### 10. `update_document`
Atomically update document content and optionally metadata. Regenerates embedding and updates hash.

**Parameters:**
- `document_id` (string, required): Document ID (Qdrant point ID)
- `content` (string, required): New document content
- `metadata_updates` (object, optional): Optional metadata fields to update

**Example:**
```json
{
  "document_id": "doc-123",
  "content": "Updated content with new information.",
  "metadata_updates": {
    "tags": ["updated", "revised"],
    "version": "v2.0"
  }
}
```

**Response:**
```json
{
  "status": "success",
  "document_id": "doc-123",
  "message": "Document content updated successfully",
  "updated_fields": ["content", "hash_content", "updated_at", "tags", "version"]
}
```

#### 11. `update_metadata`
Update only metadata fields without changing content. Efficient for metadata-only updates.

**Parameters:**
- `document_id` (string, required): Document ID (Qdrant point ID)
- `metadata_updates` (object, required): Dictionary of metadata fields to update

**Example:**
```json
{
  "document_id": "doc-123",
  "metadata_updates": {
    "status": "deprecated",
    "tags": ["archived"]
  }
}
```

#### 12. `bulk_update_metadata`
Update metadata for multiple documents matching a filter.

**Parameters:**
- `filters` (object, required): Haystack filter dictionary to match documents
- `metadata_updates` (object, required): Dictionary of metadata fields to update

**Example:**
```json
{
  "filters": {
    "field": "meta.category",
    "operator": "==",
    "value": "user_rule"
  },
  "metadata_updates": {
    "status": "deprecated",
    "tags": ["archived"]
  }
}
```

**Response:**
```json
{
  "status": "success",
  "updated_count": 50,
  "message": "Successfully updated 50 documents"
}
```

### Verification & Quality Tools

#### 13. `verify_document`
Verify the quality and integrity of a single document. Checks for placeholders, validates hash, verifies metadata, and returns a quality score.

**Parameters:**
- `document_id` (string, required): The ID of the document to verify

**Example:**
```json
{
  "document_id": "doc-123"
}
```

**Response:**
```json
{
  "document_id": "doc-123",
  "doc_id": "test_doc_1",
  "quality_score": 0.95,
  "status": "pass",
  "checks": {
    "has_content": true,
    "min_length": true,
    "no_placeholders": true,
    "has_metadata": true,
    "has_required_metadata": true,
    "hash_valid": true,
    "has_status": true
  },
  "issues": []
}
```

#### 14. `verify_category`
Bulk verify all documents in a category. Returns statistics on quality scores, failed documents, and common issues.

**Parameters:**
- `category` (string, required): Category to verify (e.g., `"user_rule"`, `"project_rule"`, `"other"`)
- `max_documents` (integer, optional): Maximum number of documents to verify (defaults to all)

**Example:**
```json
{
  "category": "user_rule",
  "max_documents": 100
}
```

**Response:**
```json
{
  "category": "user_rule",
  "total": 100,
  "passed": 95,
  "failed": 5,
  "average_quality_score": 0.92,
  "summary": {
    "common_issues": ["Missing file_path", "Hash mismatch"],
    "failed_document_ids": ["doc-1", "doc-2"]
  }
}
```

### Import/Export Tools

#### 15. `export_documents`
Export documents with metadata to JSON format. Useful for backup and migration.

**Parameters:**
- `filters` (object, optional): Haystack filter dictionary to filter documents
- `include_embeddings` (boolean, optional): Whether to include embeddings in export (default: false)

**Example:**
```json
{
  "filters": {
    "field": "meta.category",
    "operator": "==",
    "value": "user_rule"
  },
  "include_embeddings": false
}
```

**Response:**
```json
{
  "status": "success",
  "exported_count": 50,
  "documents": [
    {
      "content": "Document content...",
      "meta": {
        "doc_id": "doc1",
        "category": "user_rule",
        "version": "v1.0"
      },
      "id": "doc-123"
    }
  ]
}
```

#### 16. `import_documents`
Bulk import documents with duplicate handling strategy.

**Parameters:**
- `documents_data` (array, required): Array of document dictionaries with `content`, `meta`, etc.
- `duplicate_strategy` (string, optional): How to handle duplicates - `"skip"` (default), `"update"`, or `"error"`
- `batch_size` (integer, optional): Number of documents to process per batch (default: 100)

**Duplicate Strategies:**
- `"skip"`: Skip documents that already exist (by doc_id)
- `"update"`: Update existing documents with new content/metadata
- `"error"`: Return error if duplicates are found

**Example:**
```json
{
  "documents_data": [
    {
      "content": "Document 1 content",
      "meta": {
        "doc_id": "doc1",
        "category": "user_rule",
        "version": "v1.0"
      }
    },
    {
      "content": "Document 2 content",
      "meta": {
        "doc_id": "doc2",
        "category": "project_rule",
        "version": "v1.0"
      }
    }
  ],
  "duplicate_strategy": "skip",
  "batch_size": 100
}
```

**Response:**
```json
{
  "status": "success",
  "imported_count": 2,
  "skipped_count": 0,
  "errors": []
}
```

### Version Management Tools

#### 17. `get_version_history`
Retrieve version history for a document by doc_id. Returns all versions sorted by version/created_at.

**Parameters:**
- `doc_id` (string, required): Logical document ID (not Qdrant point ID)
- `category` (string, optional): Optional category filter
- `include_deprecated` (boolean, optional): Whether to include deprecated versions (default: true)

**Example:**
```json
{
  "doc_id": "test_doc_1",
  "category": "user_rule",
  "include_deprecated": true
}
```

**Response:**
```json
{
  "status": "success",
  "doc_id": "test_doc_1",
  "versions": [
    {
      "id": "doc-v1",
      "content": "Version 1 content",
      "meta": {
        "doc_id": "test_doc_1",
        "version": "v1.0",
        "status": "deprecated",
        "created_at": "2025-01-01T00:00:00Z"
      }
    },
    {
      "id": "doc-v2",
      "content": "Version 2 content",
      "meta": {
        "doc_id": "test_doc_1",
        "version": "v2.0",
        "status": "active",
        "created_at": "2025-01-15T00:00:00Z"
      }
    }
  ]
}
```

### Backup & Restore Tools

#### 18. `create_backup`
Create a local backup of a Qdrant collection. Backs up to a timestamped directory with documents, metadata, and manifest files. All backups are stored locally on disk.

**Parameters:**
- `backup_directory` (string, optional): Directory to store backups (default: `"./backups"`)
- `include_embeddings` (boolean, optional): Whether to include embeddings in backup (default: false)
- `filters` (object, optional): Haystack filter dictionary to filter documents for backup

**Backup Structure:**
Each backup creates a timestamped directory containing:
- `documents.json`: All documents with metadata
- `metadata.json`: Backup metadata (timestamp, collection info, stats)
- `manifest.json`: File manifest with checksums for integrity verification

**Example:**
```json
{
  "backup_directory": "./backups",
  "include_embeddings": false,
  "filters": {
    "field": "meta.category",
    "operator": "==",
    "value": "user_rule"
  }
}
```

**Response:**
```json
{
  "status": "success",
  "backup_path": "./backups/backup_haystack_mcp_20250115_103045",
  "backup_id": "backup_haystack_mcp_20250115_103045",
  "document_count": 150,
  "backup_metadata": {
    "backup_id": "backup_haystack_mcp_20250115_103045",
    "collection_name": "haystack_mcp",
    "timestamp": "2025-01-15T10:30:45Z",
    "document_count": 150,
    "include_embeddings": false,
    "filters_applied": true
  },
  "manifest": {
    "backup_id": "backup_haystack_mcp_20250115_103045",
    "files": [
      {
        "filename": "documents.json",
        "checksum": "abc123...",
        "size": 1024000
      },
      {
        "filename": "metadata.json",
        "checksum": "def456...",
        "size": 1024
      }
    ]
  }
}
```

#### 19. `restore_backup`
Restore a collection from a local backup. Verifies backup integrity using checksums and optionally verifies restored documents.

**Parameters:**
- `backup_path` (string, required): Path to backup directory
- `verify_after_restore` (boolean, optional): Whether to verify documents after restore (default: true)
- `duplicate_strategy` (string, optional): How to handle duplicates - `"skip"` (default), `"update"`, or `"overwrite"`

**Example:**
```json
{
  "backup_path": "./backups/backup_haystack_mcp_20250115_103045",
  "verify_after_restore": true,
  "duplicate_strategy": "skip"
}
```

**Response:**
```json
{
  "status": "success",
  "restored_count": 150,
  "skipped_count": 0,
  "backup_id": "backup_haystack_mcp_20250115_103045",
  "backup_collection": "haystack_mcp",
  "restore_collection": "haystack_mcp",
  "verification_results": {
    "sample_size": 100,
    "verified_count": 98,
    "failed_count": 2,
    "verification_rate": 0.98
  }
}
```

#### 20. `list_backups`
List all available backups in the backup directory with their metadata.

**Parameters:**
- `backup_directory` (string, optional): Directory containing backups (default: `"./backups"`)

**Example:**
```json
{
  "backup_directory": "./backups"
}
```

**Response:**
```json
{
  "status": "success",
  "backups": [
    {
      "backup_id": "backup_haystack_mcp_20250115_103045",
      "backup_path": "./backups/backup_haystack_mcp_20250115_103045",
      "collection_name": "haystack_mcp",
      "timestamp": "2025-01-15T10:30:45Z",
      "document_count": 150,
      "include_embeddings": false
    }
  ],
  "total_backups": 1
}
```

### Utility Tools

#### 21. `get_stats`
Get basic statistics about indexed documents.

**Parameters:** None

**Example:**
```json
{}
```

**Response:**
```json
{
  "total_documents": 150,
  "code_documents": 50,
  "docs_documents": 100
}
```

#### 22. `clear_all`
Delete all documents from both documentation and code collections.

**Parameters:** None

**Example:**
```json
{}
```

#### 23. `audit_storage_integrity`
Audit storage integrity by comparing stored documents with source files. Detects missing files, content mismatches, and quality issues.

**Parameters:**
- `source_directory` (string, optional): Source directory to compare against stored documents
- `recursive` (boolean, optional): Whether to scan source directory recursively (default: true)
- `file_extensions` (array, optional): List of file extensions to include (e.g., `[".md", ".txt"]`)

**Example:**
```json
{
  "source_directory": "/path/to/source/files",
  "recursive": true,
  "file_extensions": [".md", ".txt"]
}
```

**Response:**
```json
{
  "total_documents": 150,
  "total_files": 200,
  "stored_files": 180,
  "missing_files": [
    {
      "file_path": "/path/to/missing_file.md",
      "relative_path": "missing_file.md",
      "severity": "high",
      "issue": "not_stored"
    }
  ],
  "content_mismatches": [
    {
      "file_path": "/path/to/changed_file.md",
      "relative_path": "changed_file.md",
      "stored_hash": "abc123...",
      "source_hash": "def456...",
      "document_id": "doc-123",
      "severity": "high",
      "issue": "content_mismatch"
    }
  ],
  "passed": 145,
  "failed": 5,
  "integrity_score": 0.89,
  "issues": [...],
  "issues_by_type": {
    "missing_file": [...],
    "content_mismatch": [...]
  }
}
```

## Metadata Schema (RULE 3)

All documents stored in Qdrant follow a mandatory metadata schema:

**Required Fields:**
- `doc_id`: Stable logical ID (e.g., path or slug)
- `version`: Version string (e.g., "v1", "v1.1", "2025-11-22T10:30Z")
- `category`: One of: `user_rule`, `project_rule`, `project_command`, `design_doc`, `debug_summary`, `test_pattern`, `other`
- `hash_content`: SHA256 hash of normalized content

**Optional Fields:**
- `source`: `"manual"` | `"generated"` | `"imported"` (default: "manual")
- `repo`: Repository identifier (default: "qdrant_haystack")
- `file_path`: Logical or physical path if exists
- `hash_file`: Hash of original file (optional)
- `created_at`: ISO timestamp (auto-generated)
- `updated_at`: ISO timestamp (auto-generated)
- `status`: `"active"` | `"deprecated"` | `"draft"` (default: "active")
- `tags`: List of free-form tags

## Duplicate Detection

The system uses multi-factor duplicate detection with 4 levels:

1. **Level 1 - Exact Duplicate**: Same `content_hash` AND `metadata_hash` → **SKIP**
2. **Level 2 - Content Update**: Same `metadata_hash` BUT different `content_hash` → **UPDATE** (deprecate old, store new)
3. **Level 3 - Semantic Similarity**: High similarity (>0.85) BUT different hashes → **WARN** (store with warning flag)
4. **Level 4 - New Content**: Low similarity OR different metadata → **STORE** normally

## Integration with Cursor

Add to your Cursor MCP configuration (`~/.cursor/mcp.json` or similar):

```json
{
  "mcpServers": {
    "haystack-rag": {
      "command": "python",
      "args": ["/path/to/mcp_haystack_server.py"],
      "env": {
        "QDRANT_URL": "https://your-cluster.qdrant.io:6333",
        "QDRANT_API_KEY": "your-api-key",
        "QDRANT_COLLECTION": "haystack_mcp"
      }
    }
  }
}
```

## Testing

Test the server manually:

```python
# Test script
import asyncio
from mcp_haystack_server import initialize_haystack, document_store, doc_embedder

# Initialize
initialize_haystack()

# Index a document
doc = Document(content="Test document")
result = doc_embedder.run(documents=[doc])
document_store.write_documents(result["documents"])

# Search
# ... use search tool
```

Run unit tests:

```bash
pytest test/test_deduplication_service.py
pytest test/test_metadata_service.py
pytest test/test_verification_service.py
pytest test/test_bulk_operations_service.py
pytest test/test_query_service.py
pytest test/test_update_service.py
```

Run integration tests:

```bash
pytest test/test_integration_phase1.py
pytest test/test_integration_phase2.py
```

Run performance tests (requires Qdrant connection):

```bash
pytest test/test_performance.py -m performance
```

## Notes

- The server uses `sentence-transformers/all-MiniLM-L6-v2` for embeddings (384 dimensions)
- Documents are stored in Qdrant with their embeddings
- The server runs as a stdio server for MCP protocol communication
- All metadata follows RULE 3 schema for consistency and deduplication
- Duplicate detection is automatic and multi-factor (content hash + metadata hash + semantic similarity)
- Bulk operations use direct QdrantClient interaction for performance
- Version management tracks document evolution with deprecation support
- **Backup system**: All backups are stored locally on disk. Each backup includes integrity checksums for verification. Backups can be filtered by metadata and optionally include embeddings.
