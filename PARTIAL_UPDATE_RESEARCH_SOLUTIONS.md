# Partial/Incremental Document Updates - Research & Solutions

## Problem Statement

**Current Limitation:**
- System works at **document level** (full document replacement)
- Any content change → Entire document replaced
- No way to detect/update only changed portions
- Scenario: 50% old content + 50% new content → Entire document replaced

**User Need:**
- Update only changed portions of documents
- Preserve unchanged chunks to avoid unnecessary re-embedding
- More efficient updates for large documents

---

## Research Findings

### 1. Industry Approaches

#### A. Chunk-Based Incremental Updates (Most Common)

**How It Works:**
1. Split documents into chunks (sections, paragraphs, or fixed-size)
2. Each chunk has its own ID (e.g., `doc_id:chunk_0`, `doc_id:chunk_1`)
3. Store chunks separately in vector database
4. When document updates:
   - Re-chunk the new version
   - Compare new chunks to existing chunks (by hash or content)
   - Update only changed chunks
   - Delete obsolete chunks

**Pros:**
- ✅ Only re-embed changed chunks (saves cost/time)
- ✅ Preserves unchanged chunks
- ✅ More granular updates
- ✅ Better for large documents

**Cons:**
- ❌ More complex architecture
- ❌ Need chunk management
- ❌ Need to track chunk relationships

**Tools That Use This:**
- Microsoft GraphRAG
- Milvus incremental updates
- Pinecone partial updates

#### B. Semantic Chunking with Similarity Detection

**How It Works:**
1. Use semantic chunking to split documents by meaning
2. When updating, compare new chunks to old chunks using embeddings
3. If similarity > threshold → Chunk unchanged (keep old embedding)
4. If similarity < threshold → Chunk changed (re-embed)

**Pros:**
- ✅ Detects semantic changes, not just text changes
- ✅ More intelligent than hash-based comparison
- ✅ Handles paraphrasing well

**Cons:**
- ❌ More expensive (requires embedding comparison)
- ❌ Requires similarity threshold tuning
- ❌ May miss subtle changes

**Research Sources:**
- Semantic chunking for RAG (Stack Overflow, Medium articles)
- Microsoft Azure RAG documentation

#### C. Hierarchical Document Structure

**How It Works:**
1. Store documents in hierarchical structure (sections → paragraphs → sentences)
2. Each level has its own ID and can be updated independently
3. Query can retrieve at any level (document, section, or paragraph)

**Pros:**
- ✅ Multi-level granularity
- ✅ Can update at section level
- ✅ Better context preservation

**Cons:**
- ❌ Most complex architecture
- ❌ Requires hierarchical indexing
- ❌ More storage overhead

**Haystack Support:**
- `HierarchicalDocumentSplitter` exists in Haystack
- Creates parent-child relationships between chunks

#### D. Document Diff/Merge Approach

**How It Works:**
1. Use diff algorithm (like Git) to identify changed portions
2. Only update changed sections
3. Merge old and new content intelligently

**Pros:**
- ✅ Precise change detection
- ✅ Can show exactly what changed
- ✅ Familiar approach (like version control)

**Cons:**
- ❌ Complex diff algorithms needed
- ❌ Doesn't work well with semantic changes
- ❌ Requires sophisticated merge logic

---

## Solution Options for Our System

### Option 1: Chunk-Based Incremental Updates (RECOMMENDED) ⭐

#### Architecture:

**1. Document Chunking:**
```python
# Split document into chunks
from haystack.components.preprocessors import RecursiveDocumentSplitter

splitter = RecursiveDocumentSplitter(
    separators=["\n\n", "\n", ". "],  # Natural boundaries
    chunk_size=512,  # tokens
    chunk_overlap=50
)

chunks = splitter.run([document])
# Each chunk gets: chunk_id = f"{doc_id}_chunk_{index}"
```

