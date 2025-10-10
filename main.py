import pathlib
from pathlib import Path

from crawler import get_monthly_archive_links, scrape_month
from parser import parse

BASE_URL = "http://archive.ambermd.org/"
OUTPUT_DIR = pathlib.Path("data") / "html"
OUTPUT2_DIR = pathlib.Path("data") / "json"
START_YEAR = 2020
END_YEAR = 2025

def main():
    monthly_links = get_monthly_archive_links(START_YEAR, END_YEAR)

    # Sort to process in chronological order

    for link in sorted(monthly_links):
        scrape_month(link)
        


    pathlist = Path(OUTPUT_DIR).glob('**/*.html')

    for path in pathlist:
        path_output = OUTPUT_DIR / path.name
        parse(path, path_output )

        relative_path = path.relative_to(OUTPUT_DIR)

        # 3. Create the full output path.
        output_path = (OUTPUT2_DIR / relative_path).with_suffix('.json')

        # 4. Call your parse function with the correct input and output paths.
        parse(path, output_path)


if __name__ == "__main__":
    main()