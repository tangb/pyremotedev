try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup
from pyremotedev import __version__ as VERSION

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
    install_requires = ['watchdog>=0.8.3,<0.9', 'bson>=0.5.0,<0.6', 'sshtunnel>=0.1.2,<0.2', 'appdirs>=1.4.3,<1.5'],
    scripts=['bin/pyremotedev']
)