**2. Chunk Storage:**
```
Document: doc_id="test_001"
├── Chunk 0: chunk_id="test_001_chunk_0", content="Feature A works like X.", content_hash="abc..."
├── Chunk 1: chunk_id="test_001_chunk_1", content="Feature B works like Y.", content_hash="def..."
└── Chunk 2: chunk_id="test_001_chunk_2", content="Feature C works like Z.", content_hash="ghi..."
```

**3. Update Process:**
```
Old Document:
- Chunk 0: "Feature A works like X." (hash: abc)
- Chunk 1: "Feature B works like Y." (hash: def)

New Document:
- Chunk 0: "Feature A works like X (updated)." (hash: xyz) ← CHANGED
- Chunk 1: "Feature B works like Y." (hash: def) ← UNCHANGED
- Chunk 2: "Feature C works like Z." (hash: ghi) ← NEW

Action:
1. Keep Chunk 1 (hash matches)
2. Update Chunk 0 (hash changed)
3. Add Chunk 2 (new)
```

**4. Implementation Steps:**

**Step 1: Add Chunk Management**
- Create `chunk_service.py` for chunk operations
- Functions:
  - `chunk_document()` - Split document into chunks
  - `compare_chunks()` - Compare old vs new chunks
  - `update_chunks()` - Update only changed chunks

**Step 2: Modify Document Storage**
- When storing document:
  - Check if document should be chunked
  - If chunked → Store as multiple chunk documents
  - Each chunk has: `doc_id`, `chunk_id`, `chunk_index`, `chunk_hash`

**Step 3: Modify Update Logic**
- When updating document:
  - Re-chunk new version
  - Compare chunks (by `chunk_id` or `chunk_hash`)
  - For unchanged chunks: Keep old embedding
  - For changed chunks: Re-embed and update
  - For deleted chunks: Mark as deprecated
  - For new chunks: Embed and add

**Metadata Schema:**
```json
{
  "doc_id": "test_001",
  "chunk_id": "test_001_chunk_0",
  "chunk_index": 0,
  "chunk_hash": "abc123...",
  "parent_doc_id": "test_001",
  "is_chunk": true,
  "total_chunks": 3
}
```

#### Advantages:
- ✅ Only re-embed changed chunks (efficient)
- ✅ Preserves unchanged content
- ✅ Works with existing Haystack infrastructure
- ✅ Can leverage Haystack's `RecursiveDocumentSplitter`

#### Disadvantages:
- ❌ More complex than document-level
- ❌ Need chunk ID management
- ❌ Need to track chunk relationships

#### Estimated Effort: **Medium** (3-5 days)

---

### Option 2: Semantic Similarity-Based Detection

#### Architecture:

**1. Update Process:**
```python
# When updating document:
old_embedding = get_embedding(old_content)
new_embedding = get_embedding(new_content)
similarity = cosine_similarity(old_embedding, new_embedding)

if similarity > 0.95:  # 95% similar
    # Content mostly unchanged → Keep old embedding
    keep_old_embedding()
else:
    # Content changed → Re-embed
    re_embed(new_content)
```

**2. Implementation:**
- Use embedding similarity to detect changes
- If similarity high → Assume unchanged (no re-embedding)
- If similarity low → Re-embed

#### Advantages:
- ✅ Simple implementation
- ✅ Detects semantic changes
- ✅ No chunking needed

#### Disadvantages:
- ❌ Expensive (requires embedding comparison)
- ❌ Doesn't handle partial updates (still replaces entire document)
- ❌ May miss subtle changes
- ❌ Doesn't solve the "50% old, 50% new" problem

#### Estimated Effort: **Low** (1-2 days)  
#### Not Recommended: Doesn't solve partial update problem

---

### Option 3: Hybrid Approach (Chunking + Semantic Detection)

#### Architecture:

**1. Document Chunking:**
- Split document into semantic chunks (by section/paragraph)

**2. Change Detection:**
- Compare chunks using both:
  - Hash comparison (fast, exact)
  - Semantic similarity (for paraphrased content)

