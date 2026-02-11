#!/usr/bin/env python3
"""Production-grade scraper for AmberMD tutorials with comprehensive metadata.

This script:
1. Discovers all tutorial pages from https://ambermd.org/tutorials/
2. Extracts structured content: headings, sections, code blocks, images, links, downloads
3. Captures metadata for each tutorial and its components
4. Emits per-tutorial JSON with full metadata
5. Creates chunked JSONL ready for vector DB ingestion

Features:
- Tracks images, downloads, external links per page
- Identifies and preserves code blocks with language hints
- Handles tables and structured content
- Comprehensive logging and error tracking
- Checkpoint-based resumable crawling
- Metadata manifest for auditing and reproducibility

Usage:
    python scripts/scrape_amber_tutorials_production.py
    
    # Full crawl:
    python scripts/scrape_amber_tutorials_production.py --limit None --delay 0.5
    
    # Demo (first 10):
    python scripts/scrape_amber_tutorials_production.py --limit 10
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from tenacity import retry, wait_exponential, stop_after_attempt

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('amber_tutorials_scrape.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

BASE = "https://ambermd.org"
INDEX = f"{BASE}/tutorials/"
OUT_DIR = Path("data") / "tutorials"
CHUNK_OUT = Path("data") / "tutorials_chunks"
MANIFEST_FILE = Path("data") / "tutorials_manifest.json"
UA = "amber-tutorial-scraper/1.0 (+https://github.com/ambermd/)"


@retry(wait=wait_exponential(min=1, max=20), stop=stop_after_attempt(3))
def fetch(url: str, timeout: int = 15) -> Optional[str]:
    """Fetch URL with retry logic and proper error handling."""
    headers = {"User-Agent": UA}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            return resp.text
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        raise
    return None


def parse_index(html: str, domain_filter: Optional[str] = None) -> List[str]:
    """Parse tutorial index page and extract all tutorial links."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    
    links = set()
    for a in soup.find_all("a", href=True):
        href = a['href'].strip()
        
        # Accept tutorial-like links
        if any([
            'tutorial' in href.lower(),
            href.startswith('/tutorials'),
            href.endswith('.php'),
            href.endswith('.html')
        ]):
            full = urljoin(INDEX, href)
            # Normalize URL (remove fragment and query)
            p = urlparse(full)
            full = f"{p.scheme}://{p.netloc}{p.path}"
            
            if domain_filter:
                if urlparse(full).netloc.endswith(domain_filter):
                    links.add(full)
            else:
                links.add(full)
    
    return sorted(links)


def extract_images(soup: BeautifulSoup) -> List[Dict]:
    """Extract images with metadata (src, alt, caption)."""
    images = []
    for img in soup.find_all("img"):
        src = img.get("src", "").strip()
        if not src:
            continue
        
        src_full = urljoin(INDEX, src)
        alt = img.get("alt", "").strip() or img.get("title", "").strip()
        
        # Look for caption (text after image, or in figcaption)
        caption = ""
        parent = img.parent
        if parent and parent.name == "figure":
            figcap = parent.find("figcaption")
            if figcap:
                caption = figcap.get_text(strip=True)
        
        images.append({
            "src": src_full,
            "alt": alt,
            "caption": caption,
            "filename": Path(src).name
        })
    
    return images


def extract_downloads(soup: BeautifulSoup, page_url: str) -> List[Dict]:
    """Extract download links (common patterns: .zip, .tar.gz, .pdf, etc.)."""
    downloads = []
    download_extensions = {'.zip', '.tar.gz', '.tar', '.gzip', '.rar', '.7z', '.pdf', '.txt', '.dat', '.parm', '.in'}
    
    for a in soup.find_all("a", href=True):
        href = a['href'].strip()
        href_lower = href.lower()
        
        # Check if it's a downloadable file
        if any(href_lower.endswith(ext) for ext in download_extensions):
            href_full = urljoin(page_url, href)
            text = a.get_text(strip=True)
            
            downloads.append({
                "url": href_full,
                "filename": Path(urlparse(href_full).path).name,
                "text": text,
                "extension": ''.join(Path(href_full).suffixes)
            })
    
    return downloads


def extract_external_links(soup: BeautifulSoup) -> List[Dict]:
    """Extract external links (references, citations, documentation)."""
    links = []
    seen = set()
    
    for a in soup.find_all("a", href=True):
        href = a['href'].strip()
        
        # Skip anchors and local links
        if not href or href.startswith('#'):
            continue
        
        # Detect if external
        is_external = (
            href.startswith('http') or 
            href.startswith('www')
        )
        
        if is_external and href not in seen:
            text = a.get_text(strip=True)[:100]  # Limit text length
            links.append({
                "url": href,
                "text": text,
                "domain": urlparse(href).netloc
            })
            seen.add(href)
    
    return links


