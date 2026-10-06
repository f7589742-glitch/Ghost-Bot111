import sys
import inspect

sys.path.insert(0, '/home/ubuntu/bot-backend')
sys.path.insert(0, '/home/ubuntu/bot-backend/python')

import rok_headless_bot

print("--- cmd_resource_info ---")
try:
    print(inspect.getsource(rok_headless_bot.cmd_resource_info))
except Exception as e:
    print("err:", e)

print("--- cmd_player_state ---")
try:
    print(inspect.getsource(rok_headless_bot.cmd_player_state))
except Exception as e:
    print("err:", e)

print("--- all functions in rok_headless_bot ---")
for name in dir(rok_headless_bot):
    if name.startswith("cmd_"):
        print(name)