**3. Update Strategy:**
```
For each chunk:
  if hash_matches:
    keep_old_chunk()
  elif similarity > 0.95:
    keep_old_chunk()  # Minor paraphrase
  else:
    re_embed_and_update()
```

#### Advantages:
- ✅ Best of both worlds
- ✅ Handles exact matches (hash) and paraphrases (similarity)
- ✅ Most accurate change detection

#### Disadvantages:
- ❌ Most complex
- ❌ Requires both hash and similarity calculations
- ❌ Most expensive

#### Estimated Effort: **High** (5-7 days)

---

### Option 4: Metadata-Based Section Tracking

#### Architecture:

**1. Section-Level Tracking:**
- Document has sections (marked with headers, metadata)
- Each section has its own `section_id`
- Sections stored as separate documents with parent reference

**Example:**
```json
{
  "doc_id": "test_001",
  "section_id": "test_001_intro",
  "section_name": "Introduction",
  "parent_doc_id": "test_001",
  "section_index": 0,
  "content": "..."
}
```

**2. Update Process:**
- Update only changed sections
- Keep unchanged sections

#### Advantages:
- ✅ Natural boundaries (sections)
- ✅ Semantically meaningful chunks
- ✅ Easier to manage than arbitrary chunks

#### Disadvantages:
- ❌ Requires structured documents (sections)
- ❌ Doesn't work for unstructured text
- ❌ Need section extraction logic

#### Estimated Effort: **Medium** (3-4 days)

---

## Recommended Solution: **Option 1 - Chunk-Based Incremental Updates**

### Why This Approach?

1. **Solves the Problem:**
   - Handles "50% old, 50% new" scenario
   - Updates only changed portions
   - Preserves unchanged chunks

2. **Leverages Existing Tools:**
   - Haystack has `RecursiveDocumentSplitter`
   - Works with existing Qdrant/Haystack infrastructure
   - Can reuse existing deduplication logic

3. **Scalable:**
   - Works for documents of any size
   - Only re-embeds changed chunks
   - Efficient for large documents

4. **Practical:**
   - Clear implementation path
   - Well-documented approach
   - Used by industry leaders

---

## Implementation Plan

### Phase 1: Chunking Infrastructure

**1. Create Chunk Service** (`chunk_service.py`)
```python
def chunk_document(content, doc_id, chunk_size=512, chunk_overlap=50):
    """Split document into chunks with metadata."""
    pass

def compare_chunks(old_chunks, new_chunks):
    """Compare old and new chunks, identify changes."""
    pass

def generate_chunk_id(doc_id, chunk_index):
    """Generate stable chunk ID."""
    return f"{doc_id}_chunk_{chunk_index}"
```

**2. Modify Metadata Schema**
- Add `is_chunk: bool` field
- Add `chunk_id: str` field
- Add `chunk_index: int` field
- Add `parent_doc_id: str` field
- Add `total_chunks: int` field

**3. Add Chunk Storage**
- Store chunks as separate documents
- Each chunk has its own `doc_id` (= chunk_id)
- Track parent document relationship

### Phase 2: Update Logic

**1. Modify `add_document` Tool**
- Check if document should be chunked
- If chunked → Use chunk-based storage
- If not chunked → Use document-level storage (backward compatible)

**2. Implement Chunk Comparison**
- When updating chunked document:
  1. Re-chunk new version
  2. Compare old chunks vs new chunks (by chunk_id or hash)
  3. Identify: unchanged, changed, new, deleted

**3. Implement Incremental Update**
- Unchanged chunks: Keep old embedding
- Changed chunks: Re-embed and update
- New chunks: Embed and add
- Deleted chunks: Mark as deprecated

### Phase 3: Query Integration

**1. Chunk-Aware Search**
- Search returns chunk results
- Option to merge chunks or return separately
- Track which chunks belong to which document

**2. Document Reconstruction**
- Reconstruct full document from chunks if needed
- Maintain document-level view

---

## Code Structure

### New Files:

