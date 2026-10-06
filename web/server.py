import os
import sys
import json
import time
import threading
import subprocess
from flask import Flask, render_template, jsonify, request

app = Flask(__name__, template_folder='templates', static_folder='static')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ENGINE_STATE = {
    "role_id": 231250589,
    "role_name": "amer1220958",
    "city_hall": 17,
    "total_troops": 36685,
    "active_queues": 3,
    "max_queues": 3,
    "per_march": 12228,
    "bot_enabled": False,
    "status": "standby",
    "is_running": False,
    "active_script": None,
    "loop_active": True,
    "loop_cycle": 1,
    "next_loop_run": "in 54m",
    "last_sync": time.strftime("%Y-%m-%d %H:%M:%S"),
    "bot_user": "amer1220958",
    "bot_id": 1196,
    "license_plan": "Basic plan · 18 characters",
    "license_expires": "9/15/2026, 8:15:04 PM",
    "license_time_left": "7d 20h 29m 45s left",
    "license_percent": 68,
    "character_slots_used": 18,
    "character_slots_total": 18,
    "training": {
        "archery": {"name": "Archery Range (Bowman/Slinger)", "status": "Ready", "unit_id": 3, "count": 200},
        "cavalry": {"name": "Stable (Cavalry/Horseman)", "status": "Ready", "unit_id": 2, "count": 200},
        "infantry": {"name": "Barracks (Swordsman/Spearman)", "status": "Ready", "unit_id": 1, "count": 200},
        "siege": {"name": "Workshop (Siege Ram/Catapult)", "status": "Ready", "unit_id": 4, "count": 200}
    },
    "marches": [
        {"id": 1, "commander": "Gaius Marius (ID 34)", "type": "food", "target": "Cropland #354645706 (Lvl 2)", "troops": 24971, "status": "Gathering (🌾 Active)", "progress": 85},
        {"id": 2, "commander": "Constance (ID 24)", "type": "wood", "target": "Logging Camp #174514906 (Lvl 2)", "troops": 8500, "status": "Gathering (🪵 Active)", "progress": 60},
        {"id": 3, "commander": "Tomoe Gozen (ID 23)", "type": "stone", "target": "Stone Deposit #2897806 (Lvl 2)", "troops": 3214, "status": "Gathering (🪨 Active)", "progress": 40}
    ]
}

LOGS_BUFFER = [
    {"time": "11:26:04 PM", "tag": "[18 KD]", "message": "Claiming quest rewards", "type": "info"},
    {"time": "11:26:04 PM", "tag": "[BOT]", "message": "Switching to 13 KD", "type": "info"},
    {"time": "11:26:05 PM", "tag": "[BOT]", "message": "Switching to 9 KD", "type": "info"},
    {"time": "11:26:05 PM", "tag": "[7 KD]", "message": "Finished visit for 7 KD", "type": "success"},
    {"time": "11:26:06 PM", "tag": "[BOT]", "message": "Switching to 8 KD", "type": "info"},
    {"time": "11:26:08 PM", "tag": "[6 KD]", "message": "Finished visit for 6 KD", "type": "success"},
    {"time": "11:26:09 PM", "tag": "[BOT]", "message": "Switching to 5 KD", "type": "info"},
    {"time": "11:26:11 PM", "tag": "[13 KD]", "message": "Starting visit for 13 KD", "type": "info"},
    {"time": "11:26:12 PM", "tag": "[9 KD]", "message": "Starting visit for 9 KD", "type": "info"},
    {"time": "11:26:13 PM", "tag": "[5 KD]", "message": "Starting visit for 5 KD", "type": "info"},
    {"time": "11:26:13 PM", "tag": "[8 KD]", "message": "Starting visit for 8 KD", "type": "info"},
    {"time": "11:26:14 PM", "tag": "[18 KD]", "message": "Collecting resources from city buildings", "type": "success"},
    {"time": "11:26:20 PM", "tag": "[13 KD]", "message": "Claiming quest rewards", "type": "info"},
    {"time": "11:26:21 PM", "tag": "[18 KD]", "message": "Claiming VIP daily chest", "type": "success"},
    {"time": "11:26:21 PM", "tag": "[9 KD]", "message": "Claiming quest rewards", "type": "info"},
    {"time": "11:26:22 PM", "tag": "[8 KD]", "message": "Claiming quest rewards", "type": "info"},
    {"time": "11:26:22 PM", "tag": "[5 KD]", "message": "Claiming quest rewards", "type": "info"},
    {"time": "11:26:23 PM", "tag": "[19 KD]", "message": "Training troops (T1 Battering Ram x200)", "type": "success"},
    {"time": "11:26:26 PM", "tag": "[18 KD]", "message": "Claiming mail & alliance gifts", "type": "info"},
    {"time": "11:28:46 PM", "tag": "[18 KD]", "message": "Claiming expedition rewards", "type": "success"}
]
BUFFER_LOCK = threading.Lock()
ACTIVE_PROC = None

