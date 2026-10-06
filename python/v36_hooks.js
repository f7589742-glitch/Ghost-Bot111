
'use strict';
var base = 0;
var recvCount = 0;

function init() {
    var EngineDll = Process.getModuleByName('EngineDll.dll');
    base = EngineDll.base;
    console.log('[+] EngineDll base:', base.toString(16));
    
    var setValueAddr = base.add(0xBB930);
    var subB9850Addr = base.add(0xB9850);
    var initAddr = base.add(0x24a0);

    // Hook setValue — capture ALL writes to variant struct
    Interceptor.attach(setValueAddr, {
        onEnter: function(args) {
            this.obj = args[0];
            this.channel = args[1].toInt32();
            this.valueIdx = args[2].toInt32();
            this.r9 = args[3];
        },
        onLeave: function(retval) {
            var ch = this.channel;
            if (ch >= 1 && ch <= 5) {
                send({
                    type: 'setvalue',
                    obj: this.obj.toString(16),
                    channel: ch,
                    valueIdx: this.valueIdx,
                    r9: this.r9.toString(16),
                    pc: this.returnAddress.sub(base).toString(16)
                });
            }
        }
    });

    // Hook sub_B9850 — capture seed reads with return address
    Interceptor.attach(subB9850Addr, {
        onEnter: function(args) {
            this.obj = args[0];
            this.channel = args[1].toInt32();
        },
        onLeave: function(retval) {
            var val = retval.toInt32();
            send({
                type: 'seed_read',
                obj: this.obj.toString(16),
                channel: this.channel,
                value: '0x' + (val >>> 0).toString(16),
                valueDec: val,
                pc: this.returnAddress.sub(base).toString(16)
            });
        }
    });

    // Hook init — capture final seed values
    Interceptor.attach(initAddr, {
        onEnter: function(args) {
            var ecx = args[0].toInt32();
            var seed1 = args[2].toInt32();
            var seed2 = args[3].toInt32();
            send({
                type: 'init_called',
                ecx: ecx,
                seed1: '0x' + (seed1 >>> 0).toString(16),
                seed2: '0x' + (seed2 >>> 0).toString(16),
                seed1Dec: seed1,
                seed2Dec: seed2
            });
        }
    });

    // Hook recv
    var ws2 = Process.getModuleByName('ws2_32.dll');
    var recvExports = ws2.enumerateExports();
    var recvAddr = null;
    for (var i = 0; i < recvExports.length; i++) {
        if (recvExports[i].name === 'recv') {
            recvAddr = recvExports[i].address;
            break;
        }
    }
    
    if (recvAddr) {
        Interceptor.attach(recvAddr, {
            onEnter: function(args) {
                this.buf = args[1];
                this.len = args[2].toInt32();
            },
            onLeave: function(retval) {
                var r = retval.toInt32();
                if (r > 0) {
                    recvCount++;
                    try {
                        var arr = new Uint8Array(this.buf.readByteArray(Math.min(r, 64)));
                        var hex = Array.from(arr).map(function(b) { return ('0'+b.toString(16)).slice(-2); }).join('');
                        
                        var isGreeting = (r === 19 && arr[0] === 0x00 && arr.length >= 6 && arr[3] === 0x08 && arr[4] === 0xf2 && arr[5] === 0x42);
                        
                        if (isGreeting) {
                            var nonce = hex.substring(12, 28);
                            send({
                                type: 'greeting',
                                recvNum: recvCount,
                                len: r,
                                hex: hex,
                                nonce: nonce
                            });
                        }
                    } catch(e) {}
                }
            }
        });
        console.log('[+] recv hooked at', recvAddr.toString(16));
    }
    
    console.log('[+] All hooks installed');
    send({type: 'ready'});
}

rpc.exports = { ping: function() { return 'pong'; } };
init();
