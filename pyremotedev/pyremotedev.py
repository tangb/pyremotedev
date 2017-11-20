#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
from logging.handlers import RotatingFileHandler
import io
import os
import time
import socket
import getopt
import sys
import appdirs
import getpass
import platform
import subprocess
import configparser
import shutil
from appdirs import user_data_dir
from threading import Thread
from collections import deque
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from sshtunnel import SSHTunnelForwarder
import bson
try:
    input = raw_input
except Exception:
    pass

VERSION = '0.0.1'
SEPARATOR = u'$_$'



class RequestInfo(object):
    """
    Info request (client to server)
    """
    def __init__(self):
        """
        Constructor
        """
        self.goodbye = False
        self.log_record = None

    def __str__(self):
        """
        To string
        """
        if self.goodbye:
            return u'RequestInfo(goodbye)'
        elif self.log_record:
            return u'RequestInfo(log_record: %s)' % self.log_record.message

    def from_dict(self, request):
        """
        Fill request with specified dict

        Args:
            request (dict): request under dict format
        """
        for key in request.keys():
            if key == u'goodbye':
                self.goodbye = request[key]
            elif key == u'log_record':
                self.log_record = request[key]

    def to_dict(self):
        """
        Convert object to dict for easier json/bson conversion

        Return:
            dict: class member onto dict
        """
        out = {
            u'goodbye': self.goodbye,
            u'log_record': self.log_record
        }

        return out





class RequestCommand(object):
    """
    Command request (server to client)
    """

    COMMAND_UPDATE = 0
    COMMAND_MOVE = 1
    COMMAND_CREATE = 2
    COMMAND_DELETE = 3

    TYPE_FILE = 0
    TYPE_DIR = 1

    def __init__(self):
        """
        Constructor
        """
        self.command = None
        self.type = None
        self.src = None
        self.dest = None
        self.content = u''

    def __str__(self):
        """
        To string method
        """
        command = None
        if self.command == self.COMMAND_UPDATE:
            command = u'UPDATE'
        elif self.command == self.COMMAND_MOVE:
            command = u'MOVE'
        elif self.command == self.COMMAND_CREATE:
            command = u'CREATE'
        elif self.command == self.COMMAND_DELETE:
            command = u'DELETE'

        type_ = None
        if self.type == self.TYPE_DIR:
            type_ = u'DIR'
        else:
            type_ = u'FILE'

        return u'RequestCommand(command:%s, type:%s, src:%s, dest:%s, content:%d bytes)' % (command, type_, self.src, self.dest, len(self.content))

    def from_dict(self, request):
        """
        Fill request with specified dict

        Args:
            request (dict): request under dict format
        """
        for key in request.keys():
            if key == u'command':
                self.command = request[key]
            elif key == u'type':
                self.type = request[key]
            elif key == u'src':
                self.src = request[key]
            elif key == u'dest':
                self.dest = request[key]
            if key == u'content':
                self.content = request[key]

    def to_dict(self):
        """
        Convert object to dict for easier json/bson conversion

        Return:
            dict: class member onto dict
        """
        out = {
            u'command': self.command,
            u'type': self.type,
            u'src': self.src
        }
        if self.dest:
            out[u'dest'] = self.dest
        if len(self.content) > 0:
            out[u'content'] = self.content

        return out




class Buffer(object):
    """
    Handle socket buffer
    """

    def __init__(self, request_object):
        """
        Constructor

        Args:
            request_object (object): request class instance to build
        """
        self.buffer = '' #not unicode!
        self.request_object = request_object
        self.logger = logging.getLogger(self.__class__.__name__)

    def process(self, raw):
        """
        Process specified buffer rebuilding received request

        Args:
            raw (string): raw data received from socket

        Return:
            request instance object as specified in constructor
        """
        #update buffer
        self.buffer += raw

        #process buffer
        while True:
            if self.buffer.startswith('::LENGTH='):
                #extract content from raw
                _, header, data = self.buffer.split('::', 2)
                header_length = len(header) + 4 #add length of 2x"::"
                self.logger.debug('Header="%s" (%d bytes)' % (header, header_length))
                try:
                    data_length = int(header.split('=')[1])
                except ValueError:
                    #invalid header, remove bad part from it and continue. It will be cleaned during next statement
                    self.buffer = self.buffer[len(self.buffer)+len(header):]
                    continue

                #parse data
                self.logger.debug(u'header length=%d, len(data)=%d' % (data_length, len(data)))
                if data_length > 0 and self.buffer and len(self.buffer) >= data_length:
                    #enough data buffered, rebuild request

                    #get data and reduce buffer
                    data = data[:data_length]
                    self.buffer = self.buffer[data_length+header_length:]
                    self.logger.debug('Buffer status (first 10 chars): "%s" (%d bytes)' % (self.buffer[:10], len(self.buffer)))

                    #get request and push to executor
                    req = bson.loads(data)
                    request = self.request_object()
                    request.from_dict(req)
                    self.logger.debug(u'Received request: %s' % request)
                    return request

                else:
                    #not enough buffer, return to wait for new buffer filling
                    self.logger.debug('Buffer is not filled enough. Request socket for new data.')
                    return None

            elif len(self.buffer) == 0:
                #no more buffer to read, stop statement
                return None

            else:
                #invalid buffer, it should starts with header!
                #try to purge buffer head until start of valid new header
                self.logger.debug(u'Invalid buffer detected, trying to recover to useful buffer... [%s]' % (self.buffer[:10]))
                pos = self.buffer.find('::LENGTH=')
                if pos >= 0:
                    self.buffer = self.buffer[pos:]
                else:
                    #no header found, clear buffer
                    self.buffer = u''
                time.sleep(1.0)





class RemoteLogHandler(logging.Handler):
    """
    Catch logs and send them to developper console
    """
    def __init__(self, send_callback):
        """
        Constructor
        """
        logging.Handler.__init__(self)

        #members
        self.send_callback = send_callback

    def emit(self, record):
        """
        Emit log: send log record to developper environment

        Args:
            record (LogRecord): log record
        """
        self.send_callback(record)





