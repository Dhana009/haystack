# Remaining 5 Tools - Test Plan

**Date:** November 23, 2025  
**Status:** Ready for Testing

---

## Test Setup

### Test Directory Created
- **Path:** `test_code_dir/`
- **Files:**
  - `test1.py` - Python test file
  - `test2.js` - JavaScript test file  
  - `test3.ts` - TypeScript test file
  - `README.md` - Should be excluded

---

## Test Cases

### 1. `add_code_directory` 

**Test Command:**
```json
{
  "directory_path": "test_code_dir",
  "extensions": [".py", ".js", ".ts"],
  "exclude_patterns": ["README.md"],
  "metadata": {
    "category": "other",
    "source": "manual"
  }
}
```

**Expected Result:**
- Should index: test1.py, test2.js, test3.ts
- Should NOT index: README.md (excluded)
- Should return success with count of indexed files

**Verification:**
- Check that 3 files were indexed
- Verify language detection worked
- Verify README.md was excluded

---

### 2. `import_documents`

**Test Command:**
```json
{
  "documents_data": [
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
  ],
  "duplicate_strategy": "skip",
  "batch_size": 2
}
```

**Expected Result:**
- Should import 2 documents successfully
- Should return success with import count

**Verification:**
- Check that 2 documents were imported
- Verify metadata was preserved
- Search for imported documents to confirm

---

### 3. `restore_backup`

**Prerequisites:**
- First run `list_backups` to get a valid backup path

**Test Command:**
```json
{
  "backup_path": "backups/backup_haystack_mcp_20251122_203703",
  "verify_after_restore": false,
  "duplicate_strategy": "skip"
}
```

**Expected Result:**
- Should restore documents from backup
- Should return success with restore count

**Verification:**
- Check that documents were restored
- Verify document count matches backup

---

### 4. `delete_document`

**Prerequisites:**
- First add a test document using `add_document` to get a valid document_id

**Test Command:**
```json
{
  "document_id": "USE_VALID_DOCUMENT_ID_FROM_ADD_DOCUMENT"
}
```

**Expected Result:**
- Should delete document successfully
- Should return success message

**Verification:**
- Try to retrieve deleted document (should fail)
- Verify document no longer exists in search results

---

### 5. `clear_all` (DESTRUCTIVE)

**WARNING:** This will delete ALL documents from both collections!

**Test Command:**
```json
{}
```

**Expected Result:**
- Should delete all documents
- Should return success with deletion count

**Verification:**
- Run `get_stats` - should show 0 documents
- Only test in isolated/test environment

---

## Testing Instructions

1. **Start MCP Server** (if not already running)

2. **Test each tool in order:**
   - Use MCP tool calls for each test case above
   - Verify responses match expected results
   - Document any issues found

3. **Update MCP_TOOLS_VERIFICATION.md** with actual test results

---

## Test Results Template

```markdown
### Tool: [tool_name]
- **Tested:** [Date]
- **Status:** [PASS/FAIL/ISSUE]
- **Result:** [Description]
- **Issues:** [Any issues found]
```

---

**End of Test Plan**