def extract_code_blocks(soup: BeautifulSoup) -> List[Dict]:
    """Extract code blocks with language hints."""
    blocks = []
    
    # Look for <pre> and <code> tags
    for idx, pre in enumerate(soup.find_all("pre")):
        code = pre.find("code")
        if code:
            text = code.get_text()
        else:
            text = pre.get_text()
        
        # Try to detect language from class attribute
        language = "unknown"
        if pre.get("class"):
            classes = " ".join(pre.get("class", []))
            # Look for language hints (language-python, lang-bash, etc.)
            match = re.search(r'(language|lang)[-_]([\w]+)', classes, re.I)
            if match:
                language = match.group(2)
        
        # Fallback: check code element for class
        if code and code.get("class"):
            classes = " ".join(code.get("class", []))
            match = re.search(r'(language|lang)[-_]([\w]+)', classes, re.I)
            if match:
                language = match.group(2)
        
        blocks.append({
            "index": idx,
            "language": language,
            "code": text.strip(),
            "line_count": len(text.strip().split('\n'))
        })
    
    return blocks


def extract_tables(soup: BeautifulSoup) -> List[Dict]:
    """Extract table data with metadata."""
    tables = []
    
    for idx, table in enumerate(soup.find_all("table")):
        rows = []
        headers = []
        
        # Try to extract headers
        thead = table.find("thead")
        if thead:
            for tr in thead.find_all("tr"):
                header_cells = [td.get_text(strip=True) for td in tr.find_all(["th", "td"])]
                headers.append(header_cells)
        
        # Extract body
        tbody = table.find("tbody") or table
        for tr in tbody.find_all("tr"):
            cells = [td.get_text(strip=True)[:200] for td in tr.find_all(["td", "th"])]
            if cells:
                rows.append(cells)
        
        if rows:
            tables.append({
                "index": idx,
                "headers": headers,
                "rows": rows[: 10],  # Limit to first 10 rows
                "row_count": len(rows)
            })
    
    return tables


