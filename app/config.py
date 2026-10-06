import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "rok_cloud.db")
SECRET_KEY = os.environ.get("ROK_SECRET_KEY", "b400f6db6fcbd4a4c81cca99853cbdd9d5b51f832c12dbebd71ed728900fbb58")
