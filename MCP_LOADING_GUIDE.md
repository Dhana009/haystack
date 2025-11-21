# MCP Server Loading Guide

## Quick Verification

Before loading in Cursor, verify the server works:

```bash
python verify_mcp_server.py
```

This will test:
- ✅ Imports work correctly
- ✅ Server object is created
- ✅ Tools can be listed
- ✅ Haystack initialization works
- ✅ Server can start

## Loading the Server in Cursor

### Step 1: Verify Configuration

Your `mcp.json` should look like this (Windows path format):

```json
{
  "mcpServers": {
    "haystack-rag": {
      "command": "python",
      "args": ["D:\\planning\\haystack\\mcp_haystack_server.py"],
      "env": {
        "QDRANT_URL": "https://your-cluster.qdrant.io:6333",
        "QDRANT_API_KEY": "your-api-key",
        "QDRANT_COLLECTION": "haystack_mcp"
      }
    }
  }
}
```

### Step 2: Restart Cursor

**Important**: After adding or modifying the MCP configuration, you **must**:

1. **Completely close Cursor** (not just the window)
2. **Restart Cursor** to load the new MCP server

### Step 3: Check MCP Logs

After restarting, check Cursor's MCP logs:

1. Open the Command Palette (`Ctrl+Shift+P` or `Cmd+Shift+P`)
2. Search for "MCP" or "Model Context Protocol"
3. Look for logs showing:
   - `[info] MCP Haystack RAG Server starting...`
   - `[info] Initializing Haystack with Qdrant...`
   - `[info] Server ready and waiting for connections`

### Step 4: Test the Server

Try using one of the MCP tools:

1. In the chat, ask to use the `get_stats` tool
2. Or try: "Use the haystack-rag server to get stats"

## Troubleshooting

### Server Not Loading

**Issue**: "No server info found" errors

**Solution**: 
- This is often a Cursor client issue, not a server issue
- Verify the server works with `verify_mcp_server.py`
- Check that the Python path in `mcp.json` is correct
- Ensure you've restarted Cursor completely

### Initialization Errors

**Issue**: Server starts but tools return initialization errors

**Solution**:
- Check `QDRANT_URL` and `QDRANT_API_KEY` are correct
- Verify network connectivity to Qdrant
- Check the MCP logs for specific error messages

### Python Path Issues

**Issue**: Server can't be found

**Solution**:
- Use full path to Python: `"command": "C:\\Python\\python.exe"` (if needed)
- Or use `python` if it's in your PATH
- Verify the script path uses double backslashes: `D:\\planning\\haystack\\mcp_haystack_server.py`

### Model Download Takes Time

**Issue**: First startup is slow

**Solution**:
- First run downloads embedding models (~100-500MB)
- This is normal and only happens once
- Subsequent starts are much faster

## Verifying Server is Loaded

Once loaded, you should be able to:

1. See the server in Cursor's MCP status
2. Use tools like:
   - `index_document` - Index text documents
   - `index_file` - Index files
   - `index_code` - Index code files
   - `search` - Search indexed content
   - `get_stats` - Get statistics
   - `delete_document` - Delete documents

## Common Commands

```bash
# Test the server directly
python verify_mcp_server.py

# Test with MCP Inspector (optional)
npx @modelcontextprotocol/inspector python mcp_haystack_server.py

# Run the test suite
python test_mcp_server.py
```