class Synchronizer(Thread):
    """
    Synchronizer is in charge to send requests to remote throught ssh tunnel.
    It handles connection and reconnection with remote.
    A buffer keeps track of changes when remote is disconnected.
    """
    def __init__(self, remote_host, remote_port, ssh_username, ssh_password, forward_port=52666):
        """
        Constructor

        Args:
            remote_host (string): remote ip address
            remote_port (int): remote port
            ssh_username (string): ssh username
            ssh_password (string): ssh password
            forward_port (int): forwarded port (default is 52666)
        """
        Thread.__init__(self)

        #members
        self.logger = logging.getLogger(self.__class__.__name__)
        self.running = True
        self.__tunnel_opened = False
        self.__socket_connected = False
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.ssh_username = ssh_username
        self.ssh_password = ssh_password
        self.forward_port = forward_port
        self.__queue = deque(maxlen=200)
        self.tunnel = None
        self.socket = None
        self.__send_socket_attemps = 0
        self.buffer = Buffer(RequestInfo)

        #init remote logger
        self.remote_logger = self.__init_remote_logger()

    def __del__(self):
        """
        Destructor
        """
        self.stop()

    def __init_remote_logger(self):
        """
        Init remote logger

        Return:
            Logger: logger instance
        """
        remote_logger = logging.getLogger('remoteLogger')

        #remove handlers inherited from root logger
        for handler in remote_logger.handlers[:]:
            remote_logger.removeHandler(handler)

        #add new handler (file handler only)
        hdl = RotatingFileHandler('remote.log', maxBytes=2048000, backupCount=2, encoding='utf-8')
        fmt = logging.Formatter('%(asctime)s %(name)-12s[%(filename)s:%(lineno)d] %(levelname)-5s : %(message)s')
        hdl.setFormatter(fmt)
        remote_logger.addHandler(hdl)

        #always configure level to DEBUG
        remote_logger.setLevel(logging.DEBUG)

        return remote_logger

    def __open_tunnel(self):
        """
        Open tunnel

        Return:
            bool: True if tunnel opened successfully
        """
        try:
            self.tunnel = SSHTunnelForwarder(
                (self.remote_host, self.remote_port),
                ssh_username=self.ssh_username,
                ssh_password=self.ssh_password,
                remote_bind_address=(u'127.0.0.1', self.forward_port)
            )
            self.tunnel.start()
            self.__tunnel_opened = True

            return True

        except Exception:
            self.logger.exception(u'Tunnel exception:')
            self.__tunnel_opened = False

        return False

    def __connect_socket(self):
        """
        Connect socket

        Return:
            bool: True if socket connected successfully
        """
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(0.5)
            self.socket.connect((u'127.0.0.1', self.forward_port))
            self.__socket_connected = True

            return True

        except Exception:
            #self.logger.exception(u'Socket exception:')
            self.__socket_connected = False

        return False

    def connect(self):
        """
        Connect to remote

        Return:
            bool: True if connection is successful
        """
        if not self.__tunnel_opened:
            #open tunnel
            if self.__open_tunnel():
                #connect socket
                if self.__connect_socket():
                    self.logger.debug(u'Socket connected')
                    return True

            #unable to open tunnel or connect socket
            self.logger.debug(u'Unable to open tunnel or connect socket (please check your credentials)')
            return False

        else:
            #tunnel opened, connect socket
            if self.__connect_socket():
                return True

            #unable to connect socket
            self.logger.debug(u'Unable to connect socket')
            return False

    def __close_tunnel(self):
        """
        Close tunnel
        """
        if self.tunnel:
            self.tunnel.stop()
        self.__tunnel_opened = False

    def __disconnect_socket(self):
        """
        Disconnect socket
        """
        if self.socket:
            self.socket.close()
        self.__socket_connected = False

    def disconnect(self):
        """
        Disconnect from remote both tunnel and socket)
        """
        self.__disconnect_socket()
        self.__close_tunnel()

    def is_connected(self):
        """
        Return connection status

        Return:
            bool: True if connected to remote
        """
        return self.__tunnel_opened and self.__socket_connected

    def add_request(self, request):
        """
        Add request to queue. The request will be processed as soon as possible

        Args:
            request (Request): request instance
        """
        self.logger.debug(u'Request added %s' % request)
        self.__queue.appendleft(request)

    def __send_request_to_remote(self, request):
        """
        Send request to remote

        Args:
            request (Request): request instance

        Return:
            bool: False if remote is not connected
        """
        try:
            #send bsonified request
            data = bson.dumps(request.to_dict())
            raw = '::LENGTH=%d::%s' % (len(data), data)
            self.logger.debug('====> socket send request (%d bytes) %s' % (len(raw), request))
            self.socket.send(raw)
            self.__send_socket_attemps = 0

            return True

        except Exception:
            logging.exception(u'Send request exception:')

            #sending problem watchdog
            self.__send_socket_attemps += 1
            if self.__send_socket_attemps > 10:
                self.logger.critical('Too many sending attempts. Surely a unhandled bug, Please relaunch application with debug enabled and add new issue in repository joining debug output. Thank you very much.')
                self.stop()

            #disconnect all, it will reconnect after next try
            self.disconnect()

        return False

    def stop(self):
        """
        Stop synchronizer
        """
        self.running = False

    def run(self):
        """
        Main process
        """
        while self.running:
            can_send = False
            if not self.is_connected():
                if self.connect():
                    can_send = True
                    self.logger.info(u'Connected')
            else:
                #already connected
                can_send = True

            if not can_send:
                #not connected, retry
                self.logger.debug(u'Not connected, retry in 1 second')
                time.sleep(1.0)
                continue

            if not self.running:
                break

            try:
                req = self.__queue.pop()
                if not self.__send_request_to_remote(req):
                    #failed to send request, insert again the request for further retry
                    self.__queue.append(req)

            except IndexError:
                #no request available
                pass

            #receive data from server
            try:
                raw = self.socket.recv(1024)
                if raw:
                    request = self.buffer.process(raw)
                    if not request:
                        pass
                    elif request.goodbye:
                        #client disconnect, force server disconnection to allow new connection
                        self.logger.debug(u'Client is disconnected')
                        self.disconnect()
                    elif request.log_record:
                        #received log record
                        self.logger.debug(u'Client sent log record')
                        self.remote_logger.handle(request.log_record)

            except socket.timeout:
                pass

            except Exception:
                #error on socket. disconnect
                self.logger.exception('Exception on server process:')
                self.disconnect()

        self.logger.debug(u'Synchronizer terminated')

        #clear queue content
        self.__queue.clear()

        #disconnect
        self.disconnect()





