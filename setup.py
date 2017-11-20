try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup
from pyremotedev import pyremotedev

setup(
    name = 'pyremotedev',
    version = pyremotedev.VERSION,
    description = 'Sync your repo to remote host',
    author = 'Tanguy Bonneau',
    author_email = 'tanguy.bonneau@gmail.com',
    maintainer = 'Tanguy Bonneau',
    maintainer_email = 'tanguy.bonneau@gmail.com',
    url = 'http://www.github.com/tangb/pyremotedev/',
    packages = ['pyremotedev'],
    include_package_data = True,
    install_requires = ['watchdog==0.8.3', 'bson==0.5.0', 'sshtunnel==0.1.2', 'appdirs==1.4.3'],
    scripts=['bin/pyremotedev']
)

