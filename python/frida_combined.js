var ENGINE_DLL = "EngineDll.dll";
var WS2 = "ws2_32.dll";

var connections = {};
var handshakeCaptured = {};
var encryCalls = [];
var encryKey = null;

function arrayToHex(buffer) {
    var hex = '';
    var bytes = new Uint8Array(buffer);
    for (var i = 0; i < bytes.length; i++) {
        hex += ('0' + bytes[i].toString(16)).slice(-2);
    }
    return hex;
}

// Hook connect()
var connectAddr = Module.findExportByName(WS2, "connect");
Interceptor.attach(connectAddr, {
    onEnter: function(args) {
        this.sock = args[0].toInt32();
        this.addr = args[1];
        this.addrlen = args[2].toInt32();
        if (this.addrlen >= 16) {
            var family = Memory.readU16(this.addr);
            if (family === 2) {
                var port = (Memory.readU8(this.addr.add(2)) << 8) | Memory.readU8(this.addr.add(3));
                var ip = Memory.readU32(this.addr.add(4));
                var ipStr = (ip & 0xFF) + "." + ((ip >> 8) & 0xFF) + "." + ((ip >> 16) & 0xFF) + "." + ((ip >> 24) & 0xFF);
                connections[this.sock] = { ip: ipStr, port: port, connectTime: Date.now(), firstSend: null, firstRecv: null, allMessages: [] };
                console.log("[CONNECT] fd=" + this.sock + " -> " + ipStr + ":" + port);
                if (port === 3101) {
                    console.log("[GAME SERVER] New connection!");
                    handshakeCaptured[this.sock] = { greeting: null, firstClientMessage: null };
                }
            }
        }
    }
});

// Hook send()
var sendAddr = Module.findExportByName(WS2, "send");
Interceptor.attach(sendAddr, {
    onEnter: function(args) {
        var fd = args[0].toInt32();
        var buf = args[1];
        var len = args[2].toInt32();
        if (connections[fd] && connections[fd].port === 3101) {
            try {
                var data = Memory.readByteArray(buf, len);
                var hex = arrayToHex(data);
                connections[fd].allMessages.push({ timestamp: Date.now(), direction: 'TX', length: len, hex: hex });
                if (!connections[fd].firstSend) {
                    connections[fd].firstSend = Date.now();
                    console.log("[3101-TX] FIRST SEND fd=" + fd + " len=" + len + " data=" + hex);
                }
                console.log("[3101-TX] fd=" + fd + " len=" + len + " data=" + hex);
            } catch(e) {}
        }
    }
});

// Hook recv()
var recvAddr = Module.findExportByName(WS2, "recv");
Interceptor.attach(recvAddr, {
    onEnter: function(args) {
        this.fd = args[0].toInt32();
        this.buf = args[1];
        this.len = args[2].toInt32();
    },
    onLeave: function(retval) {
        var recvLen = retval.toInt32();
        if (recvLen > 0 && connections[this.fd] && connections[this.fd].port === 3101) {
            try {
                var data = Memory.readByteArray(this.buf, recvLen);
                var hex = arrayToHex(data);
                connections[this.fd].allMessages.push({ timestamp: Date.now(), direction: 'RX', length: recvLen, hex: hex });
                if (!connections[this.fd].firstRecv) {
                    connections[this.fd].firstRecv = Date.now();
                    console.log("[3101-RX] FIRST RECV (GREETING) fd=" + this.fd + " len=" + recvLen + " data=" + hex);
                }
                console.log("[3101-RX] fd=" + this.fd + " len=" + recvLen + " data=" + hex);
            } catch(e) {}
        }
    }
});

// Hook closesocket
var closesocketAddr = Module.findExportByName(WS2, "closesocket");
Interceptor.attach(closesocketAddr, {
    onEnter: function(args) {
        var fd = args[0].toInt32();
        if (connections[fd] && connections[fd].port === 3101) {
            console.log("[CLOSE] fd=" + fd + " total_msgs=" + connections[fd].allMessages.length);
            for (var i = 0; i < connections[fd].allMessages.length; i++) {
                var msg = connections[fd].allMessages[i];
                console.log("[DUMP] " + msg.direction + " len=" + msg.length + " data=" + msg.hex);
            }
        }
        delete connections[fd];
        delete handshakeCaptured[fd];
    }
});