class LocalRepositoryHandler(FileSystemEventHandler):
    """
    Local repository changes handler.
    It watches for filesystem changes, filter event if necessary and post request
    """

    REJECTED_FILENAMES = [
        u'4913' #vim temp file to check user permissions
    ]
    REJECTED_EXTENSIONS = [
        u'.swp', #vim
        u'.swpx', #vim
        u'.swx', #vim
        u'.tmp' #generic?
    ]
    REJECTED_PREFIXES = [u'~']
    REJECTED_SUFFIXES = [u'~']

    def __init__(self, synchronizer):
        """
        Constructor

        Args:
            synchronizer (Synchronizer): synchronizer instance
        """
        self.sync = synchronizer
        self.logger = logging.getLogger(self.__class__.__name__)

    def __get_type(self, event):
        """
        Return event type

        Return:
            int: event type as declared in Request class
        """
        if event and event.is_directory:
            return RequestCommand.TYPE_DIR

        return RequestCommand.TYPE_FILE

    def __filter_event(self, event):
        """
        Analyse event and return True if event must be filtered

        Return:
            bool: True if event must be filtered
        """
        if not event:
            #filter invalid event
            return True
        if event.src_path == u'.%s' % __file__:
            #filter event on current script
            return True
        if event.src_path == u'.':
            #filter root event
            return True
        src_ext = os.path.splitext(event.src_path)[1]
        if src_ext in self.REJECTED_EXTENSIONS:
            #filter invalid extension
            return True
        for prefix in self.REJECTED_PREFIXES:
            #filter by prefix
            if event.src_path.startswith(prefix):
                return True
            if getattr(event, u'dest_path', None) and event.dest_path.startswith(prefix):
                return True
        for suffix in self.REJECTED_SUFFIXES:
            #filter by suffix
            if event.src_path.endswith(suffix):
                return True
            if getattr(event, u'dest_path', None) and event.dest_path.endswith(prefix):
                return True
        for filename in self.REJECTED_FILENAMES:
            #filter by filename
            if event.src_path.endswith(filename):
                return True

        return False

    def send_request(self, request):
        """
        Send specified request to remote

        Args:
            request (Request): request instance
        """
        self.logger.debug(u'Request: %s' % request)
        if self.sync.running:
            self.sync.add_request(request)

    def on_modified(self, event):
        self.logger.debug(u'on_modified: %s' % event)
        if self.__filter_event(event):
            self.logger.debug(u' -> Filter event')
            return
        req = RequestCommand()
        req.command = RequestCommand.COMMAND_UPDATE
        req.type = self.__get_type(event)
        req.src = event.src_path
        if req.type == RequestCommand.TYPE_DIR:
            self.logger.debug(u'Drop update on directory')
            return
        if req.type == RequestCommand.TYPE_FILE:
            #send file content
            try:
                with io.open(event.src_path, u'rb') as src:
                    req.content = src.read()
                if len(req.content) == 0:
                    self.logger.debug('Drop empty file update')
                    return
            except Exception:
                self.logger.exception(u'Unable to read src file "%s"' % event.src_path)
                return
        self.send_request(req)

    def on_moved(self, event):
        self.logger.debug(u'on_moved: %s' % event)
        if self.__filter_event(event):
            self.logger.debug(u' -> Filter event')
            return
        req = RequestCommand()
        req.command = RequestCommand.COMMAND_MOVE
        req.type = self.__get_type(event)
        req.src = event.src_path
        req.dest = event.dest_path
        self.send_request(req)

    def on_created(self, event):
        self.logger.debug(u'on_created: %s' % event)
        if self.__filter_event(event):
            self.logger.debug(u' -> Filter event')
            return
        req = RequestCommand()
        req.command = RequestCommand.COMMAND_CREATE
        req.type = self.__get_type(event)
        req.src = event.src_path
        if req.type == RequestCommand.TYPE_FILE:
            #send file content
            try:
                with io.open(event.src_path, u'rb') as src:
                    req.content = src.read()
            except Exception:
                self.logger.exception(u'Unable to read src file "%s"' % event.src_path)
                return
        self.send_request(req)

    def on_deleted(self, event):
        self.logger.debug(u'on_deleted: %s' % event)
        if self.__filter_event(event):
            self.logger.debug(u' -> Filter event')
            return
        req = RequestCommand()
        req.command = RequestCommand.COMMAND_DELETE
        req.type = self.__get_type(event)
        req.src = event.src_path
        self.send_request(req)





