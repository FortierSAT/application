# core/config.py
import os
from dotenv import load_dotenv

# Load any .env file at project root
load_dotenv()

# Platform Login Credentials
CRL_USER = os.getenv("CRL_USER")
CRL_PASS = os.getenv("CRL_PASS")
I3_USER  = os.getenv("I3_USER")
I3_PASS  = os.getenv("I3_PASS")
ESCREEN_USERNAME = os.getenv("ESCREEN_USERNAME")
ESCREEN_PASSWORD = os.getenv("ESCREEN_PASSWORD")

# Zoho API Credentials
ZOHO_CLIENT_ID     = os.getenv("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN")
ZOHO_API_BASE      = os.getenv("ZOHO_API_BASE")
ZOHO_MODULE        = os.getenv("ZOHO_MODULE")

# Render Database Credentials
DB_USER     = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST     = os.getenv("DB_HOST")
DB_PORT     = os.getenv("DB_PORT")
DB_NAME     = os.getenv("DB_NAME")

# Database URL
DATABASE_URL = (
    f"postgresql://{DB_USER}:{DB_PASSWORD}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)