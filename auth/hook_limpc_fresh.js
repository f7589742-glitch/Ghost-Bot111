/**
 * hook_limpc_fresh.js — Capture fresh auth tokens from a real LIMPC login.
 *
 * Targets: limpc.dll exports + WinHTTP to intercept the full OAuth flow.
 *
 * Token flow:
 *   1. LIMPCLoginStart(authCode)  → starts the OAuth token exchange
 *   2. WinHttpSendRequest          → POSTs auth_code to Lilith backend
 *   3. WinHttpReadData             → reads the JSON response:
 *         { access_token, app_token, app_uid, app_token_expire_at, ... }
 *   4. When all three tokens arrive, the script dumps them to STDOUT
 *      as a JSON line and stores them via the session_manager IPC file.
 *
 * Usage (via launch_and_capture.py):
 *   frida -n MASS.exe -l hook_limpc_fresh.js --no-pause
 */

'use strict';

// ── Config ──────────────────────────────────────────────────────────
var IPC_PATH = null;  // set by launcher via rpc
var LOGIN_STARTED = false;
var ACCUMULATED_RESPONSE = '';
var CURRENT_REQUEST = null;

// Capture state — waits for BOTH tokens + seeds before firing complete
var CAPTURE = {
    tokens: false,
    seeds: false,
    access_token: null,
    app_token: null,
    app_uid: null,
    app_token_expire_at: null,
    seed1: null,
    seed2: null,
};

// ── JSON helpers ────────────────────────────────────────────────────

function tryExtractTokens(obj) {
    var t = {};
    if (obj.access_token)  t.access_token  = obj.access_token;
    if (obj.app_token)     t.app_token     = obj.app_token;
    if (obj.app_uid)       t.app_uid       = String(obj.app_uid);
    if (obj.app_token_expire_at) t.app_token_expire_at = obj.app_token_expire_at;
    if (obj.code)          t.code          = obj.code;
    if (obj.msg)           t.msg           = obj.msg;
    return t;
}

function hasAllTokens(t) {
    return t.access_token && t.app_token && t.app_uid;
}

function dumpTokens(t) {
    for (var k in t) {
        if (t[k]) CAPTURE[k] = t[k];
    }
    CAPTURE.tokens = true;
    var line = JSON.stringify({
        event: 'TOKENS_CAPTURED',
        ts: Date.now(),
        tokens: t
    });
    console.log('[LIMPC_HOOK] ' + line);
    send({type: 'tokens', tokens: t});
    tryEmitComplete();
}

function hasAllSeeds() {
    return CAPTURE.seed1 !== null && CAPTURE.seed2 !== null;
}

function tryEmitComplete() {
    if (!CAPTURE.tokens || !CAPTURE.seeds) return;
    if (!hasAllSeeds()) return;

    var complete = {
        access_token: CAPTURE.access_token,
        app_token: CAPTURE.app_token,
        app_uid: CAPTURE.app_uid,
        app_token_expire_at: CAPTURE.app_token_expire_at,
        seed1: CAPTURE.seed1,
        seed2: CAPTURE.seed2,
    };
    var line = JSON.stringify({
        event: 'CAPTURE_COMPLETE',
        ts: Date.now(),
        data: complete
    });
    console.log('[LIMPC_HOOK] ' + line);
    send({type: 'capture_complete', data: complete});
}

function dumpError(desc, raw) {
    var line = JSON.stringify({
        event: 'ERROR',
        desc: desc,
        raw: raw ? raw.slice(0, 500) : null,
        ts: Date.now()
    });
    send({type: 'error', desc: desc, raw: raw ? raw.slice(0, 500) : null});
}

function dumpLog(msg, data) {
    send({type: 'log', msg: msg, data: data});
}

// ── WinHTTP Read-Data accumulator ───────────────────────────────────

var readDataHooks = {};

