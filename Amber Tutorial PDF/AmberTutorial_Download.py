import os
import requests

def download_file(url, folder, filename):
    
   # Downloads a PDF from the given URL and stores it in the specified folder.
    #Creates the folder if it doesn't exist.
    # Make sure the destination folder exists
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)

    try:
        print(f"Starting download from: {url}")
        response = requests.get(url, stream=True)
        response.raise_for_status()  # Raise an error if the request failed

        # Write file in chunks to avoid large memory usage
        with open(filepath, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)

        print(f" Download complete! Saved to: {filepath}")

    except requests.exceptions.RequestException as e:
        print(f" Download failed: {e}")

if __name__ == "__main__":
    # URL for the Amber Tutorials PDF
    pdf_url = "https://ambermd.org/doc12/Amber25.pdf"

    # Folder where the file will be stored (on Desktop)
    project_root = os.path.expanduser("~/Desktop/Amber_Tutorials_PDF")
    folder_path = os.path.join(project_root, "data")

    # File name for the downloaded PDF
    filename = "Amber25.pdf"

    # Download the file
    download_file(pdf_url, folder_path, filename)

