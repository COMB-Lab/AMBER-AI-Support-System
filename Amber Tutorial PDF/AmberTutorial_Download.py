import requests

url = "https://ambermd.org/doc12/Amber25.pdf"
filename = "Amber25.pdf"

# Add headers to mimic a real browser
headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"
}

response = requests.get(url, headers=headers, stream=True)

if response.status_code == 200:
    with open(filename, "wb") as file:
        for chunk in response.iter_content(chunk_size=8192):
            file.write(chunk)
    print("Download complete:", filename)
else:
    print("Download failed with status code:", response.status_code)
