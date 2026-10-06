"""
Frida Script: Capture FREncry_encrypt Input (Plaintext)
This script hooks FREncry functions to capture the unencrypted game protocol
before it gets encrypted by the custom stream cipher.
"""

const ENGINE_DLL = "EngineDll.dll";
const GAME_ASSEMBLY = "GameAssembly.dll";
const NEP2 = "NEP2.dll";

// Track encryption calls
var encryCalls = [];
var encryKey = null;

// Hook FREncry_create - get encryption key
var engExports = Module.enumerateExports(ENGINE_DLL);
for (var i = 0; i < engExports.length; i++) {
    var exp = engExports[i];
    if (exp.name.indexOf("FREncry") !== -1) {
        console.log("[+] " + ENGINE_DLL + " export: " + exp.name + " @ " + exp.address);
        
        if (exp.name === "FREncry_create") {
            Interceptor.attach(exp.address, {
                onEnter: function(args) {
                    this.plainText = args[0];
                    this.plainTextLen = args[1].toInt32();
                    this.key = args[2];
                    console.log("[FREncry_create] plainText=" + this.plainText + " len=" + this.plainTextLen + " key=" + this.key);
                    
                    // Try to read the key
                    try {
                        var keyData = Memory.readByteArray(this.key, 32);
                        encryKey = keyData;
                        console.log("[FREncry_create] KEY (32 bytes): " + arrayToHex(keyData));
                    } catch(e) {}
                },
                onLeave: function(retval) {
                    console.log("[FREncry_create] retval=" + retval);
                }
            });
        }
        
        if (exp.name === "FREncry_encrypt") {
            Interceptor.attach(exp.address, {
                onEnter: function(args) {
                    this.plainText = args[0];
                    this.plainTextLen = args[1].toInt32();
                    this.output = args[2];
                    this.outputLen = args[3];
                    
                    // Read plaintext BEFORE encryption
                    try {
                        var plainData = Memory.readByteArray(this.plainText, this.plainTextLen);
                        console.log("[FREncry_encrypt] PLAINTEXT (" + this.plainTextLen + " bytes): " + arrayToHex(plainData));
                        encryCalls.push({
                            timestamp: Date.now(),
                            direction: 'encrypt',
                            length: this.plainTextLen,
                            plaintext: arrayToHex(plainData)
                        });
                    } catch(e) {
                        console.log("[FREncry_encrypt] Error reading plaintext: " + e);
                    }
                },
                onLeave: function(retval) {
                    // Read encrypted output
                    try {
                        var outLen = this.outputLen.toInt32();
                        var encData = Memory.readByteArray(this.output, outLen);
                        console.log("[FREncry_encrypt] ENCRYPTED (" + outLen + " bytes): " + arrayToHex(encData));
                    } catch(e) {}
                }
            });
        }
        
        if (exp.name === "FREncry_read") {
            Interceptor.attach(exp.address, {
                onEnter: function(args) {
                    this.cipherText = args[0];
                    this.cipherTextLen = args[1].toInt32();
                    this.output = args[2];
                    this.outputLen = args[3];
                    
                    // Read ciphertext BEFORE decryption
                    try {
                        var encData = Memory.readByteArray(this.cipherText, this.cipherTextLen);
                        console.log("[FREncry_read] CIPHERTEXT (" + this.cipherTextLen + " bytes): " + arrayToHex(encData));
                    } catch(e) {}
                },
                onLeave: function(retval) {
                    // Read decrypted output
                    try {
                        var outLen = this.outputLen.toInt32();
                        var plainData = Memory.readByteArray(this.output, outLen);
                        console.log("[FREncry_read] DECRYPTED (" + outLen + " bytes): " + arrayToHex(plainData));
                        encryCalls.push({
                            timestamp: Date.now(),
                            direction: 'decrypt',
                            length: outLen,
                            plaintext: arrayToHex(plainData)
                        });
                    } catch(e) {}
                }
            });
        }
    }
}

// Hook ws2_32 send/recv to correlate with FREncry
var ws2 = "ws2_32.dll";
var sendAddr = Module.findExportByName(ws2, "send");
var recvAddr = Module.findExportByName(ws2, "recv");

if (sendAddr) {
    Interceptor.attach(sendAddr, {
        onEnter: function(args) {
            this.fd = args[0].toInt32();
            this.buf = args[1];
            this.len = args[2].toInt32();
            
            try {
                var data = Memory.readByteArray(this.buf, Math.min(this.len, 200));
                var hex = arrayToHex(data);
                
                // Check if this is game server (3101)
                if (this.fd > 0) {
                    console.log("[SEND] fd=" + this.fd + " len=" + this.len + " data=" + hex);
                    
                    // Log with FREncry context
                    if (encryCalls.length > 0) {
                        var lastEncry = encryCalls[encryCalls.length - 1];
                        if (Date.now() - lastEncry.timestamp < 100) {
                            console.log("[CORRELATION] Last FREncry plaintext: " + lastEncry.plaintext);
                        }
                    }
                }
            } catch(e) {}
        }
    });
}

if (recvAddr) {
    Interceptor.attach(recvAddr, {
        onEnter: function(args) {
            this.fd = args[0].toInt32();
            this.buf = args[1];
            this.len = args[2].toInt32();
        },
        onLeave: function(retval) {
            var recvLen = retval.toInt32();
            if (recvLen > 0) {
                try {
                    var data = Memory.readByteArray(this.buf, Math.min(recvLen, 200));
                    var hex = arrayToHex(data);
                    console.log("[RECV] fd=" + this.fd + " len=" + recvLen + " data=" + hex);
                } catch(e) {}
            }
        }
    });
}

// Helper function to convert ArrayBuffer to hex
function arrayToHex(buffer) {
    var hex = '';
    var bytes = new Uint8Array(buffer);
    for (var i = 0; i < bytes.length; i++) {
        hex += ('0' + bytes[i].toString(16)).slice(-2);
    }
    return hex;
}

// Periodic key dump
setInterval(function() {
    if (encryKey) {
        console.log("[KEY] Current encryption key: " + arrayToHex(encryKey));
    }
    console.log("[STATS] FREncry calls: " + encryCalls.length);
}, 10000);

console.log("[*] FREncry plaintext capture script loaded");
console.log("[*] Waiting for FREncry_encrypt calls...");
console.log("[*] Key will be captured from FREncry_create");
