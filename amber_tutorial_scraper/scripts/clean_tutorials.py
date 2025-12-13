import os
from bs4 import BeautifulSoup
import json


RAW_DIR = "tutorial_data/raw_html"    
CLEAN_DIR = "tutorial_data/cleaned"  
os.makedirs(CLEAN_DIR, exist_ok=True)


def clean_html_files():
    tutorials = []

    for file_name in os.listdir(RAW_DIR):
        if file_name.endswith(".html"):
            file_path = os.path.join(RAW_DIR, file_name)
            
            # Read HTML
            with open(file_path, "r", encoding="utf-8") as f:
                soup = BeautifulSoup(f, "html.parser")
            
            # Extract main content
            content_div = soup.find("div", {"id": "main-content"}) or soup
            text = content_div.get_text(separator="\n").strip()
            
            
            tutorials.append({
                "file": file_name,
                "content": text,
                "source": file_name  # you can also store URL if you want
            })

   
    with open(os.path.join(CLEAN_DIR, "tutorials_cleaned.json"), "w", encoding="utf-8") as f:
        json.dump(tutorials, f, indent=2)

    print(f"Cleaned {len(tutorials)} tutorials and saved to tutorials_cleaned.json")

if __name__ == "__main__":
    clean_html_files()
