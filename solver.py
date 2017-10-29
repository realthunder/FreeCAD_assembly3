import random
from collections import namedtuple
import FreeCAD, FreeCADGui
import asm3.assembly as asm
from asm3.utils import syslogger as logger, objName, isSamePlacement
from asm3.constraint import Constraint, cstrName
from asm3.system import System

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
    def __init__(self,assembly,reportFailed,undo):
        self.system = System.getSystem(assembly)
        cstrs = assembly.Proxy.getConstraints()
        if not cstrs:
            logger.warn('no constraint found in assembly '
                '{}'.format(objName(assembly)))
            return

        self._fixedGroup = 2
        self.group = 1 # the solving group
        self._partMap = {}
        self._cstrMap = {}
        self._entityMap = {}

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

        undoDocs = set() if undo else None
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
                self.system.log('moving {} {} {} {}'.format(
                    partInfo.PartName,partInfo.Params,params,pla))
                asm.setPlacement(part,pla,undoDocs)

        if undo:
            for doc in undoDocs:
                doc.commitTransaction()

    def isFixedPart(self,info):
        return info.Part in self._fixedParts

    def getPartInfo(self,info):
        partInfo = self._partMap.get(info.Part,None)
        if partInfo:
            return partInfo

        # info.Object below is supposed to be the actual part geometry, while
        # info.Part may be a link to that object. We use info.Object as a key so
        # that multiple info.Part can share the same entity map.
        #
        # TODO: It is actually more complicated than that. Becuase info.Object
        # itself may be a link, and followed by a chain of multiple links. It's
        # complicated because each link can either have a linked placement or
        # not, depends on its LinkTransform property, meaning that their
        # Placement may be chained or independent.  Ideally, we should explode
        # the link chain, and recreate the transformation dependency using slvs
        # transfomation entity. We'll leave that for another day, maybe... 
        #
        # The down side for now is that we may have redundant entities, and
        # worse, the solver may not be able to get correct result if there are
        # placement dependent links among parts.  So, one should avoid using
        # LinkTransform in most cases.
        #
        entityMap = self._entityMap.get(info.Object,None)
        if not entityMap:
            entityMap = {}
            self._entityMap[info.Object] = entityMap

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
                            EntityMap = entityMap,
                            Group = g)

        self.system.log('{}'.format(partInfo))

        self._partMap[info.Part] = partInfo
        return partInfo

def solve(objs=None,recursive=None,reportFailed=True,recompute=True,undo=True):
    if not objs:
        sels = FreeCADGui.Selection.getSelectionEx('',False)
        if len(sels):
            objs = asm.Assembly.getSelection()
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
        if not asm.isTypeOf(obj,asm.Assembly):
            continue
        if System.isDisabled(obj):
            logger.debug('bypass disabled assembly {}'.format(objName(obj)))
            continue
        logger.debug('adding assembly {}'.format(objName(obj)))
        if recompute:
            obj.recompute(True)
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
        touched = False
        for obj in objs:
            if not asm.isTypeOf(obj,asm.Assembly):
                continue
            if System.isDisabled(obj):
                logger.debug('skip disabled assembly {}'.format(objName(obj)))
                continue
            if not touched:
                if not System.isTouched(obj):
                    logger.debug('skip untouched assembly {}'.format(
                        objName(obj)))
                    continue
                touched = True
            logger.debug('adding assembly {}'.format(objName(obj)))
            assemblies.append(obj)

        if not assemblies:
            raise RuntimeError('no assembly need to be solved')

    for assembly in assemblies:
        Solver(assembly,reportFailed,undo)
        if recompute:
            assembly.recompute(True)
        System.touch(assembly,False)

