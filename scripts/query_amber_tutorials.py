#!/usr/bin/env python3
"""Query and review Amber tutorials from Chroma.

This script provides utilities to:
1. Query tutorials by text similarity
2. Review tutorial metadata and structure
3. Verify ingestion status
4. Analyze tutorial coverage (images, code, links, etc.)

Usage:
    # Query tutorials:
    python scripts/query_amber_tutorials.py --query "molecular dynamics setup"
    
    # Review tutorial manifest:
    python scripts/query_amber_tutorials.py --list-tutorials
    
    # Get statistics:
    python scripts/query_amber_tutorials.py --stats
    
    # Review specific tutorial:
    python scripts/query_amber_tutorials.py --tutorial amber25_basic_tutorial
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_manifest() -> Dict:
    """Load tutorial manifest."""
    manifest_path = Path("data/tutorials_manifest.json")
    if not manifest_path.exists():
        logger.error(f"Manifest not found: {manifest_path}")
        return {}
    
    try:
        return json.loads(manifest_path.read_text(encoding='utf-8'))
    except Exception as e:
        logger.error(f"Failed to load manifest: {e}")
        return {}


def load_tutorial_json(slug: str) -> Optional[Dict]:
    """Load tutorial JSON by slug."""
    tutorial_path = Path("data/tutorials") / f"{slug}.json"
    if not tutorial_path.exists():
        logger.warning(f"Tutorial not found: {tutorial_path}")
        return None
    
    try:
        return json.loads(tutorial_path.read_text(encoding='utf-8'))
    except Exception as e:
        logger.error(f"Failed to load tutorial: {e}")
        return None


def create_chroma_client(host: Optional[str] = None, port: Optional[int] = None):
    """Create Chroma client."""
    try:
        import chromadb
        from chromadb.config import Settings
    except ImportError:
        raise RuntimeError("chromadb package required")
    
    import os
    host = host or os.environ.get('CHROMA_SERVER_HOST')
    port = port or (int(os.environ.get('CHROMA_SERVER_HTTP_PORT', '8000')) if os.environ.get('CHROMA_SERVER_HTTP_PORT') else 8000)
    
    if host:
        logger.info(f"Connecting to Chroma at {host}:{port}")
        settings = Settings(
            chroma_api_impl="rest",
            chroma_server_host=host,
            chroma_server_http_port=port,
            allow_reset=False
        )
        client = chromadb.Client(settings)
    else:
        logger.info("Using local Chroma")
        client = chromadb.Client()
    
    return client


def query_tutorials(
    query_text: str,
    collection_name: str = "amber_tutorials",
    n_results: int = 5,
    client = None
):
    """Query tutorials by text similarity."""
    if client is None:
        client = create_chroma_client()
    
    try:
        collection = client.get_collection(collection_name)
    except Exception as e:
        logger.error(f"Failed to get collection: {e}")
        return []
    
    try:
        results = collection.query(
            query_texts=[query_text],
            n_results=n_results
        )
        return results
    except Exception as e:
        logger.error(f"Query failed: {e}")
        return {}


def list_tutorials(manifest: Dict):
    """List all tutorials."""
    tutorials = manifest.get('scraped_tutorials', [])
    
    if not tutorials:
        print("No tutorials found in manifest.")
        return
    
    print(f"\n{'Title':<50} {'Chunks':<8} {'Images':<8} {'Code':<8} {'Links':<8}")
    print("-" * 90)
    
    for tut in sorted(tutorials, key=lambda t: t['title']):
        title = tut['title'][:49]
        chunks = tut.get('chunks_count', 0)
        images = tut.get('metadata', {}).get('images_count', 0)
        code = tut.get('metadata', {}).get('code_blocks_count', 0)
        links = tut.get('metadata', {}).get('external_links_count', 0)
        
        print(f"{title:<50} {chunks:<8} {images:<8} {code:<8} {links:<8}")
    
    print(f"\nTotal: {len(tutorials)} tutorials")


def print_statistics(manifest: Dict):
    """Print statistics about scraped tutorials."""
    tutorials = manifest.get('scraped_tutorials', [])
    
    if not tutorials:
        print("No tutorials found.")
        return
    
    total_chunks = sum(t.get('chunks_count', 0) for t in tutorials)
    total_images = sum(t.get('metadata', {}).get('images_count', 0) for t in tutorials)
    total_downloads = sum(t.get('metadata', {}).get('downloads_count', 0) for t in tutorials)
    total_links = sum(t.get('metadata', {}).get('external_links_count', 0) for t in tutorials)
    total_code = sum(t.get('metadata', {}).get('code_blocks_count', 0) for t in tutorials)
    total_tables = sum(t.get('metadata', {}).get('tables_count', 0) for t in tutorials)
    
    print("\n" + "=" * 60)
    print("TUTORIAL STATISTICS")
    print("=" * 60)
    print(f"Total tutorials:          {len(tutorials)}")
    print(f"Total chunks:             {total_chunks}")
    print(f"Total images:             {total_images}")
    print(f"Total download links:     {total_downloads}")
    print(f"Total external links:     {total_links}")
    print(f"Total code blocks:        {total_code}")
    print(f"Total tables:             {total_tables}")
    print(f"Last updated:             {manifest.get('last_update', 'unknown')}")
    print(f"Failed URLs:              {len(manifest.get('failed_urls', []))}")
    print("=" * 60 + "\n")
    
    # Top tutorials by content
    print("TOP TUTORIALS BY CHUNK COUNT:")
    for i, tut in enumerate(sorted(tutorials, key=lambda t: t.get('chunks_count', 0), reverse=True)[:5], 1):
        print(f"  {i}. {tut['title'][:50]:<50} {tut.get('chunks_count', 0)} chunks")
    
    print("\nTOP TUTORIALS BY IMAGES:")
    for i, tut in enumerate(sorted(tutorials, key=lambda t: t.get('metadata', {}).get('images_count', 0), reverse=True)[:5], 1):
        count = tut.get('metadata', {}).get('images_count', 0)
        if count > 0:
            print(f"  {i}. {tut['title'][:50]:<50} {count} images")
    
    print("\nTOP TUTORIALS BY CODE BLOCKS:")
    for i, tut in enumerate(sorted(tutorials, key=lambda t: t.get('metadata', {}).get('code_blocks_count', 0), reverse=True)[:5], 1):
        count = tut.get('metadata', {}).get('code_blocks_count', 0)
        if count > 0:
            print(f"  {i}. {tut['title'][:50]:<50} {count} code blocks")


def print_tutorial_details(slug: str):
    """Print detailed information about a tutorial."""
    tutorial = load_tutorial_json(slug)
    
    if not tutorial:
        logger.error(f"Tutorial not found: {slug}")
        return
    
    print("\n" + "=" * 80)
    print(f"TUTORIAL: {tutorial.get('title', 'Unknown')}")
    print("=" * 80)
    print(f"URL:               {tutorial.get('url', '')}")
    print(f"Slug:              {tutorial.get('slug', '')}")
    print(f"Scraped:           {tutorial.get('scraped_at', '')}")
    print(f"Sections:          {len(tutorial.get('sections', []))}")
    
    metadata = tutorial.get('metadata', {})
    print(f"\nCONTENT ANALYSIS:")
    print(f"  Images:          {metadata.get('images_count', 0)}")
    print(f"  Downloads:       {metadata.get('downloads_count', 0)}")
    print(f"  External links:  {metadata.get('external_links_count', 0)}")
    print(f"  Code blocks:     {metadata.get('code_blocks_count', 0)}")
    print(f"  Tables:          {metadata.get('tables_count', 0)}")
    
    # Images
    images = metadata.get('images', [])
    if images:
        print(f"\nIMAGES ({len(images)}):")
        for img in images[:3]:
            print(f"  - {img.get('filename', 'unknown'):<30} {img.get('alt', '')[:40]}")
        if len(images) > 3:
            print(f"  ... and {len(images) - 3} more")
    
    # Code blocks
    code_blocks = metadata.get('code_blocks', [])
    if code_blocks:
        print(f"\nCODE BLOCKS ({len(code_blocks)}):")
        for code in code_blocks[:3]:
            print(f"  - {code.get('language', 'unknown'):<10} ({code.get('line_count', 0)} lines)")
        if len(code_blocks) > 3:
            print(f"  ... and {len(code_blocks) - 3} more")
    
    # Downloads
    downloads = metadata.get('downloads', [])
    if downloads:
        print(f"\nDOWNLOADS ({len(downloads)}):")
        for dl in downloads[:3]:
            print(f"  - {dl.get('filename', 'unknown'):<30} ({dl.get('extension', '')})")
        if len(downloads) > 3:
            print(f"  ... and {len(downloads) - 3} more")
    
    # External links
    links = metadata.get('external_links', [])
    if links:
        print(f"\nEXTERNAL LINKS ({len(links)}):")
        domains = {}
        for link in links:
            domain = link.get('domain', 'unknown')
            domains[domain] = domains.get(domain, 0) + 1
        for domain, count in sorted(domains.items(), key=lambda x: -x[1])[:5]:
            print(f"  - {domain:<30} ({count} links)")
    
    print("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description='Query and review Amber tutorials'
    )
    parser.add_argument(
        '--query',
        type=str,
        help='Query text to search tutorials'
    )
    parser.add_argument(
        '--n-results',
        type=int,
        default=5,
        help='Number of results to return (default: 5)'
    )
    parser.add_argument(
        '--list-tutorials',
        action='store_true',
        help='List all tutorials'
    )
    parser.add_argument(
        '--stats',
        action='store_true',
        help='Print statistics'
    )
    parser.add_argument(
        '--tutorial',
        type=str,
        help='Show details for specific tutorial (by slug)'
    )
    parser.add_argument(
        '--collection',
        type=str,
        default='amber_tutorials',
        help='Chroma collection name (default: amber_tutorials)'
    )
    parser.add_argument(
        '--chroma-host',
        type=str,
        help='Chroma server host (e.g., localhost or http://mirzakhani)'
    )
    
    args = parser.parse_args()
    
    # Load manifest
    manifest = load_manifest()
    
    # Handle different commands
    if args.query:
        print(f"\nQuerying: {args.query}")
        try:
            client = create_chroma_client(host=args.chroma_host)
            results = query_tutorials(
                args.query,
                args.collection,
                args.n_results,
                client
            )
            
            if results and 'documents' in results:
                print(f"\nTop {len(results['documents'][0])} results:\n")
                for i, (doc, meta, dist) in enumerate(zip(
                    results['documents'][0],
                    results['metadatas'][0],
                    results['distances'][0]
                ), 1):
                    print(f"{i}. Page {meta.get('page', '?')}: {meta.get('title', 'Unknown')[:50]}")
                    print(f"   Distance: {dist:.4f}")
                    print(f"   {doc[:150]}...\n")
            else:
                print("No results found.")
        except Exception as e:
            logger.error(f"Query failed: {e}")
    
    elif args.list_tutorials:
        list_tutorials(manifest)
    
    elif args.stats:
        print_statistics(manifest)
    
    elif args.tutorial:
        print_tutorial_details(args.tutorial)
    
    else:
        # Default: show stats
        print_statistics(manifest)


if __name__ == '__main__':
    main()
