"""
Backup and Restore Service for Qdrant/Haystack MCP Server.

Implements local backup and restore functionality for Qdrant collections.
Backs up to local JSON files and can restore from those files with verification.
"""
import json
import os
import sys
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime
import hashlib

from haystack.dataclasses.document import Document
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from bulk_operations_service import _get_qdrant_client
from verification_service import verify_content_quality


def _backup_collection(
    collection_name: str,
    backup_path: Path,
    include_embeddings: bool = False,
    filters: Optional[Dict[str, Any]] = None
) -> tuple[List[Dict[str, Any]], int]:
    """
    Helper function to backup a single collection.
    
    Returns:
        Tuple of (documents_data, document_count)
    """
    client = _get_qdrant_client()
    documents_data = []
    offset = None
    total_count = 0
    
    # Convert Haystack filter to Qdrant filter if provided
    qdrant_filter = None
    if filters:
        from bulk_operations_service import _convert_haystack_filter_to_qdrant
        qdrant_filter = _convert_haystack_filter_to_qdrant(filters)
    
    while True:
        # Scroll through collection
        scroll_result = client.scroll(
            collection_name=collection_name,
            scroll_filter=qdrant_filter,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=include_embeddings
        )
        
        points, next_offset = scroll_result
        
        if not points:
            break
        
        # Convert points to document format
        for point in points:
            doc_data = {
                "id": str(point.id),
                "content": point.payload.get("content", ""),
                "meta": point.payload.get("meta", {}) or {},
            }
            
            # Add embedding if requested
            if include_embeddings and point.vector:
                # Handle both named and default vectors
                if isinstance(point.vector, dict):
                    doc_data["embedding"] = point.vector.get("default", list(point.vector.values())[0] if point.vector else None)
                else:
                    doc_data["embedding"] = point.vector
            
            # Add all other payload fields
            for key, value in point.payload.items():
                if key not in ["content", "meta"]:
                    doc_data[key] = value
            
            documents_data.append(doc_data)
            total_count += 1
        
        if next_offset is None:
            break
        offset = next_offset
    
    return documents_data, total_count


