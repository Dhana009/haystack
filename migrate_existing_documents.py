"""
Migration Script for Adding RULE 3 Metadata to Existing Documents.

This script migrates existing documents in Qdrant to include RULE 3 compliant metadata:
- hash_content: SHA256 hash of normalized content
- doc_id: Stable logical document ID
- version: Version string (timestamp-based if missing)
- category: Document category (extracted or defaulted to "other")
- file_path: File path if available
- file_hash: Hash of source file if file_path exists

Usage:
    python migrate_existing_documents.py [--backup-dir ./backups] [--dry-run] [--collection haystack_mcp]
"""
import os
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import hashlib

from haystack.dataclasses.document import Document
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from haystack.components.embedders import SentenceTransformersDocumentEmbedder

from deduplication_service import normalize_content, generate_content_fingerprint
from metadata_service import build_metadata_schema, VALID_CATEGORIES
from verification_service import verify_content_quality, bulk_verify_category
from bulk_operations_service import export_documents, update_metadata_by_filter
from backup_restore_service import create_backup


def get_all_documents(
    document_store: QdrantDocumentStore,
    collection_name: Optional[str] = None
) -> List[Document]:
    """
    Retrieve all documents from a Qdrant collection.
    
    Args:
        document_store: QdrantDocumentStore instance
        collection_name: Optional collection name
        
    Returns:
        List of all Document objects
    """
    all_documents = []
    
    try:
        # Use filter_documents with no filters to get all documents
        # Note: This may need pagination for very large collections
        documents = document_store.filter_documents(filters=None)
        all_documents.extend(documents)
    except Exception as e:
        print(f"Warning: Failed to retrieve some documents: {e}")
    
    return all_documents


