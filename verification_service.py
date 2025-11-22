"""
Verification Service for Qdrant/Haystack MCP Server.

Implements content quality checks, placeholder detection, hash verification,
and bulk verification operations per RULE 7.
"""
import hashlib
import re
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from haystack.dataclasses.document import Document
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore

from deduplication_service import normalize_content
from metadata_service import query_by_file_path, query_by_doc_id


# Placeholder patterns to detect incomplete content
PLACEHOLDER_PATTERNS = [
    r'\[Full content from file\.\.\.\]',
    r'\[Full content\.\.\.\]',
    r'\[\.\.\.\]',
    r'\[TODO:.*?\]',
    r'\[TBD:.*?\]',
    r'\[PLACEHOLDER:.*?\]',
    r'\[WRITE HERE\]',
    r'\[CONTENT TO BE ADDED\]',
    r'placeholder',
    r'will be stored',
    r'content will be',
    r'to be filled',
    r'to be added',
    r'to be completed',
]

# Minimum content length threshold (in characters)
MIN_CONTENT_LENGTH = 100

# Required metadata fields for quality check
REQUIRED_METADATA_FIELDS = ['doc_id', 'version', 'category', 'hash_content']


def detect_placeholders(content: str) -> Dict[str, any]:
    """
    Detect placeholder markers in content.
    
    Args:
        content: Document content to check
        
    Returns:
        Dictionary with:
        - has_placeholder: Boolean indicating if placeholders were found
        - placeholder_count: Number of placeholder patterns found
        - placeholder_types: List of placeholder types detected
        - placeholder_positions: List of (start, end) positions for each placeholder
    """
    if not content:
        return {
            'has_placeholder': False,
            'placeholder_count': 0,
            'placeholder_types': [],
            'placeholder_positions': []
        }
    
    placeholder_types = []
    placeholder_positions = []
    
    for pattern in PLACEHOLDER_PATTERNS:
        matches = list(re.finditer(pattern, content, re.IGNORECASE))
        if matches:
            pattern_name = pattern.replace('\\', '').replace('[', '').replace(']', '').replace('.*?', '')
            placeholder_types.append(pattern_name)
            for match in matches:
                placeholder_positions.append((match.start(), match.end()))
    
    return {
        'has_placeholder': len(placeholder_positions) > 0,
        'placeholder_count': len(placeholder_positions),
        'placeholder_types': list(set(placeholder_types)),
        'placeholder_positions': placeholder_positions
    }


def verify_hash_integrity(content: str, stored_hash: Optional[str]) -> Dict[str, any]:
    """
    Verify that content hash matches stored hash.
    
    Args:
        content: Document content
        stored_hash: Hash value stored in metadata
        
    Returns:
        Dictionary with:
        - hash_valid: Boolean indicating if hash matches
        - computed_hash: The computed hash from content
        - stored_hash: The stored hash value
        - match: Boolean indicating if hashes match
    """
    if not stored_hash:
        return {
            'hash_valid': False,
            'computed_hash': None,
            'stored_hash': None,
            'match': False,
            'error': 'No stored hash found in metadata'
        }
    
    # Normalize content before hashing (same as in deduplication)
    normalized_content = normalize_content(content)
    computed_hash = hashlib.sha256(normalized_content.encode('utf-8')).hexdigest()
    
    return {
        'hash_valid': computed_hash == stored_hash,
        'computed_hash': computed_hash,
        'stored_hash': stored_hash,
        'match': computed_hash == stored_hash
    }


