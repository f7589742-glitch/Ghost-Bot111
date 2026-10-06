import sys, os, json, time, logging, threading, subprocess

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("capture_android_login")

try:
    import pydivert
except ImportError:
    print("pip install pydivert")
    sys.exit(1)

ADB = r"C:\Users\MaleK\AppData\Local\Temp\platform-tools\platform-tools\adb.exe"
GAME_PKG = "com.lilithgame.roc.gp"
AUTH_SERVER = "43.159.112.101"

def kill_game():
    try:
        result = subprocess.run([ADB, "-s", "emulator-5554", "shell", "su", "0", "am", "force-stop", GAME_PKG], capture_output=True, timeout=5)
        logger.info("Game killed: %s", result.stdout.decode(errors='replace').strip())
    except Exception as e:
        logger.error("Kill failed: %s", e)

def start_game():
    try:
        subprocess.run([ADB, "-s", "emulator-5554", "shell", "monkey", "-p", GAME_PKG, "-c", "android.intent.category.LAUNCHER", "1"], capture_output=True, timeout=10)
        logger.info("Game started")
    except Exception as e:
        logger.error("Start failed: %s", e)

def capture_login():
    auth_flow = []
    start = time.time()

    w = pydivert.WinDivert()
    
    def capture_thread():
        try:
            w.open()
            count = 0
            for pkt in w:
                raw = bytes(pkt.payload)
                if len(raw) < 4:
                    w.send(pkt)
                    continue

                if pkt.is_outbound and pkt.dst_addr == AUTH_SERVER and pkt.dst_port == 3101:
                    direction = "C->S"
                elif pkt.is_inbound and pkt.src_addr == AUTH_SERVER and pkt.src_port == 3101:
                    direction = "S->C"
                else:
                    w.send(pkt)
                    continue

                count += 1
                prefix = int.from_bytes(raw[:2], 'big') if len(raw) >= 2 else 0
                logger.info("  [%d] %s %dB prefix=0x%04X hex=%s", count, direction, len(raw), prefix, raw.hex()[:120])

                auth_flow.append({
                    "dir": direction,
                    "server": AUTH_SERVER,
                    "raw": raw.hex(),
                    "len": len(raw),
                    "t": round(time.time() - start, 3)
                })

                w.send(pkt)
        except Exception as e:
            logger.error("Capture error: %s", e)

    t = threading.Thread(target=capture_thread, daemon=True)
    t.start()

    return t, auth_flow, w

logger.info("Step 1: Kill game")
kill_game()
time.sleep(3)

logger.info("Step 2: Start capture")
thread, auth_flow, w = capture_login()
time.sleep(2)

logger.info("Step 3: Launch game")
start_game()

logger.info("Step 4: Wait 50s for login flow...")
time.sleep(50)

logger.info("Step 5: Stop capture")
try:
    w.close()
except:
    pass

thread.join(timeout=5)

with open("android_login_capture.json", "w") as f:
    json.dump(auth_flow, f, indent=2)

logger.info("Captured %d packets", len(auth_flow))

if auth_flow:
    logger.info("\n=== Auth Flow ===")
    for i, p in enumerate(auth_flow):
        h = bytes.fromhex(p['raw'])
        logger.info("  [%d] %s %dB hex=%s", i, p['dir'], p['len'], h.hex()[:200])
        if p['dir'] == 'C->S' and p['len'] > 10:
            try:
                from headless_client import ProtobufCodec
                pf = ProtobufCodec.decode_message(h)
                logger.info("    protobuf: %s", pf)
            except:
                logger.info("    (not protobuf)")
