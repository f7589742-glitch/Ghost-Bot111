"""Quick bot launcher - attach to running game and test"""
import frida, time, json, sys
sys.path.insert(0, r'D:\aa\Headless Bot RoK')
from rok_protocol import decode_s2c_full, S2C_KEEPALIVE

PID = 30740
print(f'[*] Attaching Frida to PID {PID}...')
device = frida.get_local_device()
session = device.attach(PID)
print('[*] Session attached, loading script...')

with open(r'D:\aa\Headless Bot RoK\bot_frida_v5.js', 'r', encoding='utf-8') as f:
    js_code = f.read()

script = session.create_script(js_code)

s2c_count = 0
c2s_count = 0

def on_message(message, data):
    global s2c_count, c2s_count
    if message['type'] == 'send':
        payload = message['payload']
        if isinstance(payload, dict):
            t = payload.get('type','')
            if t == 'debug':
                print(f'  [engine] {payload.get("msg","")}')
            elif t == 'ring_ready':
                print(f'  [+] RING CTX CAPTURED: {payload.get("ctx","")}')
            elif t == 'send_done':
                print(f'  [OK] Cmd delivered! swap#{payload.get("n",0)}')
            elif t == 'send_start':
                print(f'  [>>] Sending cmd #{payload.get("id",0)} ({payload.get("len",0)}B)')
            elif t == 's2c':
                s2c_count += 1
                hex_d = payload.get('hex','')
                length = payload.get('len',0)
                try:
                    decoded = decode_s2c_full(hex_d)
                    name = decoded.get('name', f'op_{decoded.get("opcode")}')
                    chat = decoded.get('chat', {})
                    if chat:
                        print(f'  [<<] S2C#{s2c_count} {name}: [{chat.get("user_id","")}] {chat.get("text","")}')
                    elif decoded.get('opcode') != S2C_KEEPALIVE:
                        print(f'  [<<] S2C#{s2c_count} ({length}B) {name}')
                except:
                    pass
            elif t == 'c2s':
                c2s_count += 1
                hex_d = payload.get('hex','')
                length = payload.get('len',0)
                opcode = payload.get('opcode',-1)
                print(f'  [>>] C2S#{c2s_count} ({length}B) op={opcode} hex={hex_d[:60]}')
    elif message['type'] == 'error':
        print(f'  [ERR] {message.get("description","")}')

script.on('message', on_message)
script.load()
rpc = script.exports_sync
time.sleep(1)

stats = rpc.getstats()
print(f'[*] Bot engine loaded!')
print(f'    ringCtx valid: {stats.get("ringCtxValid")}')
print(f'    ringCtx: {stats.get("ringCtx")}')
print(f'    game call count: {stats.get("gameCallCount")}')
print()

# Wait for ringCtx
print('[*] Waiting for ringCtx to be captured (game needs to send keepalive)...')
for i in range(30):
    time.sleep(1)
    stats = rpc.getstats()
    if stats.get('ringCtxValid'):
        print('[+] ringCtx CAPTURED!')
        break
    if i % 5 == 0:
        print(f'  waiting... ({i+1}/30) gameCalls={stats.get("gameCallCount",0)}')

stats = rpc.getstats()
print()
print(f'[*] Stats: {json.dumps(stats, indent=2)}')
print()
print('[*] Ring buffer state:')
ctx_info = rpc.inspectctx()
print(json.dumps(ctx_info, indent=2))
print()

# Send test keepalive
print('[*] Sending test keepalive...')
ka_hex = '08091200'
result = rpc.queuesend(ka_hex)
print(f'    Result: {result}')

time.sleep(3)
stats = rpc.getstats()
print(f'    After send: swaps={stats.get("swapCount",0)} pending={stats.get("pendingSends",0)}')

print()
print('[*] Bot running! Waiting for traffic... (Ctrl+C to stop)')
try:
    last_s2c = 0
    last_c2s = 0
    while True:
        time.sleep(5)
        stats = rpc.getstats()
        gc = stats.get('gameCallCount', 0)
        ka = stats.get('swapCount', 0)
        s2c = stats.get('s2cCount', 0)
        c2s = stats.get('c2sRawCount', 0)
        pending = stats.get('pendingSends', 0)
        
        if s2c != last_s2c or c2s != last_c2s:
            print(f'  [stats] gc={gc} swaps={ka} s2c={s2c} c2s={c2s} pending={pending}')
            last_s2c = s2c
            last_c2s = c2s
except KeyboardInterrupt:
    print('\n[*] Stopping...')
    try:
        script.unload()
        session.detach()
    except:
        pass
    print('[*] Done!')
