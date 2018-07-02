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
        for key,default in (('printTag',True),('noUpdateUI',True),
                ('timing',True),('lineno',True),('parent',None)):
            setattr(self,key,kargs.get(key,default))

    def _isEnabledFor(self,level):
        if self.parent and not self.parent._isEnabledFor(level):
            return False
        return FreeCAD.getLogLevel(self.tag) >= level

    def isEnabledFor(self,level):
        if not isinstance(level,int):
            level = self.levels[level]
        return self._isEnabledFor(level)

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

    def _catch(self,level,msg,func,args=None,kargs=None):
        try:
            if not args:
                args = []
            if not kargs:
                kargs = {}
            return func(*args,**kargs)
        except Exception:
            if self._isEnabledFor(level):
                import traceback
                self.log(level,msg+'\n'+traceback.format_exc(),frame=2)

    def catch(self,msg,func,*args,**kargs):
        return self._catch(0,msg,func,args,kargs)

    def catchWarn(self,msg,func,*args,**kargs):
        return self._catch(1,msg,func,args,kargs)

    def catchInfo(self,msg,func,*args,**kargs):
        return self._catch(2,msg,func,args,kargs)

    def catchDebug(self,msg,func,*args,**kargs):
        return self._catch(3,msg,func,args,kargs)

    def catchTrace(self,msg,func,*args,**kargs):
        return self._catch(4,msg,func,args,kargs)

    def report(self,msg,func,*args,**kargs):
        try:
            return func(*args,**kargs)
        except Exception as e:
            import traceback
            self.error(msg+'\n'+traceback.format_exc(),frame=1)

            import PySide
            PySide.QtGui.QMessageBox.critical(
                    FreeCADGui.getMainWindow(),'Assembly',str(e))