def verify_content_quality(document: Document) -> Dict[str, any]:
    """
    Verify content quality of a document.
    
    Performs multiple checks:
    - Placeholder detection
    - Minimum length check
    - Metadata presence check
    - Hash integrity verification
    - Required metadata fields check
    
    Args:
        document: Document object to verify
        
    Returns:
        Dictionary with:
        - document_id: Document ID
        - quality_score: Score from 0.0 to 1.0
        - checks: Dictionary of individual check results
        - status: 'pass' or 'fail'
        - issues: List of issue descriptions
    """
    checks = {}
    issues = []
    
    # Check 1: Content exists
    content = document.content or ""
    checks['has_content'] = bool(content)
    if not checks['has_content']:
        issues.append("Document has no content")
    
    # Check 2: Minimum length
    checks['min_length'] = len(content) >= MIN_CONTENT_LENGTH
    if not checks['min_length']:
        issues.append(f"Content too short: {len(content)} characters (minimum: {MIN_CONTENT_LENGTH})")
    
    # Check 3: Placeholder detection
    placeholder_info = detect_placeholders(content)
    checks['no_placeholders'] = not placeholder_info['has_placeholder']
    if placeholder_info['has_placeholder']:
        issues.append(f"Found {placeholder_info['placeholder_count']} placeholder(s): {', '.join(placeholder_info['placeholder_types'])}")
    
    # Check 4: Metadata exists
    meta = document.meta or {}
    checks['has_metadata'] = bool(meta)
    if not checks['has_metadata']:
        issues.append("Document has no metadata")
    
    # Check 5: Required metadata fields
    missing_fields = []
    for field in REQUIRED_METADATA_FIELDS:
        if field not in meta or not meta[field]:
            missing_fields.append(field)
    checks['has_required_metadata'] = len(missing_fields) == 0
    if missing_fields:
        issues.append(f"Missing required metadata fields: {', '.join(missing_fields)}")
    
    # Check 6: File path (if applicable)
    checks['has_file_path'] = 'file_path' in meta or 'path' in meta
    if not checks['has_file_path'] and meta.get('category') in ['user_rule', 'project_rule', 'project_command']:
        issues.append("Document should have file_path but it's missing")
    
    # Check 7: Hash integrity
    stored_hash = meta.get('hash_content') or meta.get('content_hash')
    hash_verification = verify_hash_integrity(content, stored_hash)
    checks['hash_valid'] = hash_verification['hash_valid']
    if not hash_verification['hash_valid']:
        if hash_verification.get('error'):
            issues.append(f"Hash verification failed: {hash_verification['error']}")
        else:
            issues.append("Content hash mismatch - possible corruption")
    
    # Check 8: Status field
    checks['has_status'] = 'status' in meta
    if not checks['has_status']:
        issues.append("Document missing status field")
    elif meta.get('status') not in ['active', 'deprecated', 'draft']:
        issues.append(f"Invalid status value: {meta.get('status')}")
    
    # Calculate quality score (weighted average)
    # Critical checks have higher weight
    critical_checks = ['has_content', 'hash_valid', 'has_required_metadata']
    normal_checks = [k for k in checks.keys() if k not in critical_checks]
    
    critical_score = sum(checks[k] for k in critical_checks) / len(critical_checks) if critical_checks else 1.0
    normal_score = sum(checks[k] for k in normal_checks) / len(normal_checks) if normal_checks else 1.0
    
    # Weighted: 70% critical, 30% normal
    quality_score = (critical_score * 0.7) + (normal_score * 0.3)
    
    # Determine status
    status = 'pass' if quality_score >= 0.8 and len(issues) == 0 else 'fail'
    
    return {
        'document_id': document.id,
        'doc_id': meta.get('doc_id'),
        'quality_score': round(quality_score, 3),
        'checks': checks,
        'status': status,
        'issues': issues,
        'placeholder_info': placeholder_info,
        'hash_verification': hash_verification,
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    }