function hookWinHttpReadData() {
    var mod = Process.findModuleByName('WINHTTP.dll');
    if (!mod) { dumpLog('WINHTTP.dll not found'); return; }

    var exports = mod.enumerateExports();
    var readData = exports.find(function(e) { return e.name === 'WinHttpReadData'; });
    var sendReq   = exports.find(function(e) { return e.name === 'WinHttpSendRequest'; });
    var recvResp  = exports.find(function(e) { return e.name === 'WinHttpReceiveResponse'; });
    var openReq   = exports.find(function(e) { return e.name === 'WinHttpOpenRequest'; });
    var connect   = exports.find(function(e) { return e.name === 'WinHttpConnect'; });

    if (!readData) { dumpLog('WinHttpReadData not found'); return; }

    // Track the current request URL
    var requestInfo = {};
    var reqCounter = 0;

    if (connect) {
        Interceptor.attach(connect.address, {
            onEnter: function(args) {
                try {
                    var hostPtr = args[1];
                    if (!hostPtr.isNull()) {
                        this.reqId = ++reqCounter;
                        requestInfo[this.reqId] = {
                            host: hostPtr.readUtf16String(128),
                            port: args[2].toInt32(),
                            path: '',
                            verb: ''
                        };
                    }
                } catch(e) {}
            }
        });
    }

    if (openReq) {
        Interceptor.attach(openReq.address, {
            onEnter: function(args) {
                // Find which request info to update - walk back to find connect
                try {
                    var verb = args[1].readUtf16String(16);
                    var path = args[2].readUtf16String(512);
                    // Store on this call
                    this._verb = verb;
                    this._path = path;
                } catch(e) {}
            },
            onLeave: function(retval) {
                // We can associate this with a connect by the handle in args[0]
                // For simplicity, attach to the most recent requestInfo
                for (var id in requestInfo) {
                    var ri = requestInfo[id];
                    if (!ri.path && this._verb) {
                        ri.verb = this._verb;
                        ri.path = this._path;
                        break;
                    }
                }
            }
        });
    }

    if (sendReq) {
        Interceptor.attach(sendReq.address, {
            onEnter: function(args) {
                try {
                    var bodyLen = args[3].toInt32();
                    var bodyStr = null;
                    if (bodyLen > 0 && bodyLen < 32768) {
                        try {
                            bodyStr = Memory.readUtf8String(args[2], bodyLen);
                        } catch(e) {}
                    }
                    // Determine URL from request info
                    var url = 'unknown';
                    for (var id in requestInfo) {
                        var ri = requestInfo[id];
                        if (ri.path) {
                            url = 'https://' + ri.host + ri.path;
                            break;
                        }
                    }
                    this._url = url;
                    this._body = bodyStr;
                    dumpLog('HTTP_SEND', {url: url, body: bodyStr ? bodyStr.slice(0, 300) : null, bodyLen: bodyLen});

                    // If this is a login-related request, flag it
                    if (url.indexOf('login') >= 0 || url.indexOf('token') >= 0 ||
                        url.indexOf('oauth') >= 0 || url.indexOf('auth') >= 0) {
                        this._isLogin = true;
                        LOGIN_STARTED = true;
                    }
                } catch(e) {}
            }
        });
    }

    if (recvResp) {
        Interceptor.attach(recvResp.address, {
            onEnter: function(args) {
                // Reset accumulator for a new response
                this._resetAccumulator = true;
            },
            onLeave: function(retval) {
                // Determine URL from sendRequest context
                try {
                    // Walk the callstack or use thread-local
                    var tls = this.context;
                    // Simplification: just flag that we're receiving
                } catch(e) {}
            }
        });
    }

    // ── Main ReadData hook ──────────────────────────────────────────
    Interceptor.attach(readData.address, {
        onEnter: function(args) {
            this._hRequest = args[0].toInt32();
            this._buffer   = args[1];
            this._dwSize   = args[2].toInt32();
            this._accumulate = true;

            // If recvResp just fired, reset accumulation
            if (this._resetAccumulator) {
                ACCUMULATED_RESPONSE = '';
                this._resetAccumulator = false;
            }
        },
        onLeave: function(retval) {
            var bytesRead = retval.toInt32();
            if (bytesRead <= 0) return;

            try {
                var data = Memory.readUtf8String(this._buffer, bytesRead);
                if (!data) return;

                ACCUMULATED_RESPONSE += data;
                dumpLog('HTTP_CHUNK', {bytes: bytesRead, data: data.slice(0, 200)});

                // Try to find JSON in the accumulated data
                var braceStart = ACCUMULATED_RESPONSE.indexOf('{');
                var braceEnd   = ACCUMULATED_RESPONSE.lastIndexOf('}');

                if (braceStart >= 0 && braceEnd > braceStart) {
                    var jsonStr = ACCUMULATED_RESPONSE.slice(braceStart, braceEnd + 1);
                    try {
                        var parsed = JSON.parse(jsonStr);
                        var extracted = tryExtractTokens(parsed);

                        if (extracted.access_token || extracted.app_token) {
                            dumpLog('TOKEN_FRAGMENT', extracted);

                            if (hasAllTokens(extracted)) {
                                dumpTokens(extracted);
                                TOKENS = extracted;
                            } else {
                                // Merge with previous
                                for (var k in extracted) {
                                    if (extracted[k]) TOKENS[k] = extracted[k];
                                }
                                if (hasAllTokens(TOKENS)) {
                                    dumpTokens(TOKENS);
                                }
                            }
                        }

                        // Also check for auth code in redirect
                        if (parsed.code && parsed.code.length > 20 && !parsed.access_token) {
                            dumpLog('AUTH_CODE', {code: parsed.code.slice(0, 20) + '...'});
                        }

                        // Clear accumulated data after successful parse
                        ACCUMULATED_RESPONSE = ACCUMULATED_RESPONSE.slice(braceEnd + 1);
                    } catch(parseErr) {
                        // Partial JSON - keep accumulating
                    }
                }

                // Prevent accumulation growing unbounded
                if (ACCUMULATED_RESPONSE.length > 65536) {
                    ACCUMULATED_RESPONSE = ACCUMULATED_RESPONSE.slice(-32768);
                }

            } catch(e) {
                dumpError('WinHttpReadData error', e.message);
            }
        }
    });

    dumpLog('WinHTTP hooks installed');
}


