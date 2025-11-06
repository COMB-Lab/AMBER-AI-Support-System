# Amber Mailing List Web Scraper
This project automatically crawls and downloads all messages from the Amber mailing list archive starting from 2020 to 2025, organizing them into a JSON thread file.
It runs continuously using Apache Airflow, ensuring new messages are scraped and stored every 24 hours.

# Getting Started 
. macOS

. Docker Desktop 

. Python 3.7

# Start Airflow 
Make sure Docker Desktop is running, then start all Airflow services:
docker compose up -d

# Access Airflow UI
Open your browser: 

http://localhost:8080

Default credentials:

. Username: airflow 

. password: airflow 


# AmberMD Tutorials Data Extraction and Cleaning

##  Project Overview
This scraper automates the collection of all tutorials and their subpages, converts the HTML content into clean Markdown text, and outputs structured JSON files for downstream use.

# Objective 

Extract tutorial content, including main and subpages

Clean and standardize text data by removing unnecessary HTML elements

Convert cleaned HTML into Markdown for uniformity