def extract_main_content(html: str, page_url: str) -> Dict:
    """Extract structured content from page HTML."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    
    # Find main content area
    main = (
        soup.find(id="content") or 
        soup.find("main") or 
        soup.find("article") or 
        soup.body
    )
    
    if main is None:
        return {"title": "", "sections": [], "full_text": "", "metadata": {}}
    
    # Make a working copy to avoid modifying original
    main_copy = BeautifulSoup(str(main), "html.parser").find(main.name)
    
    # Remove navigation and structural elements
    for sel in main_copy.select("nav, header, footer, .nav, .menu, .breadcrumb, .breadcrumbs, script, style"):
        sel.decompose()
    
    # Extract title
    title_tag = main_copy.find(["h1", "h2"]) or soup.find(["h1", "h2"])
    title = title_tag.get_text(strip=True) if title_tag else ""
    
    # Extract full text
    full_text = main_copy.get_text(separator="\n", strip=True) if main_copy else ""
    
    # Extract sections with headings
    sections = []
    current_heading = ""
    current_text = []
    
    for el in main_copy.find_all(recursive=True) if main_copy else []:
        if el.name and re.match(r'h[1-4]', el.name):
            # New heading found
            if current_text:
                sections.append({
                    "heading": current_heading,
                    "text": "\n".join(current_text)
                })
            current_heading = el.get_text(strip=True)
            current_text = []
        elif el.name in ("p", "div", "li", "td") and el.parent.name not in ("p", "div", "li", "td"):
            txt = el.get_text(strip=True)
            if txt and len(txt) > 3:
                current_text.append(txt)
    
    if current_text:
        sections.append({
            "heading": current_heading,
            "text": "\n".join(current_text)
        })
    
    # Extract comprehensive metadata
    metadata = {
        "images": extract_images(main_copy),
        "downloads": extract_downloads(main_copy, page_url),
        "external_links": extract_external_links(main_copy),
        "code_blocks": extract_code_blocks(main_copy),
        "tables": extract_tables(main_copy)
    }
    
    return {
        "title": title,
        "sections": sections,
        "full_text": full_text,
        "metadata": metadata
    }


def slug_from_url(url: str) -> str:
    """Generate slug from URL."""
    p = urlparse(url)
    slug = p.path.strip('/').replace('/', '_') or 'root'
    slug = re.sub(r'[^A-Za-z0-9_\-\.]+', '_', slug)
    return slug[:200]


def chunk_text(text: str, max_chars: int = 2000, overlap: int = 200) -> List[str]:
    """Split text into overlapping chunks."""
    # Split by paragraphs
    paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    
    chunks = []
    current_chunk = []
    current_length = 0
    
    for para in paras:
        para_len = len(para)
        
        # If adding this paragraph exceeds limit and we have content
        if current_length + para_len + 2 > max_chars and current_chunk:
            chunks.append('\n\n'.join(current_chunk))
            # Start new chunk with overlap from previous paragraph
            if overlap > 0 and len(current_chunk) > 1:
                prev_para = current_chunk[-1]
                # Add tail of previous to maintain context
                overlap_text = prev_para[-overlap:] if len(prev_para) > overlap else prev_para
                current_chunk = [overlap_text, para]
                current_length = len(overlap_text) + para_len
            else:
                current_chunk = [para]
                current_length = para_len
        else:
            current_chunk.append(para)
            current_length += para_len + 2
    
    if current_chunk:
        chunks.append('\n\n'.join(current_chunk))
    
    return chunks


def save_tutorial(url: str, scraped: Dict, page_content_summary: Dict):
    """Save tutorial as JSON and create chunks JSONL."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CHUNK_OUT.mkdir(parents=True, exist_ok=True)
    
    slug = slug_from_url(url)
    out_path = OUT_DIR / (slug + '.json')
    
    # Build comprehensive tutorial object
    tutorial_obj = {
        "url": url,
        "slug": slug,
        "title": scraped.get('title', ''),
        "scraped_at": datetime.utcnow().isoformat(),
        "sections": scraped.get('sections', []),
        "full_text": scraped.get('full_text', ''),
        "metadata": {
            "images_count": len(scraped['metadata'].get('images', [])),
            "downloads_count": len(scraped['metadata'].get('downloads', [])),
            "external_links_count": len(scraped['metadata'].get('external_links', [])),
            "code_blocks_count": len(scraped['metadata'].get('code_blocks', [])),
            "tables_count": len(scraped['metadata'].get('tables', [])),
            "images": scraped['metadata'].get('images', []),
            "downloads": scraped['metadata'].get('downloads', []),
            "external_links": scraped['metadata'].get('external_links', []),
            "code_blocks": scraped['metadata'].get('code_blocks', []),
            "tables": scraped['metadata'].get('tables', []),
        }
    }
    
    # Save tutorial JSON
    out_path.write_text(
        json.dumps(tutorial_obj, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    logger.info(f"Saved tutorial JSON: {out_path}")
    
    # Create chunks JSONL for vector DB
    chunks = chunk_text(tutorial_obj['full_text'])
    chunk_path = CHUNK_OUT / (slug + '_chunks.jsonl')
    
    with chunk_path.open('w', encoding='utf-8') as f:
        for chunk_idx, chunk_text_content in enumerate(chunks):
            chunk_metadata = {
                "source_url": url,
                "title": tutorial_obj['title'],
                "slug": slug,
                "chunk_index": chunk_idx,
                "total_chunks": len(chunks),
                "images_count": tutorial_obj['metadata']['images_count'],
                "downloads_count": tutorial_obj['metadata']['downloads_count'],
                "external_links_count": tutorial_obj['metadata']['external_links_count'],
                "code_blocks_count": tutorial_obj['metadata']['code_blocks_count'],
            }
            
            doc = {
                'id': f"{slug}_c{chunk_idx:04d}",
                'text': chunk_text_content,
                'metadata': chunk_metadata
            }
            f.write(json.dumps(doc, ensure_ascii=False) + '\n')
    
    logger.info(f"Saved {len(chunks)} chunks to: {chunk_path}")
    
    # Return summary for manifest
    return {
        "url": url,
        "slug": slug,
        "title": tutorial_obj['title'],
        "sections_count": len(tutorial_obj['sections']),
        "chunks_count": len(chunks),
        "scraped_at": tutorial_obj['scraped_at'],
        "metadata": {
            "images_count": tutorial_obj['metadata']['images_count'],
            "downloads_count": tutorial_obj['metadata']['downloads_count'],
            "external_links_count": tutorial_obj['metadata']['external_links_count'],
            "code_blocks_count": tutorial_obj['metadata']['code_blocks_count'],
            "tables_count": tutorial_obj['metadata']['tables_count'],
        }
    }


def load_manifest() -> Dict:
    """Load tracking manifest if exists."""
    if MANIFEST_FILE.exists():
        try:
            return json.loads(MANIFEST_FILE.read_text(encoding='utf-8'))
        except Exception as e:
            logger.warning(f"Failed to load manifest: {e}")
    return {"scraped_tutorials": [], "last_update": None, "total_chunks": 0}


def save_manifest(manifest: Dict):
    """Save tracking manifest."""
    manifest['last_update'] = datetime.utcnow().isoformat()
    MANIFEST_FILE.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    logger.info(f"Saved manifest: {MANIFEST_FILE}")


def main():
    parser = argparse.ArgumentParser(
        description='Production-grade Amber tutorial scraper'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=10,
        help='Maximum number of tutorials to scrape (default: 10, None for all)'
    )
    parser.add_argument(
        '--domain',
        type=str,
        default='ambermd.org',
        help='Restrict links to domain (default: ambermd.org)'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=0.5,
        help='Seconds between requests (default: 0.5)'
    )
    parser.add_argument(
        '--checkpoint',
        type=str,
        default=str(OUT_DIR / 'processed_urls.json'),
        help='Path to checkpoint file'
    )
    parser.add_argument(
        '--resume',
        action='store_true',
        help='Resume from checkpoint'
    )
    
    args = parser.parse_args()
    
    logger.info("=" * 80)
    logger.info("Starting Amber Tutorial Scraper (Production Grade)")
    logger.info(f"Index URL: {INDEX}")
    logger.info(f"Limit: {args.limit}")
    logger.info(f"Domain: {args.domain}")
    logger.info(f"Delay: {args.delay}s")
    logger.info("=" * 80)
    
    # Fetch index
    try:
        logger.info(f"Fetching index: {INDEX}")
        idx_html = fetch(INDEX)
    except Exception as e:
        logger.error(f"Failed to fetch index: {e}")
        return
    
    if not idx_html:
        logger.error("Failed to fetch index HTML")
        return
    
    # Parse links
    links = parse_index(idx_html, domain_filter=args.domain)
    logger.info(f"Found {len(links)} candidate tutorial links")
    
    # Load checkpoint
    checkpoint_path = Path(args.checkpoint)
    processed = set()
    
    if args.resume and checkpoint_path.exists():
        try:
            processed = set(json.loads(checkpoint_path.read_text(encoding='utf-8')))
            logger.info(f"Resuming from checkpoint: {len(processed)} already processed")
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}")
    
    # Load manifest
    manifest = load_manifest()
    
    # Scrape tutorials
    count = 0
    failed = []
    
    for url in links:
        if args.limit and count >= args.limit:
            break
        
        if url in processed:
            logger.debug(f"Skipping already processed: {url}")
            continue
        
        logger.info(f"[{count+1}] Processing: {url}")
        
        try:
            html = fetch(url)
            
            # Fallback: try with /index.php
            if html is None:
                alt_url = url.rstrip('/') + '/index.php' if not url.endswith('/') else urljoin(url, 'index.php')
                logger.info(f"Trying fallback URL: {alt_url}")
                html = fetch(alt_url)
                if html:
                    url = alt_url
            
            if not html:
                logger.warning(f"Skipped {url}: no content")
                failed.append(url)
                continue
            
            # Extract content
            scraped = extract_main_content(html, url)
            
            if not scraped.get('title'):
                logger.warning(f"Skipped {url}: no title found")
                failed.append(url)
                continue
            
            # Save and get summary
            summary = save_tutorial(url, scraped, {})
            manifest['scraped_tutorials'].append(summary)
            
            processed.add(url)
            count += 1
            
            logger.info(f"✓ Saved: {scraped['title']}")
            logger.info(f"  Images: {len(scraped['metadata']['images'])}, "
                       f"Downloads: {len(scraped['metadata']['downloads'])}, "
                       f"Links: {len(scraped['metadata']['external_links'])}, "
                       f"Code: {len(scraped['metadata']['code_blocks'])}")
            
        except Exception as e:
            logger.error(f"Error processing {url}: {e}")
            failed.append(url)
        
        # Save checkpoint after each successful scrape
        try:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            checkpoint_path.write_text(
                json.dumps(sorted(list(processed)), indent=2),
                encoding='utf-8'
            )
        except Exception as e:
            logger.warning(f"Failed to save checkpoint: {e}")
        
        time.sleep(args.delay)
    
    # Calculate total chunks
    total_chunks = sum(t['chunks_count'] for t in manifest['scraped_tutorials'])
    manifest['total_chunks'] = total_chunks
    manifest['total_tutorials'] = len(manifest['scraped_tutorials'])
    manifest['failed_urls'] = failed
    
    # Save final manifest
    save_manifest(manifest)
    
    # Print summary
    logger.info("=" * 80)
    logger.info("SCRAPING COMPLETE")
    logger.info(f"Tutorials processed: {count}")
    logger.info(f"Total chunks created: {total_chunks}")
    logger.info(f"Failed: {len(failed)}")
    logger.info(f"Checkpoint: {checkpoint_path}")
    logger.info(f"Manifest: {MANIFEST_FILE}")
    logger.info("=" * 80)


if __name__ == '__main__':
    main()