// ── LIMPC function hooks ────────────────────────────────────────────

function hookLimpcExport(name, onEnterCb, onLeaveCb) {
    try {
        var exports = Process.getModuleByName('limpc.dll').enumerateExports();
        var exp = exports.find(function(e) { return e.name === name; });
        if (!exp) { dumpLog('Export not found: ' + name); return false; }

        Interceptor.attach(exp.address, {
            onEnter: function(args) {
                if (onEnterCb) onEnterCb.call(this, args);
            },
            onLeave: function(retval) {
                if (onLeaveCb) onLeaveCb.call(this, retval);
            }
        });
        dumpLog('Hooked: ' + name + ' @ ' + exp.address.toString());
        return true;
    } catch(e) {
        dumpError('Hook failed: ' + name, e.message);
        return false;
    }
}

function readStrAt(ptr, maxLen) {
    try {
        if (ptr.isNull()) return null;
        var s = ptr.readUtf8String(maxLen || 2048);
        return s || null;
    } catch(e) { return null; }
}

function readArgStr(args, idx) {
    try {
        return readStrAt(args[idx]);
    } catch(e) { return null; }
}

var HOOKED_COUNT = 0;

// ── 1. LIMPCLoginStart ─────────────────────────────────────────────
hookLimpcExport('LIMPCLoginStart',
    function(args) {
        var arg0 = readArgStr(args, 0);
        var arg1 = readArgStr(args, 1);

        dumpLog('LIMPCLoginStart', {
            arg0: arg0 ? arg0.slice(0, 300) : 'ptr(' + args[0].toString() + ')',
            arg1: arg1 ? arg1.slice(0, 300) : 'ptr(' + args[1].toString() + ')',
            arg2_int: args[2] ? args[2].toInt32() : null
        });

        LOGIN_STARTED = true;
    },
    function(retval) {
        dumpLog('LIMPCLoginStart_ret', {ret: retval.toString()});
    }
);

// ── 2. LIMPCUserInfoGet — returns current session JSON ──────────────
hookLimpcExport('LIMPCUserInfoGet',
    null,
    function(retval) {
        var str = readStrAt(retval);
        if (str) {
            // This might contain user data but probably not tokens
            dumpLog('LIMPCUserInfoGet', {data: str.slice(0, 1000)});
            try {
                var parsed = JSON.parse(str);
                var t = tryExtractTokens(parsed);
                if (hasAllTokens(t)) {
                    dumpTokens(t);
                    TOKENS = t;
                }
            } catch(e) {}
        }
    }
);