def generate_migration_metadata(
    doc: Document,
    existing_meta: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Generate RULE 3 compliant metadata for an existing document.
    
    Args:
        doc: Document object
        existing_meta: Existing metadata dictionary
        
    Returns:
        Dictionary with new metadata fields to add
    """
    content = doc.content or ""
    
    # Generate content hash
    normalized_content = normalize_content(content)
    hash_content = hashlib.sha256(normalized_content.encode('utf-8')).hexdigest()
    
    # Extract or generate doc_id
    doc_id = (
        existing_meta.get('doc_id') or
        existing_meta.get('id') or
        existing_meta.get('file_path') or
        f"doc_{hash_content[:16]}"
    )
    
    # Extract or generate file_path
    file_path = (
        existing_meta.get('file_path') or
        existing_meta.get('path') or
        None
    )
    
    # Generate file_hash if file_path exists and file is accessible
    file_hash = None
    if file_path:
        try:
            path = Path(file_path)
            if path.exists() and path.is_file():
                file_content = path.read_bytes()
                file_hash = hashlib.sha256(file_content).hexdigest()
        except Exception:
            # File not accessible, leave file_hash as None
            pass
    
    # Extract or assign category
    category = existing_meta.get('category', 'other')
    if category not in VALID_CATEGORIES:
        # Try to infer category from other metadata
        if 'file_path' in existing_meta or 'path' in existing_meta:
            category = 'project_rule'
        elif 'source' in existing_meta and existing_meta['source'] == 'generated':
            category = 'design_doc'
        else:
            category = 'other'
    
    # Extract or generate version
    version = existing_meta.get('version')
    if not version:
        # Use created_at if available, otherwise use current timestamp
        created_at = existing_meta.get('created_at')
        if created_at:
            version = created_at
        else:
            version = datetime.utcnow().isoformat() + 'Z'
    
    # Extract other metadata
    source = existing_meta.get('source', 'manual')
    tags = existing_meta.get('tags', [])
    if not isinstance(tags, list):
        tags = []
    
    # Build metadata for fingerprinting (use existing metadata as base)
    metadata_for_fingerprint = {
        'doc_id': doc_id,
        'category': category,
        'file_path': file_path,
        'source': source,
        'tags': tags
    }
    
    # Generate fingerprint to get metadata_hash
    fingerprint = generate_content_fingerprint(content, metadata_for_fingerprint)
    
    # Build new metadata fields to add
    new_metadata = {
        'hash_content': hash_content,
        'content_hash': hash_content,  # Alias for backward compatibility
        'doc_id': doc_id,
        'category': category,
        'version': version,
        'metadata_hash': fingerprint['metadata_hash'],
        'source': source,
        'repo': existing_meta.get('repo', 'qdrant_haystack'),
        'status': existing_meta.get('status', 'active'),
        'tags': tags
    }
    
    # Add file_path and file_hash if available
    if file_path:
        new_metadata['file_path'] = file_path
        new_metadata['path'] = file_path  # Alias
    
    if file_hash:
        new_metadata['hash_file'] = file_hash
    
    # Add timestamps if missing
    if 'created_at' not in existing_meta:
        new_metadata['created_at'] = datetime.utcnow().isoformat() + 'Z'
    
    new_metadata['updated_at'] = datetime.utcnow().isoformat() + 'Z'
    
    return new_metadata


def migrate_documents(
    document_store: QdrantDocumentStore,
    code_document_store: Optional[QdrantDocumentStore] = None,
    dry_run: bool = False,
    batch_size: int = 100
) -> Dict[str, Any]:
    """
    Migrate all documents to include RULE 3 compliant metadata.
    
    Args:
        document_store: Main QdrantDocumentStore instance
        code_document_store: Optional code QdrantDocumentStore instance
        dry_run: If True, don't actually update documents
        batch_size: Number of documents to process per batch
        
    Returns:
        Dictionary with migration results
    """
    results = {
        'status': 'success',
        'total_documents': 0,
        'migrated_count': 0,
        'failed_count': 0,
        'skipped_count': 0,
        'errors': [],
        'categories': {},
        'quality_scores': {}
    }
    
    all_documents = []
    
    # Get documents from main collection
    print("Retrieving documents from main collection...")
    main_docs = get_all_documents(document_store)
    all_documents.extend(main_docs)
    print(f"Found {len(main_docs)} documents in main collection")
    
    # Get documents from code collection if provided
    if code_document_store:
        print("Retrieving documents from code collection...")
        code_docs = get_all_documents(code_document_store)
        all_documents.extend(code_docs)
        print(f"Found {len(code_docs)} documents in code collection")
    
    results['total_documents'] = len(all_documents)
    
    if not all_documents:
        print("No documents found to migrate.")
        return results
    
    # Process documents in batches
    print(f"\nProcessing {len(all_documents)} documents in batches of {batch_size}...")
    
    for i in range(0, len(all_documents), batch_size):
        batch = all_documents[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(all_documents) + batch_size - 1) // batch_size
        
        print(f"\nProcessing batch {batch_num}/{total_batches} ({len(batch)} documents)...")
        
        # Group documents by category for batch updates
        documents_by_category = {}
        
        for doc in batch:
            try:
                existing_meta = doc.meta or {}
                
                # Generate new metadata
                new_metadata = generate_migration_metadata(doc, existing_meta)
                category = new_metadata['category']
                
                # Track category statistics
                if category not in results['categories']:
                    results['categories'][category] = {
                        'total': 0,
                        'migrated': 0,
                        'failed': 0
                    }
                results['categories'][category]['total'] += 1
                
                # Group by category for batch updates
                if category not in documents_by_category:
                    documents_by_category[category] = []
                documents_by_category[category].append({
                    'doc': doc,
                    'new_metadata': new_metadata
                })
                
            except Exception as e:
                results['failed_count'] += 1
                results['errors'].append({
                    'document_id': doc.id,
                    'error': str(e),
                    'type': type(e).__name__
                })
                print(f"  Error processing document {doc.id}: {e}")
        
        # Update documents by category in batches
        if not dry_run:
            for category, doc_list in documents_by_category.items():
                try:
                    # Create filter for documents in this category batch
                    doc_ids = [item['doc'].id for item in doc_list]
                    
                    # Update each document individually
                    # Each document needs different metadata values, so we update individually
                    from update_service import update_document_metadata
                    
                    for item in doc_list:
                        doc = item['doc']
                        new_metadata = item['new_metadata']
                        
                        try:
                            # Update metadata for this specific document
                            update_result = update_document_metadata(
                                document_store,
                                str(doc.id),
                                new_metadata
                            )
                            
                            if update_result.get('status') == 'success':
                                results['migrated_count'] += 1
                                results['categories'][category]['migrated'] += 1
                            else:
                                results['failed_count'] += 1
                                results['categories'][category]['failed'] += 1
                                results['errors'].append({
                                    'document_id': doc.id,
                                    'error': update_result.get('error', 'Unknown error'),
                                    'category': category
                                })
                        
                        except Exception as e:
                            results['failed_count'] += 1
                            results['categories'][category]['failed'] += 1
                            results['errors'].append({
                                'document_id': doc.id,
                                'error': str(e),
                                'type': type(e).__name__,
                                'category': category
                            })
                
                except Exception as e:
                    print(f"  Error updating batch for category {category}: {e}")
                    results['failed_count'] += len(doc_list)
        else:
            # Dry run - just count
            for category, doc_list in documents_by_category.items():
                results['migrated_count'] += len(doc_list)
                results['categories'][category]['migrated'] += len(doc_list)
    
    # Verify migrated documents
    if not dry_run and results['migrated_count'] > 0:
        print("\nVerifying migrated documents...")
        for category in results['categories'].keys():
            if results['categories'][category]['migrated'] > 0:
                try:
                    verify_result = bulk_verify_category(
                        document_store,
                        code_document_store,
                        category=category,
                        max_documents=100  # Sample verification
                    )
                    results['quality_scores'][category] = {
                        'average_score': verify_result.get('average_quality_score', 0),
                        'pass_rate': verify_result.get('pass_rate', 0)
                    }
                except Exception as e:
                    print(f"  Warning: Failed to verify category {category}: {e}")
    
    return results


def generate_migration_report(
    results: Dict[str, Any],
    output_file: Optional[str] = None
) -> str:
    """
    Generate a migration report.
    
    Args:
        results: Migration results dictionary
        output_file: Optional file path to save report
        
    Returns:
        Report text
    """
    report_lines = [
        "=" * 80,
        "MIGRATION REPORT",
        "=" * 80,
        f"Generated: {datetime.utcnow().isoformat()}Z",
        "",
        "SUMMARY",
        "-" * 80,
        f"Total Documents: {results['total_documents']}",
        f"Successfully Migrated: {results['migrated_count']}",
        f"Failed: {results['failed_count']}",
        f"Success Rate: {(results['migrated_count'] / results['total_documents'] * 100) if results['total_documents'] > 0 else 0:.2f}%",
        "",
        "BY CATEGORY",
        "-" * 80,
    ]
    
    for category, stats in results['categories'].items():
        report_lines.append(f"{category}:")
        report_lines.append(f"  Total: {stats['total']}")
        report_lines.append(f"  Migrated: {stats['migrated']}")
        report_lines.append(f"  Failed: {stats['failed']}")
        if category in results.get('quality_scores', {}):
            score_info = results['quality_scores'][category]
            report_lines.append(f"  Average Quality Score: {score_info['average_score']:.3f}")
            report_lines.append(f"  Pass Rate: {score_info['pass_rate']:.2f}%")
        report_lines.append("")
    
    if results['errors']:
        report_lines.extend([
            "ERRORS",
            "-" * 80,
        ])
        for error in results['errors'][:20]:  # Show first 20 errors
            report_lines.append(f"Document ID: {error.get('document_id', 'unknown')}")
            report_lines.append(f"  Error: {error.get('error', 'Unknown error')}")
            if 'category' in error:
                report_lines.append(f"  Category: {error['category']}")
            report_lines.append("")
        
        if len(results['errors']) > 20:
            report_lines.append(f"... and {len(results['errors']) - 20} more errors")
            report_lines.append("")
    
    report_lines.extend([
        "RECOMMENDATIONS",
        "-" * 80,
    ])
    
    if results['failed_count'] > 0:
        report_lines.append(f"- Review {results['failed_count']} failed migrations")
        report_lines.append("- Check error log for details")
    
    if results.get('quality_scores'):
        low_quality_categories = [
            cat for cat, scores in results['quality_scores'].items()
            if scores.get('average_score', 1.0) < 0.8
        ]
        if low_quality_categories:
            report_lines.append(f"- Review quality issues in categories: {', '.join(low_quality_categories)}")
    
    report_lines.append("- Run verification tools to check migrated documents")
    report_lines.append("- Consider re-running migration for failed documents")
    
    report_text = "\n".join(report_lines)
    
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report_text)
        print(f"\nReport saved to: {output_file}")
    
    return report_text


def main():
    """Main migration function."""
    parser = argparse.ArgumentParser(
        description="Migrate existing Qdrant documents to include RULE 3 compliant metadata"
    )
    parser.add_argument(
        '--backup-dir',
        default='./backups',
        help='Directory for backups (default: ./backups)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Perform a dry run without updating documents'
    )
    parser.add_argument(
        '--collection',
        default=None,
        help='Collection name (default: from QDRANT_COLLECTION env var)'
    )
    parser.add_argument(
        '--code-collection',
        default=None,
        help='Code collection name (optional)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Batch size for processing (default: 100)'
    )
    parser.add_argument(
        '--skip-backup',
        action='store_true',
        help='Skip creating backup before migration'
    )
    
    args = parser.parse_args()
    
    # Check environment variables
    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    collection_name = args.collection or os.getenv("QDRANT_COLLECTION", "haystack_mcp")
    
    if not qdrant_url or not qdrant_api_key:
        print("Error: QDRANT_URL and QDRANT_API_KEY environment variables must be set")
        sys.exit(1)
    
    print("=" * 80)
    print("MIGRATION SCRIPT - Adding RULE 3 Metadata to Existing Documents")
    print("=" * 80)
    print(f"Collection: {collection_name}")
    print(f"Dry Run: {args.dry_run}")
    print(f"Batch Size: {args.batch_size}")
    print("")
    
    try:
        # Initialize document store
        from haystack.utils import Secret
        from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
        
        document_store = QdrantDocumentStore(
            url=qdrant_url,
            index=collection_name,
            embedding_dim=384,
            api_key=Secret.from_token(qdrant_api_key),
            return_embedding=True
        )
        
        code_document_store = None
        if args.code_collection:
            code_document_store = QdrantDocumentStore(
                url=qdrant_url,
                index=args.code_collection,
                embedding_dim=384,
                api_key=Secret.from_token(qdrant_api_key),
                return_embedding=True
            )
        
        # Create backup before migration
        if not args.skip_backup and not args.dry_run:
            print("Creating backup before migration...")
            backup_result = create_backup(
                document_store,
                backup_directory=args.backup_dir,
                include_embeddings=False
            )
            if backup_result.get('status') == 'success':
                print(f"Backup created: {backup_result.get('backup_path')}")
            else:
                print(f"Warning: Backup failed: {backup_result.get('error')}")
                response = input("Continue without backup? (yes/no): ")
                if response.lower() != 'yes':
                    print("Migration cancelled.")
                    sys.exit(1)
        
        # Run migration
        print("\nStarting migration...")
        results = migrate_documents(
            document_store,
            code_document_store,
            dry_run=args.dry_run,
            batch_size=args.batch_size
        )
        
        # Generate report
        print("\n" + "=" * 80)
        report = generate_migration_report(results)
        print(report)
        
        # Save report to file
        report_file = f"migration_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
        generate_migration_report(results, output_file=report_file)
        
        if args.dry_run:
            print("\n" + "=" * 80)
            print("DRY RUN COMPLETE - No documents were modified")
            print("=" * 80)
        else:
            print("\n" + "=" * 80)
            print("MIGRATION COMPLETE")
            print("=" * 80)
    
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