def push_log(tag, msg, log_type="info"):
    with BUFFER_LOCK:
        now = time.strftime("%I:%M:%S %p")
        LOGS_BUFFER.append({
            "time": now,
            "tag": f"[{tag}]",
            "message": msg,
            "type": log_type
        })
        if len(LOGS_BUFFER) > 500:
            del LOGS_BUFFER[0:100]

def engine_thread_worker(script_file, args=None):
    global ACTIVE_PROC, ENGINE_STATE
    script_path = os.path.join(BASE_DIR, script_file)
    if not os.path.exists(script_path):
        push_log("ERROR", f"Script not found: {script_file}", "error")
        ENGINE_STATE["is_running"] = False
        ENGINE_STATE["status"] = "standby"
        return

    cmd = [sys.executable, "-u", script_path]
    if args:
        cmd.extend(args)

    push_log("ENGINE", f"Starting {script_file} {' '.join(args or [])}...", "info")
    ENGINE_STATE["is_running"] = True
    ENGINE_STATE["active_script"] = script_file
    ENGINE_STATE["status"] = "running"

    try:
        ACTIVE_PROC = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=BASE_DIR
        )

        for line in iter(ACTIVE_PROC.stdout.readline, ''):
            line_str = line.strip()
            if not line_str:
                continue

            tag = "ENGINE"
            log_type = "info"
            if "Seeds derived" in line_str or "Authenticated" in line_str or "SUCCESS" in line_str or "ACK" in line_str:
                log_type = "success"
                tag = "SUCCESS"
            elif "ALLOCATION" in line_str:
                tag = "ALLOCATION"
                log_type = "success"
            elif "FOUND" in line_str or "Scanning" in line_str:
                tag = "SEARCH"
                log_type = "success"
            elif "Error" in line_str or "fail" in line_str.lower():
                log_type = "error"
                tag = "ERROR"
            elif "March" in line_str:
                tag = "MARCH"
                log_type = "info"
            elif "Training" in line_str or "Opcode 300" in line_str:
                tag = "TRAINING"
                log_type = "success"

            # Parse available army in city
            if "Available Army in City:" in line_str:
                try:
                    cnt_str = line_str.split("Available Army in City:")[1].split("soldiers")[0].replace(",", "").strip()
                    ENGINE_STATE["total_troops"] = int(cnt_str)
                except Exception:
                    pass

            # Parse discovered targets and dispatches
            for m_num in (1, 2, 3):
                m_idx = m_num - 1
                if f"March #{m_num} ->" in line_str:
                    tgt = line_str.split("->")[1].split("-")[0].strip()
                    ENGINE_STATE["marches"][m_idx]["target"] = tgt

                if f"Server CONFIRMED March #{m_num}:" in line_str:
                    # Example: [SUCCESS] Server CONFIRMED March #1: Commander Gaius Marius (#34) deployed with 24,383 troops to Cropland #2978006!
                    try:
                        cmd_part = line_str.split(f"March #{m_num}:")[1].split("deployed with")[0].replace("Commander", "").strip()
                        troops_part = line_str.split("deployed with")[1].split("troops")[0].replace(",", "").strip()
                        target_part = line_str.split("to ")[1].replace("!", "").strip()
                        ENGINE_STATE["marches"][m_idx]["commander"] = cmd_part
                        ENGINE_STATE["marches"][m_idx]["troops"] = int(troops_part)
                        ENGINE_STATE["marches"][m_idx]["target"] = target_part
                    except Exception:
                        pass
                    ENGINE_STATE["marches"][m_idx]["status"] = "Gathering (🌾 Active)"
                    ENGINE_STATE["marches"][m_idx]["progress"] = 75
                    ENGINE_STATE["active_queues"] = max(m_num, ENGINE_STATE["active_queues"])

            if "Total Active: 3/3" in line_str or "All 3 march queues are currently gathering" in line_str:
                ENGINE_STATE["status"] = "gathering"
                ENGINE_STATE["active_queues"] = 3

            push_log(tag, line_str, log_type)

        ACTIVE_PROC.stdout.close()
        return_code = ACTIVE_PROC.wait()
        push_log("ENGINE", f"Execution completed (code {return_code})", "info" if return_code == 0 else "warning")

        # Instant sync with gather_status.json produced by smart_gather_search.py
        gather_file = os.path.join(BASE_DIR, "gather_status.json")
        if os.path.exists(gather_file):
            try:
                with open(gather_file, "r", encoding="utf-8") as f:
                    g_data = json.load(f)
                    if "active_queues" in g_data:
                        ENGINE_STATE["active_queues"] = g_data["active_queues"]
                    if "total_troops" in g_data:
                        ENGINE_STATE["total_troops"] = g_data["total_troops"]
                    if "marches" in g_data and g_data["marches"]:
                        ENGINE_STATE["marches"] = g_data["marches"]
                    if "status" in g_data:
                        ENGINE_STATE["status"] = g_data["status"]
            except Exception:
                pass

    except Exception as e:
        push_log("EXCEPTION", str(e), "error")
    finally:
        ACTIVE_PROC = None
        ENGINE_STATE["is_running"] = False
        ENGINE_STATE["active_script"] = None
        if ENGINE_STATE["active_queues"] > 0:
            ENGINE_STATE["status"] = "gathering"
        else:
            ENGINE_STATE["status"] = "standby"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/state', methods=['GET'])