// ── 3. ParkGoogleOAuthUrl — Google OAuth URL ────────────────────────
hookLimpcExport('ParkGoogleOAuthUrl',
    function(args) {
        this._buf = args[0];
        this._sizePtr = args[1];
    },
    function(retval) {
        var retInt = retval.toInt32();
        dumpLog('ParkGoogleOAuthUrl_ret', {ret: retInt});

        if (this._buf && !this._buf.isNull()) {
            try {
                var url = this._buf.readCString();
                if (url && url.length > 20) {
                    dumpLog('OAUTH_URL', {url: url});
                }
            } catch(e) {}
        }

        // Also try reading from result pointer
        if (retInt > 0 && retInt < 0x10000) {
            // ret is a status code, not a pointer
        } else if (!retval.isNull()) {
            try {
                var str = retval.readCString();
                if (str && str.length > 20) {
                    dumpLog('OAUTH_URL_RET', {url: str});
                }
            } catch(e) {}
        }
    }
);

// ── 4. ParkConfig — endpoint configuration ──────────────────────────
hookLimpcExport('ParkConfig',
    null,
    function(retval) {
        try {
            if (!retval.isNull()) {
                var str = retval.readCString(2000);
                if (str) dumpLog('ParkConfig', {config: str.slice(0, 1000)});
            }
        } catch(e) {}
    }
);

// ── 5. LoginSucc / Token callback ───────────────────────────────────
// Some builds use an internal `LIMPCLoginCallback` or similar.
// Hook any function whose name contains "Login" that we missed.
function hookAllLoginExports() {
    try {
        var exports = Process.getModuleByName('limpc.dll').enumerateExports();
        for (var i = 0; i < exports.length; i++) {
            var n = exports[i].name;
            if (n === 'LIMPCLoginStart' || n === 'LIMPCUserInfoGet' ||
                n === 'ParkGoogleOAuthUrl' || n === 'ParkConfig') continue;

            if (n.indexOf('Login') >= 0 || n.indexOf('login') >= 0 ||
                n.indexOf('Token') >= 0 || n.indexOf('token') >= 0 ||
                n.indexOf('Auth') >= 0 || n.indexOf('auth') >= 0) {

                (function(addr, name) {
                    try {
                        Interceptor.attach(addr, {
                            onEnter: function(args) {
                                var info = {func: name, args: []};
                                for (var i = 0; i < Math.min(6, args.length); i++) {
                                    try {
                                        var a = args[i];
                                        var entry = {idx: i, ptr: a.toString()};
                                        var s = readStrAt(a);
                                        if (s) entry.str = s.slice(0, 300);
                                        info.args.push(entry);
                                    } catch(e) { break; }
                                }
                                dumpLog('LIMPC_CALL:' + name, info);
                            },
                            onLeave: function(retval) {
                                var info = {func: name, ret: retval.toString()};
                                var s = readStrAt(retval);
                                if (s) info.str = s.slice(0, 500);
                                if (info.str) dumpLog('LIMPC_RET:' + name, info);

                                // Check if return value has tokens
                                if (s) {
                                    try {
                                        var parsed = JSON.parse(s);
                                        var t = tryExtractTokens(parsed);
                                        if (hasAllTokens(t)) {
                                            dumpTokens(t);
                                            TOKENS = t;
                                        }
                                    } catch(e) {}
                                }
                            }
                        });
                        HOOKED_COUNT++;
                    } catch(e) {}
                })(exports[i].address, n);
            }
        }
    } catch(e) {
        dumpError('hookAllLoginExports', e.message);
    }
}

// ── 6. Error listeners ──────────────────────────────────────────────
// Listen for all console errors
var origOnError = window.onerror;
window.onerror = function(msg, url, line, col, error) {
    dumpLog('WINDOW_ERROR', {msg: msg, url: url, line: line, col: col});
    if (origOnError) return origOnError.apply(this, arguments);
};

// Poll for uncaught exceptions via process event
try {
    Process.setExceptionHandler(function(details) {
        dumpLog('NATIVE_CRASH', {
            address: details.address.toString(),
            type: details.type,
            context: details.context ? 'available' : 'null'
        });
        return false;  // let the OS handle it
    });
} catch(e) {}

// ── EngineDll Seed Capture ──────────────────────────────────────────
// Hooks the internal crypto init to capture seed1/seed2
// Call chain: 0x63590 → sub_B9850 (ch1@ret=0x635ca, ch2@ret=0x63620) → init@0x24a0(ecx=seed)

