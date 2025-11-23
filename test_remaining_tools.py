"""
Test script for remaining 5 MCP tools that need testing.
Run this when MCP server is available.
"""
import asyncio
import json
import os
from pathlib import Path

# Test data
TEST_CODE_DIR = "test_code_dir"
TEST_BACKUP_PATH = "backups/backup_haystack_mcp_20251122_203703"  # Use existing backup
TEST_DOCUMENT_ID = None  # Will be set after adding a test document


async def test_add_code_directory():
    """Test add_code_directory tool"""
    print("\n" + "="*60)
    print("TEST 1: add_code_directory")
    print("="*60)
    
    # This would be called via MCP tool:
    # mcp_haystack-rag_add_code_directory(
    #     directory_path=TEST_CODE_DIR,
    #     extensions=['.py', '.js', '.ts'],
    #     exclude_patterns=['README.md'],
    #     metadata={'category': 'other', 'source': 'manual'}
    # )
    
    print(f"Would test: add_code_directory")
    print(f"  - directory_path: {TEST_CODE_DIR}")
    print(f"  - extensions: ['.py', '.js', '.ts']")
    print(f"  - exclude_patterns: ['README.md']")
    print(f"  - Expected: Should index test1.py, test2.js, test3.ts")
    print(f"  - Should NOT index README.md (excluded)")
    
    return {
        "tool": "add_code_directory",
        "status": "needs_testing",
        "test_params": {
            "directory_path": TEST_CODE_DIR,
            "extensions": ['.py', '.js', '.ts'],
            "exclude_patterns": ['README.md'],
            "metadata": {'category': 'other', 'source': 'manual'}
        }
    }


async def test_import_documents():
    """Test import_documents tool"""
    print("\n" + "="*60)
    print("TEST 2: import_documents")
    print("="*60)
    
    test_documents = [
        {
            "content": "Test import document 1 for bulk import testing",
            "meta": {
                "doc_id": "import_test_001",
                "category": "other",
                "source": "manual",
                "version": "v1"
            }
        },
        {
            "content": "Test import document 2 for bulk import testing with different content",
            "meta": {
                "doc_id": "import_test_002",
                "category": "other",
                "source": "manual",
                "version": "v1"
            }
        }
    ]
    
    print(f"Would test: import_documents")
    print(f"  - documents_data: {len(test_documents)} documents")
    print(f"  - duplicate_strategy: 'skip'")
    print(f"  - batch_size: 2")
    print(f"  - Expected: Should import 2 documents successfully")
    
    return {
        "tool": "import_documents",
        "status": "needs_testing",
        "test_params": {
            "documents_data": test_documents,
            "duplicate_strategy": "skip",
            "batch_size": 2
        }
    }


async def test_restore_backup():
    """Test restore_backup tool"""
    print("\n" + "="*60)
    print("TEST 3: restore_backup")
    print("="*60)
    
    backup_path = TEST_BACKUP_PATH
    if not os.path.exists(backup_path):
        print(f"  WARNING: Backup path not found: {backup_path}")
        print(f"  -> Use an existing backup from list_backups")
        backup_path = None
    
    print(f"Would test: restore_backup")
    print(f"  - backup_path: {backup_path or 'USE_EXISTING_BACKUP'}")
    print(f"  - verify_after_restore: False")
    print(f"  - duplicate_strategy: 'skip'")
    print(f"  - Expected: Should restore documents from backup")
    
    return {
        "tool": "restore_backup",
        "status": "needs_testing",
        "test_params": {
            "backup_path": backup_path or "USE_EXISTING_BACKUP",
            "verify_after_restore": False,
            "duplicate_strategy": "skip"
        }
    }


async def test_delete_document():
    """Test delete_document tool"""
    print("\n" + "="*60)
    print("TEST 4: delete_document")
    print("="*60)
    
    print(f"Would test: delete_document")
    print(f"  - document_id: 'USE_VALID_DOCUMENT_ID'")
    print(f"  - Expected: Should delete document successfully")
    print(f"  - Note: Need to get a valid document_id first (e.g., from add_document)")
    
    return {
        "tool": "delete_document",
        "status": "needs_testing",
        "test_params": {
            "document_id": "USE_VALID_DOCUMENT_ID"
        },
        "note": "Need to get valid document_id first"
    }


async def test_clear_all():
    """Test clear_all tool - DESTRUCTIVE"""
    print("\n" + "="*60)
    print("TEST 5: clear_all (DESTRUCTIVE)")
    print("="*60)
    
    print(f"WARNING: This is a DESTRUCTIVE operation!")
    print(f"Would test: clear_all")
    print(f"  - No parameters")
    print(f"  - Expected: Should delete ALL documents from both collections")
    print(f"  - ⚠️  Should only be tested in isolated/test environment")
    
    return {
        "tool": "clear_all",
        "status": "needs_testing",
        "test_params": {},
        "warning": "DESTRUCTIVE - only test in isolated environment",
        "skip_in_production": True
    }


async def main():
    """Run all tests"""
    print("="*60)
    print("MCP Tools Testing Plan - Remaining 5 Tools")
    print("="*60)
    
    results = []
    
    # Test 1: add_code_directory
    results.append(await test_add_code_directory())
    
    # Test 2: import_documents
    results.append(await test_import_documents())
    
    # Test 3: restore_backup
    results.append(await test_restore_backup())
    
    # Test 4: delete_document
    results.append(await test_delete_document())
    
    # Test 5: clear_all
    results.append(await test_clear_all())
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"Total tools to test: {len(results)}")
    print(f"Status: All need actual MCP tool testing")
    print("\nTo run actual tests:")
    print("1. Ensure MCP server is running")
    print("2. Use MCP tool calls for each test")
    print("3. Verify responses match expected behavior")
    
    # Save test plan
    with open("test_plan_remaining_tools.json", "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\nTest plan saved to: test_plan_remaining_tools.json")


if __name__ == "__main__":
    asyncio.run(main())

