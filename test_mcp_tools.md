# MCP Tools Testing Plan

## Tools to Test

### 1. Backup & Restore Tools
- `create_backup` - Create local backup
- `restore_backup` - Restore from backup
- `list_backups` - List available backups

### 2. Audit Tools
- `audit_storage_integrity` - Audit storage integrity with source directory comparison

## Test Scenarios

### Test 1: Create Backup
```json
{
  "backup_directory": "./backups",
  "include_embeddings": false
}
```

### Test 2: List Backups
```json
{
  "backup_directory": "./backups"
}
```

### Test 3: Audit Storage Integrity (without source directory)
```json
{}
```

### Test 4: Audit Storage Integrity (with source directory)
```json
{
  "source_directory": "D:\\planning\\haystack",
  "recursive": true,
  "file_extensions": [".py", ".md"]
}
```

## Expected Results

1. **create_backup**: Should create a backup directory with documents.json, metadata.json, and manifest.json
2. **list_backups**: Should return list of available backups
3. **audit_storage_integrity** (no source): Should return quality check results
4. **audit_storage_integrity** (with source): Should compare stored documents with source files