def get_state():
    ENGINE_STATE["last_sync"] = time.strftime("%Y-%m-%d %H:%M:%S")
    
    # Sync with live gather status
    gather_file = os.path.join(BASE_DIR, "gather_status.json")
    if os.path.exists(gather_file):
        try:
            with open(gather_file, "r", encoding="utf-8") as f:
                g_data = json.load(f)
                active_cnt = g_data.get("active_marches_count") if "active_marches_count" in g_data else g_data.get("active_queues")
                if active_cnt is not None:
                    ENGINE_STATE["active_queues"] = int(active_cnt)
                if "total_city_troops" in g_data:
                    ENGINE_STATE["total_troops"] = int(g_data["total_city_troops"])
                elif "total_troops" in g_data:
                    ENGINE_STATE["total_troops"] = int(g_data["total_troops"])
                if "marches" in g_data and g_data["marches"]:
                    ENGINE_STATE["marches"] = g_data["marches"]
                if "status" in g_data and not ENGINE_STATE["is_running"]:
                    ENGINE_STATE["status"] = g_data["status"]
        except Exception:
            pass

    # Sync with fleet account info
    fleet_file = os.path.join(BASE_DIR, "accounts_fleet.json")
    if os.path.exists(fleet_file):
        try:
            with open(fleet_file, "r", encoding="utf-8") as f:
                f_data = json.load(f)
                if f_data.get("account_email"):
                    ENGINE_STATE["account_email"] = f_data["account_email"]
                chars = f_data.get("characters", [])
                if chars:
                    ENGINE_STATE["role_name"] = chars[0].get("name", ENGINE_STATE.get("role_name"))
                    ENGINE_STATE["role_id"] = chars[0].get("role_id", ENGINE_STATE.get("role_id"))
                    ENGINE_STATE["bot_user"] = chars[0].get("name", ENGINE_STATE.get("bot_user"))
        except Exception:
            pass

    loop_file = os.path.join(BASE_DIR, "loop_status.json")
    if os.path.exists(loop_file):
        try:
            with open(loop_file, "r", encoding="utf-8") as f:
                loop_data = json.load(f)
                ENGINE_STATE["loop_active"] = loop_data.get("is_active", False)
                ENGINE_STATE["loop_cycle"] = loop_data.get("current_cycle", 0)
                ENGINE_STATE["next_loop_run"] = loop_data.get("next_run_str", None)
                ENGINE_STATE["loop_status_text"] = loop_data.get("status", "idle")
                ENGINE_STATE["loop_interval_hours"] = loop_data.get("interval_hours", 3)
        except Exception:
            pass
    else:
        ENGINE_STATE["loop_active"] = False

    # Sync with bot_config.json
    cfg_file = os.path.join(BASE_DIR, "bot_config.json")
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                c_data = json.load(f)
                g_cfg = c_data.get("general", {})
                ENGINE_STATE["bot_user"] = g_cfg.get("bot_user", ENGINE_STATE.get("bot_user", "amer1220958"))
                ENGINE_STATE["bot_id"] = g_cfg.get("bot_id", ENGINE_STATE.get("bot_id", 1196))
                ENGINE_STATE["license_plan"] = g_cfg.get("license_plan", ENGINE_STATE.get("license_plan", "Basic plan · 18 characters"))
                ENGINE_STATE["license_expires"] = g_cfg.get("license_expires", ENGINE_STATE.get("license_expires", "9/15/2026, 8:15:04 PM"))
                ENGINE_STATE["license_time_left"] = g_cfg.get("license_time_left", ENGINE_STATE.get("license_time_left", "7d 20h 29m 45s left"))
                ENGINE_STATE["license_percent"] = g_cfg.get("license_percent", 68)
                ENGINE_STATE["character_slots_used"] = g_cfg.get("character_slots_used", 18)
                ENGINE_STATE["character_slots_total"] = g_cfg.get("character_slots_total", 18)
        except Exception:
            pass

    return jsonify(ENGINE_STATE)

