# Level 2 Update Detection Fix - Plan & Research

## Issue Summary

**Problem:** `check_duplicate_level()` fails to detect Level 2 (content update) when documents have:
- Same `doc_id`
- Different `content_hash`
- Different `metadata_hash` (due to metadata changes)

**Current Behavior:** Detected as Level 4 (new content) instead of Level 2 (update)

**Impact:** Multiple active versions stored instead of deprecating old versions

---

## Research Findings

### 1. Current Implementation Analysis

#### `check_duplicate_level()` Function (deduplication_service.py:122-189)
- **Current Level 2 Check:** Only checks `metadata_hash` match + `content_hash` mismatch
- **Missing:** Check for `doc_id` match + `content_hash` mismatch
- **Function Signature:** `check_duplicate_level(fingerprint, existing_docs)` - no `doc_id` parameter

#### Metadata Hash Calculation (metadata_service.py:148-152)
```python
# Excludes: 'created_at', 'updated_at', 'status', 'version'
metadata_for_hash = {k: v for k, v in metadata.items() 
                    if k not in ['created_at', 'updated_at', 'status', 'version']}
```
- If ANY other metadata field changes (e.g., `tags`, `file_path`, `source`), `metadata_hash` will differ
- This causes Level 2 detection to fail

#### Call Sites (mcp_haystack_server.py)
- Line 784: `add_document` tool
- Line 930: `add_code` tool  
- Line 1137: `add_code_directory` tool

**Key Finding:** All call sites:
1. Query by `doc_id` first (using `query_by_doc_id()`)
2. Have `doc_id` available in scope
3. Pass `existing_docs` (which contain documents with matching `doc_id`)
4. BUT: Don't pass `doc_id` to `check_duplicate_level()`

### 2. Root Cause