def create_backup(
    document_store: QdrantDocumentStore,
    backup_directory: str = "./backups",
    collection_name: Optional[str] = None,
    include_embeddings: bool = False,
    filters: Optional[Dict[str, Any]] = None,
    code_document_store: Optional[QdrantDocumentStore] = None
) -> Dict[str, Any]:
    """
    Create a local backup of Qdrant collections (documentation and optionally code).
    
    Creates a timestamped backup directory containing:
    - documents.json: All documentation documents with metadata
    - code_documents.json: All code documents with metadata (if code_document_store provided)
    - metadata.json: Backup metadata (timestamp, collection info, stats)
    - manifest.json: File manifest with checksums
    
    Args:
        document_store: QdrantDocumentStore instance for documentation
        backup_directory: Directory to store backups (default: "./backups")
        collection_name: Optional collection name (defaults to document_store.index)
        include_embeddings: Whether to include embeddings in backup (default: False)
        filters: Optional Haystack filter dictionary to filter documents
        code_document_store: Optional QdrantDocumentStore instance for code collection
        
    Returns:
        Dictionary with backup information:
        - status: "success" or "error"
        - backup_path: Path to backup directory
        - backup_id: Unique backup identifier
        - document_count: Total number of documents backed up
        - documentation_count: Number of documentation documents
        - code_count: Number of code documents (0 if not backed up)
        - backup_metadata: Backup metadata
    """
    try:
        # Get collection names
        docs_collection = collection_name or document_store.index
        code_collection = code_document_store.index if code_document_store else None
        
        # Create backup directory with timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_id = f"backup_{docs_collection}_{timestamp}"
        backup_path = Path(backup_directory) / backup_id
        backup_path.mkdir(parents=True, exist_ok=True)
        
        # Backup documentation collection
        docs_data, docs_count = _backup_collection(
            collection_name=docs_collection,
            backup_path=backup_path,
            include_embeddings=include_embeddings,
            filters=filters
        )
        
        # Save documentation documents to JSON
        documents_file = backup_path / "documents.json"
        with open(documents_file, "w", encoding="utf-8") as f:
            json.dump(docs_data, f, indent=2, default=str)
        documents_checksum = _calculate_file_checksum(documents_file)
        
        # Backup code collection if provided
        code_count = 0
        code_checksum = None
        if code_document_store and code_collection:
            try:
                code_data, code_count = _backup_collection(
                    collection_name=code_collection,
                    backup_path=backup_path,
                    include_embeddings=include_embeddings,
                    filters=filters
                )
                
                # Save code documents to JSON
                code_documents_file = backup_path / "code_documents.json"
                with open(code_documents_file, "w", encoding="utf-8") as f:
                    json.dump(code_data, f, indent=2, default=str)
                code_checksum = _calculate_file_checksum(code_documents_file)
            except Exception as e:
                # Log error but continue with docs backup
                print(f"Warning: Failed to backup code collection: {e}", file=sys.stderr)
                code_count = 0
        
        total_count = docs_count + code_count
        
        # Create backup metadata
        backup_metadata = {
            "backup_id": backup_id,
            "collections": {
                "documentation": {
                    "collection_name": docs_collection,
                    "document_count": docs_count
                }
            },
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "document_count": total_count,
            "documentation_count": docs_count,
            "code_count": code_count,
            "include_embeddings": include_embeddings,
            "filters_applied": filters is not None,
            "filters": filters,
            "backup_version": "2.0"  # Version 2.0 supports multiple collections
        }
        
        # Add code collection info if backed up
        if code_collection and code_count > 0:
            backup_metadata["collections"]["code"] = {
                "collection_name": code_collection,
                "document_count": code_count
            }
        
        metadata_file = backup_path / "metadata.json"
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(backup_metadata, f, indent=2, default=str)
        metadata_checksum = _calculate_file_checksum(metadata_file)
        
        # Create manifest
        manifest_files = [
            {
                "filename": "documents.json",
                "checksum": documents_checksum,
                "size": documents_file.stat().st_size
            },
            {
                "filename": "metadata.json",
                "checksum": metadata_checksum,
                "size": metadata_file.stat().st_size
            }
        ]
        
        # Add code documents to manifest if backed up
        if code_collection and code_count > 0:
            code_documents_file = backup_path / "code_documents.json"
            manifest_files.append({
                "filename": "code_documents.json",
                "checksum": code_checksum,
                "size": code_documents_file.stat().st_size
            })
        
        manifest = {
            "backup_id": backup_id,
            "files": manifest_files,
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
        
        manifest_file = backup_path / "manifest.json"
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, default=str)
        
        return {
            "status": "success",
            "backup_path": str(backup_path),
            "backup_id": backup_id,
            "document_count": total_count,
            "documentation_count": docs_count,
            "code_count": code_count,
            "backup_metadata": backup_metadata,
            "manifest": manifest
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "type": type(e).__name__
        }


