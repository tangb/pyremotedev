import platform
import os
try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup
from pyremotedev import __version__ as VERSION
from setuptools.command.install import install

SYSTEMD_SERVICE = """[Unit]
Description=PyRemoteDev
After=network-online.target
Requires=network-online.target

[Service]
ExecStart=/usr/bin/pyremotedev
WorkingDirectory=/usr/bin
StandardOutput=syslog
StandardError=syslog
Restart=always
RestartSec=10
User=root
[Install]
WantedBy=multi-user.target"""

SYSVINIT_SERVICE = """#!/bin/sh
### BEGIN INIT INFO
# Provides: pyremotedev
# Required-Start:   $syslog $local_fs 
# Required-Stop:    $syslog $local_fs 
# Default-Start:    2 3 4 5
# Default-Stop:     0 1 6
# Short-Description: PyRemoteDev
### END INIT INFO

. /lib/lsb/init-functions

BIN_PATH=/usr/bin/
PID_PATH=/var/run/
DAEMON_USER=root
DAEMON_GROUP=root
APP=pyremotedev
DESC=PyRemoteDev

start_module() {
    start-stop-daemon --start --quiet --background --chuid $DAEMON_USER:$DAEMON_GROUP --pidfile "$3" --make-pidfile --exec "$2" -- "$4"
    if [ $? -ne 0 ]; then
        log_failure_msg "Failed"
        exit 1
    fi
    if [ $? -eq 0 ]; then
        log_success_msg "Done"
    fi
}

start() {
    echo "Starting $DESC..."
    if [ -f "$BIN_PATH$APP" ]
    then
        start_module "$APP" "$BIN_PATH$APP" "$PID_PATH$APP.pid"
    fi
}

stop_module() {
    start-stop-daemon --stop --quiet --oknodo --pidfile "$3"
    if [ $? -ne 0 ]; then
        log_failure_msg "Failed"
        exit 1
    fi
    if [ $? -eq 0 ]; then
        log_success_msg "Done"
    fi
}

stop() {
    echo "Stopping $DESC..."
    if [ -f "$BIN_PATH$APP" ]
    then
        stop_module "$APP" "$BIN_PATH$APP" "$PID_PATH$APP.pid"
    fi
}

force_reload() {
    stop
    start
}

status() {
    run=`pgrep -f /usr/bin/$APP | wc -l`
    if [ $run -eq 1 ]
    then
        echo "$APP is running"
    else
        echo "$APP is NOT running"
    fi
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    force-reload)
        force_reload
        ;;
    restart)
        stop
        start
        ;;
    status)
        status
        ;;
    *)
        echo "Usage: $DESC {start|stop|force-reload|restart}"
        exit 2
esac
"""

DEFAULT_CONFIG = """DAEMON_PROFILE_NAME=None
DAEMON_MODE='slave'
"""

class InstallExtraFiles(install):
    def run(self):
        install.run(self)
        if os.path.exists('/lib/systemd/system/'):
            #systemd service
            fd = open('/lib/systemd/system/pyremotedev.service', 'w+')
            fd.write(SYSTEMD_SERVICE)
            fd.close()

        else:
            #sysvinit service
            fd = open('/etc/init.d/pyremotedev', 'w+')
            fd.write(SYSVINIT_SERVICE)
            fd.close()

        #default config
        if os.path.exists('/etc/default'):
            fd = open('/etc/default/pyremotedev.conf', 'w+')
            fd.write(DEFAULT_CONFIG)
            fd.close()

setup(
    name = 'pyremotedev',
    version = VERSION,
    description = 'Sync your repo to remote host',
    author = 'Tanguy Bonneau',
    author_email = 'tanguy.bonneau@gmail.com',
    maintainer = 'Tanguy Bonneau',
    maintainer_email = 'tanguy.bonneau@gmail.com',
    url = 'http://www.github.com/tangb/pyremotedev/',
    packages = ['pyremotedev'],
    include_package_data = True,
    install_requires = ['watchdog>=0.8.3,<0.9', 'bson>=0.5.0,<0.6', 'sshtunnel>=0.1.2,<0.2', 'appdirs>=1.4.3,<1.5', 'pygtail>=0.6.1,<0.7'],
    scripts = ['bin/pyremotedev'],
    cmdclass = {'install': InstallExtraFiles}
)

