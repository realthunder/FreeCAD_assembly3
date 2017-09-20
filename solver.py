import FreeCAD, FreeCADGui
import asm3.slvs as slvs
import asm3.assembly as asm
from asm3.utils import logger, objName, isSamePlacement
import asm3.constraint as constraint

class AsmSolver(object):
    def __init__(self,assembly,reportFailed):
        cstrs = assembly.Proxy.getConstraints()
        if not cstrs:
            logger.debug('no constraint found in assembly '
                '{}'.format(objName(assembly)))
            return

        parts = assembly.Proxy.getPartGroup().Group
        if len(parts)<=1:
            logger.debug('not enough parts in {}'.format(objName(assembly)))
            return

        self.system = slvs.System()
        self._fixedGroup = 2
        self.group = 1 # the solving group
        self._partMap = {}
        self._cstrMap = {}
        self._cstrs = []
        self._entityMap = {}
        self._fixedParts = set()

        for cstr in cstrs:
            if constraint.isLocked(cstr):
                constraint.prepare(cstr,self)
            else:
                self._cstrs.append(cstr)
        if not self._fixedParts:
            logger.debug('lock first part {}'.format(objName(parts[0])))
            self._fixedParts.add(parts[0])

        self.system.GroupHandle = self._fixedGroup
        for cstr in self._cstrs:
            logger.debug('preparing {}, type {}'.format(
                objName(cstr),cstr.Type))
            self.system.GroupHandle += 1
            handle = self.system.ConstraintHandle
            constraint.prepare(cstr,self)
            for h in range(handle,self.system.ConstraintHandle):
                self._cstrMap[h+1] = cstr

        logger.debug('solving {}'.format(objName(assembly)))
        ret = self.system.solve(group=self.group,reportFailed=reportFailed)
        if ret:
            if reportFailed:
                msg = 'List of failed constraint:'
                for h in self.system.Failed:
                    cstr = self._cstrMap.get(h,None)
                    if not cstr:
                        c = self.system.getConstraint(h)
                        if c.group <= self._fixedGroup or \
                           c.group-self._fixedGroup >= len(self._cstrs):
                            logger.error('failed constraint in unexpected group'
                                    ' {}'.format(c.group))
                            continue
                        cstr = self._cstrs[c.group-self._fixedGroup]
                    msg += '\n{}, type: {}, handle: {}'.format(
                            objName(cstr),cstr.Type,h)
                logger.error(msg)
            if ret==1:
                reason = 'redundent constraints'
            elif ret==2:
                reason = 'not converging'
            elif ret==3:
                reason = 'too many unknowns'
            elif ret==4:
                reason = 'init failed'
            else:
                reason = 'unknown failure'
            raise RuntimeError('Failed to solve {}: {}'.format(
                objName(assembly),reason))

        logger.debug('done sloving, dof {}'.format(self.system.Dof))

        undoDocs = set()
        for part,partInfo in self._partMap.items():
            if part in self._fixedParts:
                continue
            params = [ self.system.getParam(h).val for h in partInfo.Params ]
            p = params[:3]
            q = (params[4],params[5],params[6],params[3])
            pla = FreeCAD.Placement(FreeCAD.Vector(*p),FreeCAD.Rotation(*q))
            if isSamePlacement(partInfo.Placement,pla):
                logger.debug('not moving {}'.format(partInfo.PartName))
            else:
                logger.debug('moving {} {} {} {}'.format(
                    partInfo.PartName,partInfo.Params,params,pla))
                asm.AsmElementLink.setPlacement(part,pla,undoDocs)

        for doc in undoDocs:
            doc.commitTransaction()

    def addFixedPart(self,info):
        logger.debug('lock part ' + info.PartName)
        self._fixedParts.add(info.Part)

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
        q = info.Placement.Rotation.Q
        vals = list(info.Placement.Base) + [q[3],q[0],q[1],q[2]]
        params = [self.system.addParamV(v,g) for v in vals]

        p = self.system.addPoint3d(*params[:3],group=g)
        n = self.system.addNormal3d(*params[3:],group=g)
        w = self.system.addWorkplane(p,n,group=g)
        h = (w,p,n)

        logger.debug('{} {}, {}, {}, {}'.format(
            info.PartName,info.Placement,h,params,vals))

        partInfo = constraint.PartInfo(
                info.PartName, info.Placement.copy(),params,h,entityMap,g)
        self._partMap[info.Part] = partInfo
        return partInfo


def solve(objs=None,recursive=True,reportFailed=True,recompute=True):
    if not objs:
        objs = FreeCAD.ActiveDocument.Objects
    elif not isinstance(objs,(list,tuple)):
        objs = [objs]

    if not objs:
        logger.error('no objects')
        return

    if recompute:
        docs = set()
        for o in objs:
            docs.add(o.Document)
        for d in docs:
            logger.debug('recomputing {}'.format(d.Name))
            d.recompute()

    if recursive:
        # Get all dependent object, including external ones, and return as a
        # topologically sorted list.
        objs = FreeCAD.getDependentObjects(objs,False,True)

    assemblies = []
    for obj in objs:
        if asm.isTypeOf(obj,asm.Assembly):
            logger.debug('adding assembly {}'.format(objName(obj)))
            assemblies.append(obj)

    if not assemblies:
        logger.error('no assembly found')
        return

    for assembly in assemblies:
        logger.debug('solving assembly {}'.format(objName(assembly)))
        AsmSolver(assembly,reportFailed)
        if recompute:
            assembly.Document.recompute()

