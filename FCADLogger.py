import os, inspect, sys
from datetime import datetime
import FreeCAD, FreeCADGui

class FCADLogger:
    def __init__(self, tag, **kargs):
        self.tag = tag
        self.levels = { 'error':0, 'warn':1, 'info':2,
                'debug':3, 'trace':4 }
        self.printer = [
                FreeCAD.Console.PrintError,
                FreeCAD.Console.PrintWarning,
                FreeCAD.Console.PrintMessage,
                FreeCAD.Console.PrintLog,
                FreeCAD.Console.PrintLog ]
        self.laststamp = datetime.now()
        for key in ('printTag','noUpdateUI','timing','lineno'):
            setattr(self,key,kargs.get(key,True))

    def _isEnabledFor(self,level):
        return FreeCAD.getLogLevel(self.tag) >= level

    def isEnabledFor(self,level):
        self._isEnabledOf(self.levels[level])

    def error(self,msg,frame=0):
        self.log(0,msg,frame+1)

    def warn(self,msg,frame=0):
        self.log(1,msg,frame+1)

    def info(self,msg,frame=0):
        self.log(2,msg,frame+1)

    def debug(self,msg,frame=0):
        self.log(3,msg,frame+1)

    def trace(self,msg,frame=0):
        self.log(4,msg,frame+1)

    def log(self,level,msg,frame=0):
        if not self._isEnabledFor(level):
            return

        prefix = ''

        if self.printTag:
            prefix += '<{}> '.format(self.tag)

        if self.timing:
            now = datetime.now()
            prefix += '{} - '.format((now-self.laststamp).total_seconds())
            self.laststamp = now

        if self.lineno:
            try:
                frame = sys._getframe(frame+1)
                prefix += '{}({}): '.format(os.path.basename(
                    frame.f_code.co_filename),frame.f_lineno)
            except Exception:
                frame = inspect.stack()[frame+1]
                prefix += '{}({}): '.format(os.path.basename(frame[1]),frame[2])

        self.printer[level]('{}{}\n'.format(prefix,msg))

        if not self.noUpdateUI:
            try:
                FreeCADGui.updateGui()
            except Exception:
                pass
