from .deps import with_metaclass
from .system import System, SystemBase, SystemExtension
from .utils import syslogger as logger, objName
import platform

if platform.system() == 'Darwin':
    from .py_slvs_mac import slvs
else:
    try:
        from py_slvs import slvs
    except ImportError:
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

    def solve(self, group=0, reportFailed=False):
        ret = super(_SystemSlvs,self).solve(group,reportFailed)
        if ret:
            reason = None
            if ret==1:
                reason = 'inconsistent constraints'
            elif ret==2:
                reason = 'not converging'
            elif ret==3:
                reason = 'too many unknowns'
            elif ret==4:
                reason = 'init failed'
            elif ret==5:
                if logger.isEnabledFor('debug'):
                    logger.warn('redundant constraints')
                else:
                    logger.info('redundant constraints')
            else:
                reason = 'unknown failure'
            if reason:
                raise RuntimeError(reason)
        self.log('dof remaining: {}'.format(self.Dof))

