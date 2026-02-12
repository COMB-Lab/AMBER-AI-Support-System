# Setting Up the Environment
### Installing UV Package Manager
### https://github.com/astral-sh/uv
Scroll down to install to find the correct command for your system.
Since we're on a linux server, I will be using:
### On macOS and Linux.
curl -LsSf https://astral.sh/uv/install.sh | sh
to verify install try:$ uv --version

### Initialize UV
$ uv init
<br>various files will be created.

### Create new virtual environment
$ uv venv
<br>located at .venv

### The terminal will output
Activate with: "your command will be here"
copy and paste your command in the terminal and run it.

### Create requirements.txt
create requirements.txt at this same directory root
In this file, list your required packages
This file can be updated as needed.

### Create .env file
create .env file in the same directory

### Install requirements
$ uv add -r requirement.txt
<br>If the above command doesn't work, try<br>
uv pip install -r requirements.txt

## Select the Kernel