class RequestExecutor(Thread):
    """
    Request executor will process request command on remote filesystem
    """

    def __init__(self, mappings):
        """
        Constructor

        Args:
            mappings (dict): directory mappings (src<=>dst)
        """
        Thread.__init__(self)

        #members
        self.logger = logging.getLogger(self.__class__.__name__)
        self.running = True
        self.__queue = deque(maxlen=200)
        self.mappings = mappings

        #build new mappings for process convenience
        self.new_mappings = {}
        for src in self.mappings.keys():
            src_parts = self.split_path(src)
            new_src = SEPARATOR.join(src_parts)
            link_parts = self.split_path(self.mappings[src][u'link'])
            new_link = SEPARATOR.join(link_parts)

            #always end new src path by separator to protect substitution
            new_src += SEPARATOR

            #save new mappings
            self.new_mappings[new_src] = {
                u'original_src': src,
                u'original_dest': self.mappings[src][u'dest'],
                u'original_link': self.mappings[src][u'link'],
                u'link': new_link
            }
        self.logger.debug('New mappings: %s' % self.new_mappings)

    def stop(self):
        """
        Stop process
        """
        self.running = False

    def add_request(self, request):
        """
        Add specified request to queue

        Args:
            request (Request): request instance
        """
        self.logger.debug(u'Request added %s' % request)
        self.__queue.appendleft(request)

    def split_path(self, path):
        """
        Explode path into dir/dir/.../filename

        Source:
            https://stackoverflow.com/a/27065945

        Args:
            path (string): path to split

        Return:
            list: list of path parts
        """
        parts = []
        (path, tail) = os.path.split(path)
        while path and tail:
            parts.append(tail)
            (path, tail) = os.path.split(path)
        parts.append(os.path.join(path, tail))

        out = map(os.path.normpath, parts)[::-1]
        if len(out) > 0 and out[0] == u'.':
            #remove starting .
            return out[1:]
        return out

    def __apply_mapping(self, path):
        """
        Apply mapping on specified path substituing src path by dest path

        Args:
            path (string): path from dev environment

        Return:
            dict or None: None if mapping not found, or mapped dir and link::
                {
                    'path': mapped path
                    'link': link
                }
        """
        if len(self.mappings) == 0:
            #no mapping configured, copy to current path
            return path

        else:
            #mappings configured, try to find valid one

            #make path useable for processing
            parts = self.split_path(path)
            if len(parts) > 0 and parts[0] == u'.':
                parts = parts[1:]
            path = os.path.sep.join(parts)
            new_path = SEPARATOR.join(parts)
            self.logger.debug('path=%s new_path=%s' % (path, new_path))

            #look for valid mapping
            for mapping_src in self.new_mappings.keys():
                self.logger.debug(' --> %s startswith %s' % (new_path, mapping_src))
                if new_path.startswith(mapping_src):
                    #found mapping
                    self.logger.debug('  Found!')
                    new_path = path.replace(self.new_mappings[mapping_src][u'original_src'], self.new_mappings[mapping_src][u'original_dest'], 1)
                    link = None
                    if self.new_mappings[mapping_src][u'original_link']:
                        self.logger.debug(self.new_mappings[mapping_src])
                        self.logger.debug(mapping_src)
                        #link = new_path.replace(mapping_src, self.new_mappings[mapping_src][u'original_link'], 1)
                        link = path.replace(self.new_mappings[mapping_src][u'original_src'], self.new_mappings[mapping_src][u'original_link'], 1)
                    return {
                        u'path': new_path,
                        u'link': link
                    }

            #no mapping found
            return None

    def __process_request(self, request):
        """
        Process request

        Args:
            request (Request): request to process

        Return:
            bool: True if request processed succesfully
        """
        try:
            #set is_dir
            is_dir = False
            if request.type == RequestCommand.TYPE_DIR:
                is_dir = True

            #apply mappings
            if request.src:
                src_mapping = self.__apply_mapping(request.src)
                self.logger.debug('Src mapping: %s <==> %s' % (request.src, src_mapping))
                if src_mapping is None:
                    self.logger.debug(u'Unmapped src %s directory. Drop request' % request.src)
                    return False
                src = src_mapping[u'path']
                link_src = src_mapping[u'link']

            if request.dest:
                dest_mapping = self.__apply_mapping(request.dest)
                self.logger.debug('Dest mapping: %s <==> %s' % (request.dest, dest_mapping))
                if dest_mapping is None:
                    self.logger.debug(u'Unmapped dest %s directory. Drop request' % request.dest)
                    return False
                dest = dest_mapping[u'path']
                link_dest = dest_mapping[u'link']

            #execute request
            if request.command == RequestCommand.COMMAND_CREATE:
                self.logger.debug('Process request CREATE for src=%s' % (src))
                if is_dir:
                    #create new directory
                    if not os.path.exists(src):
                        os.makedirs(src)
                else:
                    #create new file
                    fd = io.open(src, u'wb')
                    fd.write(request.content)
                    fd.close()

                    #create link
                    if link_src and not os.path.exists(link_src):
                        os.symlink(src, link_src)

            elif request.command == RequestCommand.COMMAND_DELETE:
                self.logger.debug('Process request DELETE for src=%s' % (src))
                if is_dir:
                    #delete directory
                    if os.path.exists(src):
                        shutil.rmtree(src)
                else:
                    #remove associated symlink firstly
                    self.logger.debug('=======> %s %s' % (link_src, os.path.exists(link_src)))
                    if link_src and os.path.exists(link_src):
                        self.logger.debug('Remove link_src: %s' % link_src)
                        os.remove(link_src)

                    #delete file
                    if os.path.exists(src):
                        os.remove(src)

            elif request.command == RequestCommand.COMMAND_MOVE:
                self.logger.debug('Process request MOVE for src=%s dest=%s' % (src, dest))

                #remove link firstly
                if not is_dir:
                    if link_src and os.path.exists(link_src):
                        self.logger.debug(u'Remove src symlink %s' % link_src)
                        os.remove(link_src)
                        self.logger.debug(u'Create dest symlink %s==>%s' % (dest, link_dest))
                        os.symlink(dest, link_dest)

                #move directory or file
                if os.path.exists(src):
                    os.rename(src, dest)

            elif request.command == RequestCommand.COMMAND_UPDATE:
                self.logger.debug('Process request UPDATE for src=%s' % (src))
                if is_dir:
                    #update directory
                    self.logger.debug(u'Update request dropped for directories (useless command)')
                else:
                    #update file content
                    #if os.path.exists(src):
                    fd = io.open(src, u'wb')
                    fd.write(request.content)
                    fd.close()

                    #create link
                    if link_src and not os.path.exists(link_src):
                        self.logger.debug(u'Create symlink %s' % link_src)
                        os.symlink(src, link_src)

            else:
                #unhandled case
                self.logger.warning(u'Unhandled command in request %s' % request)
                return False

            return True

        except:
            self.logger.exception(u'Exception during request processing %s:' % request)
            return False

    def run(self):
        """
        Main process: unqueue request and process it
        """
        while self.running:
            try:
                request = self.__queue.pop()
                if not self.__process_request(request):
                    #failed to process request
                    #TODO what to do ?
                    pass

            except IndexError:
                #no request available
                time.sleep(0.25)





