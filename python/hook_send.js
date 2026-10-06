var ws2 = null;
Process.enumerateModules().forEach(function(m) {
    if (m.name.toLowerCase().indexOf('ws2_32') !== -1) ws2 = m;
});
if (!ws2) { console.log('ws2_32 not loaded'); }
else {
    var exports = ws2.enumerateExports();
    for (var i = 0; i < exports.length; i++) {
        if (exports[i].name === 'send') {
            Interceptor.attach(exports[i].address, {
                onEnter: function(args) {
                    this.fd = args[0].toInt32();
                    this.buf = args[1];
                    this.len = args[2].toInt32();
                    if (this.fd > 100 && this.len > 0 && this.len < 2000) {
                        var data = Memory.readByteArray(this.buf, Math.min(this.len, 100));
                        var arr = new Uint8Array(data);
                        var hex = Array.from(arr).map(function(b){return ('0'+b.toString(16)).slice(-2)}).join(' ');
                        console.log('[SEND fd=' + this.fd + ' len=' + this.len + '] ' + hex);
                    }
                }
            });
            console.log('Hooked send on ws2_32!');
            break;
        }
    }
}