def _restore_collection(
    documents_data: List[Dict[str, Any]],
    document_store: QdrantDocumentStore,
    collection_name: str,
    duplicate_strategy: str,
    embedder,
    backup_has_embeddings: bool
) -> tuple[int, int, List[str]]:
    """
    Helper function to restore a single collection.
    
    Returns:
        Tuple of (restored_count, skipped_count, errors)
    """
    restored_count = 0
    skipped_count = 0
    errors = []
    
    # Get Qdrant client
    client = _get_qdrant_client()
    
    # Check for existing documents if duplicate_strategy is "skip"
    existing_doc_ids = set()
    if duplicate_strategy == "skip":
        offset = None
        while True:
            scroll_result = client.scroll(
                collection_name=collection_name,
                limit=100,
                offset=offset,
                with_payload=False,
                with_vectors=False
            )
            points, next_offset = scroll_result
            if not points:
                break
            existing_doc_ids.update(str(p.id) for p in points)
            if next_offset is None:
                break
            offset = next_offset
    
    # Check if documents actually have embeddings
    all_docs_have_embeddings = all(
        "embedding" in doc_data and doc_data.get("embedding") is not None
        for doc_data in documents_data
    ) if documents_data else False
    
    # Use Haystack path (regenerates embeddings) if:
    # 1. Embedder is provided (allows embedding regeneration), OR
    # 2. Backup doesn't have embeddings, OR  
    # 3. Documents don't have embeddings
    use_haystack_path = embedder is not None or (not backup_has_embeddings) or (not all_docs_have_embeddings)
    
    if use_haystack_path:
        # Use Haystack's write_documents to restore with automatic embedding regeneration
        batch_size = 100
        documents_to_restore = []
        
        for doc_data in documents_data:
            doc_id = doc_data.get("id")
            
            # Skip if duplicate and strategy is "skip"
            if duplicate_strategy == "skip" and doc_id in existing_doc_ids:
                skipped_count += 1
                continue
            
            # Recreate Haystack Document from backup data
            content = doc_data.get("content", "")
            meta = doc_data.get("meta", {})
            
            # Preserve original doc_id if available
            if "doc_id" in meta:
                meta["doc_id"] = meta["doc_id"]
            
            # Create Document (embeddings will be regenerated by Haystack)
            doc = Document(
                content=content,
                meta=meta
            )
            
            documents_to_restore.append(doc)
            
            # Write in batches
            if len(documents_to_restore) >= batch_size:
                try:
                    # Embed documents before writing (required by Haystack)
                    if embedder:
                        result = embedder.run(documents=documents_to_restore)
                        documents_with_embeddings = result.get("documents", documents_to_restore)
                    else:
                        documents_with_embeddings = documents_to_restore
                    
                    document_store.write_documents(documents_with_embeddings)
                    restored_count += len(documents_with_embeddings)
                    documents_to_restore = []
                except Exception as e:
                    errors.append(f"Batch restore error: {str(e)}")
        
        # Write remaining documents
        if documents_to_restore:
            try:
                if embedder:
                    result = embedder.run(documents=documents_to_restore)
                    documents_with_embeddings = result.get("documents", documents_to_restore)
                else:
                    documents_with_embeddings = documents_to_restore
                
                document_store.write_documents(documents_with_embeddings)
                restored_count += len(documents_with_embeddings)
            except Exception as e:
                errors.append(f"Final batch restore error: {str(e)}")
    
    else:
        # Use direct Qdrant upsert when we have embeddings (faster, preserves original IDs)
        batch_size = 100
        points_to_upsert = []
        
        for doc_data in documents_data:
            doc_id = doc_data.get("id")
            
            # Skip if duplicate and strategy is "skip"
            if duplicate_strategy == "skip" and doc_id in existing_doc_ids:
                skipped_count += 1
                continue
            
            # Prepare point for upsert
            payload = {
                "content": doc_data.get("content", ""),
                "meta": doc_data.get("meta", {})
            }
            
            # Add other payload fields
            for key, value in doc_data.items():
                if key not in ["id", "content", "meta", "embedding"]:
                    payload[key] = value
            
            # Prepare vector (we know it exists here)
            vector = doc_data.get("embedding")
            
            point = PointStruct(
                id=doc_id,
                vector=vector,
                payload=payload
            )
            
            points_to_upsert.append(point)
            
            # Upsert in batches
            if len(points_to_upsert) >= batch_size:
                try:
                    client.upsert(
                        collection_name=collection_name,
                        points=points_to_upsert
                    )
                    restored_count += len(points_to_upsert)
                    points_to_upsert = []
                except Exception as e:
                    errors.append(f"Batch upsert error: {str(e)}")
        
        # Upsert remaining points
        if points_to_upsert:
            try:
                client.upsert(
                    collection_name=collection_name,
                    points=points_to_upsert
                )
                restored_count += len(points_to_upsert)
            except Exception as e:
                errors.append(f"Final batch upsert error: {str(e)}")
    
    return restored_count, skipped_count, errors