1. **`chunk_service.py`**
   - Chunk management functions
   - Chunk comparison logic
   - Chunk ID generation

2. **`chunk_update_service.py`**
   - Incremental update logic
   - Chunk diff algorithms
   - Update orchestration

### Modified Files:

1. **`mcp_haystack_server.py`**
   - Add chunking option to `add_document` tool
   - Add chunk-aware update logic
   - Add chunk management parameters

2. **`metadata_service.py`**
   - Add chunk metadata fields
   - Chunk metadata validation

3. **`deduplication_service.py`**
   - Chunk-level duplicate detection
   - Chunk hash comparison

---

## Configuration Options

### User Control:

```python
add_document(
    content="...",
    doc_id="test_001",
    chunking={
        "enabled": True,
        "chunk_size": 512,  # tokens
        "chunk_overlap": 50,
        "split_by": "paragraph"  # or "sentence", "word"
    }
)
```

### Default Behavior:
- **Backward Compatible:** If `chunking.enabled=False`, works as before (document-level)
- **New Feature:** If `chunking.enabled=True`, uses chunk-based incremental updates

---

## Testing Strategy

### Test Scenarios:

1. **Full Document Update**
   - All chunks changed → All re-embedded

2. **Partial Update (50% old, 50% new)**
   - Half chunks unchanged → Keep old embeddings
   - Half chunks changed → Re-embed changed chunks

3. **Single Chunk Update**
   - One chunk changed → Only that chunk re-embedded
   - Other chunks unchanged → Keep old embeddings

4. **Chunk Addition**
   - New chunk added → Only new chunk embedded
   - Existing chunks unchanged

5. **Chunk Deletion**
   - Chunk removed → Mark as deprecated
   - Other chunks unchanged

---

## Risk Assessment

### Low Risk:
- ✅ Backward compatible (opt-in feature)
- ✅ Existing functionality unchanged
- ✅ Can be tested incrementally

### Medium Risk:
- ⚠️ Chunk ID management complexity
- ⚠️ Need to handle chunk relationships
- ⚠️ Query logic changes

### Mitigation:
- Start with simple chunking (by paragraph)
- Add complexity gradually
- Comprehensive testing
- Documentation

---

## Success Criteria

1. ✅ Only changed chunks are re-embedded
2. ✅ Unchanged chunks preserve old embeddings
3. ✅ Chunk updates are atomic
4. ✅ Document-level queries still work
5. ✅ Backward compatible (existing documents work)
6. ✅ Performance improved for partial updates

---

## Estimated Timeline

- **Research & Design:** ✅ Complete
- **Phase 1 (Chunking Infrastructure):** 2-3 days
- **Phase 2 (Update Logic):** 2-3 days
- **Phase 3 (Query Integration):** 1-2 days
- **Testing & Refinement:** 1-2 days
- **Total:** 6-10 days

---

## Alternative: Keep Current System + Add Chunking Option

**Simpler Approach:**
- Keep document-level updates as default
- Add chunking as optional feature
- Users can enable chunking when needed
- Backward compatible

**Advantages:**
- ✅ Less risk
- ✅ Backward compatible
- ✅ Users can choose based on use case
- ✅ Simpler implementation

---

## Research Sources

1. **Microsoft GraphRAG:** Incremental updates with chunking
2. **Milvus Documentation:** Partial vector updates
3. **Pinecone:** Incremental index updates
4. **Perplexity Research:** Chunk-based incremental updates for RAG
5. **Haystack Documentation:** Document splitting and chunking
6. **Industry Best Practices:** Semantic chunking, hierarchical structures

---

## Recommendation

**Implement Option 1: Chunk-Based Incremental Updates**

- Solves the problem effectively
- Leverages existing Haystack tools
- Industry-proven approach
- Scalable and efficient
- Backward compatible

**Implementation Priority:**
1. Start with simple chunking (by paragraph/section)
2. Add incremental update logic
3. Test with real scenarios
4. Add advanced features (semantic similarity) later

