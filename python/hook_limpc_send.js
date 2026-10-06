/**
 * Frida hook for limpc.dll send/recv
 * Captures the game protocol handshake
 * 
 * Usage: frida -p <MASS_PID> -l hook_limpc_send.js
 */

// Find limpc.dll base
var limpcBase = null;
Process.enumerateModules().forEach(function(mod) {
    if (mod.name.toLowerCase().includes('limpc.dll') || 
        mod.path.toLowerCase().includes('limpc.dll')) {
        limpcBase = mod.base;
        console.log("[+] limpc.dll found at: " + mod.base + " (" + mod.size + " bytes)");
        console.log("    Path: " + mod.path);
    }
});

if (!limpcBase) {
    console.log("[-] limpc.dll not found! Make sure MASS.exe is running.");
} else {
    // The send/recv wrapper offsets from our earlier analysis
    var SEND_OFFSET = 0x4b5030;
    var RECV_OFFSET = 0x4b4fa0;
    
    var sendAddr = limpcBase.add(SEND_OFFSET);
    var recvAddr = limpcBase.add(RECV_OFFSET);
    
    console.log("[+] Hook addresses:");
    console.log("    Send: " + sendAddr);
    console.log("    Recv: " + recvAddr);
    
    var sendCount = 0;
    var recvCount = 0;
    
    // Hook send
    Interceptor.attach(sendAddr, {
        onEnter: function(args) {
            this.fd = args[0].toInt32();
            this.buf = args[1];
            this.len = args[2].toInt32();
            
            sendCount++;
            
            // Read the data being sent
            var data = Memory.readByteArray(this.buf, Math.min(this.len, 512));
            var hexStr = hexDump(data);
            
            console.log("\n[SEND #" + sendCount + "] fd=" + this.fd + " len=" + this.len);
            console.log("    Hex: " + hexStr);
            
            // Check for interesting patterns
            var firstBytes = new Uint8Array(data);
            if (firstBytes.length > 0) {
                console.log("    First byte: 0x" + firstBytes[0].toString(16));
                
                // Check for protobuf markers
                if (firstBytes[0] === 0x08 || firstBytes[0] === 0x0a || firstBytes[0] === 0x12) {
                    console.log("    -> Looks like protobuf!");
                }
                
                // Check for STS credentials
                var textData = '';
                for (var i = 0; i < Math.min(this.len, 200); i++) {
                    var b = Memory.readU8(this.buf.add(i));
                    if (b >= 32 && b < 127) textData += String.fromCharCode(b);
                }
                if (textData.includes('STS.') || textData.includes('AccessKey')) {
                    console.log("    -> Contains STS credentials!");
                    console.log("    Text: " + textData.substring(0, 200));
                }
                if (textData.includes('{') && textData.includes('}')) {
                    console.log("    -> Contains JSON!");
                    console.log("    Text: " + textData.substring(0, 500));
                }
            }
        },
        onLeave: function(retval) {
            console.log("    -> Returned: " + retval);
        }
    });
    
    // Hook recv
    Interceptor.attach(recvAddr, {
        onEnter: function(args) {
            this.fd = args[0].toInt32();
            this.buf = args[1];
            this.len = args[2].toInt32();
        },
        onLeave: function(retval) {
            var recvLen = retval.toInt32();
            recvCount++;
            
            if (recvLen > 0) {
                var data = Memory.readByteArray(this.buf, Math.min(recvLen, 512));
                var hexStr = hexDump(data);
                
                console.log("\n[RECV #" + recvCount + "] fd=" + this.fd + " len=" + recvLen);
                console.log("    Hex: " + hexStr);
                
                // Check for greeting
                var firstBytes = new Uint8Array(data);
                if (firstBytes.length >= 2 && firstBytes[0] === 0x00 && firstBytes[2] === 0x08) {
                    console.log("    -> Looks like server greeting!");
                }
            }
        }
    });
    
    console.log("[+] Hooks installed! Waiting for game protocol traffic...");
    console.log("    Connect to a city in the game to trigger the connection.");
}

function hexDump(arrayBuffer) {
    var bytes = new Uint8Array(arrayBuffer);
    var result = '';
    for (var i = 0; i < bytes.length; i++) {
        result += ('0' + bytes[i].toString(16)).slice(-2);
        if (i % 16 === 15) break; // Limit output
    }
    if (bytes.length > 16) result += '...';
    return result;
}
