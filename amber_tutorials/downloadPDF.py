import os
import requests

def download_pdf(url: str) -> bool:

    # Request URL and get response object
    response = requests.get(url, stream=True)

    # Isolate PDF filename from URL
    pdf_file_name = os.path.basename(url)
    if response.status_code == 200:

        # PDF is saved here
        filepath = os.path.join(os.getcwd(), pdf_file_name)

        with open(filepath, 'wb') as pdf_object:
            pdf_object.write(response.content)
            print(f'{pdf_file_name} was successfully saved!')
            return True
    else:
        print(f'Could not download {pdf_file_name},')
        print(f'HTTP response status code: {response.status_code}')
        return False


if __name__ == '__main__':
    # URL from which pdfs to be downloaded
    URL = 'https://ambermd.org/doc12/Amber25.pdf'
    download_pdf(URL)