from bs4 import BeautifulSoup
import requests
from urllib.parse import urljoin, urlparse, urlunparse
import json, hashlib, datetime as dt, re, time

# ---------- Step 1: collect tutorial links ----------
base_url = "https://ambermd.org/tutorials/"
response = requests.get(base_url)
response.raise_for_status()
soup = BeautifulSoup(response.text, "html.parser")

raw_links = [urljoin(base_url, a["href"]) for a in soup.select("li.tutorial_toc a[href]")]

def canonicalize_url(u: str) -> str:
    """Normalize URLs so the same page maps to the same ID."""
    p = urlparse(u)
    # drop query + fragment
    path = p.path
    # normalize '/something/index.php' -> '/something/'
    if path.lower().endswith("/index.php"):
        path = path[:-10]  # remove '/index.php'
        if not path.endswith("/"):
            path += "/"
    # remove duplicate slashes in path
    path = re.sub(r"/{2,}", "/", path)
    p2 = p._replace(query="", fragment="", path=path)
    return urlunparse(p2)
 
# dedupe links by canonical form
tutorial_links = []
seen_canon = set()
for u in raw_links:
    cu = canonicalize_url(u)
    if cu not in seen_canon:
        seen_canon.add(cu)
        tutorial_links.append(cu)

print(f"Found {len(tutorial_links)} tutorial links after canonicalization/dedup")

# ---------- Step 2: helper functions ----------
def sha1(s): return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()
def now_iso(): return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc).isoformat()

def extract_tutorial(url, html):
    """Return a clean structured document for one tutorial, with a special
    handler for the <table style="padding:8px"> layout (e.g., BuildingSystems.php)."""
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text(strip=True) if soup.title else "").strip() or url

    # --- remove obvious boilerplate ---
    for sel in ["script","style","nav","footer","header",".sidebar",".toc"]:
        for t in soup.select(sel):
            t.decompose()

    # --- SPECIAL CASE: BuildingSystems-style table content ---
    table = soup.find("table", attrs={"style": re.compile("padding", re.I)})
    if table:
        md_parts = []

        def abs_url(href: str) -> str:
            if not href:
                return ""
            return href if href.startswith("http") else urljoin(url, href)

        for br in table.find_all("br"):
            br.replace_with("\n")

        for el in table.descendants:
            name = getattr(el, "name", None)
            if name == "h1":
                md_parts.append(f"# {el.get_text(' ', strip=True)}\n")
            elif name == "h2":
                md_parts.append(f"## {el.get_text(' ', strip=True)}\n")
            elif name == "a":
                text = el.get_text(" ", strip=True)
                href = abs_url(el.get("href", ""))
                if text:
                    md_parts.append(f"[{text}]({href})\n")
            elif name == "p":
                txt = el.get_text(" ", strip=True)
                if txt:
                    md_parts.append(txt + "\n")

        content_md = "\n".join(md_parts).strip()
        has_code = "```" in content_md
        equations = len(re.findall(r"(\\\[.*?\\\]|\\\(.*?\\\)|\$\$.*?\$\$)", html, re.S))

        section_path = []
        h1 = table.find("h1")
        if h1: section_path.append(h1.get_text(" ", strip=True))
        h2 = table.find("h2")
        if h2: section_path.append(h2.get_text(" ", strip=True))

        content_text = re.sub(r"[#*_`]", "", content_md)

        canon = canonicalize_url(url)
        base_id = sha1(canon)

        return {
            "id": base_id,
            "title": title,
            "url": canon,
            "tutorial_id": f"ambermd-tut-{base_id[:8]}",
            "section_path": section_path,
            "content_md": content_md,
            "content_text": content_text,
            "tags": ["amber", "tutorial"],
            "has_code": has_code,
            "equations": equations,
            "captured_at": now_iso()
        }

    # --- FALLBACK: generic extractor ---
    has_code = False
    for pre in soup.find_all("pre"):
        has_code = True
        code = pre.get_text("\n", strip=False).replace("\r\n", "\n")
        pre.replace_with(soup.new_string(f"\n```\n{code}\n```\n"))

    md = []
    for el in soup.find_all(["h1","h2","h3","h4","p","li"]):
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        if el.name.startswith("h"):
            md.append("#"*int(el.name[1]) + " " + text)
        elif el.name == "li":
            md.append("- " + text)
        else:
            md.append(text)
    content_md = "\n".join(md)
    content_text = re.sub(r"```.*?```", "", content_md, flags=re.S)

    canon = canonicalize_url(url)
    base_id = sha1(canon)

    return {
        "id": base_id,
        "title": title,
        "url": canon,
        "tutorial_id": f"ambermd-tut-{base_id[:8]}",
        "section_path": [h.get_text(" ", strip=True) for h in soup.find_all(["h1","h2"])],
        "content_md": content_md,
        "content_text": content_text,
        "tags": ["amber", "tutorial"],
        "has_code": has_code,
        "equations": len(re.findall(r"(\\\[.*?\\\]|\\\(.*?\\\)|\$\$.*?\$\$)", html, re.S)),
        "captured_at": now_iso()
    }

# ---------- Step 3: crawl and extract (with unique IDs guaranteed) ----------
seen_ids = set()

def uniquify_id(base_id: str) -> str:
    if base_id not in seen_ids:
        seen_ids.add(base_id)
        return base_id
    # collision → suffix with #dupXXXX
    n = 1
    uid = f"{base_id}#dup{n:04d}"
    while uid in seen_ids:
        n += 1
        uid = f"{base_id}#dup{n:04d}"
    seen_ids.add(uid)
    return uid

with open("amber_tutorials.jsonl", "w", encoding="utf-8") as f:
    for i, link in enumerate(tutorial_links, 1):
        try:
            print(f"[{i}/{len(tutorial_links)}] Fetching {link}")
            html = requests.get(link, timeout=25).text
            doc = extract_tutorial(link, html)

            # enforce unique id at write time
            uid = uniquify_id(doc["id"])
            if uid != doc["id"]:
                # keep tutorial_id stable, only change the storage id
                doc["id"] = uid

            f.write(json.dumps(doc, ensure_ascii=False) + "\n")
            time.sleep(0.7)
        except Exception as e:
            print(f"⚠️  Skipping {link}: {e}")

print("Saved cleaned tutorial data to amber_tutorials.jsonl")