def bulk_verify_category(
    document_store: QdrantDocumentStore,
    code_document_store: Optional[QdrantDocumentStore] = None,
    category: str = None,
    max_documents: Optional[int] = None
) -> Dict[str, any]:
    """
    Verify all documents in a category.
    
    Args:
        document_store: QdrantDocumentStore instance (main collection)
        code_document_store: Optional QdrantDocumentStore instance (code collection)
        category: Category to verify
        max_documents: Maximum number of documents to verify (None = all)
        
    Returns:
        Dictionary with:
        - category: Category name
        - total: Total number of documents verified
        - passed: Number of documents that passed
        - failed: Number of documents that failed
        - average_quality_score: Average quality score
        - issues: List of failed document verifications
        - summary: Summary statistics
    """
    # Query all documents in category from both stores
    all_documents = []
    
    try:
        filters = {
            "operator": "AND",
            "conditions": [
                {"field": "meta.category", "operator": "==", "value": category}
            ]
        }
        docs_from_main = document_store.filter_documents(filters=filters)
        all_documents.extend(docs_from_main)
    except Exception as e:
        return {
            'category': category,
            'error': f"Failed to query documents from main store: {str(e)}",
            'total': 0,
            'passed': 0,
            'failed': 0
        }
    
    # Query from code store if provided
    if code_document_store:
        try:
            docs_from_code = code_document_store.filter_documents(filters=filters)
            all_documents.extend(docs_from_code)
        except Exception as e:
            # Log warning but continue with main store results
            pass
    
    documents = all_documents
    
    # Limit documents if specified
    if max_documents:
        documents = documents[:max_documents]
    
    # Verify each document
    results = []
    for doc in documents:
        result = verify_content_quality(doc)
        results.append(result)
    
    # Calculate statistics
    total = len(results)
    passed = sum(1 for r in results if r['status'] == 'pass')
    failed = total - passed
    average_score = sum(r['quality_score'] for r in results) / total if total > 0 else 0.0
    
    # Get failed documents
    failed_docs = [r for r in results if r['status'] == 'fail']
    
    # Count issues by type
    issue_counts = {}
    for result in failed_docs:
        for issue in result.get('issues', []):
            issue_type = issue.split(':')[0] if ':' in issue else issue
            issue_counts[issue_type] = issue_counts.get(issue_type, 0) + 1
    
    return {
        'category': category,
        'total': total,
        'passed': passed,
        'failed': failed,
        'pass_rate': round(passed / total * 100, 2) if total > 0 else 0.0,
        'average_quality_score': round(average_score, 3),
        'issues': failed_docs,
        'issue_counts': issue_counts,
        'summary': {
            'total_documents': total,
            'passed': passed,
            'failed': failed,
            'average_quality_score': round(average_score, 3),
            'top_issues': sorted(issue_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        },
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    }


def audit_storage_integrity(
    document_store: QdrantDocumentStore,
    source_directory: Optional[str] = None,
    code_document_store: Optional[QdrantDocumentStore] = None,
    recursive: bool = True,
    file_extensions: Optional[List[str]] = None
) -> Dict[str, any]:
    """
    Audit storage integrity by comparing stored documents with source files.
    
    Performs comprehensive integrity check:
    - Compares stored content with source files (if source_directory provided)
    - Detects missing files (files in source directory not stored)
    - Detects content mismatches (stored hash differs from source file hash)
    - Verifies content quality of stored documents
    - Calculates integrity score
    
    Args:
        document_store: QdrantDocumentStore instance (main collection)
        source_directory: Optional source directory to compare against
        code_document_store: Optional QdrantDocumentStore instance (code collection)
        recursive: Whether to scan source directory recursively (default: True)
        file_extensions: Optional list of file extensions to include (e.g., ['.md', '.txt'])
        
    Returns:
        Dictionary with audit results:
        - total_documents: Total documents in storage
        - total_files: Total files in source directory (if provided)
        - stored_files: Number of files that are stored
        - missing_files: List of files in source directory not stored
        - content_mismatches: List of files with hash mismatches
        - passed: Number of documents that passed quality checks
        - failed: Number of documents that failed quality checks
        - integrity_score: Overall integrity score (0.0 to 1.0)
        - issues: List of all issues found
        - issues_by_type: Issues grouped by type
    """
    from pathlib import Path
    from metadata_service import query_by_file_path
    from deduplication_service import normalize_content
    import hashlib
    
    # Get all stored documents
    try:
        all_documents = document_store.filter_documents(filters=None)
    except Exception:
        all_documents = []
    
    # Get documents from code collection if provided
    if code_document_store:
        try:
            code_documents = code_document_store.filter_documents(filters=None)
            all_documents.extend(code_documents)
        except Exception:
            pass
    
    # Build map of stored file paths to documents
    stored_file_paths = {}
    for doc in all_documents:
        meta = doc.meta or {}
        file_path = meta.get('file_path') or meta.get('path')
        if file_path:
            # Normalize path for comparison
            normalized_path = str(Path(file_path).resolve())
            stored_file_paths[normalized_path] = doc
            # Also store with original path for matching
            stored_file_paths[file_path] = doc
    
    # Verify each document's quality
    verification_results = []
    for doc in all_documents:
        result = verify_content_quality(doc)
        verification_results.append(result)
    
    # Calculate quality statistics
    total_docs = len(verification_results)
    passed = sum(1 for r in verification_results if r['status'] == 'pass')
    failed = total_docs - passed
    
    # Initialize results
    issues = []
    missing_files = []
    content_mismatches = []
    
    # If source_directory provided, compare with source files
    if source_directory:
        source_dir = Path(source_directory)
        if not source_dir.exists():
            issues.append({
                'type': 'source_directory_not_found',
                'severity': 'high',
                'message': f"Source directory not found: {source_directory}"
            })
        else:
            # Scan source directory for files
            source_files = []
            if recursive:
                pattern = "**/*" if not file_extensions else "**/*" + "|**/*".join(file_extensions)
                for ext in (file_extensions or [""]):
                    if ext:
                        source_files.extend(source_dir.rglob(f"*{ext}"))
                    else:
                        source_files.extend(source_dir.rglob("*"))
            else:
                source_files = [f for f in source_dir.iterdir() if f.is_file()]
            
            # Filter by extensions if specified
            if file_extensions:
                source_files = [f for f in source_files if f.suffix in file_extensions]
            
            # Remove directories from list
            source_files = [f for f in source_files if f.is_file()]
            
            # Compare each source file with stored documents
            for source_file in source_files:
                try:
                    # Normalize path for comparison
                    normalized_source_path = str(source_file.resolve())
                    relative_path = str(source_file.relative_to(source_dir))
                    
                    # Try multiple path variations for matching
                    path_variations = [
                        normalized_source_path,
                        relative_path,
                        str(source_file),
                        str(source_file.absolute())
                    ]
                    
                    stored_doc = None
                    matched_path = None
                    for path_var in path_variations:
                        if path_var in stored_file_paths:
                            stored_doc = stored_file_paths[path_var]
                            matched_path = path_var
                            break
                    
                    if not stored_doc:
                        # File not stored
                        missing_files.append({
                            'file_path': str(source_file),
                            'relative_path': relative_path,
                            'severity': 'high',
                            'issue': 'not_stored'
                        })
                        issues.append({
                            'type': 'missing_file',
                            'severity': 'high',
                            'file_path': str(source_file),
                            'relative_path': relative_path
                        })
                    else:
                        # File is stored - check content hash
                        try:
                            # Read source file content
                            source_content = source_file.read_text(encoding='utf-8')
                            
                            # Normalize and hash source content
                            normalized_source = normalize_content(source_content)
                            source_hash = hashlib.sha256(normalized_source.encode('utf-8')).hexdigest()
                            
                            # Get stored hash
                            stored_meta = stored_doc.meta or {}
                            stored_hash = stored_meta.get('hash_content') or stored_meta.get('content_hash')
                            
                            if stored_hash and stored_hash != source_hash:
                                # Content mismatch
                                content_mismatches.append({
                                    'file_path': str(source_file),
                                    'relative_path': relative_path,
                                    'stored_hash': stored_hash,
                                    'source_hash': source_hash,
                                    'document_id': stored_doc.id,
                                    'severity': 'high',
                                    'issue': 'content_mismatch'
                                })
                                issues.append({
                                    'type': 'content_mismatch',
                                    'severity': 'high',
                                    'file_path': str(source_file),
                                    'relative_path': relative_path,
                                    'document_id': stored_doc.id,
                                    'stored_hash': stored_hash[:16] + '...',
                                    'source_hash': source_hash[:16] + '...'
                                })
                        except Exception as e:
                            # Error reading or comparing file
                            issues.append({
                                'type': 'file_comparison_error',
                                'severity': 'medium',
                                'file_path': str(source_file),
                                'error': str(e)
                            })
                
                except Exception as e:
                    issues.append({
                        'type': 'file_scan_error',
                        'severity': 'medium',
                        'file_path': str(source_file) if 'source_file' in locals() else 'unknown',
                        'error': str(e)
                    })
    
    # Group issues by type
    issues_by_type = {}
    for issue in issues:
        issue_type = issue.get('type', 'Unknown')
        if issue_type not in issues_by_type:
            issues_by_type[issue_type] = []
        issues_by_type[issue_type].append(issue)
    
    # Calculate integrity score
    # Score = (stored_files - missing_files - mismatches) / total_files
    # If no source_directory, score is based on quality checks only
    total_files = 0
    if source_directory:
        source_dir = Path(source_directory)
        if source_dir.exists():
            # Recalculate source_files count for score
            source_files_list = []
            if recursive:
                if file_extensions:
                    for ext in file_extensions:
                        source_files_list.extend(source_dir.rglob(f"*{ext}"))
                else:
                    source_files_list.extend(source_dir.rglob("*"))
            else:
                source_files_list = [f for f in source_dir.iterdir() if f.is_file()]
            
            if file_extensions:
                source_files_list = [f for f in source_files_list if f.is_file() and f.suffix in file_extensions]
            else:
                source_files_list = [f for f in source_files_list if f.is_file()]
            
            total_files = len(source_files_list)
            stored_count = total_files - len(missing_files)
            matched_count = stored_count - len(content_mismatches)
            integrity_score = matched_count / total_files if total_files > 0 else 0.0
        else:
            # Source directory doesn't exist - base score on quality checks
            integrity_score = passed / total_docs if total_docs > 0 else 0.0
    else:
        # No source directory - base score on quality checks
        integrity_score = passed / total_docs if total_docs > 0 else 0.0
    
    return {
        'total_documents': total_docs,
        'total_files': total_files if source_directory else None,
        'stored_files': len(stored_file_paths),
        'missing_files': missing_files,
        'content_mismatches': content_mismatches,
        'passed': passed,
        'failed': failed,
        'integrity_score': round(integrity_score, 3),
        'issues': issues,
        'issues_by_type': issues_by_type,
        'failed_documents': [r for r in verification_results if r['status'] == 'fail'],
        'source_directory': source_directory,
        'timestamp': datetime.utcnow().isoformat() + 'Z'
    }

