'use strict';
// hook_boringssl.js — Hook BoringSSL (limpc.dll) SSL_read/SSL_write
// Scans for function references dynamically via string xrefs

function h2(b) { return ('0' + (b & 0xFF).toString(16)).slice(-2); }
function buf2hex(buf, max) {
    max = max || 256;
    var a = new Uint8Array(buf);
    var len = Math.min(a.length, max);
    var s = '';
    for (var i = 0; i < len; i++) s += h2(a[i]);
    if (a.length > max) s += '...(' + a.length + ' total)';
    return s;
}
function buf2ascii(buf, max) {
    max = max || 256;
    var a = new Uint8Array(buf);
    var len = Math.min(a.length, max);
    var s = '';
    for (var i = 0; i < len; i++) {
        s += (a[i] >= 32 && a[i] < 127) ? String.fromCharCode(a[i]) : '.';
    }
    return s;
}
function ts() {
    var n = new Date();
    return n.toTimeString().split(' ')[0] + '.' + String(n.getMilliseconds()).padStart(3, '0');
}

var hookedFuncs = {};
var callCounters = {};

function doHook() {
    var limpc;
    try {
        limpc = Process.getModuleByName('limpc.dll');
    } catch(e) {
        send({type: 'error', data: {msg: 'limpc.dll not found, retrying...'}});
        setTimeout(doHook, 2000);
        return;
    }

    send({type: 'module_found', data: {name: 'limpc.dll', base: limpc.base.toString(), size: limpc.size}});

    // Find strings
    var targetStrs = ['SSL_read', 'SSL_write', 'ssl_read', 'ssl_write'];
    var stringAddrs = {};

    var ranges = Process.enumerateRanges('r--');
    for (var ri = 0; ri < ranges.length; ri++) {
        var range = ranges[ri];
        if (range.base.compare(limpc.base) < 0 ||
            range.base.compare(limpc.base.add(limpc.size)) >= 0) continue;
        for (var si = 0; si < targetStrs.length; si++) {
            var needle = targetStrs[si];
            try {
                var results = Memory.scanSync(range.base, range.size, needle + '\x00');
                for (var i = 0; i < results.length; i++) {
                    if (!stringAddrs[needle]) stringAddrs[needle] = [];
                    stringAddrs[needle].push(results[i].address);
                }
            } catch(e) {}
        }
    }

    var strSummary = {};
    for (var k in stringAddrs) strSummary[k] = stringAddrs[k].map(function(a) { return a.toString(); });
    send({type: 'strings_found', data: strSummary});

    // Find .text section — use executable ranges within limpc
    var textBase = null;
    var textSize = null;
    try {
        var execRanges = Process.enumerateRanges('x--');
        for (var i = 0; i < execRanges.length; i++) {
            var r = execRanges[i];
            if (r.base.compare(limpc.base) >= 0 &&
                r.base.compare(limpc.base.add(limpc.size)) < 0) {
                // First executable range in limpc is likely .text
                if (!textBase || r.base.compare(textBase) < 0) {
                    textBase = r.base;
                    textSize = r.size;
                }
            }
        }
    } catch(e) {
        send({type: 'error', data: {msg: 'Range scan failed: ' + e.toString()}});
    }

    if (!textBase) {
        send({type: 'error', data: {msg: 'No executable range found in limpc.dll'}});
        return;
    }

    send({type: 'text_section', data: {base: textBase.toString(), size: textSize.toString()}});

    // Scan for LEA RIP-relative referencing SSL strings
    var prologuePatterns = [
        [0x48, 0x89, 0x5c, 0x24],
        [0x48, 0x89, 0x6c, 0x24],
        [0x48, 0x89, 0x74, 0x24],
        [0x48, 0x89, 0x7c, 0x24],
        [0x55, 0x48, 0x8b, 0xec],
        [0x53, 0x48, 0x83, 0xec],
        [0x57, 0x48, 0x83, 0xec],
        [0x56, 0x48, 0x83, 0xec],
        [0x40, 0x53, 0x48, 0x83, 0xec],
        [0x40, 0x55, 0x48, 0x8b, 0xec],
        [0x40, 0x56, 0x48, 0x83, 0xec],
        [0x40, 0x57, 0x48, 0x83, 0xec],
    ];

    function findPrologue(addr) {
        var scanStart = addr.sub(4096);
        if (scanStart.compare(limpc.base) < 0) scanStart = limpc.base;
        try {
            var codeBytes = new Uint8Array(Memory.readByteArray(scanStart, addr.sub(scanStart).toInt32() + 16));
        } catch(e) { return null; }

        for (var i = codeBytes.length - 16; i >= 0; i--) {
            for (var p = 0; p < prologuePatterns.length; p++) {
                var pat = prologuePatterns[p];
                var match = true;
                for (var j = 0; j < pat.length; j++) {
                    if (codeBytes[i + j] !== pat[j]) { match = false; break; }
                }
                if (match) return scanStart.add(i);
            }
        }
        return null;
    }

    var foundFuncs = {};
    var interestingTargets = ['SSL_read', 'SSL_write', 'ssl_read', 'ssl_write'];

    for (var ti = 0; ti < interestingTargets.length; ti++) {
        var targetStr = interestingTargets[ti];
        var addrs = stringAddrs[targetStr];
        if (!addrs) continue;

        for (var ai = 0; ai < addrs.length; ai++) {
            var strAddr = addrs[ai];

            // Scan .text for LEA [rip+disp32] referencing this string
            var chunkSize = 256 * 1024;
            for (var offset = 0; offset < textSize.toInt32(); offset += chunkSize) {
                var scanBase = textBase.add(offset);
                var scanLen = Math.min(chunkSize, textSize.toInt32() - offset);
                if (scanLen <= 0) break;

                try {
                    // LEA r64, [rip+disp32]: 48 8d 0d/15/1d/25/2d/35/3d disp32
                    var matches = Memory.scanSync(scanBase, scanLen, '48 8d ?? ?? ?? ?? ?? ??');
                    for (var mi = 0; mi < matches.length; mi++) {
                        var instrAddr = matches[mi].address;
                        var instrBytes = new Uint8Array(Memory.readByteArray(instrAddr, 7));

                        var modrm = instrBytes[2];
                        if ((modrm & 0xc7) !== 0x05) continue;

                        var disp32 = instrBytes[3] | (instrBytes[4] << 8) | (instrBytes[5] << 16) | ((instrBytes[6] << 24) >> 24);
                        var refAddr = instrAddr.add(7).add(disp32);

                        if (refAddr.compare(strAddr) === 0) {
                            var funcAddr = findPrologue(instrAddr);
                            if (funcAddr) {
                                var key = funcAddr.toString();
                                if (!foundFuncs[key]) {
                                    foundFuncs[key] = { addr: funcAddr, string: targetStr, xref: instrAddr };
                                    send({type: 'func_found', data: {
                                        string: targetStr,
                                        funcAddr: funcAddr.toString(),
                                        offset: funcAddr.sub(limpc.base).toString(),
                                    }});
                                }
                            }
                        }
                    }
                } catch(e) {}

                // Also try 4c 8d (REX.WR)
                try {
                    var matches2 = Memory.scanSync(scanBase, scanLen, '4c 8d ?? ?? ?? ?? ?? ??');
                    for (var mi2 = 0; mi2 < matches2.length; mi2++) {
                        var instrAddr2 = matches2[mi2].address;
                        var instrBytes2 = new Uint8Array(Memory.readByteArray(instrAddr2, 7));
                        var modrm2 = instrBytes2[2];
                        if ((modrm2 & 0xc7) !== 0x05) continue;
                        var disp32_2 = instrBytes2[3] | (instrBytes2[4] << 8) | (instrBytes2[5] << 16) | ((instrBytes2[6] << 24) >> 24);
                        var refAddr2 = instrAddr2.add(7).add(disp32_2);
                        if (refAddr2.compare(strAddr) === 0) {
                            var funcAddr2 = findPrologue(instrAddr2);
                            if (funcAddr2) {
                                var key2 = funcAddr2.toString();
                                if (!foundFuncs[key2]) {
                                    foundFuncs[key2] = { addr: funcAddr2, string: targetStr, xref: instrAddr2 };
                                    send({type: 'func_found', data: {
                                        string: targetStr,
                                        funcAddr: funcAddr2.toString(),
                                        offset: funcAddr2.sub(limpc.base).toString(),
                                    }});
                                }
                            }
                        }
                    }
                } catch(e2) {}
            }
        }
    }

    // Hook found functions
    var funcKeys = Object.keys(foundFuncs);
    send({type: 'scan_complete', data: {funcsFound: funcKeys.length}});

    for (var fi = 0; fi < funcKeys.length; fi++) {
        var fInfo = foundFuncs[funcKeys[fi]];
        var fAddr = fInfo.addr;
        var fName = fInfo.string;

        if (hookedFuncs[fAddr.toString()]) continue;
        hookedFuncs[fAddr.toString()] = true;

        (function(addr, name) {
            var isRead = name.indexOf('read') >= 0;
            var isWrite = name.indexOf('write') >= 0;
            callCounters[name] = 0;

            send({type: 'hooking', data: {func: name, addr: addr.toString()}});

            Interceptor.attach(addr, {
                onEnter: function(args) {
                    this._name = name;
                    this._isRead = isRead;
                    this._isWrite = isWrite;
                    this._num = callCounters[name]++;

                    if (isWrite) {
                        this._buf = args[1];
                        this._len = args[2].toInt32();
                        try {
                            this._plain = Memory.readByteArray(this._buf, Math.min(this._len, 512));
                        } catch(e) { this._plain = null; }
                    }
                    if (isRead) {
                        this._buf = args[1];
                    }
                },
                onLeave: function(retval) {
                    var ret = retval.toInt32();

                    if (this._isRead && ret > 0) {
                        try {
                            var data = Memory.readByteArray(this._buf, Math.min(ret, 512));
                            var info = {
                                func: this._name, num: this._num, ret: ret, ts: ts(),
                                size: ret, hex: buf2hex(data), ascii: buf2ascii(data),
                            };

                            var arr = new Uint8Array(data);
                            if (arr.length >= 19 && arr[0] === 0x00 && arr[1] === 0x11 && arr[2] === 0x08 && arr[3] === 0xf2) {
                                info.pattern = 'GREETING';
                                info.fullHex = buf2hex(Memory.readByteArray(this._buf, Math.min(ret, 256)));
                            } else if (arr.length >= 4 && arr[0] === 0x00 && arr[1] === 0x09) {
                                info.pattern = 'KEEPALIVE';
                            } else if (arr.length >= 4 && arr[0] === 0x00 && arr[1] === 0x12) {
                                info.pattern = 'SERVER_DATA';
                            } else if (arr.length >= 4 && arr[0] === 0x00 && arr[1] === 0x00) {
                                info.pattern = 'CONTROL';
                            }

                            send({type: 'ssl_read', data: info});
                        } catch(e) {
                            send({type: 'ssl_read', data: {error: e.toString(), size: ret}});
                        }
                    }

                    if (this._isWrite && this._plain) {
                        var info2 = {
                            func: this._name, num: this._num, ts: ts(),
                            size: this._len, hex: buf2hex(this._plain), ascii: buf2ascii(this._plain),
                        };

                        var arr2 = new Uint8Array(this._plain);
                        if (arr2.length >= 4 && arr2[0] === 0x08 && arr2[1] === 0x09 && arr2[2] === 0x12 && arr2[3] === 0x00) {
                            info2.pattern = 'HANDSHAKE';
                        } else if (arr2.length >= 4 && arr2[0] === 0x00 && arr2[1] === 0x09) {
                            info2.pattern = 'KEEPALIVE';
                        }

                        send({type: 'ssl_write', data: info2});
                    }
                }
            });

            send({type: 'hook_installed', data: {func: name, addr: addr.toString()}});
        })(fAddr, fName);
    }
}

doHook();
send({type: 'started', data: {}});
