import requests
import pathlib

output = pathlib.Path("data") / "html" / "202204" / "0000.html"
output.parent.mkdir(parents=True, exist_ok=True)

response = None
url = "http://archive.ambermd.org/202204/0000.html"

for i in range(3):
    try:
        response = requests.get(url, timeout=10)
        print(response.text)

        response.raise_for_status()

        # If we get here, the request was successful, so we break the loop.
        print("Successfully connected and received a 200 OK status.")
        break
    except requests.exceptions.RequestException as e:
        print("Connection refused by the server")

if response:
    try:
        with open(output, "wb") as f:
            f.write(response.content)
        print(f"Successfully saved HTML to '{output}'")
    except IOError as e:
        print(f"Error saving file: {e}")


