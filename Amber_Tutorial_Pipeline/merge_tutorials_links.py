import json
import os

INPUT_FILES = [
    "scraped_all_tutorials_output/all_tutorials.json",
    "scraped_all_links_output/all_links_tutorials.json",
]
OUTPUT_FOLDER = "scraped_combined_tutorials_output"
OUTPUT_FILE = os.path.join(OUTPUT_FOLDER, "combined_tutorials.json")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    merged = {}
    total_read = 0

    for path in INPUT_FILES:
        print(f"Loading {path}")
        data = load_json(path)
        if not isinstance(data, list):
            raise ValueError(f"Expected list in {path}, got {type(data).__name__}")

        for item in data:
            total_read += 1
            url = item.get("url")
            if not url:
                continue
            if url not in merged:
                merged[url] = item

    combined = list(merged.values())
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)

    print(f"Loaded {total_read} total items")
    print(f"Wrote {len(combined)} unique items to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
