# run_month.py
import sys
import os

from crawler import scrape_month, BASE_URL
from parse_month import main as parse_month
from merge_month import merge_month

# Default absolute root where html/json/threads live
DEFAULT_DATA_ROOT = "/opt/chromadb/data/data"

def run(month: str, data_root: str = DEFAULT_DATA_ROOT):
    # Force all imported modules to use the same root (even in Airflow)
    os.environ["AMBER_DATA_ROOT"] = data_root

    month_url = f"{BASE_URL}{month}/"
    scrape_month(month_url)
    parse_month(month)
    merge_month(month)

if __name__ == "__main__":
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print("Usage: python run_month.py YYYYMM [DATA_ROOT]")
        raise SystemExit(2)

    month = sys.argv[1]
    data_root = sys.argv[2] if len(sys.argv) == 3 else DEFAULT_DATA_ROOT
    run(month, data_root=data_root)
