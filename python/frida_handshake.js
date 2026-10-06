"""
Frida Script: Capture Complete Port 3101 Handshake
Focus on initial bytes after connect() - the missing piece
"""

const ENGINE_DLL = "EngineDll.dll";
const WS2 = "ws2_32.dll";

// Track connections
var connections = {};
var handshakeCaptured = {};

// Hook connect() to detect new connections
var connectAddr = Module.findExportByName(WS2, "connect");
Interceptor.attach(connectAddr, {
    onEnter: function(args) {
        this.sock = args[0].toInt32();
        this.addr = args[1];
        this.addrlen = args[2].toInt32();
        
        // Parse sockaddr_in
        if (this.addrlen >= 16) {
            var family = Memory.readU16(this.addr);
            if (family === 2) { // AF_INET
                var port = (Memory.readU8(this.addr.add(2)) << 8) | Memory.readU8(this.addr.add(3));
                var ip = Memory.readU32(this.addr.add(4));
                var ipStr = (ip & 0xFF) + "." + ((ip >> 8) & 0xFF) + "." + ((ip >> 16) & 0xFF) + "." + ((ip >> 24) & 0xFF);
                
                connections[this.sock] = {
                    ip: ipStr,
                    port: port,
                    connectTime: Date.now(),
                    firstSend: null,
                    firstRecv: null,
                    allMessages: []
                };
                
                console.log("[CONNECT] fd=" + this.sock + " → " + ipStr + ":" + port);
                
                if (port === 3101) {
                    console.log("[GAME SERVER] New connection to game server!");
                    handshakeCaptured[this.sock] = {
                        greeting: null,
                        firstClientMessage: null,
                        handshakeComplete: false
                    };
                }
            }
        }
    }
});

// Hook send() to capture first bytes
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
                
                // Log ALL messages on port 3101
                connections[fd].allMessages.push({
                    timestamp: Date.now(),
                    direction: 'TX',
                    length: len,
                    hex: hex
                });
                
                // Track first send
                if (!connections[fd].firstSend) {
                    connections[fd].firstSend = Date.now();
                    console.log("[3101-TX] FIRST SEND fd=" + fd + " len=" + len + " data=" + hex);
                    
                    if (handshakeCaptured[fd]) {
                        handshakeCaptured[fd].firstClientMessage = data;
                    }
                }
                
                // Log all sends for game server
                console.log("[3101-TX] fd=" + fd + " len=" + len + " data=" + hex);
                
            } catch(e) {}
        }
    }
});

// Hook recv() to capture greeting and responses
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
                
                // Log ALL received messages
                connections[this.fd].allMessages.push({
                    timestamp: Date.now(),
                    direction: 'RX',
                    length: recvLen,
                    hex: hex
                });
                
                // Track first recv (greeting)
                if (!connections[this.fd].firstRecv) {
                    connections[this.fd].firstRecv = Date.now();
                    console.log("[3101-RX] FIRST RECV (GREETING) fd=" + this.fd + " len=" + recvLen + " data=" + hex);
                    
                    if (handshakeCaptured[this.fd]) {
                        handshakeCaptured[this.fd].greeting = data;
                    }
                }
                
                // Log all received
                console.log("[3101-RX] fd=" + this.fd + " len=" + recvLen + " data=" + hex);
                
            } catch(e) {}
        }
    }
});

// Hook closesocket to know when connection ends
var closesocketAddr = Module.findExportByName(WS2, "closesocket");
Interceptor.attach(closesocketAddr, {
    onEnter: function(args) {
        var fd = args[0].toInt32();
        if (connections[fd] && connections[fd].port === 3101) {
            console.log("[CLOSE] fd=" + fd + " - Total messages: " + connections[fd].allMessages.length);
            // Dump all messages
            for (var i = 0; i < connections[fd].allMessages.length; i++) {
                var msg = connections[fd].allMessages[i];
                console.log("[DUMP] " + msg.direction + " len=" + msg.length + " data=" + msg.hex);
            }
        }
        delete connections[fd];
        delete handshakeCaptured[fd];
    }
});

// Helper function
function arrayToHex(buffer) {
    var hex = '';
    var bytes = new Uint8Array(buffer);
    for (var i = 0; i < bytes.length; i++) {
        hex += ('0' + bytes[i].toString(16)).slice(-2);
    }
    return hex;
}

// Periodic status
setInterval(function() {
    var gameConns = Object.keys(connections).filter(function(fd) {
        return connections[fd].port === 3101;
    });
    
    if (gameConns.length > 0) {
        console.log("[STATUS] Active game connections: " + gameConns.length);
        for (var i = 0; i < gameConns.length; i++) {
            var fd = gameConns[i];
            var conn = connections[fd];
            var duration = ((Date.now() - conn.connectTime) / 1000).toFixed(1);
            console.log("[STATUS] fd=" + fd + " " + conn.ip + ":" + conn.port + 
                       " duration=" + duration + "s msgs=" + conn.allMessages.length);
        }
    }
}, 5000);

console.log("[*] Port 3101 handshake capture script loaded");
console.log("[*] Waiting for connections to game server...");
