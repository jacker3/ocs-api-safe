import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    OCS_API_KEY = os.getenv('OCS_API_KEY')
    OCS_BASE_URL = os.getenv('OCS_BASE_URL', 'https://connector.b2b.ocs.ru/api/v2')
    FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'