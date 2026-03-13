import os
import re
import json

# -----------------------------
# Configuration
# -----------------------------
INPUT_JSON = "output/amber_tutorials.json"
OUT_DIR = "chunks"
OUT_JSON = os.path.join(OUT_DIR, "amber_chunks.json")

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200


# -----------------------------
# Helpers
# -----------------------------
def normalize_text(text):
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    text = normalize_text(text)
    if not text:
        return []

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end == text_len:
            break

        start += chunk_size - overlap

    return chunks


# -----------------------------
# Main
# -----------------------------
def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        tutorials = json.load(f)

    all_chunks = []

    for tutorial in tutorials:
        tutorial_label_id = tutorial.get("label_id", "")
        tutorial_title = tutorial.get("title", "")
        tutorial_url = tutorial.get("url", "")

        for page_index, page in enumerate(tutorial.get("pages", [])):
            page_url = page.get("url", tutorial_url)
            page_title = page.get("page_title", "")

            for section_index, section in enumerate(page.get("sections", [])):
                heading = section.get("heading", "Introduction")
                text = section.get("text", "")
                section_type = section.get("type", "text")

                chunks = chunk_text(text)

                for chunk_index, chunk in enumerate(chunks):
                    chunk_id = (
                        f"{tutorial_label_id}"
                        f"_p{page_index}"
                        f"_s{section_index}"
                        f"_c{chunk_index}"
                    )

                    all_chunks.append({
                        "id": chunk_id,
                        "text": chunk,
                        "tutorial_label_id": tutorial_label_id,
                        "tutorial_title": tutorial_title,
                        "tutorial_url": tutorial_url,
                        "page_url": page_url,
                        "page_title": page_title,
                        "heading": heading,
                        "section_type": section_type,
                        "page_index": page_index,
                        "section_index": section_index,
                        "chunk_index": chunk_index
                    })

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, indent=2, ensure_ascii=False)

    print("Done.")
    print(f"Total chunks: {len(all_chunks)}")
    print(f"Saved to: {OUT_JSON}")


if __name__ == "__main__":
    main()