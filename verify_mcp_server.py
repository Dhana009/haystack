"""
Quick verification script to test if the MCP server can start and initialize.
Run this to verify the server works before loading it in Cursor.
"""
import sys
import os
import asyncio

# Set environment variables (adjust these to match your config)
# These should be set in your environment or .env file
qdrant_url = os.getenv("QDRANT_URL")
qdrant_api_key = os.getenv("QDRANT_API_KEY")
qdrant_collection = os.getenv("QDRANT_COLLECTION", "haystack_mcp")

if not qdrant_url or not qdrant_api_key:
    print("Error: QDRANT_URL and QDRANT_API_KEY must be set in environment variables")
    print("Set them before running this script:")
    print("  export QDRANT_URL='https://your-cluster.qdrant.io:6333'")
    print("  export QDRANT_API_KEY='your-api-key'")
    sys.exit(1)

os.environ["QDRANT_URL"] = qdrant_url
os.environ["QDRANT_API_KEY"] = qdrant_api_key
os.environ["QDRANT_COLLECTION"] = qdrant_collection

print("=" * 60)
print("MCP Server Verification")
print("=" * 60)

# Test 1: Check imports
print("\n1. Checking imports...")
try:
    from mcp_haystack_server import server, initialize_haystack, list_tools
    print("✓ All imports successful")
except Exception as e:
    print(f"✗ Import error: {e}")
    sys.exit(1)

# Test 2: Check server object
print("\n2. Checking server object...")
try:
    print(f"✓ Server name: {server.name}")
except Exception as e:
    print(f"✗ Server error: {e}")
    sys.exit(1)

# Test 3: Test list_tools (doesn't require initialization)
print("\n3. Testing list_tools (no initialization needed)...")
try:
    async def test_list_tools():
        # Call the actual list_tools function directly (not server.list_tools which is a decorator)
        tools = await list_tools()
        print(f"✓ Found {len(tools)} tools:")
        for tool in tools:
            print(f"  - {tool.name}")
        return tools
    
    tools = asyncio.run(test_list_tools())
except Exception as e:
    print(f"✗ list_tools error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 4: Test initialization (this will download models if needed)
print("\n4. Testing Haystack initialization...")
print("   (This may take a minute to download models on first run)")
try:
    initialize_haystack()
    print("✓ Haystack initialized successfully!")
except Exception as e:
    print(f"✗ Initialization error: {e}")
    import traceback
    traceback.print_exc()
    print("\nNote: If this is a connection error, check your QDRANT_URL and QDRANT_API_KEY")
    sys.exit(1)

# Test 5: Test server can start (quick test)
print("\n5. Testing server startup (quick test)...")
try:
    # Just verify the main function exists and is callable
    from mcp_haystack_server import main
    print("✓ Server main function is ready")
    print("  (Full server test requires MCP client connection)")
except Exception as e:
    print(f"✗ Server startup error: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("✓ All verification tests passed!")
print("=" * 60)
print("\nNext steps:")
print("1. Restart Cursor to load the MCP server")
print("2. Check Cursor's MCP logs to see if the server connects")
print("3. Try using one of the tools (e.g., get_stats) to verify it works")

