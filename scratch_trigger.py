import urllib.request
import json

url = "http://127.0.0.1:8000/api/characters/222172865/run-task?user_id=8e7bb3f0-5e7f-4ad0-9f30-9f4e4949b25f"
payload = json.dumps({"task_name": "gather", "params": {}}).encode("utf-8")
req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req) as resp:
    print(resp.read().decode("utf-8"))
