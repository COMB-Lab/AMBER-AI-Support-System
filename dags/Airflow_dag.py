from __future__ import annotations

import pendulum

from airflow.models.dag import DAG
from airflow.operators.python import PythonOperator

import pathlib
from pathlib import Path

from Airflow_Crawler import get_monthly_archive_links, scrape_month
from Airflow_Parser import parse
from Airflow_Joiner import join_threads

# Define constants
BASE_URL = "http://archive.ambermd.org/"
OUTPUT_DIR_HTML = pathlib.Path("data") / "html"
OUTPUT_DIR_JSON = pathlib.Path("data") / "json"
OUTPUT_DIR_THREADS = pathlib.Path("data") / "threads"
START_YEAR = 2020
END_YEAR = pendulum.now().year

def scrape_data():

    # Scrapes the website for new data.
    monthly_links = get_monthly_archive_links(START_YEAR, END_YEAR)
    for link in sorted(monthly_links):
        scrape_month(link)

def parse_data():

    # Parses the scraped HTML files into JSON.
    pathlist = Path(OUTPUT_DIR_HTML).glob('**/*.html')
    for path in pathlist:
        relative_path = path.relative_to(OUTPUT_DIR_HTML)
        output_path = (OUTPUT_DIR_JSON / relative_path).with_suffix('.json')
        parse(path, output_path)

def join_data():

    # Joins the parsed JSON files into threads.
    join_threads()

with DAG(
    dag_id="amberAI_scraping_dag",
    schedule="@daily",
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    catchup=False,
    tags=["scraping", "amber"],
    doc_md="""
    ### Amber Mailing List Scraping DAG
    This DAG scrapes, parses, and joins data from the Amber mailing list archive.
    """,
) as dag:
    scrape_task = PythonOperator(
        task_id="scrape_html",
        python_callable=scrape_data,
    )

    parse_task = PythonOperator(
        task_id="parse_to_json",
        python_callable=parse_data,
    )

    join_task = PythonOperator(
        task_id="join_threads",
        python_callable=join_data,
    )

    scrape_task >> parse_task >> join_task