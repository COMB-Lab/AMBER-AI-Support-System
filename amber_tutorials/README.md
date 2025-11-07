# AMBER-AI-Support-System-Scraper

This script automates the process of scraping and cleaning content from (https://ambermd.org/tutorials/).

It performs the following steps:
1.  Scrapes the main tutorial index page to discover all available tutorial URLs.
2.  Visits each unique tutorial URL.
3.  Extracts the main content from the page, removing unneeded elements
4.  Converts the cleaned HTML content into Markdown
5.  Saves the content of each tutorial as a separate JSON file

# How-To-Run

Open this script in your environment and download the requirements

ALl output will be saved to the root of your project folder in : amber_tutorials/amber_tutorials_output/