def restore_backup(
    backup_path: str,
    document_store: QdrantDocumentStore,
    collection_name: Optional[str] = None,
    verify_after_restore: bool = True,
    duplicate_strategy: str = "skip",
    embedder=None,  # Optional embedder for regenerating embeddings (docs)
    code_document_store: Optional[QdrantDocumentStore] = None,
    code_embedder=None  # Optional embedder for regenerating embeddings (code)
) -> Dict[str, Any]:
    """
    Restore collections from a local backup (documentation and optionally code).
    
    Args:
        backup_path: Path to backup directory
        document_store: QdrantDocumentStore instance for documentation
        collection_name: Optional collection name (defaults to document_store.index)
        verify_after_restore: Whether to verify documents after restore (default: True)
        duplicate_strategy: How to handle duplicates - "skip", "update", or "overwrite"
        embedder: Optional embedder for regenerating embeddings (documentation)
        code_document_store: Optional QdrantDocumentStore instance for code collection
        code_embedder: Optional embedder for regenerating embeddings (code)
        
    Returns:
        Dictionary with restore information:
        - status: "success" or "error"
        - restored_count: Total number of documents restored
        - documentation_restored: Number of documentation documents restored
        - code_restored: Number of code documents restored (0 if not restored)
        - skipped_count: Total number of documents skipped
        - verification_results: Verification results if verify_after_restore is True
    """
    try:
        backup_dir = Path(backup_path)
        
        if not backup_dir.exists():
            return {
                "status": "error",
                "error": f"Backup directory not found: {backup_path}"
            }
        
        # Load manifest and verify integrity
        manifest_file = backup_dir / "manifest.json"
        if not manifest_file.exists():
            return {
                "status": "error",
                "error": "Manifest file not found in backup directory"
            }
        
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        
        # Verify file checksums
        verification_result = _verify_backup_integrity(backup_dir, manifest)
        if not verification_result["valid"]:
            return {
                "status": "error",
                "error": "Backup integrity check failed",
                "verification_errors": verification_result["errors"]
            }
        
        # Load metadata
        metadata_file = backup_dir / "metadata.json"
        with open(metadata_file, "r", encoding="utf-8") as f:
            backup_metadata = json.load(f)
        
        # Check backup version for backward compatibility
        backup_version = backup_metadata.get("backup_version", "1.0")
        is_multi_collection = backup_version >= "2.0" or "collections" in backup_metadata
        
        # Load documentation documents
        documents_file = backup_dir / "documents.json"
        if not documents_file.exists():
            return {
                "status": "error",
                "error": "documents.json not found in backup directory"
            }
        
        with open(documents_file, "r", encoding="utf-8") as f:
            documents_data = json.load(f)
        
        # Get collection names
        if is_multi_collection:
            collections_info = backup_metadata.get("collections", {})
            docs_collection_info = collections_info.get("documentation", {})
            backup_docs_collection = docs_collection_info.get("collection_name")
            code_collection_info = collections_info.get("code", {})
            backup_code_collection = code_collection_info.get("collection_name") if code_collection_info else None
        else:
            # Legacy backup format (version 1.0)
            backup_docs_collection = backup_metadata.get("collection_name")
            backup_code_collection = None
        
        docs_collection = collection_name or document_store.index
        
        # Check if backup has embeddings
        backup_has_embeddings = backup_metadata.get("include_embeddings", False)
        
        # Restore documentation collection
        docs_restored, docs_skipped, docs_errors = _restore_collection(
            documents_data=documents_data,
            document_store=document_store,
            collection_name=docs_collection,
            duplicate_strategy=duplicate_strategy,
            embedder=embedder,
            backup_has_embeddings=backup_has_embeddings
        )
        
        # Restore code collection if backup contains it and code_document_store is provided
        code_restored = 0
        code_skipped = 0
        code_errors = []
        code_collection = None
        
        code_documents_file = backup_dir / "code_documents.json"
        if code_documents_file.exists() and code_document_store:
            try:
                with open(code_documents_file, "r", encoding="utf-8") as f:
                    code_documents_data = json.load(f)
                
                code_collection = code_document_store.index
                code_restored, code_skipped, code_errors = _restore_collection(
                    documents_data=code_documents_data,
                    document_store=code_document_store,
                    collection_name=code_collection,
                    duplicate_strategy=duplicate_strategy,
                    embedder=code_embedder or embedder,  # Fallback to docs embedder if code embedder not provided
                    backup_has_embeddings=backup_has_embeddings
                )
            except Exception as e:
                code_errors.append(f"Failed to restore code collection: {str(e)}")
        
        total_restored = docs_restored + code_restored
        total_skipped = docs_skipped + code_skipped
        all_errors = docs_errors + code_errors
        
        result = {
            "status": "success",
            "restored_count": total_restored,
            "documentation_restored": docs_restored,
            "code_restored": code_restored,
            "skipped_count": total_skipped,
            "documentation_skipped": docs_skipped,
            "code_skipped": code_skipped,
            "backup_id": backup_metadata.get("backup_id"),
            "backup_collections": {
                "documentation": backup_docs_collection,
                "code": backup_code_collection
            } if backup_code_collection else {"documentation": backup_docs_collection},
            "restore_collections": {
                "documentation": docs_collection,
                "code": code_collection
            } if code_collection else {"documentation": docs_collection},
            "errors": all_errors if all_errors else None
        }
        
        # Verify after restore if requested
        if verify_after_restore:
            verification_results = {}
            if docs_restored > 0:
                verification_results["documentation"] = _verify_restored_documents(
                    document_store,
                    docs_collection,
                    sample_size=min(100, docs_restored)
                )
            if code_restored > 0 and code_collection:
                verification_results["code"] = _verify_restored_documents(
                    code_document_store,
                    code_collection,
                    sample_size=min(100, code_restored)
                )
            result["verification_results"] = verification_results
        
        return result
    
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "type": type(e).__name__
        }


