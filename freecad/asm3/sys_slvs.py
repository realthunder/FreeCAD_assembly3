try:
    from six import with_metaclass
except ImportError:
    from .deps import with_metaclass
from .system import System, SystemBase, SystemExtension
from .utils import syslogger as logger, objName
import platform, sys

from FreeCAD import Qt
translate = Qt.translate

try:
    import slvs
except ImportError:
    try:
        from py_slvs import slvs
    except ImportError:
        if platform.system() == 'Darwin':
            if sys.version_info[0] == 3:
                from .py3_slvs_mac import slvs
            else:
                from .py_slvs_mac import slvs
        elif sys.version_info[0] == 3:
            from .py3_slvs import slvs
        else:
            from .py_slvs import slvs

class SystemSlvs(with_metaclass(System, SystemBase)):
    _id = 1

    def __init__(self,obj):
        super(SystemSlvs,self).__init__(obj)

    @classmethod
    def getName(cls):
        return 'SolveSpace'

    def isDisabled(self,_obj):
        return False

    def getSystem(self,_obj):
        return _SystemSlvs(self.log)


class _SystemSlvs(SystemExtension,slvs.System):
    def __init__(self,log):
        super(_SystemSlvs,self).__init__()
        self.log = log

    def getName(self):
        return SystemSlvs.getName()

    def solve(self, group=0, reportFailed=False, findFreeParams=False):
        ret = super(_SystemSlvs,self).solve(group,reportFailed,findFreeParams)
        if ret:
            reason = None
            if ret==1:
                reason = translate("asm3Logger", "inconsistent constraints")
            elif ret==2:
                reason = translate("asm3Logger", "not converging")
            elif ret==3:
                reason = translate("asm3Logger", "too many unknowns")
            elif ret==4:
                reason = translate("asm3Logger", "init failed")
            elif ret==5:
                logger.warn(translate('asm3Logger', 'redundant constraints'))
            else:
                reason = translate("asm3Logger", "unknown failure")
            if reason:
                raise RuntimeError(reason)
        logger.info(translate('asm3Logger', 'dof remaining: {}'), self.Dof)