// Hook FREncry functions via Process.findModuleByName
try {
    var eng = Process.findModuleByName(ENGINE_DLL);
    if (eng) {
        var exports = eng.enumerateExports();
        for (var i = 0; i < exports.length; i++) {
            var exp = exports[i];
            if (exp.name === "FREncry_create") {
                console.log("[+] FREncry_create @ " + exp.address);
                Interceptor.attach(exp.address, {
                    onEnter: function(args) {
                        this.plainText = args[0];
                        this.plainTextLen = args[1].toInt32();
                        this.key = args[2];
                        console.log("[FREncry_create] len=" + this.plainTextLen + " key=" + this.key);
                        try {
                            var keyData = Memory.readByteArray(this.key, 32);
                            encryKey = keyData;
                            console.log("[FREncry_create] KEY: " + arrayToHex(keyData));
                        } catch(e) {}
                    }
                });
            }
            if (exp.name === "FREncry_encrypt") {
                console.log("[+] FREncry_encrypt @ " + exp.address);
                Interceptor.attach(exp.address, {
                    onEnter: function(args) {
                        this.plainText = args[0];
                        this.plainTextLen = args[1].toInt32();
                        this.output = args[2];
                        this.outputLen = args[3];
                        try {
                            var plainData = Memory.readByteArray(this.plainText, this.plainTextLen);
                            console.log("[FREncry_encrypt] PLAINTEXT (" + this.plainTextLen + "B): " + arrayToHex(plainData));
                            encryCalls.push({ t: Date.now(), d: 'enc', l: this.plainTextLen, p: arrayToHex(plainData) });
                        } catch(e) {}
                    },
                    onLeave: function(retval) {
                        try {
                            var outLen = this.outputLen.toInt32();
                            var encData = Memory.readByteArray(this.output, outLen);
                            console.log("[FREncry_encrypt] ENCRYPTED (" + outLen + "B): " + arrayToHex(encData));
                        } catch(e) {}
                    }
                });
            }
            if (exp.name === "FREncry_read") {
                console.log("[+] FREncry_read @ " + exp.address);
                Interceptor.attach(exp.address, {
                    onEnter: function(args) {
                        this.cipherText = args[0];
                        this.cipherTextLen = args[1].toInt32();
                        this.output = args[2];
                        this.outputLen = args[3];
                        try {
                            var encData = Memory.readByteArray(this.cipherText, this.cipherTextLen);
                            console.log("[FREncry_read] CIPHER (" + this.cipherTextLen + "B): " + arrayToHex(encData));
                        } catch(e) {}
                    },
                    onLeave: function(retval) {
                        try {
                            var outLen = this.outputLen.toInt32();
                            var plainData = Memory.readByteArray(this.output, outLen);
                            console.log("[FREncry_read] DECRYPTED (" + outLen + "B): " + arrayToHex(plainData));
                            encryCalls.push({ t: Date.now(), d: 'dec', l: outLen, p: arrayToHex(plainData) });
                        } catch(e) {}
                    }
                });
            }
        }
    }
} catch(e) { console.log("[!] FREncry hook error: " + e); }

// Status every 10s
setInterval(function() {
    var count = 0;
    for (var fd in connections) {
        if (connections[fd].port === 3101) {
            var conn = connections[fd];
            var dur = ((Date.now() - conn.connectTime) / 1000).toFixed(1);
            console.log("[STATUS] fd=" + fd + " " + conn.ip + ":" + conn.port + " dur=" + dur + "s msgs=" + conn.allMessages.length);
            count++;
        }
    }
    if (count === 0) console.log("[STATUS] No active 3101 connections");
    if (encryKey) console.log("[KEY] " + arrayToHex(encryKey));
    console.log("[STATS] FREncry calls: " + encryCalls.length);
}, 10000);

console.log("[*] All hooks loaded. Waiting for game activity...");
