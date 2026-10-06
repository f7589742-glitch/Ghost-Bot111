import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "rok_cloud.db")
SECRET_KEY = os.environ.get("ROK_SECRET_KEY", "7b2e91a0c4f8d5e6b1a3c7f9e2d4a6b8c0e2f4a6b8d0e2f4a6b8c0d2e4f6a8b0")
