import json
import os

# Paths to the input files
ALL_LINKS_FILE = "scraped_all_links_output/all_links_tutorials.json"
ALL_TUTORIALS_FILE = "scraped_all_tutorials_output/all_tutorials.json"

# Output file
OUTPUT_FILE = "merged_tutorials.json"

def load_json(file_path):
    """Load JSON data from file."""
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    # Load the data from both files
    print("Loading all_links_tutorials.json...")
    all_links_data = load_json(ALL_LINKS_FILE)
    
    print("Loading all_tutorials.json...")
    all_tutorials_data = load_json(ALL_TUTORIALS_FILE)
    
    # Use a dict to merge and deduplicate based on 'url'
    merged = {}
    
    # Process all_links_tutorials.json
    for item in all_links_data:
        url = item.get("url")
        if url:
            merged[url] = item
    
    # Process all_tutorials.json, overwriting if url already exists
    for item in all_tutorials_data:
        url = item.get("url")
        if url:
            merged[url] = item
    
    # Convert back to list
    merged_list = list(merged.values())
    
    # Save to output file
    print(f"Saving merged data to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(merged_list, f, indent=2, ensure_ascii=False)
    
    print(f"Merged {len(merged_list)} unique tutorials.")

if __name__ == "__main__":
    main()