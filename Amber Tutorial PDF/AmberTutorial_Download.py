import requests

url = "https://ambermd.org/doc12/Amber25.pdf"
filename = "Amber25.pdf"

response = requests.get(url, stream=True)

if response.status_code == 200:
    with open(filename, "wb") as file:
        for chunk in response.iter_content(chunk_size=8192):
            file.write(chunk)
    print("Download complete:", filename)
else:
    print("Download failed with status code:", response.status_code)