class RemoteClient(Thread):
    """
    Remote client thread handles request send by repository handler
    It will execute request commands on remote host.
    """

    def __init__(self, ip, port, clientsocket, executor):
        """
        Constructor

        Args:
            ip (string): repository ip address
            port (int): repository connection port
            clientsocket (socket): socket instance returned by accept
            executor (RequestExecutor): RequestExecutor instance
        """
        Thread.__init__(self)
        #Thread.daemon = True #autokill client threads when slave stopped

        #members
        self.logger = logging.getLogger(self.__class__.__name__)
        self.ip = ip
        self.port = port
        self.clientsocket = clientsocket
        self.clientsocket.settimeout(0.5)
        self.executor = executor
        self.buffer = Buffer(RequestCommand)
        self.running = True

    """
    def __process_buffer(self, buf):
        #Process specified buffer rebuilding received request
        while True:
            if buf.startswith('::LENGTH='):
                #extract content from raw
                _, header, data = buf.split('::', 2)
                header_length = len(header) + 4 #add length of 2x"::"
                self.logger.debug('Header="%s" (%d bytes)' % (header, header_length))
                try:
                    data_length = int(header.split('=')[1])
                except ValueError:
                    #invalid header, remove bad part from it and continue. It will be cleaned during next statement
                    buf = buf[len(buf)+len(header):]
                    continue

                #parse data
                self.logger.debug(u'header length=%d, len(data)=%d' % (data_length, len(data)))
                if data_length > 0 and buf and len(buf) >= data_length:
                    #enough data buffered, rebuild request

                    #get data and reduce buffer
                    data = data[:data_length]
                    buf = buf[data_length+header_length:]
                    self.logger.debug('Buffer status (first 10 chars): "%s" (%d bytes)' % (buf[:10], len(buf)))

                    #get request and push to executor
                    req = bson.loads(data)
                    request = RequestCommand()
                    request.from_dict(req)
                    self.logger.debug(u'Received request: %s' % request)
                    self.executor.add_request(request)

                else:
                    #not enough buffer, return to wait for new buffer filling
                    self.logger.debug('Buffer is not filled enough. Request socket for new data.')
                    return buf

            elif len(buf) == 0:
                #no more buffer to read, stop statement
                return buf

            else:
                #invalid buffer, it should starts with header!
                #try to purge buffer head until start of valid new header
                self.logger.debug(u'Invalid buffer detected, trying to recover to useful buffer... [%s]' % (buf[:10]))
                pos = buf.find('::LENGTH=')
                if pos >= 0:
                    buf = buf[pos:]
                else:
                    #no header found, clear buffer
                    return u''
    """

    def stop(self):
        """
        Stop process
        """
        self.logger.debug('Stop requested')
        self.running = False

    def send_log(self, record):
        """
        Send log to developper

        Args:
            record (LogRecord): log record to send
        """
        if self.clientsocket:
            #prepare request
            request = RequestInfo()
            request.log_record = record

            #send request
            try:
                data = bson.dumps(request.to_dict())
                raw = '::LENGTH=%d::%s' % (len(data), data)
                self.logger.debug('==> socket send log record (%d bytes) %s' % (len(raw), request))
                self.clientsocket.send(raw)

            except Exception:
                self.logger.exception(u'Exception during log sending:')

    def get_log_handler(self):
        """
        Return logging.Handler instance to send log message to server

        Return:
            RemoteLogHandler: log handler
        """
        return RemoteLogHandler(self.send_log)

    def run(self):
        """
        Main process: read data from socket and rebuild request.
        Then it send it to request executor instance
        """
        self.logger.debug(u'Connection of %s:%s' % (self.ip, self.port))
        #data_length = 0
        #buf = ''
        while self.running:

            try:
                raw = self.clientsocket.recv(1024)
                self.logger.debug(u'<<<<<<<<<< recv socket raw=%d bytes' % len(raw))

                #check end of connection
                if not raw:
                    self.logger.debug(u'Disconnection of %s:%s' % (self.ip, self.port))
                    break

                #process buffer with received raw data
                #buf += raw
                #buf = self.__process_buffer(buf)
                request = self.buffer.process(raw)
                if request:
                    self.executor.add_request(request)

            except socket.timeout:
                pass

            except Exception:
                self.logger.exception(u'Exception for %s:%s:' % (self.ip, self.port))

        #properly close server connection
        request = RequestInfo()
        request.goodbye = True
        data = bson.dumps(request.to_dict())
        raw = '::LENGTH=%d::%s' % (len(data), data)
        self.logger.debug('====> socket send request (%d bytes) %s' % (len(raw), request))
        self.clientsocket.send(raw)

        #close socket
        if self.clientsocket:
            try:
                self.clientsocket.shutdown(socket.SHUT_WR)
                self.clientsocket.close()
            except Exception:
                pass

        self.logger.debug(u'Thread stopped for %s:%s' % (self.ip, self.port))





