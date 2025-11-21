"""
Test script for the MCP Haystack server.
Tests the server functionality without running the full MCP protocol.
"""
import os
import asyncio
import json
from mcp_haystack_server import (
    initialize_haystack,
    document_store,
    doc_embedder,
    search_pipeline,
    server
)


async def test_tools():
    """Test the MCP tools directly."""
    print("=" * 60)
    print("Testing MCP Haystack Server Tools")
    print("=" * 60)
    
    # Initialize
    print("\n1. Initializing Haystack...")
    try:
        initialize_haystack()
        print("✓ Initialized successfully!")
    except Exception as e:
        print(f"✗ Error: {e}")
        return
    
    # Test list_tools
    print("\n2. Testing list_tools...")
    tools = await server.list_tools()
    print(f"✓ Found {len(tools)} tools:")
    for tool in tools:
        print(f"  - {tool.name}: {tool.description[:60]}...")
    
    # Test index_document
    print("\n3. Testing index_document...")
    result = await server.call_tool(
        "index_document",
        {
            "content": "This is a test document for the MCP server.",
            "metadata": {"source": "test", "type": "example"}
        }
    )
    response = json.loads(result[0].text)
    print(f"✓ Result: {response.get('status')}")
    if "document_id" in response:
        test_doc_id = response["document_id"]
        print(f"  Document ID: {test_doc_id}")
    
    # Test search
    print("\n4. Testing search...")
    result = await server.call_tool(
        "search",
        {"query": "test document", "top_k": 3}
    )
    response = json.loads(result[0].text)
    print(f"✓ Found {response.get('results_count', 0)} results")
    if "results" in response:
        for res in response["results"][:2]:
            print(f"  - Score: {res.get('score', 'N/A'):.4f}")
            print(f"    Content: {res.get('content', '')[:60]}...")
    
    # Test get_stats
    print("\n5. Testing get_stats...")
    result = await server.call_tool("get_stats", {})
    response = json.loads(result[0].text)
    print(f"✓ Total documents: {response.get('total_documents', 0)}")
    
    # Test delete_document (if we have a doc ID)
    if "test_doc_id" in locals():
        print("\n6. Testing delete_document...")
        result = await server.call_tool(
            "delete_document",
            {"document_id": test_doc_id}
        )
        response = json.loads(result[0].text)
        print(f"✓ {response.get('message', 'Deleted')}")
    
    print("\n" + "=" * 60)
    print("✓ All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    # Load environment variables from .env if it exists
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # dotenv not installed, skip
    
    asyncio.run(test_tools())

