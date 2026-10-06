import sys
sys.path.insert(0, '/home/ubuntu/bot-backend')

try:
    from app.models.character import CharacterDAO
    print("from app.models.character WORKED")
except Exception as e:
    print("from app.models.character FAILED:", e)

try:
    from app.models import CharacterDAO, CharacterSettingsDAO
    c = CharacterDAO.get_by_role_id('222157544')
    s = CharacterSettingsDAO.get_by_character_id(c['id'])
    print("SUCCESS from app.models:", c['name'], "City:", s.get('gather', {}).get('city_x'), s.get('gather', {}).get('city_y'), "Cmds:", s.get('commanders'))
except Exception as e:
    print("app.models FAILED:", e)
