# Haystack MCP Server

MCP (Model Context Protocol) server that exposes Haystack RAG functions as tools.

## Features

- **Index Documents**: Add text documents to the RAG system
- **Index Files**: Index files from the filesystem
- **Index Code**: Index code files with language detection
- **Index Code Directory**: Index all code files from a directory recursively
- **Search**: Semantic search across indexed documents
- **Get Stats**: View statistics about indexed documents
- **Delete Documents**: Remove documents from the index

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

### 1. `index_document`
Index a text document into the RAG system.

**Parameters:**
- `content` (string, required): The text content to index
- `metadata` (object, optional): Additional metadata (e.g., `{"file_path": "doc.txt", "source": "manual"}`)

**Example:**
```json
{
  "content": "Haystack is a framework for building RAG applications.",
  "metadata": {"source": "documentation"}
}
```

### 2. `index_file`
Index a file by reading its content.

**Parameters:**
- `file_path` (string, required): Path to the file to index
- `metadata` (object, optional): Additional metadata

**Example:**
```json
{
  "file_path": "/path/to/document.txt",
  "metadata": {"category": "docs"}
}
```

### 3. `index_code`
Index a code file with automatic language detection and code-specific metadata.

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
  "metadata": {"project": "my-app"}
}
```

### 4. `index_code_directory`
Index all code files from a directory recursively. Automatically detects and indexes common code file extensions.

**Parameters:**
- `directory_path` (string, required): Path to the directory containing code files
- `extensions` (array, optional): List of file extensions to include (e.g., `[".py", ".js"]`). Defaults to common code extensions.
- `exclude_patterns` (array, optional): Patterns to exclude (e.g., `["__pycache__", "node_modules", ".git"]`). Defaults to common exclusion patterns.
- `metadata` (object, optional): Additional metadata to add to all indexed files

**Example:**
```json
{
  "directory_path": "/path/to/project",
  "extensions": [".py", ".js", ".ts"],
  "exclude_patterns": ["__pycache__", "node_modules", ".git"],
  "metadata": {"project": "my-app", "version": "1.0.0"}
}
```

### 5. `search`
Search for documents using semantic search.

**Parameters:**
- `query` (string, required): The search query
- `top_k` (integer, optional): Number of results (default: 5, max: 50)

**Example:**
```json
{
  "query": "What is Haystack?",
  "top_k": 5
}
```

### 6. `get_stats`
Get statistics about indexed documents.

**Parameters:** None

**Example:**
```json
{}
```

### 7. `delete_document`
Delete a document by its ID.

**Parameters:**
- `document_id` (string, required): The document ID to delete

**Example:**
```json
{
  "document_id": "doc-123"
}
```

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

## Notes

- The server uses `sentence-transformers/all-MiniLM-L6-v2` for embeddings (384 dimensions)
- Documents are stored in Qdrant with their embeddings
- The server runs as a stdio server for MCP protocol communication