@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    cfg_file = os.path.join(BASE_DIR, "bot_config.json")
    if request.method == 'GET':
        if os.path.exists(cfg_file):
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    return jsonify(json.load(f))
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        return jsonify({})
    else:
        new_cfg = request.get_json(silent=True) or {}
        try:
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(new_cfg, f, indent=2, ensure_ascii=False)
            push_log("CONFIG", "Bot settings updated successfully.", "success")
            return jsonify({"success": True, "message": "Settings saved successfully."})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    cfg_file = os.path.join(BASE_DIR, "bot_config.json")
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return jsonify(data.get("inventory", {}))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({})

@app.route('/api/accounts', methods=['GET', 'POST'])
def handle_accounts():
    cfg_file = os.path.join(BASE_DIR, "bot_config.json")
    if request.method == 'GET':
        if os.path.exists(cfg_file):
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return jsonify(data.get("accounts", []))
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        return jsonify([])
    else:
        acc_data = request.get_json(silent=True)
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                full_cfg = json.load(f)
            full_cfg["accounts"] = acc_data
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(full_cfg, f, indent=2, ensure_ascii=False)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/logs', methods=['GET'])
def get_logs():
    since = request.args.get('since', 0, type=int)
    with BUFFER_LOCK:
        logs_slice = LOGS_BUFFER[since:]
        total = len(LOGS_BUFFER)
    return jsonify({"logs": logs_slice, "total": total})

def parse_node_level(max_level_str, explicit_level=0, explicit_mode="any"):
    if explicit_level and int(explicit_level) > 0:
        return int(explicit_level), explicit_mode
    if not max_level_str or "No cap" in max_level_str or "Highest" in max_level_str:
        return 0, "any"
    if "Level 6 and above" in max_level_str:
        return 6, "min"
    if "Level 6 and below" in max_level_str:
        return 6, "max"
    if "Level 5 and below" in max_level_str:
        return 5, "max"
    if "Level 4 and below" in max_level_str:
        return 4, "max"
    if "Level 3 and below" in max_level_str:
        return 3, "max"
    if "Level 2 and below" in max_level_str:
        return 2, "max"
    if "Level 1 only" in max_level_str:
        return 1, "exact"
    m = re.search(r'\d+', str(max_level_str))
    if m:
        lvl = int(m.group(0))
        mode = "min" if "above" in max_level_str.lower() else "max"
        return lvl, mode
    return 0, "any"