class ConfigFile():
    """
    Master config file handler
    """
    def __init__(self, config_file):
        """
        Constructor

        Args:
            config_file (string): valid configuration file path (including filename)
        """
        self.config_file = config_file
        self.logger = logging.getLogger(self.__class__.__name__)

    def __load_config_parser(self):
        """
        Load config parser instance:
        """
        if not os.path.exists(os.path.dirname(self.config_file)):
            os.makedirs(os.path.dirname(self.config_file))

        if not os.path.exists(self.config_file):
            #file doesn't exist, create empty one
            with open(self.config_file, u'w') as fd:
                fd.write('')
            #make sure file is written
            time.sleep(1.0)
            self.logger.info(u'Config file written to "%s"' % self.config_file)

        #load config parser
        config = configparser.ConfigParser()
        config.read(self.config_file)

        return config

    def __save_config_parser(self, config):
        """
        Save config parser instance to file

        Args:
            config (ConfigParser): config parser instance
        """
        with open(self.config_file, u'w') as config_file:
            config.write(config_file)

    def clear_terminal(self):
        """
        Clear terminal
        """
        os.system(u'cls' if platform.system() == u'Windows' else u'clear')

    def load(self):
        """
        Load config file

        Return:
            dict: dictionnary of profiles
        """
        try:
            #get config parser
            config = self.__load_config_parser()

            #convert config parser to dict
            profiles = {}
            for profile_name in config.sections():
                profiles[profile_name] = self._get_profile_values(profile_name, config[profile_name])

            return profiles

        except:
            self.logger.exception(u'Unable to read config file "%s"' % self.config_file)

    def _get_profile_values(self, profile_name, profile):
        """
        Return profile values

        Return:
            dict: dict of profile values
        """
        raise NotImplemented('Method _get_profile_values must be implemented!')

    def select_profile(self):
        """
        Display profile selector
        """
        #load current conf
        conf = self.load()

        #iterate until profile index is selected
        profile_index = 0
        while True:
            (profile_index, conf) = self.__load_profile_menu(conf)
            if profile_index >= 0:
                #profile selected
                break

        #load profile
        return conf[conf.keys()[profile_index]]

    def __add_profile_menu(self, conf):
        """
        Show profile addition menu

        Args:
            conf (dict): current config (dict format as returned by load method)

        Return:
            dict: updated (or not) conf dict
        """
        self.clear_terminal()
        print(u'Follow this wizard to create new configuration profile.')
        print(u'Be careful if existing profile name already exists, it will be overwritten!')

        (profile_name, profile) = self._get_new_profile_values()
        self.add_profile(profile_name, profile)

        return self.load()

    def _get_new_profile_values(self):
        """
        Return new profile values

        Return:
            tuple::
                (
                    string: profile name
                    dict: dict of new profile values
                )
        """
        raise NotImplemented('Method _get_new_profile_values must be implemented!')

    def __delete_profile_menu(self, conf):
        """
        Show profile deletion menu

        Args:
            conf (dict): current config (dict format as returned by load method)

        Return:
            dict: updated (or not) conf dict
        """
        self.clear_terminal()
        print('Type profile number to delete:')
        index = 0
        max_profiles = len(conf.keys())
        for profile_name in conf.keys():
            profile_string = self._get_profile_entry_string(profile_name, conf[profile_name])
            print(u' %d) %s' % (index, profile_string))
            index += 1
        print(u'Empty entry to return back')
        choice = ''
        while len(choice) == 0:
            choice = input(u'>> ').decode(u'utf-8')
            if choice.strip() == u'':
                #return back
                return conf
            else:
                try:
                    temp = int(choice)
                    if temp < 0 or temp >= max_profiles:
                        choice = u''
                except:
                    choice = u''

        #perform deletion
        profile_name = conf.keys()[int(choice)]
        self.delete_profile(profile_name)

        return self.load()

    def _get_profile_entry_string(self, profile_name, profile):
        """
        Return profile entry string

        Return:
            string: entry string
        """
        raise NotImplemented('Method _get_profile_entry_string must be implemented!')

    def __load_profile_menu(self, conf):
        """
        Show load profiles menu

        Args:
            conf (dict): current config (dict format as returned by load method)

        Return:
            tuple: output values::
                (
                    int: profile index to load, or negative value if other action performed,
                    dict: current conf
                )
        """
        self.clear_terminal()
        print(u'Type profile number to load it:')
        index = 0
        max_profiles = len(conf.keys())
        if len(conf.keys()) == 0:
            #no profile
            print(u'  No profile yet. Please add new one.')
        for profile_name in conf.keys():
            profile_string = self._get_profile_entry_string(profile_name, conf[profile_name])
            print(u' %d) %s' % (index, profile_string))
            index += 1
        print(u'Type "a" to add new profile')
        print(u'Type "d" to delete existing profile')
        print(u'Type "q" to quit application')
        choice = ''
        while len(choice) == 0:
            choice = input(u'>> ')
            if choice.strip() == u'a':
                conf = self.__add_profile_menu(conf)
                return -1, conf
            elif choice.strip() == u'd':
                conf = self.__delete_profile_menu(conf)
                return -2, conf
            elif choice.strip() == u'q':
                print(u'Bye bye')
                sys.exit(0)
            else:
                try:
                    temp = int(choice)
                    if temp < 0 or temp >= max_profiles:
                        #out of bounds
                        choice = u''
                except:
                    #invalid index typed
                    choice = u''

        return int(choice), conf

    def add_profile(self, profile_name, profile):
        """
        Add new profile to config

        Args:
            profile_name (string): profile name
            profile (dict): profile content
        """
        try:
            #get config parser
            config = self.__load_config_parser()

            #append new profile
            config[profile_name] = profile

            #save config
            self.__save_config_parser(config)

        except:
            self.logger.exception(u'Unable to add profile:')

    def delete_profile(self, profile_name):
        """
        Delete specified profile
        """
        try:
            #get config parser
            config = self.__load_config_parser()

            #append new profile
            if profile_name in config.sections():
                del config[profile_name]

            #save config
            self.__save_config_parser(config)

        except:
            self.logger.exception(u'Unable delete profile:')





