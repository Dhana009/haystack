# Unified Tool Naming Standard

## Goal
Create consistent tool names across Graphiti and Haystack MCP servers so a unified wrapper can route tool calls to the appropriate backend.

## Naming Convention
- Use **snake_case** for all tool names
- Use **descriptive verbs**: `add`, `search`, `get`, `delete`
- Prefix with server name when needed: `haystack_*` or `graphiti_*`
- Keep names semantic and consistent across backends

## Tool Name Mapping

### Graphiti Tools (Knowledge Graph)
- `add_memory` - Add episode/memory to knowledge graph
- `search_nodes` - Search for entities/nodes
- `search_facts` - Search for relationships/facts
- `get_episodes` - Get recent episodes
- `get_entity_edge` - Get specific relationship by UUID
- `delete_episode` - Delete episode by UUID
- `delete_entity_edge` - Delete relationship by UUID

### Haystack Tools (Vector Search) - PROPOSED RENAMING
Current → Proposed:
- `index_document` → `add_document` (matches `add_memory` pattern)
- `index_file` → `add_file` (matches `add_memory` pattern)
- `index_code` → `add_code` (matches `add_memory` pattern)
- `index_code_directory` → `add_code_directory` (matches `add_memory` pattern)
- `search` → `search_documents` (more specific, matches `search_nodes`/`search_facts` pattern)
- `get_stats` → `get_stats` (matches `get_stats` pattern)
- `delete_document` → `delete_document` (already consistent)

## Unified Tool Registry Pattern

The wrapper will:
1. Register all tools with consistent naming
2. Route calls to appropriate backend based on tool name
3. Provide unified interface for AI to choose tools

## Benefits
- AI can choose tools by semantic meaning, not backend
- Consistent naming makes tool selection more intuitive
- Easy to add more backends with same naming pattern
- Clear separation between knowledge graph and vector search operations

