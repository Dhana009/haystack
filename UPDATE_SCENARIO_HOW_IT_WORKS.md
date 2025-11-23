# How Document Updates Work - Your Scenario Explained

## Your Scenario

1. **Initial State:**
   - Document: "Feature A works like X. Feature B works like Y."
   - Code: `function calculate() { return a + b; }`
   - Both embedded in Qdrant DB

2. **Changes Made:**
   - Documentation: Added Feature C, modified Feature A
   - Code: Changed logic (e.g., `return a * b` instead of `return a + b`)
   - Result: ~50% old content, ~50% new content

3. **Question:** What happens when you re-embed?

---

## How It Works (Step-by-Step)

### Step 1: Document Identification

When you add/update a document:
```
System checks: "Does a document with this doc_id (or file_path) already exist?"
```

**For Documentation:**
- Checks by `doc_id` (e.g., "test_doc_001")
- If found → Proceeds to duplicate detection

**For Code:**
- Checks by `file_path` (e.g., "src/calculator.js")
- If found → Proceeds to duplicate detection

### Step 2: Content Hash Calculation

**Old Document:**
```
Content: "Feature A works like X. Feature B works like Y."
Content Hash: "abc123def456..." (SHA256 of normalized content)
```

**New Document:**
```
Content: "Feature A works like X (updated). Feature B works like Y. Feature C works like Z."
Content Hash: "xyz789ghi012..." (SHA256 of normalized content)
```

**Result:** Different hashes because content changed

### Step 3: Duplicate Detection (Level 2 - Content Update)

**Detection Logic:**
1. ✅ Same `doc_id` found → Document exists
2. ✅ Different `content_hash` → Content changed
3. ✅ **Result:** Level 2 (Content Update) detected

**What Happens:**
- System identifies this as an **update**, not a new document
- Old version will be deprecated
- New version will be stored as active

### Step 4: Deprecate Old Version

**Before storing new version:**
```
Old Document:
- status: "active" → "deprecated"
- content: "Feature A works like X. Feature B works like Y."
- content_hash: "abc123..."
- Still in database (for history)
```

### Step 5: Store New Version

**New Document:**
```
- status: "active"
- content: "Feature A works like X (updated). Feature B works like Y. Feature C works like Z."
- content_hash: "xyz789..."
- New embeddings generated
- This is what gets retrieved in searches
```

---

## What About "50% Old, 50% New"?

### ❌ The System Does NOT Do Partial Merges

**What You Might Think:**
- System identifies: "50% is old (keep it), 50% is new (add it)"
- Merges them intelligently
- Only updates the changed parts

**What Actually Happens:**
- System treats entire document as **one unit**
- If content changed (even 1%) → Different `content_hash`
- **Entire document is replaced**
- Old version deprecated, new version stored

### Why?

1. **Content Hash is All-or-Nothing:**
   ```
   Hash = SHA256(entire_document_content)
   Any change → Different hash
   Can't detect "which parts changed"
   ```

2. **Document-Level Versioning:**
   - Designed for **document versioning**, not **incremental updates**
   - Keeps full history of each version
   - You can query old versions if needed

3. **Embeddings:**
   - Embeddings capture semantic meaning of **entire document**
   - Partial updates would require re-embedding anyway
   - Full document replacement is simpler and more reliable

---

## Database State After Update

### Before Update:
```
Document 1:
- id: "doc_001"
- doc_id: "test_doc_001"
- status: "active"
- content: "Feature A works like X. Feature B works like Y."
- content_hash: "abc123..."
- embeddings: [0.1, 0.2, 0.3, ...]
```

### After Update:
```
Document 1 (OLD):
- id: "doc_001"
- doc_id: "test_doc_001"
- status: "deprecated" ← Changed!
- content: "Feature A works like X. Feature B works like Y."
- content_hash: "abc123..."
- embeddings: [0.1, 0.2, 0.3, ...] (still there)

Document 2 (NEW):
- id: "doc_002"
- doc_id: "test_doc_001" (same doc_id)
- status: "active" ← New active version
- content: "Feature A works like X (updated). Feature B works like Y. Feature C works like Z."
- content_hash: "xyz789..."
- embeddings: [0.4, 0.5, 0.6, ...] (new embeddings)
```

### Search Behavior:

**Default Search (status="active"):**
```
Returns: Document 2 (new version only)
Old version is hidden from normal searches
```

**Search with include_deprecated=true:**
```
Returns: Both Document 1 and Document 2
You can see version history
```

---

## Code Update Example

### Scenario: Code File Changed

**Old Code:**
```javascript
function calculate(a, b) {
    return a + b;  // Addition
}
```

**New Code:**
```javascript
function calculate(a, b) {
    return a * b;  // Multiplication (logic changed)
}
```

### Process:

1. **File Path Check:**
   - System finds existing code by `file_path: "src/calculator.js"`

2. **Content Hash:**
   - Old: `content_hash = "old123..."`
   - New: `content_hash = "new456..."` (different)

3. **Result:**
   - Level 2 (Content Update) detected
   - Old code version → `status="deprecated"`
   - New code version → `status="active"`

4. **Database State:**
   ```
   Old Version (deprecated):
   - file_path: "src/calculator.js"
   - status: "deprecated"
   - content: "return a + b;"
   
   New Version (active):
   - file_path: "src/calculator.js"
   - status: "active"
   - content: "return a * b;"
   ```

---

## Key Points

### ✅ What the System Does:

1. **Detects Updates:**
   - Same `doc_id` + different content → Update detected

2. **Version Management:**
   - Old version: `status="deprecated"`
   - New version: `status="active"`
   - Both versions kept in database

3. **Search Behavior:**
   - Default: Only active versions
   - Can query deprecated versions for history

4. **Embeddings:**
   - Old version: Old embeddings (still in Qdrant)
   - New version: New embeddings generated
   - Only active version is searched

### ❌ What the System Does NOT Do:

1. **Partial Updates:**
   - Doesn't merge 50% old + 50% new
   - Entire document is replaced

2. **Intelligent Merging:**
   - Doesn't detect "which parts changed"
   - Doesn't keep only changed parts

3. **Incremental Updates:**
   - Doesn't update only changed sections
   - Full document replacement

---

## Summary

**Your Scenario:**
- 50% old content + 50% new content
- **Result:** Entire document replaced
- Old version: `status="deprecated"` (kept for history)
- New version: `status="active"` (used in searches)
- Both versions in database

**Key Takeaway:**
- System works at **document level**, not **content level**
- Any content change → Full document replacement
- Version history is preserved (old versions marked deprecated)
- Searches return only active versions by default