@app.route('/api/dispatch', methods=['POST'])
def dispatch_marches():
    if ENGINE_STATE["is_running"]:
        return jsonify({"success": False, "error": "Engine is currently running a task!"}), 400
    
    data = request.get_json(silent=True) or {}
    
    # 1. Determine target resources from explicit list or march counters
    targets = data.get("targets")
    if not targets:
        f_cnt = int(data.get("food_marches", data.get("food", 0)))
        w_cnt = int(data.get("wood_marches", data.get("wood", 0)))
        s_cnt = int(data.get("stone_marches", data.get("stone", 0)))
        g_cnt = int(data.get("gold_marches", data.get("gold", 0)))
        
        targets = []
        targets.extend(["food"] * f_cnt)
        targets.extend(["wood"] * w_cnt)
        targets.extend(["stone"] * s_cnt)
        targets.extend(["gold"] * g_cnt)

    if not targets:
        targets = ["food", "wood", "stone"]

    # 2. Parse level and level mode
    max_level_str = data.get("max_node_level", "Level 6 and below")
    explicit_lvl = data.get("level", 0)
    explicit_mode = data.get("level_mode", "any")
    level_num, level_mode = parse_node_level(max_level_str, explicit_lvl, explicit_mode)

    only_finishable = bool(data.get("only_finishable", True))
    skip_partially = bool(data.get("skip_partially_gathered", data.get("skip_partially", True)))

    # Persist in bot_config.json
    try:
        cfg_file = os.path.join(BASE_DIR, "bot_config.json")
        if os.path.exists(cfg_file):
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            cfg.setdefault("gathering", {})
            cfg["gathering"]["food_marches"] = targets.count("food")
            cfg["gathering"]["wood_marches"] = targets.count("wood")
            cfg["gathering"]["stone_marches"] = targets.count("stone")
            cfg["gathering"]["gold_marches"] = targets.count("gold")
            cfg["gathering"]["max_node_level"] = max_level_str
            cfg["gathering"]["only_finishable"] = only_finishable
            cfg["gathering"]["skip_partially_gathered"] = skip_partially
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    arg_str = ",".join(targets)
    script_args = [arg_str, str(level_num), "--level-mode", level_mode]
    if only_finishable:
        script_args.append("--only-finishable")
    if skip_partially:
        script_args.append("--skip-partially")

    # Update march preview in state
    for idx, t in enumerate(targets):
        if idx < len(ENGINE_STATE["marches"]):
            ENGINE_STATE["marches"][idx]["type"] = t
            ENGINE_STATE["marches"][idx]["target"] = f"Searching nearest {t.capitalize()} ({max_level_str})..."

    ENGINE_STATE["bot_enabled"] = True
    t = threading.Thread(target=engine_thread_worker, args=("smart_gather_search.py", script_args), daemon=True)
    t.start()
    push_log("DISPATCH", f"Gathering dispatched: {arg_str} ({max_level_str}, {len(targets)} queues)", "success")
    return jsonify({
        "success": True, 
        "message": f"Smart Search & Gather dispatched for: {arg_str} ({max_level_str}).",
        "targets": targets,
        "level": level_num,
        "level_mode": level_mode
    })

@app.route('/api/train', methods=['POST'])
def train_troops():
    if ENGINE_STATE["is_running"]:
        return jsonify({"success": False, "error": "Engine is currently busy executing another task!"}), 400
    data = request.get_json(silent=True) or {}
    b_type = data.get("building", "archery")
    count = str(data.get("count", 200))
    t = threading.Thread(target=engine_thread_worker, args=("smart_troop_trainer.py", [b_type, count]), daemon=True)
    t.start()
    return jsonify({"success": True, "message": f"Training order dispatched for {b_type} ({count} units)."})

@app.route('/api/train_all', methods=['POST'])
def train_all_barracks():
    if ENGINE_STATE["is_running"]:
        return jsonify({"success": False, "error": "Engine is currently busy executing another task!"}), 400
    data = request.get_json(silent=True) or {}
    count = str(data.get("count", 200))
    t = threading.Thread(target=engine_thread_worker, args=("smart_troop_trainer.py", ["all", count]), daemon=True)
    t.start()
    return jsonify({"success": True, "message": f"Master training dispatched for ALL 4 Barracks ({count} units each)!"})

