# -*- coding: utf-8 -*-
import socket
import sys
import bson
try:
    _unicode = unicode
except NameError:
    _unicode = str

# Create a TCP/IP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# Connect the socket to the port where the server is listening
server_address = ('localhost', 9668)
print('connecting to %s port %s' % server_address)
sock.connect(server_address)

try:
    
    # Send data
    data = {
        u'key1': u'saluté',
        u'key2': {
            u'key3': u'value3',
            u'key4': 666
        }
    }
    raw = bson.dumps(data)
    #if isinstance(raw, _unicode):
    #    raw = raw.encode('utf-8')
    print('send %s' % raw)
    
    #message = 'This is the message.  It will be repeated.'
    #raw = 'This is the message.  It will be repeated.'
    #print >>sys.stderr, 'sending "%s"' % message
    #sock.sendall(message)
    sock.send(raw)

    # Look for the response
    amount_received = 0
    #amount_expected = len(message)
    amount_expected = len(raw)
    
    while amount_received < amount_expected:
        data = sock.recv(1024)
        amount_received += len(data)
        if len(data)==0:
            break
        print('received "%s"' % data)

finally:
    print('closing socket')
    sock.close()