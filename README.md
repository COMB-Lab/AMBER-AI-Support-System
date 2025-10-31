# AMBER-AI-Support-System
Amber is one of the most widely used software suites for molecular dynamics simulations in computational chemistry and biology. Over the decades, it has been refined and extended—but finding reliable solutions to errors, workflow issues, or best practices is still challenging. Knowledge is scattered across mailing list archives (1999–2025), manuals, and fragmented user discussions.

This project builds an Agentic Retrieval-Augmented Generation (RAG) System to provide clear, AI-powered support for Amber users. Instead of relying solely on model memory, our system searches historical archives and manuals, then uses an AI Agent to generate step-by-step solutions with citations.

## Privacy & Access
This is a private repository.
No code, data, or internal information may be shared externally without explicit permission from the Lab Director.
Please consult with the Lab Director before sharing results, documentation, or demonstrations outside the lab.

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


