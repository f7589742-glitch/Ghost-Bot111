import json

fleet = json.load(open("/home/ubuntu/bot-backend/accounts_fleet.json"))
for acc in fleet:
    for c in acc.get("characters", []):
        if str(c.get("role_id")) == "232812223":
            print("Found account:", acc.get("email"))
            print("Character info:", c)