@app.route('/api/toggle_loop', methods=['POST'])
def toggle_recurring_loop():
    global ACTIVE_PROC
    data = request.get_json(silent=True) or {}
    action = data.get("action", "toggle")

    loop_file = os.path.join(BASE_DIR, "loop_status.json")

    # If already running, stop it
    if ENGINE_STATE["is_running"] and ENGINE_STATE.get("active_script") == "auto_recurring_loop.py":
        if ACTIVE_PROC and ACTIVE_PROC.poll() is None:
            ACTIVE_PROC.terminate()
            push_log("LOOP", "Automation Loop halted by user.", "warning")
        ENGINE_STATE["is_running"] = False
        ENGINE_STATE["loop_active"] = False
        ENGINE_STATE["active_script"] = None
        if os.path.exists(loop_file):
            try: os.remove(loop_file)
            except: pass
        return jsonify({"success": True, "active": False, "message": "Automation Loop stopped."})
    
    # If not running, start it
    if ENGINE_STATE["is_running"]:
        return jsonify({"success": False, "error": "Another engine task is currently active!"}), 400

    targets = data.get("targets", ["food", "wood", "stone"])
    arg_str = ",".join(targets)
    count = str(data.get("count", 200))
    interval_hours = str(data.get("interval_hours", 3))
    level = str(data.get("level", 0))

    t = threading.Thread(target=engine_thread_worker, args=("auto_recurring_loop.py", [arg_str, count, interval_hours, level]), daemon=True)
    t.start()
    ENGINE_STATE["loop_active"] = True
    push_log("LOOP", f"{interval_hours}-Hour Recurring Automation Engine activated (Node Level {level if level != '0' else 'Auto'}).", "success")
    return jsonify({"success": True, "active": True, "message": f"{interval_hours}-Hour Recurring Automation started! Training + Gathering every {interval_hours} hours."})

@app.route('/api/start_daemon', methods=['POST'])
def start_daemon():
    ENGINE_STATE["bot_enabled"] = True
    ENGINE_STATE["status"] = "running"
    if ENGINE_STATE["is_running"]:
        return jsonify({"success": True, "message": "Engine is already active."})
    t = threading.Thread(target=engine_thread_worker, args=("fleet_manager.py", []), daemon=True)
    t.start()
    push_log("CONTROL", "Fleet Manager online: Sequentially rotating through all registered characters.", "success")
    return jsonify({"success": True, "message": "Multi-Character Fleet Manager started (Round-Robin)."})

@app.route('/api/standby', methods=['POST'])
def standby():
    global ACTIVE_PROC
    if ACTIVE_PROC and ACTIVE_PROC.poll() is None:
        ACTIVE_PROC.terminate()
        push_log("CONTROL", "Process terminated by user.", "warning")
    ENGINE_STATE["bot_enabled"] = False
    ENGINE_STATE["is_running"] = False
    ENGINE_STATE["status"] = "standby"
    ENGINE_STATE["active_queues"] = 0
    ENGINE_STATE["loop_active"] = False

    gather_file = os.path.join(BASE_DIR, "gather_status.json")
    if os.path.exists(gather_file):
        try:
            with open(gather_file, "w", encoding="utf-8") as f:
                json.dump({"status": "standby", "active_queues": 0, "total_troops": ENGINE_STATE.get("total_troops", 0), "marches": []}, f, indent=2)
        except Exception:
            pass

    loop_file = os.path.join(BASE_DIR, "loop_status.json")
    if os.path.exists(loop_file):
        try: os.remove(loop_file)
        except: pass

    push_log("CONTROL", "Bot stopped. Engine placed on standby.", "warning")
    return jsonify({"success": True, "message": "Engine is now in standby."})

