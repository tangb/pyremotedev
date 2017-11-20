# pyremotedev
This utility helps you developping with Python and push your changes on a remote device such as Raspberry pi.
It isn't limited on py files and can sync all files you want (typically you can use it to develop ui)
It does not help you debugging but it can gives you output logs from python application.

## How to use
This utility is supposed to be imported in your python application but you can launch it manually (in this case you can't get output logs).

### Profiles
This application can map local directories to remote new ones,
ie: I'm developping my application locally on my desktop computer from my repository and want to test my code on my raspberry pi:
*  Python files from <root>/sources/ local dir can be mapped to ```/usr/share/pyshared/<mypythonmodule>/```
*  Html files from <root>/html local dir can be mapped to ```/opt/<mypythonapp>/```
*  Binaries from <root>/bin local dir can be mapped to ```/usr/local/bin/```

You can also create links to transferred files to another path. Typically python files from ```/usr/share/pyshared/<mypythonmodule>/``` can be symlinked to ```/usr/lib/python2.7/dist-packages/<mypythonmodule>/```

Console wizard can help you create your profiles.

## Embed it in your application

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
