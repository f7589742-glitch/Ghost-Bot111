connections = [
    ("65709F2B", "0C1D", "tcp", 10074),
    ("5EE4AF2B", "1F90", "tcp", 10074),
    ("46956D2B", "01BB", "tcp6", 10074),
    ("28966D2B", "01BB", "tcp6", 10074),
    ("B14AF4D5", "01BB", "tcp6", 10074),
    ("BCA8FB8E", "146C", "tcp6", 10042),
    ("42956D2B", "01BB", "tcp6", 10074),
    ("8D449039", "01BB", "tcp6", 10074),
]

def decode_ip(hex_str):
    val = int(hex_str, 16)
    b = val.to_bytes(4, "little")
    return "%d.%d.%d.%d" % (b[0], b[1], b[2], b[3])

def decode_port(hex_str):
    return int(hex_str, 16)

print("Game connections (uid 10074):")
for ip_hex, port_hex, proto, uid in connections:
    if uid == 10074:
        ip = decode_ip(ip_hex)
        port = decode_port(port_hex)
        print("  %s %s:%d (0x%s:0x%s)" % (proto, ip, port, ip_hex, port_hex))

print("\nAll connections:")
for ip_hex, port_hex, proto, uid in connections:
    ip = decode_ip(ip_hex)
    port = decode_port(port_hex)
    print("  uid=%d %s %s:%d" % (uid, proto, ip, port))
