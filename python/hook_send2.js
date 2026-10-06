var ws2 = null;
Process.enumerateModules().forEach(function(m) {
    if (m.name.toLowerCase().indexOf('ws2_32') !== -1) ws2 = m;
});
if (!ws2) { rpc.exports.log('ws2_32 not loaded'); }
else {
    var exports = ws2.enumerateExports();
    for (var i = 0; i < exports.length; i++) {
        if (exports[i].name === 'send') {
            Interceptor.attach(exports[i].address, {
                onEnter: function(args) {
                    this.fd = args[0].toInt32();
                    this.buf = args[1];
                    this.len = args[2].toInt32();
                    if (this.fd > 100 && this.len > 0 && this.len < 5000) {
                        var sz = Math.min(this.len, 200);
                        var arr = [];
                        for (var j = 0; j < sz; j++) {
                            arr.push(this.buf.add(j).readU8());
                        }
                        rpc.exports.log(JSON.stringify({fd: this.fd, len: this.len, data: arr}));
                    }
                }
            });
            rpc.exports.log('Hooked send on ws2_32!');
            break;
        }
    }
}
