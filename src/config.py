
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_KEY = os.getenv("KITE_API_KEY")
    API_SECRET = os.getenv("KITE_API_SECRET")
    ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")