class MasterConfigFile(ConfigFile):
    def __init__(self, config_file):
        ConfigFile.__init__(self, config_file)

    def _get_profile_values(self, profile_name, profile):
        """
        Return profile values

        Return:
            dict: dictionnary of master profile::
                {
                    'profile1': {
                        remote_host,
                        remote_port,
                        ssh_username,
                        ssh_password,
                        local_dir
                    },
                    ...
                }
        """
        return  {
            u'remote_host': profile[u'remote_host'],
            u'remote_port': int(profile[u'remote_port']),
            u'ssh_username': profile[u'ssh_username'],
            u'ssh_password': profile[u'ssh_password'].replace(u'%%', '%'),
            u'local_dir': profile[u'local_dir']
        }

    def _get_new_profile_values(self):
        """
        Return new profile values

        Return:
            tuple: profile tuple::
                (
                    profile name,
                    {
                        remote_host,
                        remote_port,
                        ssh_username,
                        ssh_password,
                        local_dir
                    }
                )
        """
        profile_name = u''
        while len(profile_name) == 0:
            profile_name = input(u'Profile name (cannot be empty): ')

        remote_host = u''
        while len(remote_host) == 0:
            remote_host = input(u'Remote ip address (cannot be empty): ')

        remote_port = u''
        while len(remote_port) == 0:
            remote_port = input(u'Remote ssh port (cannot be empty): ')
            try:
                int(remote_port)
            except:
                remote_port = ''

        ssh_username = u''
        while len(ssh_username) == 0:
            ssh_username = input(u'Remote ssh username (cannot be empty): ')

        ssh_password = u''
        while len(ssh_password) == 0:
            ssh_password = getpass.getpass(u'Remote ssh password (cannot be empty): ')
        ssh_password = ssh_password.replace(u'%', u'%%')

        local_dir = input(u'Local directory to watch (default .): ')
        if len(local_dir) == 0:
            local_dir = os.getcwd()

        #return new profile
        return (
            profile_name,
            {
                u'remote_host': remote_host,
                u'remote_port': remote_port,
                u'ssh_username': ssh_username,
                u'ssh_password': ssh_password,
                u'local_dir': local_dir
            }
        )

    def _get_profile_entry_string(self, profile_name, profile):
        """
        Return profile entry string

        Return:
            string: entry string
        """
        return u'%s [%s:%s]' % (profile_name, profile[u'remote_host'], profile[u'remote_port'])





class SlaveConfigFile(ConfigFile):
    """
    Slave config handler
    """

    def __init__(self, config_file):
        """
        Constructor
        """
        ConfigFile.__init__(self, config_file)

    def _get_profile_values(self, profile_name, profile):
        """
        Return profile values

        Return:
            dict: dictionnary of master profile::
                {
                    'profile1': {
                        'src1': {
                            'dest: 'dest1',
                            'link': 'link'
                        },
                        'src2': {
                            'dest': 'dest2',
                            'link': ''
                        }
                    },
                    ...
                }
        """
        mappings = {}
        for src in profile:
            if profile[src].find(SEPARATOR) >= 0:
                (dest, link) = profile[src].split(SEPARATOR)
            else:
                dest = profile[src]
                link = None

            mappings[src] = {
                u'dest': dest,
                u'link': link
            }

        return mappings

    def _get_new_profile_values(self):
        """
        Return new profile values

        Return:
            tuple: profile tuple::
                (
                    profile name,
                    {
                        src1: dest1,
                        ...
                    }
                )
        """
        profile_name = u''
        while len(profile_name) == 0:
            profile_name = input(u'Profile name (cannot be empty): ')

        print(u'')
        print(u'Now add mappings: source from repository root (local dir) <=> full destination path (remote dir)')
        print(u'Type "q" to stop adding mappings.')
        mappings = {}
        while True:
            print(u'')
            src = u''
            while len(src) == 0:
                src = input(u'Source directory (cannot be empty): ')
                if src == u'q':
                    break
            if src == u'q':
                break

            dest = u''
            while len(dest) == 0:
                dest = input(u'Destination directory (cannot be empty): ')
                if dest == u'q':
                    break
                if not os.path.exists(dest):
                    print(u' --> Specified path does not exist')
                    dest = u''
            if dest == u'q':
                break

            link = u''
            link_ok = False
            while not link_ok:
                link = input(u'Create link into directory (empty when no link): ')
                if link == u'q':
                    break
                if not os.path.exists(link):
                    print(u' --> Specified path does not exist')
                    link_ok = False
                link_ok = True
            if link == u'q':
                break

            #save new mapping
            if link:
                mappings[src] = u'%s%s%s' % (dest, SEPARATOR, link)
            else:
                mappings[src] = u'dest'

        #return new profile
        return (
            profile_name,
            mappings
        )

    def _get_profile_entry_string(self, profile_name, profile):
        """
        Return profile entry string

        Return:
            string: entry string
        """
        mapping = u''
        if len(profile) > 0:
            src = profile.keys()[0]
            dest = profile[src][u'dest']
            link = profile[src][u'link']
            if not link:
                link = u'(no link)'
            else:
                link = u'with link to %s' % link
            mapping = u'[%s<=>%s %s]' % (src, dest, link)
        return u'%s - %d mappings %s' % (profile_name, len(profile), mapping)




class RemotePyDevMaster(Thread):
    """
    Remotepydev master
    """
    def __init__(self):
        """
        Constructor
        """
        Thread.__init__(self)

        #members
        self.running = True
        self.logger = logging.getLogger(self.__class__.__name__)

    def stop(self):
        """
        Stop master
        """
        self.running = False

    def run(self):
        """
        Main process
        """
        #create synchronizer
        synchronizer = Synchronizer(profile[u'remote_host'], profile[u'remote_port'], profile[u'ssh_username'], profile[u'ssh_password'])
        synchronizer.start()

        #create filesystem watchdog
        observer = Observer()
        observer.schedule(LocalRepositoryHandler(synchronizer), path=profile[u'local_dir'], recursive=True)
        observer.start()

        #main loop
        try:
            while self.running:
                if not synchronizer.running:
                    break
                time.sleep(0.25)

        except:
            self.logger.exception(u'Exception:')

        finally:
            observer.stop()
            synchronizer.stop()

        #close properly application
        observer.join()
        synchronizer.join()





