"""
Simple test script for Haystack + Qdrant integration.
Tests basic indexing and search functionality.
"""
import os
from haystack.dataclasses.document import Document
from haystack.components.embedders import SentenceTransformersDocumentEmbedder, SentenceTransformersTextEmbedder
from haystack.utils import Secret
from haystack import Pipeline

# Qdrant integration (separate package)
try:
    from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
    from haystack_integrations.components.retrievers.qdrant import QdrantEmbeddingRetriever
except ImportError:
    print("Error: qdrant-haystack package not installed.")
    print("Install it with: pip install qdrant-haystack")
    raise


def test_qdrant_connection():
    """Test basic Qdrant connection."""
    print("=" * 60)
    print("Testing Haystack + Qdrant Connection")
    print("=" * 60)
    
    # Get Qdrant credentials from environment or user input
    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    collection_name = os.getenv("QDRANT_COLLECTION", "haystack_test")
    
    if not qdrant_url:
        qdrant_url = input("Enter Qdrant URL (e.g., https://xxx.qdrant.io:6333): ").strip()
    
    if not qdrant_api_key:
        qdrant_api_key = input("Enter Qdrant API Key: ").strip()
    
    print(f"\nConnecting to Qdrant...")
    print(f"URL: {qdrant_url}")
    print(f"Collection: {collection_name}")
    
    try:
        # Create document store
        document_store = QdrantDocumentStore(
            url=qdrant_url,
            index=collection_name,
            embedding_dim=384,  # sentence-transformers/all-MiniLM-L6-v2 dimension
            api_key=Secret.from_token(qdrant_api_key),
            recreate_index=False,  # Set to True if you want to recreate the collection
            return_embedding=True,
            wait_result_from_api=True,
        )
        
        print("✓ Connected to Qdrant successfully!")
        
        # Test 1: Write documents
        print("\n" + "-" * 60)
        print("Test 1: Writing documents to Qdrant")
        print("-" * 60)
        
        # Create sample documents
        documents = [
            Document(content="Haystack is a framework for building RAG applications with LLMs."),
            Document(content="Qdrant is a vector database for similarity search."),
            Document(content="Python is a programming language used for AI and machine learning."),
            Document(content="MCP stands for Model Context Protocol, a standard for AI tool integration."),
        ]
        
        # Create embedding pipeline
        doc_embedder = SentenceTransformersDocumentEmbedder(
            model="sentence-transformers/all-MiniLM-L6-v2"
        )
        doc_embedder.warm_up()
        
        # Embed documents
        result = doc_embedder.run(documents=documents)
        documents_with_embeddings = result["documents"]
        
        # Write to Qdrant
        document_store.write_documents(documents_with_embeddings)
        print(f"✓ Wrote {len(documents_with_embeddings)} documents to Qdrant")
        
        # Test 2: Count documents
        print("\n" + "-" * 60)
        print("Test 2: Counting documents")
        print("-" * 60)
        count = document_store.count_documents()
        print(f"✓ Total documents in collection: {count}")
        
        # Test 3: Search documents
        print("\n" + "-" * 60)
        print("Test 3: Searching documents")
        print("-" * 60)
        
        # Create search pipeline
        text_embedder = SentenceTransformersTextEmbedder(
            model="sentence-transformers/all-MiniLM-L6-v2"
        )
        text_embedder.warm_up()
        
        retriever = QdrantEmbeddingRetriever(document_store=document_store, top_k=3)
        
        search_pipeline = Pipeline()
        search_pipeline.add_component("text_embedder", text_embedder)
        search_pipeline.add_component("retriever", retriever)
        search_pipeline.connect("text_embedder.embedding", "retriever.query_embedding")
        
        # Test queries
        test_queries = [
            "What is Haystack?",
            "vector database",
            "Python programming"
        ]
        
        for query in test_queries:
            print(f"\nQuery: '{query}'")
            result = search_pipeline.run({"text_embedder": {"text": query}})
            retrieved_docs = result["retriever"]["documents"]
            
            for i, doc in enumerate(retrieved_docs, 1):
                score = getattr(doc, 'score', getattr(doc, 'relevance_score', 'N/A'))
                print(f"  {i}. Score: {score}")
                print(f"     Content: {doc.content[:80]}...")
        
        print("\n" + "=" * 60)
        print("✓ All tests passed!")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    test_qdrant_connection()

