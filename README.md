# pyremotedev
This utility helps you developping with Python and push your changes on a remote device such as Raspberry pi.

It isn't limited on .py files and can sync all files you want (typically you can use it to develop ui).

It does not help you debugging but it can returns you output logs from python application.

## Installation
Install it from pip
> pip install pyremotedev

This will install pyremotedev python module and pyremotedev binary.

## Compatibility
Pyremotedev has been tested on:
Master on:
  *  Debian/Raspbian
  *  Windows (please make sure to add ```<python install dir>/scripts``` dir in your path)
Slave on:
  *  Debian/Raspbian

Your remote host must have ssh server installed and running.

## How it works
This utility is supposed to be imported in your python application but you can launch it manually (in this case you can't get output logs) to synchronize your directories.

Pyremotedev opens a tunnel between your computer and your remote host. Then it opens sockets to transfer requests and retrieve logs. Files are only sync from your dev env to remote, not from remote to dev env!

### Profiles
This application is based on profiles (different profiles on master and slave).

Master profile handles ip and port of your remote host while slave profile handles directory mappings (and symlink) and log file to watch

An interactive console wizard can help you to create your profiles (both master and slave)

Typical usage: I'm developping my application on my desktop computer from my cloned repository and want to test my code on my raspberry pi:
*  Python files from ```<repo>/sources/``` local dir can be mapped to ```/usr/share/pyshared/<mypythonmodule>/```
*  Html files from ```<repo>/html``` local dir can be mapped to ```/opt/<mypythonapp>/```
*  Binaries from ```<repo>/bin``` local dir can be mapped to ```/usr/local/bin/```
*  ...

You can also create symbolic links to uploaded files into another path. Typically python files from ```/usr/share/pyshared/<mypythonmodule>/``` can be symlinked to ```/usr/lib/python2.7/dist-packages/<mypythonmodule>/```

#### Master profile example
```
[myapp]
  local_dir = /home/me/myapp/
  ssh_username = pi
  remote_host = 192.168.1.XX
  ssh_password = ******
  remote_port = 22
```

#### Slave profile example
```
[myapp]
  mypython/ = /usr/share/pyshared/myapp/$_$/usr/lib/python2.7/dist-packages/raspiot/
  mybin/ = /usr/bin/$_$
  log_file_path = /var/log/raspiot.log
  myhtml/ = /opt/myapp/html/$_$
```

### Log handling
Pyremotedev is able to watch for application logs and write them in new dev env log file.

The local log file is called ```remote_<host>.log```.
 
If you embed pyremodev python module directly on your application, it can catches your application log messages (using new loghandler).

It also can watch for local file changes. To configure this case, simply fill log file entry in your profile.

Finally you can disable this feature.

Follow your remote logs using tailf (or tail -f) on the new remote log file.

## Manual launch
```
Usage: pyremotedev --master|--slave -D|--dir "directory to watch" <-c|--conf "config filepath"> <-d|--debug> <-h|--help>
  -m|--master: launch pyremotedev as master, files from watched directory will be sent to remote slave.
  -s|--slave: launch pyremotedev as slave, app will wait for sync operations.
  -c|--conf: configuration filepath. If not specify use user home dir one.
  -p|--prof: profile name to launch (doesn\'t launch wizard)
  -d|--debug: enable debug.
  -v|--version: display version.
  -h|--help: display this help.
```

### On development environment
To manage profiles or choose one:
> pyremotedev --master

To directly launch application and bypass wizard
> pyremotedev --master --prof "myprofile"

### On remote environment
To manage profiles or choose one:
> pyremotedev --slave

To directly launch application and bypass wizard
> pyremotedev --slave --prof "myprofile"

## Embed PyRemoteDev in your application (remote side)
Example of how to embed pyremotedev in your code to 
```
from pyremotedev import pyremotedev
from threading import Thread
import logging

#create profile
PROFILE = {
    u'raspiot/': {
        u'dest': u'/usr/share/pyshared/raspiot/',
        u'link': u'/usr/lib/python2.7/dist-packages/raspiot/'
    },
    u'html/': {
        u'dest': u'/opt/raspiot/html/',
        u'link': None
    },
    u'bin/': {
        u'dest': u'/usr/bin/',
        u'link': None
    }
}

class MyPyRemoteDev(Thread):
  def __init__(self):
    Thread.__init__(self)
    self.running = True
    
  def stop(self):
    self.running = False
    
  def run(self):
    slave = None
    try:
      #start pyremotedev with internal remote logging (catch all message from app logger)
      slave = pyremotedev.PyRemoteDevSlave(PROFILE, remote_logging=True)
      slave.start()

      while self.running:
        time.sleep(0.25)

    except:
      logging.exception(u'Exception occured during pyremotedev execution:')

    finally:
      slave.stop()

    slave.join()
```

## PyRemoteDev as service
You can launch pyremotedev as service (only available on linux env. Not tested on Mac env but it could be possible).
```
systemctl start pyremotedev.service
```

### Configuration
By default pyremotedev service will load your first profile, but you can override this behavior specifying the profile to launch on /etc/default/pyremotedev.conf