def list_backups(backup_directory: str = "./backups") -> Dict[str, Any]:
    """
    List all available backups in the backup directory.
    
    Args:
        backup_directory: Directory containing backups (default: "./backups")
        
    Returns:
        Dictionary with list of backups and their metadata
    """
    try:
        backup_dir = Path(backup_directory)
        
        if not backup_dir.exists():
            return {
                "status": "success",
                "backups": [],
                "message": "Backup directory does not exist"
            }
        
        backups = []
        
        # Find all backup directories
        for item in backup_dir.iterdir():
            if item.is_dir() and item.name.startswith("backup_"):
                manifest_file = item / "manifest.json"
                metadata_file = item / "metadata.json"
                
                if manifest_file.exists() and metadata_file.exists():
                    try:
                        with open(metadata_file, "r", encoding="utf-8") as f:
                            metadata = json.load(f)
                        
                        backups.append({
                            "backup_id": metadata.get("backup_id", item.name),
                            "backup_path": str(item),
                            "collection_name": metadata.get("collection_name"),
                            "timestamp": metadata.get("timestamp"),
                            "document_count": metadata.get("document_count", 0),
                            "include_embeddings": metadata.get("include_embeddings", False)
                        })
                    except Exception:
                        # Skip corrupted backups
                        continue
        
        # Sort by timestamp (newest first)
        backups.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        return {
            "status": "success",
            "backups": backups,
            "total_backups": len(backups)
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "type": type(e).__name__
        }


def _calculate_file_checksum(file_path: Path) -> str:
    """Calculate SHA256 checksum of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def _verify_backup_integrity(backup_dir: Path, manifest: Dict) -> Dict[str, Any]:
    """Verify backup file integrity using checksums."""
    errors = []
    
    for file_info in manifest.get("files", []):
        filename = file_info["filename"]
        expected_checksum = file_info["checksum"]
        file_path = backup_dir / filename
        
        if not file_path.exists():
            errors.append(f"File not found: {filename}")
            continue
        
        actual_checksum = _calculate_file_checksum(file_path)
        if actual_checksum != expected_checksum:
            errors.append(f"Checksum mismatch for {filename}: expected {expected_checksum[:16]}..., got {actual_checksum[:16]}...")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors
    }


def _verify_restored_documents(
    document_store: QdrantDocumentStore,
    collection_name: str,
    sample_size: int = 100
) -> Dict[str, Any]:
    """Verify a sample of restored documents."""
    try:
        client = _get_qdrant_client()
        
        # Get sample of documents
        scroll_result = client.scroll(
            collection_name=collection_name,
            limit=sample_size,
            with_payload=True,
            with_vectors=False
        )
        
        points, _ = scroll_result
        
        verified_count = 0
        failed_count = 0
        issues = []
        
        for point in points:
            try:
                # Reconstruct document
                doc = Document(
                    content=point.payload.get("content", ""),
                    meta=point.payload.get("meta", {}) or {},
                    id=str(point.id)
                )
                
                # Verify quality
                quality_result = verify_content_quality(doc)
                
                if quality_result["status"] == "pass":
                    verified_count += 1
                else:
                    failed_count += 1
                    issues.append({
                        "document_id": str(point.id),
                        "issues": quality_result.get("issues", [])
                    })
            except Exception as e:
                failed_count += 1
                issues.append({
                    "document_id": str(point.id),
                    "error": str(e)
                })
        
        return {
            "sample_size": len(points),
            "verified_count": verified_count,
            "failed_count": failed_count,
            "verification_rate": verified_count / len(points) if points else 0,
            "issues": issues[:10]  # Limit to first 10 issues
        }
    
    except Exception as e:
        return {
            "error": str(e),
            "type": type(e).__name__
        }

