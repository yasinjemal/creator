# PowerShell helper to setup backend virtualenv and install requirements
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