class RemotePyDevSlave(Thread):
    """
    Remotepydev slave
    """
    def __init__(self):
        """
        Constructor
        """
        Thread.__init__(self)

        #members
        self.running = True
        self.logger = logging.getLogger(self.__class__.__name__)

    def stop(self):
        """
        Stop master
        """
        self.running = False

    def run(self):
        """
        Main process
        """
        #create request executor
        executor = RequestExecutor(profile)
        executor.start()

        #remote clients
        remotes = []

        #main loop
        try:
            #create communication server
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.settimeout(1.0)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(('', 52666))

            self.logger.debug(u'Listening for connections...')
            while self.running:
                try:
                    server.listen(10)
                    (clientsocket, (ip, port)) = server.accept()

                    self.logger.debug(u'New client connection')
                    new_thread = RemoteClient(ip, port, clientsocket, executor)
                    remotes.append(new_thread)
                    new_thread.start()

                except socket.timeout:
                    pass

        except:
            self.logger.exception(u'Exception:')

        finally:
            executor.stop()
            for remote in remotes:
                remote.stop()

        #close properly application
        executor.join()





#main application
if __name__ == '__main__':

    logging.basicConfig(level=logging.INFO, format=u'%(asctime)s %(levelname)s : %(message)s')

    APP_NAME = os.path.splitext(__file__)[0]
    APP_AUTHOR = u'tangb'

    #main logger
    logger = logging.getLogger(u'main')

    def reset_logging(level):
        """
        Reset main logging
        """
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)

        logging.basicConfig(level=level, format=u'%(asctime)s %(levelname)s : %(message)s')

    def usage(error=''):
        """
        Application usage
        Args:
            error (string): error message to display
        """
        if len(error) > 0:
            print(u'Error: %s' % error)
            print(u'')
            print(u'Usage: pyremotedev --master|--slave -D|--dir "directory to watch" <-c|--conf "config filepath"> <-p|--prof "profile"> <-d|--debug> <-h|--help>')
            print(u' -m|--master: launch remotesync as master, files from watched directory will be sent to remote slave.')
            print(u' -s|--slave: launch remotesync as slave, app will wait for sync operations.')
            print(u' -c|--conf: configuration filepath. If not specify use user home dir one')
            print(u' -p|--prof: profile name to launch (doesn\'t launch wizard)')
            print(u' -d|--debug: enable debug.')
            print(u' -v|--version: display version.')
            print(u' -h|--help: display this help.')

    def version():
        """
        Display version
        """
        print(u'%s version %s' % (os.path.splitext(__file__)[0], VERSION))

    def application_parameters():
        """
        Parse command line and return list of application parameters

        Return:
            dict: list of application parameters::
                {
                    master (bool): True if application is launched as master
                    slave (bool): True if application is launched as slave
                    debug (bool): True if debug enabled
                    conf (string): Path of config file to open
                    prof (string): profile name to launch (drop startup select wizard)
                }
        """
        params = {
            u'master': False,
            u'slave': False,
            u'debug': False,
            u'conf' : None,
            u'prof': None
        }

        try:
            opts, args = getopt.getopt(sys.argv[1:], u'mshdc:vp:', [u'master', u'slave', u'help', u'debug', u'conf=', u'version', u'prof='])

            for opt, arg in opts:
                if opt in (u'-m', u'--master'):
                    if params[u'slave']:
                        raise Exception(u'You can\'t enable both slave and master mode')
                    params[u'master'] = True
                elif opt in (u'-m', u'--slave'):
                    if params['master']:
                        raise Exception(u'You can\'t enable both slave and master mode')
                    params[u'slave'] = True
                elif opt in (u'-h', u'--help'):
                    usage()
                    sys.exit(2)
                elif opt in (u'-d', u'--debug'):
                    params[u'debug'] = True
                elif opt in (u'-c', u'--conf'):
                    params[u'conf'] = arg
                    if not os.path.exists(params[u'conf']):
                        raise Exception(u'Specified config file does not exist (%s)' % params[u'conf'])
                elif opt in (u'-v', u'--version'):
                    version()
                    sys.exit(2)
                elif opt in (u'-p', u'--prof'):
                    params[u'prof'] = arg
                    #profile existence will be checked later

            #check some parameters
            if not params[u'master'] and not params[u'slave']:
                raise Exception(u'You must launch application as master or slave')

            #default config path
            if params[u'conf'] is None:
                path = user_data_dir(APP_NAME, APP_AUTHOR)
                if params[u'master']:
                    params[u'conf'] = os.path.join(path, u'master.conf')
                else:
                    params[u'conf'] = os.path.join(path, u'slave.conf')

        except Exception as e:
            #logger.exception('Error parsing command line arguments:')
            usage(str(e))
            sys.exit(1)

        return params

    def load_profile(params):
        """
        Load profile to run

        Args:
            params (dict): application parameters
        """
        #load conf according to master/slave switch
        if params[u'master']:
            conf = MasterConfigFile(params[u'conf'])
        else:
            conf = SlaveConfigFile(params[u'conf'])

        profile = None
        if params[u'prof'] is None:
            #show profile wizard
            profile = conf.select_profile()
            logger.debug(u'Selected profile: %s' % profile)
        else:
            #profile selected from command line
            profiles = conf.load()
            if params[u'prof'] not in profiles.keys():
                logger.fatal(u'Profile "%s" does not exist.' % params[u'prof'])
                sys.exit(1)
            profile = profiles[params[u'prof']]
            logger.debug(u'Selected profile: %s' % profile)

        return profile

    #get application parameters
    params = application_parameters()

    #reset logging
    if params[u'debug']:
        reset_logging(logging.DEBUG)

    #load application profile
    profile = load_profile(params)

    if params[u'master']:
        #local side: supposed to be the place where developper is working on
        try:
            master = RemotePyDevMaster()
            master.start()
            while master.isAlive():
                master.join(1.0)

        except KeyboardInterrupt:
            pass

        except:
            logger.exception(u'Exception occured during master exceution:')

        finally:
            logger.info(u'Stopping application...')
            master.stop()

        master.join()

    else:
        #remote side: supposed to the place where files must be updated (ie a raspberry pi)
        try:
            slave = RemotePyDevSlave()
            slave.start()
            while True:
                time.sleep(1.0)

        except KeyboardInterrupt:
            pass

        except:
            logger.exception(u'Exception occured during slave execution:')

        finally:
            logger.info(u'Stopping application...')
            slave.stop()

        slave.join()
