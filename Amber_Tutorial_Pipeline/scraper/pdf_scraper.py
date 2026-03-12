import os
import requests

PDF_DIR = "downloaded_pdfs"

os.makedirs(PDF_DIR, exist_ok=True)


def download_pdf(url):

    filename = url.split("/")[-1]

    filepath = os.path.join(PDF_DIR, filename)

    if os.path.exists(filepath):
        return filepath

    r = requests.get(url)

    with open(filepath, "wb") as f:
        f.write(r.content)

    return filepath