# -*- coding: utf-8 -*-
import bson
import socket
import sys
try:
    _unicode = unicode
except NameError:
    _unicode = str

# Create a TCP/IP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# Bind the socket to the port
server_address = ('localhost', 9668)
print('starting up on %s port %s' % (server_address))
sock.bind(server_address)

# Listen for incoming connections
sock.listen(1)

while True:
    # Wait for a connection
    print('waiting for a connection...')
    connection, client_address = sock.accept()

    try:
        print('connection from %s:%s' % (client_address))

        # Receive the data in small chunks and retransmit it
        while True:
            raw = connection.recv(1024)
            print('len(raw)=%d type(raw)=%s' % (len(raw), type(raw)))
            if raw:
                print('received type(raw)=%s raw=%s' % (type(raw), raw))
                #if isinstance(raw, str):
                #    raw = raw.decode('utf-8')
                data = bson.loads(raw)
                print('received type(data)=%s data="%s"' % (type(data), str(data)))

                print('sending data back to the client')
                connection.send(raw)
            else:
                print('no more data from %s:%s' % (client_address))
                break
            
    finally:
        # Clean up the connection
        connection.close()
