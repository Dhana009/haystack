# Document Update Scenario - How It Works

## Your Scenario

1. **Initial State:**
   - Document with content (e.g., "Feature A, Feature B")
   - Code files embedded in Qdrant
   - Everything stored as active documents

2. **Changes Made:**
   - Documentation updated: Added Feature C, modified Feature A
   - Code changed significantly
   - Result: ~50% old content, ~50% new content

3. **Question:** What happens when you re-embed?

---

## How The System Works (After Level 2 Fix)

### Document-Level Updates (Not Partial/Incremental)

**Important:** The system works at the **document level**, not at the sentence/paragraph level.

### Step-by-Step Process

#### 1. **Document Identification**
When you add/update a document:
- System checks for existing document by `doc_id` (or `file_path`)
- If found → Proceeds to duplicate detection
- If not found → Stores as new (Level 4)

#### 2. **Duplicate Detection (4 Levels)**

**Level 1: Exact Duplicate**
- Same `content_hash` AND same `metadata_hash`
- **Action:** Skip (don't store again)

**Level 2: Content Update** ✅ (This is what happens in your scenario)
- Same `doc_id` BUT different `content_hash`
- **Action:** 
  - Mark old version as `status="deprecated"`
  - Store new version as `status="active"`
  - Both versions remain in database (for history)

**Level 3: Semantic Similarity** (Not implemented yet)
- High similarity but different hashes
- **Action:** Store with warning

**Level 4: New Content**
- Different `doc_id` or no match found
- **Action:** Store as new document

---

## What Happens in Your Scenario

### Scenario: Documentation Changed (50% old, 50% new)

**Example:**
- **Old Document:** "Feature A works like X. Feature B works like Y."
- **New Document:** "Feature A works like X (updated). Feature B works like Y. Feature C works like Z."

**Process:**

1. **Content Hash Calculation:**
   - Old content → `content_hash = "abc123..."`
   - New content → `content_hash = "xyz789..."` (different because content changed)

2. **Duplicate Detection:**
   - System finds existing document by `doc_id`
   - Compares hashes: `content_hash` differs
   - **Result:** Level 2 (Content Update) detected ✅

3. **Storage Action:**
   ```
   OLD VERSION:
   - status: "deprecated"
   - content: "Feature A works like X. Feature B works like Y."
   - content_hash: "abc123..."
   - Still in database (for history/versioning)
   
   NEW VERSION:
   - status: "active"
   - content: "Feature A works like X (updated). Feature B works like Y. Feature C works like Z."
   - content_hash: "xyz789..."
   - This is what gets retrieved in searches
   ```

### Important Points:

1. **No Partial Updates:**
   - The system doesn't merge 50% old + 50% new
   - It replaces the entire document
   - Old version is deprecated, new version is active

2. **Both Versions Stored:**
   - Old version: `status="deprecated"` (kept for history)
   - New version: `status="active"` (used in searches)
   - You can query version history if needed

3. **Search Behavior:**
   - By default, searches only return `status="active"` documents
   - Old deprecated versions are hidden from normal searches
   - But they're still in the database (for version history)

4. **Embeddings:**
   - Old version: Has old embeddings (still in Qdrant)
   - New version: Gets new embeddings generated
   - Both embeddings exist, but only active version is searched

---

## Code Changes Scenario

### Scenario: Code File Changed

**Example:**
- **Old Code:** `function calculate() { return a + b; }`
- **New Code:** `function calculate() { return a * b; }` (logic changed)

**Process:**

1. **File Path Check:**
   - System finds existing code by `file_path`
   - Same file path → Proceeds to duplicate detection

2. **Content Hash:**
   - Old code → `content_hash = "old123..."`
   - New code → `content_hash = "new456..."` (different)

3. **Result:**
   - Level 2 (Content Update) detected
   - Old code version → `status="deprecated"`
   - New code version → `status="active"`

---

## What About "50% Old, 50% New"?

### The System Doesn't Do Partial Merges

**What You Might Expect:**
- System identifies which 50% is old (keep it)
- System identifies which 50% is new (add it)
- Merge them intelligently

**What Actually Happens:**
- System treats entire document as one unit
- If content changed (even 1%) → Different `content_hash`
- Old version deprecated, new version stored
- **No intelligent merging or partial updates**

### Why?

1. **Content Hash is All-or-Nothing:**
   - Hash of entire document content
   - Any change → Different hash
   - Can't detect "which parts changed"

2. **Document-Level Versioning:**
   - Designed for document versioning, not incremental updates
   - Keeps full history of each version
   - You can query old versions if needed

3. **Semantic Search:**
   - Embeddings capture semantic meaning of entire document
   - Partial updates would require re-embedding anyway
   - Full document replacement is simpler and more reliable

---

## How to Test This

### Test Scenario 1: Documentation Update

1. **Add Initial Document:**
   ```
   doc_id: "test_doc_001"
   content: "Feature A works like X. Feature B works like Y."
   ```

2. **Update Document:**
   ```
   doc_id: "test_doc_001" (same)
   content: "Feature A works like X (updated). Feature B works like Y. Feature C works like Z."
   ```

3. **Expected Result:**
   - Level 2 detected
   - Old version: `status="deprecated"`
   - New version: `status="active"`
   - Search returns only new version

### Test Scenario 2: Code Update

1. **Add Initial Code:**
   ```
   file_path: "src/calculator.js"
   content: "function add(a, b) { return a + b; }"
   ```

2. **Update Code:**
   ```
   file_path: "src/calculator.js" (same)
   content: "function add(a, b) { return a * b; }" // Logic changed
   ```

3. **Expected Result:**
   - Level 2 detected
   - Old version: `status="deprecated"`
   - New version: `status="active"`

---

## Limitations & Considerations

### What the System Does:
✅ Detects when same document is updated
✅ Deprecates old version
✅ Stores new version as active
✅ Keeps version history
✅ Only searches active versions

### What the System Doesn't Do:
❌ Partial/incremental updates
❌ Intelligent merging of old + new content
❌ Detecting "which parts changed"
❌ Keeping only changed parts

### If You Need Partial Updates:

You would need to:
1. Split documents into smaller chunks (e.g., by section)
2. Each chunk has its own `doc_id`
3. Update only changed chunks
4. This requires a different architecture

---

## Summary

**Your Scenario:**
- 50% old content + 50% new content
- **Result:** Entire document replaced
- Old version deprecated, new version active
- Both versions in database (old for history, new for search)

**Key Takeaway:**
- System works at **document level**, not **content level**
- Any content change → Full document replacement
- Version history is preserved (old versions marked deprecated)

