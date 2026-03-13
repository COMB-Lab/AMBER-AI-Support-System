import os
import json

INPUT_JSON = "output/amber_tutorials.json"
OUT_DIR = "chunks"
OUT_JSON = os.path.join(OUT_DIR, "amber_chunks_big.json")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        tutorials = json.load(f)

    output = []

    for tutorial in tutorials:
        title = tutorial.get("title", "")
        text = tutorial.get("full_text", "")

        output.append({
            "id": tutorial.get("label_id", ""),
            "text": f"Amber Tutorial: {title}\n\n{text}",
            "metadata": {
                "tutorial_label_id": tutorial.get("label_id", ""),
                "tutorial_title": title,
                "tutorial_url": tutorial.get("url", ""),
                "source": "Amber Tutorials",
                "chunk_type": "full_tutorial"
            }
        })

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(output)} tutorials to {OUT_JSON}")


if __name__ == "__main__":
    main()