import re
import json
from pdfminer.high_level import extract_text
import uuid

# Check if amper pdf is there
try:
    raw_text = extract_text("Amber25.pdf")
except FileNotFoundError:
    print("Error: 'Amber25.pdf' not found. Please place the PDF in the same directory as the script.")
    exit()

def clean_text(text: str) -> str:
    # remove hyphenated line breaks
    text = re.sub(r'-\n', '', text)

    # remove page numbers (lines with only digits)
    text = re.sub(r'\n\d+\n', '\n', text)

    # remove repeated headers
    text = re.sub(r'Amber 2025\nReference Manual.*?\n', '', text)

    # normalize newlines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


text = clean_text(raw_text)

# We need to figure out the structure
CHAPTER_RE = re.compile(r'^\d+\.\s+[A-Z].+', re.MULTILINE)
SECTION_RE = re.compile(r'^\d+\.\d+\.\s+.+', re.MULTILINE)
SUBSECTION_RE = re.compile(r'^\d+\.\d+\.\d+\.\s+.+', re.MULTILINE)


def split_by_headers(text, header_regex):
    matches = list(header_regex.finditer(text))
    blocks = []

    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append(text[start:end].strip())

    return blocks


chapters = split_by_headers(text, CHAPTER_RE)


# chunking and classifying
def classify_section(title: str) -> str:
    title_lower = title.lower()

    if any(k in title_lower for k in ["introduction", "theory", "background"]):
        return "concept"
    if any(k in title_lower for k in ["usage", "running", "workflow", "example"]):
        return "workflow"
    if any(k in title_lower for k in ["installation", "setup", "building"]):
        return "setup"
    if any(k in title_lower for k in ["parameters", "options", "commands"]):
        return "reference"

    return "general"


structured = []

for chapter in chapters:
    chapter_title = chapter.splitlines()[0]

    sections = split_by_headers(chapter, SECTION_RE)
    section_entries = []

    for section in sections:
        lines = section.splitlines()
        section_title = lines[0]
        section_body = "\n".join(lines[1:]).strip()

        section_entries.append({
            # thread ID is here
            "thread_id": str(uuid.uuid4()),
            "title": section_title,
            "type": classify_section(section_title),
            "content": section_body
        })

    structured.append({
        "chapter": chapter_title,
        "sections": section_entries
    })


# export to json
with open("amber_manual_structured.json", "w", encoding="utf-8") as f:
    json.dump(structured, f, indent=2, ensure_ascii=False)

print("output written to amber_manual_structured.json")