var ENGINE_SEED_RET_CH1 = null;  // will be set when EngineDll is found
var ENGINE_SEED_RET_CH2 = null;

function hookEngineDllSeeds() {
    var mod = Process.findModuleByName('EngineDll.dll');
    if (!mod) {
        dumpLog('EngineDll.dll not loaded yet');
        return false;
    }

    var base = mod.base;
    dumpLog('EngineDll at ' + base.toString());

    // Hook sub_B9850 — reads seed from variant struct by channel
    var subB9850 = base.add(0xB9850);
    ENGINE_SEED_RET_CH1 = base.add(0x635ca);
    ENGINE_SEED_RET_CH2 = base.add(0x63620);
    var initAddr = base.add(0x24a0);

    Interceptor.attach(subB9850, {
        onEnter: function(args) {
            var retAddr = this.returnAddress;
            if (retAddr.equals(ENGINE_SEED_RET_CH1)) {
                this._ch = 1;
            } else if (retAddr.equals(ENGINE_SEED_RET_CH2)) {
                this._ch = 2;
            } else {
                this._ch = 0;
            }
        },
        onLeave: function(retval) {
            if (this._ch === 0) return;
            var seedVal = retval.toInt32() >>> 0;
            var seedHex = '0x' + seedVal.toString(16).padStart(8, '0');

            if (this._ch === 1) {
                CAPTURE.seed1 = seedVal;
                dumpLog('SEED1', {seed: seedHex, ch: 1});
            } else {
                CAPTURE.seed2 = seedVal;
                dumpLog('SEED2', {seed: seedHex, ch: 2});
            }

            send({type: 'seed', data: {ch: this._ch, seed: seedVal, seed_hex: seedHex}});

            // Check if both seeds captured
            if (CAPTURE.seed1 !== null && CAPTURE.seed2 !== null) {
                if (!CAPTURE.seeds) {
                    CAPTURE.seeds = true;
                    dumpLog('SEEDS_CAPTURED', {seed1: seedHex, seed2: '0x' + (CAPTURE.seed2 >>> 0).toString(16).padStart(8, '0')});
                    send({type: 'seeds', data: {seed1: CAPTURE.seed1, seed2: CAPTURE.seed2}});
                    tryEmitComplete();
                }
            }
        }
    });

    // Fallback: hook init function directly
    Interceptor.attach(initAddr, {
        onEnter: function(args) {
            var seed = args[0].toInt32() >>> 0;
            dumpLog('INIT_CALL', {seed: '0x' + seed.toString(16).padStart(8, '0'), state: args[1].toString()});
        }
    });

    dumpLog('EngineDll seed hooks installed');
    return true;
}


// ── Initialization ──────────────────────────────────────────────────

function init() {
    dumpLog('INIT', {msg: 'hook_limpc_fresh.js loaded'});

    hookWinHttpReadData();
    hookAllLoginExports();

    // Hook EngineDll for seed capture (may not be loaded yet)
    var hooked = hookEngineDllSeeds();
    if (!hooked) {
        dumpLog('EngineDll not loaded, will retry in 5s...');
        setTimeout(function() {
            if (!hookEngineDllSeeds()) {
                setTimeout(function() {
                    hookEngineDllSeeds();
                }, 5000);
            }
        }, 5000);
    }

    dumpLog('READY', {msg: 'hooks installed', total: HOOKED_COUNT + 7});

    // Expose RPC for launcher to set IPC path
    rpc.exports = {
        setIpcPath: function(path) {
            IPC_PATH = path;
            dumpLog('IPC_PATH', {path: path});
        },
        getState: function() {
            return {
                tokens: CAPTURE.tokens,
                seeds: CAPTURE.seeds,
                access_token: CAPTURE.access_token ? CAPTURE.access_token.slice(0, 20) + '...' : null,
                app_uid: CAPTURE.app_uid,
                seed1: CAPTURE.seed1 ? '0x' + (CAPTURE.seed1 >>> 0).toString(16).padStart(8, '0') : null,
                seed2: CAPTURE.seed2 ? '0x' + (CAPTURE.seed2 >>> 0).toString(16).padStart(8, '0') : null,
            };
        },
        isComplete: function() {
            return CAPTURE.tokens && CAPTURE.seeds;
        }
    };
}

// Allow some time for modules to load
setTimeout(init, 500);