**Primary Issue:** Level 2 detection relies solely on `metadata_hash` matching, which fails when:
- Metadata fields change (e.g., tags, file_path, source, additional metadata)
- Even though `doc_id` matches (indicating it's the same logical document)

**Secondary Issue:** `doc_id` is available at call sites but not passed to the deduplication function

### 3. Solution Options

#### Option 1: Add `doc_id` Parameter to `check_duplicate_level()` ✅ RECOMMENDED
**Pros:**
- Clean, explicit parameter
- Maintains function signature clarity
- Easy to test
- Follows existing pattern (fingerprint parameter)

**Cons:**
- Requires updating function signature
- Requires updating all 3 call sites

**Implementation:**
```python
def check_duplicate_level(
    fingerprint: Dict[str, str],
    existing_docs: List[Document],
    doc_id: Optional[str] = None  # NEW parameter
) -> Tuple[int, Optional[Document], Optional[str]]:
    # ...
    # Level 2: Check for content update
    # Case 1: Same doc_id but different content_hash (document update)
    # Case 2: Same metadata_hash but different content_hash (metadata-based update)
    for doc in existing_docs:
        doc_meta = doc.meta or {}
        doc_metadata_hash = doc_meta.get('metadata_hash')
        doc_content_hash = doc_meta.get('hash_content') or doc_meta.get('content_hash')
        doc_doc_id = doc_meta.get('doc_id')
        
        # Case 1: Same doc_id + different content_hash → Level 2 (update)
        if doc_id and doc_doc_id == doc_id and doc_content_hash != content_hash:
            return (
                DUPLICATE_LEVEL_UPDATE,
                doc,
                f"Content update: same doc_id ({doc_id}) but different content_hash"
            )
        
        # Case 2: Same metadata_hash + different content_hash → Level 2 (update)
        if doc_metadata_hash == metadata_hash and doc_content_hash != content_hash:
            return (
                DUPLICATE_LEVEL_UPDATE,
                doc,
                f"Content update: same metadata_hash ({metadata_hash[:8]}...) but different content_hash"
            )
```

#### Option 2: Check `doc_id` from `existing_docs` Without Parameter
**Pros:**
- No function signature change
- Less call site updates

**Cons:**
- Less explicit
- If multiple docs in list, which `doc_id` to check?
- Assumes all docs in list have same `doc_id` (not guaranteed)

**Not Recommended:** Too implicit and error-prone

#### Option 3: Include `doc_id` in Fingerprint
**Pros:**
- No function signature change

**Cons:**
- Mixes concerns (fingerprint is for content/metadata hashing)
- `doc_id` is not a hash/checksum
- Breaks abstraction

**Not Recommended:** Violates separation of concerns

---

## Recommended Fix: Option 1

### Implementation Plan

#### Phase 1: Update Deduplication Service
1. **File:** `deduplication_service.py`
2. **Function:** `check_duplicate_level()`
3. **Changes:**
   - Add `doc_id: Optional[str] = None` parameter
   - Add Level 2 check for same `doc_id` + different `content_hash` (before metadata_hash check)
   - Update docstring to document new parameter and behavior

#### Phase 2: Update Call Sites
1. **File:** `mcp_haystack_server.py`
2. **Locations:**
   - Line 784: `add_document` tool
   - Line 930: `add_code` tool
   - Line 1137: `add_code_directory` tool
3. **Changes:**
   - Pass `doc_id=doc_id` to `check_duplicate_level()`

#### Phase 3: Update Tests
1. **File:** `test/test_deduplication_service.py`
2. **Add Test Cases:**
   - Test Level 2 detection with same `doc_id` + different `content_hash`
   - Test Level 2 detection with same `doc_id` + different `content_hash` + different `metadata_hash`
   - Test backward compatibility (works without `doc_id` parameter)

#### Phase 4: Integration Testing
1. Test end-to-end update scenarios:
   - Add document with `doc_id="test_001"`
   - Update same document with different content (same `doc_id`)
   - Verify Level 2 detection
   - Verify old version deprecated
   - Verify new version stored as active

---

## Detailed Implementation Steps

### Step 1: Modify `check_duplicate_level()` Function

**File:** `deduplication_service.py`
**Lines:** 122-189

**Changes:**
1. Add `doc_id: Optional[str] = None` to function signature
2. Add Level 2 check for `doc_id` match BEFORE `metadata_hash` check (priority)
3. Update docstring

**Priority Order:**
1. Level 1: Exact duplicate (same content_hash AND metadata_hash)
2. Level 2 Case 1: Same doc_id + different content_hash (NEW)
3. Level 2 Case 2: Same metadata_hash + different content_hash (existing)
4. Level 3: Semantic similarity (future)
5. Level 4: New content

### Step 2: Update Function Call Sites

**File:** `mcp_haystack_server.py`

**Location 1: `add_document` tool (around line 784)**
```python
level, matching_doc, reason = check_duplicate_level(fingerprint, existing_docs, doc_id=doc_id)
```

**Location 2: `add_code` tool (around line 930)**
```python
level, matching_doc, reason = check_duplicate_level(fingerprint, existing_docs, doc_id=doc_id)
```

**Location 3: `add_code_directory` tool (around line 1137)**
```python
level, matching_doc, reason = check_duplicate_level(fingerprint, existing_docs, doc_id=doc_id)
```

### Step 3: Add Test Cases

**File:** `test/test_deduplication_service.py`

**New Test Cases:**
1. `test_level_2_content_update_same_doc_id()` - Test doc_id-based Level 2 detection
2. `test_level_2_content_update_same_doc_id_different_metadata_hash()` - Test doc_id detection even when metadata_hash differs
3. `test_level_2_backward_compatibility()` - Test function works without doc_id parameter

---

## Testing Strategy

### Unit Tests
- Test `check_duplicate_level()` with and without `doc_id` parameter
- Test all duplicate levels still work correctly
- Test edge cases (None doc_id, empty doc_id, etc.)

### Integration Tests
- Test complete document update flow:
  1. Add document → Level 4 (new)
  2. Update same doc_id → Level 2 (update)
  3. Verify old version deprecated
  4. Verify new version active

### Regression Tests
- Verify Level 1 (exact duplicate) still works
- Verify Level 2 (metadata_hash-based) still works
- Verify Level 4 (new content) still works

---

## Risk Assessment

### Low Risk
- Adding optional parameter maintains backward compatibility
- Existing tests should still pass
- No breaking changes to API

### Medium Risk
- Need to ensure all call sites updated
- Need to verify behavior with documents that don't have `doc_id` in metadata

### Mitigation
- Make `doc_id` parameter optional (default: None)
- Maintain existing behavior when `doc_id` is None
- Comprehensive test coverage

---

## Success Criteria

1. ✅ Same `doc_id` + different `content_hash` → Level 2 (update) detected
2. ✅ Old version marked as `deprecated`
3. ✅ New version stored as `active`
4. ✅ Backward compatibility maintained (works without `doc_id` parameter)
5. ✅ All existing tests pass
6. ✅ New tests added and passing

---

## Estimated Effort

- **Implementation:** 2-3 hours
- **Testing:** 1-2 hours
- **Review & Refinement:** 1 hour
- **Total:** 4-6 hours

---

## Next Steps

1. Review and approve this plan
2. Implement Phase 1 (deduplication service)
3. Implement Phase 2 (call sites)
4. Implement Phase 3 (tests)
5. Run integration tests
6. Code review
7. Merge and deploy