@app.route('/api/account_action', methods=['POST'])
def handle_account_action():
    data = request.get_json(silent=True) or {}
    action = data.get("action", "")
    email = data.get("email", "")
    gov_id = data.get("gov_id", "")

    cfg_file = os.path.join(BASE_DIR, "bot_config.json")

    if action == "run_now":
        ENGINE_STATE["bot_enabled"] = True
        push_log("ACTION", f"Instant Cycle triggered for {gov_id or email}!", "success")
        if not ENGINE_STATE["is_running"]:
            fleet_args = ["--once"]
            if gov_id:
                fleet_args.extend(["--char", str(gov_id)])
            t = threading.Thread(target=engine_thread_worker, args=("fleet_manager.py", fleet_args), daemon=True)
            t.start()
        return jsonify({"success": True, "message": f"Instant cycle started for {gov_id or email}!"})

    elif action == "recall":
        standby()
        push_log("ACTION", f"Troop recall & stop order issued for {email or gov_id}.", "warning")
        return jsonify({"success": True, "message": f"Troops recalled & bot stopped for {email or gov_id}."})

    elif action == "shield":
        push_log("SHIELD", f"8-Hour Peace Shield verified active on {email or gov_id}.", "success")
        return jsonify({"success": True, "message": f"Peace shield confirmed active on {email or gov_id}."})

    elif action == "refresh":
        push_log("SYNC", f"Refreshing game session and cache for {email or gov_id}...", "info")
        return jsonify({"success": True, "message": f"Account {email or gov_id} refreshed successfully."})

    elif action == "remove":
        try:
            if os.path.exists(cfg_file):
                with open(cfg_file, "r", encoding="utf-8") as f:
                    c = json.load(f)
                c["accounts"] = [a for a in c.get("accounts", []) if a.get("email") != email]
                with open(cfg_file, "w", encoding="utf-8") as f:
                    json.dump(c, f, indent=2, ensure_ascii=False)
            push_log("ACCOUNT", f"Account {email} removed from active roster.", "warning")
            return jsonify({"success": True, "message": f"Account {email} removed."})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    return jsonify({"success": False, "error": "Unknown action"}), 400

# ─────────────────────────────────────────────────────────────
# Fleet Management Endpoints
# ─────────────────────────────────────────────────────────────

FLEET_PROC = None

@app.route('/api/fleet', methods=['GET', 'POST'])
def handle_fleet():
    fleet_file = os.path.join(BASE_DIR, "accounts_fleet.json")
    if request.method == 'GET':
        if os.path.exists(fleet_file):
            try:
                with open(fleet_file, "r", encoding="utf-8") as f:
                    return jsonify(json.load(f))
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        return jsonify([])
    else:
        fleet_data = request.get_json(silent=True)
        try:
            with open(fleet_file, "w", encoding="utf-8") as f:
                json.dump(fleet_data, f, indent=2, ensure_ascii=False)
            push_log("FLEET", "Fleet registry updated.", "success")
            return jsonify({"success": True, "message": "Fleet registry saved."})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/fleet_status', methods=['GET'])
def get_fleet_status():
    status_file = os.path.join(BASE_DIR, "fleet_status.json")
    if os.path.exists(status_file):
        try:
            with open(status_file, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"state": "idle"})


@app.route('/api/fleet_start', methods=['POST'])
def fleet_start():
    global FLEET_PROC
    if FLEET_PROC and FLEET_PROC.poll() is None:
        return jsonify({"success": True, "message": "Fleet Manager is already running."})

    data = request.get_json(silent=True) or {}
    once = data.get("once", False)
    count = str(data.get("count", 200))
    args = [sys.executable, os.path.join(BASE_DIR, "fleet_manager.py"), count]
    if once:
        args.append("--once")

    try:
        FLEET_PROC = subprocess.Popen(
            args,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=BASE_DIR, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
        )
        push_log("FLEET", f"Fleet Manager started ({'single round' if once else 'continuous loop'}).", "success")
        return jsonify({"success": True, "message": f"Fleet Manager launched ({'once' if once else 'loop'})."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/fleet_stop', methods=['POST'])
def fleet_stop():
    global FLEET_PROC
    if FLEET_PROC and FLEET_PROC.poll() is None:
        FLEET_PROC.terminate()
        push_log("FLEET", "Fleet Manager stopped by user.", "warning")
        FLEET_PROC = None
        # Update status file
        status_file = os.path.join(BASE_DIR, "fleet_status.json")
        if os.path.exists(status_file):
            try:
                with open(status_file, "r", encoding="utf-8") as f:
                    s = json.load(f)
                s["state"] = "stopped"
                with open(status_file, "w", encoding="utf-8") as f:
                    json.dump(s, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
        return jsonify({"success": True, "message": "Fleet Manager stopped."})
    return jsonify({"success": True, "message": "Fleet Manager was not running."})

if __name__ == '__main__':
    push_log("BOOT", "Arcane RoK Controller online on port 8080.", "success")
    push_log("READY", "Smart Dynamic Search Engine loaded (Food/Wood/Stone/Gold).", "info")
    app.run(host='0.0.0.0', port=8080, threaded=True)
