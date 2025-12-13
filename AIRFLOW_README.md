AMBER DAILY SCRAPER AUTOMATION USING APACHE AIRFLOW (AIRFLOW 2.9)

This project automates an existing Python web scraping workflow to run automatically every 24 hours using 
Apache Airflow 2.9 on Ubuntu. The scraper is reused with minimal modification and runs without manual intervention. 
All execution output and errors are captured through Airflow task logs. No database is required; scraped data is 
stored as files.

WHAT THIS PROJECT DOES

• Runs an existing Python scraper automatically every 24 hours
• Uses Apache Airflow for scheduling and orchestration
• Reuses the original scraping scripts without rewriting them
• Captures execution output and errors using Airflow task logs
• Supports retries for reliability
• Stores scraped data as files (no database required)

PROJECT STRUCTURE

amber-airflow-scraper/
dags/
amber_daily_scraper.py

amber_scraper_mar2024.py
fetch_single_email.py
parse_single_email.py
AIRFLOW_README.md
.gitignore
README.txt

SYSTEM REQUIREMENTS

• Ubuntu (native Linux or Ubuntu virtual machine)
• Python 3.x
• Apache Airflow 2.9.x
• VirtualBox (if using a VM)
• VirtualBox Guest Additions (required for shared folders)

PYTHON REQUIREMENTS

• apache-airflow==2.9.x
• aiofiles
• any additional dependencies required by the scraper

All dependencies should be installed inside a Python virtual environment.

VIRTUALBOX SHARED FOLDER SETUP (RECOMMENDED)

This project commonly runs the scraper from a VirtualBox shared folder so the Ubuntu VM can access existing code without copying it.

Steps:

Power off the Ubuntu VM

Open VirtualBox → VM Settings → Shared Folders

Add a new shared folder

Folder Path: your Windows project folder
Example: C:\Users<YOUR_NAME>\OneDrive\Desktop\Amber

Folder Name: Amber

Check “Auto-mount” and “Make Permanent”

Start the VM

The shared folder will be available in Ubuntu at:
/media/sf_Amber

If this folder does not appear, install VirtualBox Guest Additions and reboot.

SETUP INSTRUCTIONS (UBUNTU)
STEP 1: CREATE A PROJECT ENVIRONMENT
mkdir -p ~/amber
cd ~/amber
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel

STEP 2: INSTALL DEPENDENCIES
pip install -r requirements.txt

STEP 3: CONFIGURE AIRFLOW HOME
export AIRFLOW_HOME=~/amber/airflow_home
mkdir -p $AIRFLOW_HOME/dags

(Optional: make permanent)
echo 'export AIRFLOW_HOME=~/amber/airflow_home' >> ~/.bashrc
source ~/.bashrc

STEP 4: INITIALIZE AIRFLOW DATABASE (AIRFLOW 2.9)
airflow db migrate

STEP 5: CREATE ADMIN USER
airflow users create

Verify:
airflow users list

INSTALL THE DAG

Copy the DAG into the Airflow dags folder:
cp dags/amber_daily_scraper.py $AIRFLOW_HOME/dags/

RUN AIRFLOW (TWO TERMINALS REQUIRED)
TERMINAL 1: WEB SERVER
cd ~/amber
source venv/bin/activate
export AIRFLOW_HOME=~/amber/airflow_home
airflow webserver --port 8080

TERMINAL 2: SCHEDULER
cd ~/amber
source venv/bin/activate
export AIRFLOW_HOME=~/amber/airflow_home
airflow scheduler

ACCESS AIRFLOW UI
Open a browser and go to:
• http://localhost:8080
 (NAT / port forwarding)
OR
• http://<VM_IP>:8080 (Bridged adapter)
