import random
from collections import namedtuple
import FreeCAD, FreeCADGui
from .assembly import Assembly, isTypeOf, setPlacement
from .utils import syslogger as logger, objName, isSamePlacement
from .constraint import Constraint, cstrName
from .system import System

# PartName: text name of the part
# Placement: the original placement of the part
# Params: 7 parameters that defines the transformation of this part
# Workplane: a tuple of three entity handles, that is the workplane, the origin
#            point, and the normal. The workplane, defined by the origin and
#            norml, is essentially the XY reference plane of the part.
# EntityMap: string -> entity handle map, for caching
# Group: transforming entity group handle
PartInfo = namedtuple('SolverPartInfo',
        ('PartName','Placement','Params','Workplane','EntityMap','Group'))

class Solver(object):
    def __init__(self,assembly,reportFailed,dragPart,recompute,rollback):
        self.system = System.getSystem(assembly)
        cstrs = assembly.Proxy.getConstraints()
        if not cstrs:
            logger.debug('skip assembly {} with no constraint'.format(
                objName(assembly)))
            return

        self._fixedGroup = 2
        self.group = 1 # the solving group
        self._partMap = {}
        self._cstrMap = {}

        self.system.GroupHandle = self._fixedGroup

        self._fixedParts = Constraint.getFixedParts(cstrs)
        if self._fixedParts is None:
            logger.warn('no fixed part found')
            return

        for cstr in cstrs:
            self.system.log('preparing {}'.format(cstrName(cstr)))
            self.system.GroupHandle += 1
            ret = Constraint.prepare(cstr,self)
            if ret:
                if isinstance(ret,(list,tuple)):
                    for h in ret:
                        self._cstrMap[h] = cstr
                else:
                    self._cstrMap[ret] = cstr

        if dragPart:
            # TODO: this is ugly, need a better way to expose dragging interface
            addDragPoint = getattr(self.system,'addWhereDragged')
            if addDragPoint:
                info = self._partMap.get(dragPart,None)
                if info:
                    # add dragging point
                    self.system.log('add drag point '
                        '{}'.format(info.Workplane[1]))
                    # TODO: slvs addWhereDragged doesn't work as expected, need
                    # to investigate more
                    # addDragPoint(info.Workplane[1],group=self.group)

        self.system.log('solving {}'.format(objName(assembly)))
        try:
            self.system.solve(group=self.group,reportFailed=reportFailed)
        except RuntimeError as e:
            if reportFailed and self.system.Failed:
                msg = 'List of failed constraint:'
                for h in self.system.Failed:
                    cstr = self._cstrMap.get(h,None)
                    if not cstr:
                        try:
                            c = self.system.getConstraint(h)
                        except Exception as e2:
                            logger.error('cannot find failed constraint '
                                    '{}: {}'.format(h,e2))
                            continue
                        if c.group <= self._fixedGroup or \
                           c.group-self._fixedGroup >= len(cstrs):
                            logger.error('failed constraint in unexpected group'
                                    ' {}'.format(c.group))
                            continue
                        cstr = cstrs[c.group-self._fixedGroup]
                    msg += '\n{}, handle: {}'.format(cstrName(cstr),h)
                logger.error(msg)
            raise RuntimeError('Failed to solve {}: {}'.format(
                objName(assembly),e.message))
        self.system.log('done sloving')

        touched = False
        for part,partInfo in self._partMap.items():
            if part in self._fixedParts:
                continue
            params = [ self.system.getParam(h).val for h in partInfo.Params ]
            p = params[:3]
            q = (params[4],params[5],params[6],params[3])
            pla = FreeCAD.Placement(FreeCAD.Vector(*p),FreeCAD.Rotation(*q))
            if isSamePlacement(partInfo.Placement,pla):
                self.system.log('not moving {}'.format(partInfo.PartName))
            else:
                touched = True
                self.system.log('moving {} {} {} {}'.format(
                    partInfo.PartName,partInfo.Params,params,pla))
                setPlacement(part,pla)
                if rollback is not None:
                    rollback.append((partInfo.PartName,
                                     part,
                                     partInfo.Placement.copy()))

        if recompute and touched:
            assembly.recompute(True)

    def isFixedPart(self,info):
        return info.Part in self._fixedParts

    def getPartInfo(self,info):
        partInfo = self._partMap.get(info.Part,None)
        if partInfo:
            return partInfo

        if info.Part in self._fixedParts:
            g = self._fixedGroup
        else:
            g = self.group

        self.system.NameTag = info.PartName
        params = self.system.addPlacement(info.Placement,group=g)

        p = self.system.addPoint3d(*params[:3],group=g)
        n = self.system.addNormal3d(*params[3:],group=g)
        w = self.system.addWorkplane(p,n,group=g)
        h = (w,p,n)

        partInfo = PartInfo(PartName = info.PartName,
                            Placement = info.Placement.copy(),
                            Params = params,
                            Workplane = h,
                            EntityMap = {},
                            Group = g)

        self.system.log('{}'.format(partInfo))

        self._partMap[info.Part] = partInfo
        return partInfo

def _solve(objs=None,recursive=None,reportFailed=True,
        recompute=True,dragPart=None,rollback=None):
    if not objs:
        sels = FreeCADGui.Selection.getSelectionEx('',False)
        if len(sels):
            objs = Assembly.getSelection()
            if not objs:
                raise RuntimeError('No assembly found in selection')
        else:
            objs = FreeCAD.ActiveDocument.Objects
            if recursive is None:
                recursive = True
    elif not isinstance(objs,(list,tuple)):
        objs = [objs]

    assemblies = []
    for obj in objs:
        if not isTypeOf(obj,Assembly):
            continue
        if System.isDisabled(obj):
            logger.debug('bypass disabled assembly {}'.format(objName(obj)))
            continue
        logger.debug('adding assembly {}'.format(objName(obj)))
        assemblies.append(obj)

    if not assemblies:
        raise RuntimeError('no assembly found')

    if recursive:
        # Get all dependent object, including external ones, and return as a
        # topologically sorted list.
        #
        # TODO: it would be ideal if we can filter out those disabled assemblies
        # found during the recrusive search. Can't think of an easy way right
        # now
        objs = FreeCAD.getDependentObjects(assemblies,False,True)
        assemblies = []
        for obj in objs:
            if not isTypeOf(obj,Assembly):
                continue
            if System.isDisabled(obj):
                logger.debug('skip disabled assembly {}'.format(objName(obj)))
                continue
            logger.debug('adding assembly {}'.format(objName(obj)))
            assemblies.append(obj)

        if not assemblies:
            raise RuntimeError('no assembly need to be solved')

    try:
        for assembly in assemblies:
            if recompute:
                assembly.recompute(True)
            if not System.isTouched(assembly):
                logger.debug('skip untouched assembly '
                    '{}'.format(objName(assembly)))
                continue
            Solver(assembly,reportFailed,dragPart,recompute,rollback)
            System.touch(assembly,False)
    except Exception:
        if rollback is not None:
            for name,part,pla in reversed(rollback):
                logger.debug('roll back {} to {}'.format(name,pla))
                setPlacement(part,pla)
        raise

    return True

_SolverBusy = False

def solve(*args, **kargs):
    global _SolverBusy
    if _SolverBusy:
        raise RuntimeError("Recursive call of solve() is not allowed")
    try:
        _SolverBusy = True
        return _solve(*args,**kargs)
    finally:
        _SolverBusy = False

def isBusy():
    return _SolverBusy

