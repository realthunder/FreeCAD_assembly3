from collections import namedtuple
import FreeCAD, FreeCADGui, Part
from . import utils, gui
from .deps import with_metaclass
from .utils import objName,cstrlogger as logger, guilogger
from .proxy import ProxyType, PropertyInfo, propGet, propGetValue

import os
_iconPath = os.path.join(utils.iconPath,'constraints')

PointInfo = namedtuple('PointInfo', ('entity','params','vector'))
LineInfo = namedtuple('LineInfo', ('entity','p0','p1'))
NormalInfo = namedtuple('NormalInfo',
        ('entity','rot','params','p0','ln','p1','px','vx','pla'))
PlaneInfo = namedtuple('PlaneInfo', ('entity','origin','normal'))
CircleInfo = namedtuple('CurcleInfo',('entity','radius','p0'))
ArcInfo = namedtuple('CurcleInfo',('entity','p1','p0','params'))

def _d(solver,partInfo,subname,shape,retAll=False):
    'return a handle of any supported element of a draft object'
    if not solver:
        if utils.isDraftObject(partInfo):
            return
        raise RuntimeError('Expects only elements from a draft wire or '
            'draft circle/arc')
    if subname.startswith('Vertex'):
        return _p(solver,partInfo,subname,shape,retAll)
    elif subname.startswith('Edge'):
        return _l(solver,partInfo,subname,shape,retAll)
    else:
        raise RuntimeError('Invalid element {} of object {}'.format(subname,
            partInfo.PartName))

def _prepareDraftCircle(solver,partInfo,requireArc=False):
    part = partInfo.Part
    shape = utils.getElementShape((part,'Edge1'),Part.Edge)
    func = _a if requireArc else _c
    return func(solver,partInfo,'Edge1',shape,retAll=True)

def _p(solver,partInfo,subname,shape,retAll=False):
    'return a handle of a transformed point derived from "shape"'
    if not solver:
        if not utils.hasCenter(shape):
            return 'a vertex or circular edge/face'
        if utils.isDraftWire(partInfo):
            if utils.draftWireVertex2PointIndex(partInfo,subname) is None:
                raise RuntimeError('Invalid draft wire vertex "{}" {}'.format(
                    subname,objName(partInfo)))
        return

    part = partInfo.Part
    key = subname+'.p'
    h = partInfo.EntityMap.get(key,None)
    system = solver.system
    if h:
        system.log('cache {}: {}',key,h)
        return h if retAll else h.entity

    v = utils.getElementPos(shape)

    if utils.isDraftWire(part):
        nameTag = partInfo.PartName + '.' + key
        v = partInfo.Placement.multVec(v)
        params = []
        for n,val in (('.x',v.x),('.y',v.y),('.z',v.z)):
            system.NameTag = nameTag+n
            params.append(system.addParamV(val,group=partInfo.Group))
        system.NameTag = nameTag
        e = system.addPoint3d(*params)
        h = PointInfo(entity=e,params=params,vector=v)
        system.log('{}: add draft point {}',key,h)

        if system.sketchPlane and not solver.isFixedElement(part,subname):
            system.NameTag = nameTag + '.i'
            e2 = system.addPointInPlane(e,system.sketchPlane.entity,
                group=partInfo.Group)
            system.log('{}: add draft point in plane {},{}',
                partInfo.PartName,e2,system.sketchPlane.entity)

    elif utils.isDraftCircle(part):
        requireArc = subname=='Vertex2'
        e = _prepareDraftCircle(solver,partInfo,requireArc)
        if requireArc or subname=='Vertex1':
            h = PointInfo(entity=e.p0,params=partInfo.Params,vector=v)
        elif subname=='Edge1':
            # center point
            h = partInfo.Workplane.origin
        else:
            raise RuntimeError('Invalid draft circle subname {} of '
                    '{}'.format(subname,partInfo.PartName))
        system.log('{}: add circle point {}',key,h)

    else:
        nameTag = partInfo.PartName + '.' + key
        system.NameTag = nameTag
        e = system.addPoint3dV(*v)
        system.NameTag = nameTag + 't'
        h = system.addTransform(e,*partInfo.Params,group=partInfo.Group)
        h = PointInfo(entity=h, params=partInfo.Params,vector=v)
        system.log('{}: {},{}',system.NameTag,h,partInfo.Group)

    partInfo.EntityMap[key] = h
    return h if retAll else h.entity

def _n(solver,partInfo,subname,shape,retAll=False):
    'return a handle of a transformed normal quaterion derived from shape'
    if not solver:
        if not utils.isPlanar(shape) and not utils.isCylindricalPlane(shape):
            return 'an edge or face with a planar or cylindrical surface'
        if utils.isDraftWire(partInfo):
            logger.warn('Use draft wire {} for normal. Draft wire placement'
                ' is not transformable',partInfo.PartName)
        return

    key = subname+'.n'
    h = partInfo.EntityMap.get(key,None)
    system = solver.system
    if h:
        system.log('cache {}: {}',key,h)
    else:
        if utils.isDraftCircle(partInfo.Part):
            _prepareDraftCircle(solver,partInfo)

        rot = utils.getElementRotation(shape)
        nameTag = partInfo.PartName + '.' + key
        system.NameTag = nameTag
        e = system.addNormal3dV(*utils.getNormal(rot))
        system.NameTag += 't'
        nz = system.addTransform(e,*partInfo.Params,group=partInfo.Group)

        p0 = _p(solver,partInfo,subname,shape,True)
        v0 = rot.inverted().multVec(p0.vector)

        vz = rot.multVec(FreeCAD.Vector(v0.x,v0.y,v0.z+1))
        system.NameTag = nameTag + 'p1'
        e = system.addPoint3dV(*vz)
        system.NameTag += 't'
        p1 = system.addTransform(e,*partInfo.Params,group=partInfo.Group)

        system.NameTag = nameTag + 'l'
        ln = system.addLineSegment(p0.entity,p1,group=partInfo.Group)

        vx = rot.multVec(FreeCAD.Vector(v0.x+1,v0.y,v0.z))
        system.NameTag = nameTag + 'px'
        e = system.addPoint3dV(*vx)
        system.NameTag += 't'
        px = system.addTransform(e,*partInfo.Params,group=partInfo.Group)

        h = NormalInfo(entity=nz, rot=rot, params=partInfo.Params,
                p0=p0.entity, ln=ln, p1=p1, px=px, vx=vx,
                pla=partInfo.Placement)

        system.log('{}: {},{}',system.NameTag,h,partInfo.Group)
        partInfo.EntityMap[key] = h
    return h if retAll else h.entity

def _l(solver,partInfo,subname,shape,retAll=False):
    'return a pair of handle of the end points of an edge in "shape"'
    if not solver:
        if not utils.isLinearEdge(shape):
            return 'a linear edge'

        if not utils.isDraftWire(partInfo):
            return
        vname1,vname2 = utils.edge2VertexIndex(partInfo,subname)
        if not vname1:
            raise RuntimeError('Invalid draft subname {} or {}'.format(
                subname,objName(partInfo)))
        v = shape.Edge1.Vertexes
        ret = _p(solver,partInfo,vname1,v[0])
        if ret:
            return ret
        return _p(solver,partInfo,vname2,v[1])

    part = partInfo.Part
    key = subname+'.l'
    h = partInfo.EntityMap.get(key,None)
    system = solver.system
    if h:
        system.log('cache {}: {}',key,h)
    else:
        nameTag = partInfo.PartName + '.' + key
        v = utils.getVertexes(shape)
        if utils.isDraftWire(part):
            vname1,vname2 = utils.edge2VertexIndex(part,subname)
            if not vname1:
                raise RuntimeError('Invalid draft subname {} or {}'.format(
                    subname,partInfo.PartName))
            tp0 = _p(solver,partInfo,vname1,v[0])
            tp1 = _p(solver,partInfo,vname2,v[1])
        else:
            system.NameTag = nameTag + 'p0'
            try:
                p0 = system.addPoint3dV(*v[0].Point)
            except Exception:
                logger.info(system.NameTag)
                raise
            system.NameTag = nameTag + 'p0t'
            tp0 = system.addTransform(p0,*partInfo.Params,group=partInfo.Group)
            system.NameTag = nameTag + 'p1'
            p1 = system.addPoint3dV(*v[-1].Point)
            system.NameTag = nameTag + 'p1t'
            tp1 = system.addTransform(p1,*partInfo.Params,group=partInfo.Group)

        system.NameTag = nameTag
        h = system.addLineSegment(tp0,tp1,group=partInfo.Group)
        h = LineInfo(entity=h,p0=tp0,p1=tp1)
        system.log('{}: {},{}',system.NameTag,h,partInfo.Group)
        partInfo.EntityMap[key] = h

    return h if retAll else h.entity

def _la(solver,partInfo,subname,shape,retAll=False):
   _ = retAll
   return _l(solver,partInfo,subname,shape,True)

def _dl(solver,partInfo,subname,shape,retAll=False):
    'return a handle of a draft wire'
    if not solver:
        if utils.isDraftWire(partInfo):
            return
        raise RuntimeError('Requires a non-subdivided draft wire')
    return _l(solver,partInfo,subname,shape,retAll)

def _ln(solver,partInfo,subname,shape,retAll=False):
    'return a handle for either a line or a normal depends on the shape'
    if not solver:
        if utils.isLinearEdge(shape) or \
           utils.isPlanar(shape) or \
           utils.isCylindricalPlane(shape):
            return
        return 'a linear edge or edge/face with planar or cylindrical surface'
    if utils.isLinearEdge(shape):
        return _l(solver,partInfo,subname,shape,retAll)
    return _n(solver,partInfo,subname,shape,retAll)

def _lna(solver,partInfo,subname,shape,retAll=False):
    _ = retAll
    return _ln(solver,partInfo,subname,shape,True)

def _lw(solver,partInfo,subname,shape,retAll=False):
    'return a handle for either a line or a plane depending on the shape'
    _ = retAll
    if not solver:
        if utils.isLinearEdge(shape) or utils.isPlanar(shape):
            return
        return 'a linear edge or edge/face with planar surface'
    if utils.isLinearEdge(shape):
        return _l(solver,partInfo,subname,shape,False)
    return _wa(solver,partInfo,subname,shape)

def _w(solver,partInfo,subname,shape,retAll=False,noCheck=False):
    'return a handle of a transformed plane/workplane from "shape"'
    if not solver:
        if noCheck or utils.isPlanar(shape):
            return
        return 'an edge/face with a planar surface'

    key = subname+'.w'
    h = partInfo.EntityMap.get(key,None)
    system = solver.system
    if h:
        system.log('cache {}: {}',key,h)
    else:
        p = _p(solver,partInfo,subname,shape,True)
        n = _n(solver,partInfo,subname,shape,True)
        system.NameTag = partInfo.PartName + '.' + key
        w = system.addWorkplane(p.entity,n.entity,group=partInfo.Group)
        h = PlaneInfo(entity=w,origin=p,normal=n)
        system.log('{}: {},{}',system.NameTag,h,partInfo.Group)
    return h if retAll else h.entity

def _wa(solver,partInfo,subname,shape,retAll=False):
    _ = retAll
    return _w(solver,partInfo,subname,shape,True)

def _wa_no_check(solver,partInfo,subname,shape,retAll=False):
    _ = retAll
    return _w(solver,partInfo,subname,shape,True,True)

def _c(solver,partInfo,subname,shape,requireArc=False,retAll=False):
    'return a handle of a transformed circle/arc derived from "shape"'
    if not solver:
        r = utils.getElementCircular(shape)
        if r:
            if requireArc and not isinstance(r,tuple):
                return 'an arc edge'
            return
        return 'a cicular edge'
    if requireArc:
        key = subname+'.a'
    else:
        key = subname+'.c'
    h = partInfo.EntityMap.get(key,None)
    system = solver.system
    if h:
        system.log('cache {}: {}',key,h)
        return h if retAll else h.entity

    g = partInfo.Group
    nameTag = partInfo.PartName + '.' + key

    if utils.isDraftCircle(partInfo.Part):
        part = partInfo.Part
        pln = partInfo.Workplane

        if system.sketchPlane and not solver.isFixedElement(part,subname):
            system.NameTag = nameTag + '.o'
            e1 = system.addSameOrientation(pln.normal.entity,
                    system.sketchPlane.normal.entity, group=g)
            system.NameTag = nameTag + '.i'
            e2 = system.addPointInPlane(
                    pln.origin.entity, system.sketchPlane.entity, group=g)
            system.log('{}: fix draft circle in plane {},{}',
                partInfo.PartName,e1,e2)

        if part.FirstAngle == part.LastAngle:
            if requireArc:
                raise RuntimeError('expecting an arc from {}'.format(
                    partInfo.PartName))
            system.NameTag = nameTag + '.r'
            r = system.addParamV(part.Radius.Value,group=g)
            system.NameTag = nameTag + '.p0'
            p0 = system.addPoint2d(pln.entity,r,solver.v0,group=g)
            system.NameTag = nameTag
            e = system.addCircle(pln.origin.entity, pln.normal.entity,
                                 system.addDistance(r), group=g)
            h = CircleInfo(entity=e,radius=r,p0=p0)
            system.log('{}: add draft circle {}, {}',nameTag,h,g)
        else:
            system.NameTag = nameTag + '.c'
            center = system.addPoint2d(pln.entity,solver.v0,solver.v0,group=g)
            params = []
            points = []
            v = shape.Vertexes
            for i in 0,1:
                for n,val in ('.x{}',v[i].Point.x),('.y{}',v[i].Point.y):
                    system.NameTag = nameTag+n.format(i)
                    params.append(system.addParamV(val,group=g))
                system.NameTag = nameTag + '.p{}'.format(i)
                pt = system.addPoint2d(pln.entity,*params[-2:],group=g)
                points.append(pt)
            system.NameTag = nameTag
            e = system.addArcOfCircle(pln.entity,center,*points,group=g)
            h = ArcInfo(entity=e,p1=points[1],p0=points[0],params=params)
            system.log('{}: add draft arc {}, {}',nameTag,h,g)

            # exhaust all possible keys from a draft circle to save
            # recomputation
            sub = subname + '.c' if requireArc else '.a'
            partInfo.EntityMap[sub] = h
    else:
        pln = _w(solver,partInfo,subname,shape,True)
        r = utils.getElementCircular(shape)
        if not r:
            raise RuntimeError('shape is not cicular')
        system.NameTag = nameTag + '.r'
        hr = system.addDistanceV(r)
        if requireArc or isinstance(r,(list,tuple)):
            l = _l(solver,partInfo,subname,shape,True)
            system.NameTag = nameTag
            h = system.addArcOfCircle(
                    pln.entity, pln.origin.entity, l.p0, l.p1, group=g)
            h = ArcInfo(entity=h,p1=l.p1,p0=l.p0,params=None)
        else:
            system.NameTag = nameTag
            h = system.addCircle(
                    pln.origin.entity, pln.normal.entity, hr, group=g)
            h = CircleInfo(entity=h,radius=hr,p0=None)
        system.log('{}: {},{}',nameTag,h,g)

    partInfo.EntityMap[key] = h

    return h if retAll else h.entity

def _dc(solver,partInfo,subname,shape,requireArc=False,retAll=False):
    'return a handle of a draft circle'
    if not solver:
        if utils.isDraftCircle(partInfo):
            return
        raise RuntimeError('Requires a draft circle')
    return _c(solver,partInfo,subname,shape,requireArc,retAll)

def _a(solver,partInfo,subname,shape,retAll=False):
    'return a handle of a transformed arc derived from "shape"'
    return _c(solver,partInfo,subname,shape,True,retAll)


class ConstraintCommand:
    _menuGroupName = None

    def __init__(self,tp):
        self.tp = tp
        self._id = 100 + tp._id
        self._active = None

    @property
    def _toolbarName(self):
        if self.tp._measure:
            return 'Assembly3 Measurements'
        return self.tp._toolbarName

    @property
    def _toolbarVisible(self):
        return self.tp._measure or self.tp._toolbarVisible

    def workbenchActivated(self):
        self._active = None

    def workbenchDeactivated(self):
        pass

    def getContextMenuName(self):
        pass

    def getName(self):
        return 'asm3Add'+self.tp.getName()

    def GetResources(self):
        return self.tp.GetResources()

    def Activated(self):
        self.tp.activate()

    def IsActive(self):
        if not FreeCAD.ActiveDocument:
            return False
        if self._active is None:
            self._active = self.tp.checkActive()
        return self._active

    def onSelectionChange(self,hasSelection):
        Constraint._selInfo = None
        self._active = None if hasSelection else False

class Constraint(ProxyType):
    'constraint meta class'

    _typeID = '_ConstraintType'
    _typeEnum = 'ConstraintType'
    _disabled = 'Disabled'
    _selInfo = None

    @classmethod
    def register(mcs,cls):
        super(Constraint,mcs).register(cls)
        if cls._id!=-1:
            try:
                gui.AsmCmdManager.register(ConstraintCommand(cls))
            except Exception:
                logger.error('failed to register {}',cls.getName())
                raise

    @classmethod
    def attach(mcs,obj,checkType=True):
        if checkType:
            if not mcs._disabled in obj.PropertiesList:
                obj.addProperty("App::PropertyBool",mcs._disabled,"Base",'')
        return super(Constraint,mcs).attach(obj,checkType)

    @classmethod
    def onChanged(mcs,obj,prop):
        if prop == mcs._disabled:
            obj.ViewObject.signalChangeIcon()
        if super(Constraint,mcs).onChanged(obj,prop):
            try:
                if obj.Name==obj.Label or \
                   mcs.getType(str(utils.getLabel(obj))):
                    obj.Label = mcs.getTypeName(obj)
            except Exception as e:
                logger.debug('auto constraint label failed: {}',e)

    @classmethod
    def isDisabled(mcs,obj):
        return getattr(obj,mcs._disabled,False)

    @classmethod
    def propMultiply(mcs):
        return 'Multiply'

    @classmethod
    def canMultiply(mcs,obj):
        return getattr(obj,mcs.propMultiply(),None)

    @classmethod
    def copy(mcs,obj,target):
        mcs.getProxy(obj).__class__.copyProperties(obj,target)

    @classmethod
    def setDisable(mcs,obj):
        return setattr(obj,mcs._disabled,True)

    @classmethod
    def check(mcs,tp,elements,checkCount=False):
        mcs.getType(tp).check(elements,checkCount)

    @classmethod
    def execute(mcs,obj):
        mcs.getProxy(obj).execute(obj)

    @classmethod
    def prepare(mcs,obj,solver):
        return mcs.getProxy(obj).prepare(obj,solver)

    @classmethod
    def getFixedParts(mcs,solver,cstrs,partGroup,rollback):
        firstInfo = None
        if partGroup.Proxy.derivedParts:
            ret = set(partGroup.Proxy.derivedParts)
        else:
            ret = set()
        from .assembly import isTypeOf, AsmWorkPlane, flattenGroup
        for obj in flattenGroup(partGroup):
            if not hasattr(obj,'Placement'):
                ret.add(obj)
                logger.debug('part without Placement {}',objName(obj))
            elif isTypeOf(obj,AsmWorkPlane) and getattr(obj,'Fixed',False):
                ret.add(obj)
                logger.debug('fix workplane {}',objName(obj))
        found = len(ret)

        attachments = []
        for obj in cstrs:
            cstr = mcs.getProxy(obj)

            if isinstance(cstr, Attachment):
                attachments.append(obj)

            # Build array constraint map for constraint multiplication
            if mcs.canMultiply(obj):
                element0 = obj.Proxy.getElements()[0].Proxy
                for info in element0.getInfo(expand=True):
                    solver.countArrayPartConstraint(info.Part)
            else:
                for info in obj.Proxy.getElementsInfo():
                    if isinstance(info.Part,tuple):
                        solver.countArrayPartConstraint(info.Part)

            if cstr.hasFixedPart(obj):
                found = True
                for info in cstr.getFixedParts(solver,obj):
                    logger.debug('fixed part {}',info.PartName)
                    ret.add(info.Part)

            if not found and not firstInfo:
                elements = obj.Proxy.getElements()
                if elements:
                    firstInfo = elements[0].Proxy.getInfo()

        if not found:
            if not firstInfo or not solver:
                logger.warn('no fixed part')
                return ret
            if utils.isDraftObject(firstInfo.Part):
                Locked.lockElement(firstInfo,solver)
                logger.debug('lock first draft object {}',firstInfo.PartName)
                solver.getPartInfo(firstInfo,True,solver.group)
            else:
                logger.debug('lock first part {}',firstInfo.PartName)
                ret.add(firstInfo.Part)

        if logger.isEnabledFor('debug'):
            logger.debug('found fixed parts:')
            for o in ret:
                if isinstance(o,tuple):
                    logger.debug('\t{}.{}',o[0].Name,o[1])
                else:
                    logger.debug('\t{}',o.Name)

        if not ret:
            return ret

        # Early solving for Attachment constraint, which requires only simple
        # matrix calculation. We only solve those directly or indirectly
        # attached to some fixed part, and treat the rest as PlaneCoincident
        # with locked angle.

        from .assembly import setPlacement
        handled = set()
        while True:
            nxt = []
            for obj in attachments:
                cstr = obj.Proxy

                firstInfo = []
                infos = []

                if obj.Cascade:
                    # for cascading attachment, we should handle it if there is
                    # any fixed part inside. We also need to sort the element
                    # pairs properly so that they can be recognized as fixed one
                    # after another
                    prev = None
                    fixed = None
                    for e in cstr.getElements():
                        info = e.Proxy.getInfo()
                        if prev and prev.Part!=info.Part:
                            firstInfo.append(prev)
                            infos.append(info)
                            if fixed is None \
                                    and (prev.Part in ret or info.Part in ret):
                                fixed = len(firstInfo)
                        prev = info

                    if fixed is None:
                        continue

                    if fixed:
                        # reorder the element pairs to put the pair with the
                        # fixed part first, and then reversed the ones that are
                        # before it.
                        firstInfo = firstInfo[fixed:] +\
                                list(reversed(firstInfo[:fixed]))
                        infos = infos[fixed:] + list(reversed(infos[:fixed]))
                else:
                    if not mcs.canMultiply(obj):
                        infos = cstr.getElementsInfo()
                        firstInfo = [infos[0]]*(len(infos)-1)
                        infos = infos[1:]
                    else:
                        elements = cstr.getElements()
                        firstInfo = elements[0].Proxy.getInfo(expand=True)
                        infos = []
                        for element in elements[1:]:
                            infos += element.Proxy.getInfo(expand=True)
                        count = min(len(infos),len(firstInfo))
                        firstInfo = firstInfo[:count]
                        infos = infos[:count]

                    if any([ not (info0.Part in ret or info.Part in ret)
                            for info0,info in zip(firstInfo,infos)]):
                        # we only handle if all element pair has at least one
                        # part that are fixed
                        continue

                if rollback is not False:
                    handled.add(obj)

                for info0,info in zip(firstInfo,infos):
                    if info.Part in ret:
                        if info0.Part in ret:
                            logger.warn('skip fixed part "{}" and "{}" in {}',
                                info.PartName,info0.PartName,cstrName(obj))
                            continue
                        info0,info = info,info0

                    ret.add(info.Part)

                    pla0 = info0.Placement.multiply(
                            utils.getElementPlacement(info0.Shape))
                    pla = pla0.multiply(
                            utils.getElementPlacement(info.Shape).inverse())
                    if rollback is not False and \
                            not utils.isSamePlacement(pla,info.Placement):
                        solver.touched = True
                        solver.system.log('attaching "{}" -> "{}"',
                                info.PartName, info0.PartName)
                        if rollback is not None:
                            rollback.append((info.PartName,
                                            info.Part,
                                            info.Placement.copy()))
                        setPlacement(info.Part,pla)

            if len(nxt) == len(attachments):
                break
            attachments = nxt

        if handled:
            cstrs[:] = [ obj for obj in cstrs if obj not in handled ]

        return ret

    @classmethod
    def getFixedTransform(mcs,cstrs):
        firstPart = None
        found = False
        ret = {}
        for obj in cstrs:
            cstr = mcs.getProxy(obj)
            if cstr.hasFixedPart(obj):
                for info in cstr.getFixedTransform(obj):
                    found = True
                    ret[info.Part] = info

            if not found and not firstPart:
                elements = obj.Proxy.getElements()
                if elements:
                    info = elements[0].Proxy.getInfo()
                    firstPart = info.Part
        if not found and firstPart and not utils.isDraftObject(firstPart):
            ret[firstPart] = False
        return ret

    @classmethod
    def getIcon(mcs,obj):
        cstr = mcs.getProxy(obj)
        if cstr:
            return cstr.getIcon(obj)

    @classmethod
    def init(mcs,obj):
        cstr = mcs.getProxy(obj)
        if not cstr:
            return
        cstr.init(obj)
        if hasattr(obj,'Label2'):
            if cstr._measure:
                obj.setExpression('.Label2', '.{}'.format(cstr._props[0]))
            else:
                obj.setExpression('.Label2', None)


def _makeProp(name,tp,doc='',getter=propGet,internal=False,default=None):
    return PropertyInfo(Constraint,name,tp,doc,getter=getter,duplicate=True,
            group='Constraint',internal=internal,default=default).Key

_makeProp('Distance','App::PropertyDistance',getter=propGetValue)
_makeProp('Length','App::PropertyDistance',getter=propGetValue,default=5.0)
_makeProp('Offset','App::PropertyDistance',getter=propGetValue)
_makeProp('OffsetX','App::PropertyDistance',getter=propGetValue)
_makeProp('OffsetY','App::PropertyDistance',getter=propGetValue)
_makeProp('Cascade','App::PropertyBool',internal=True)
_makeProp('Multiply','App::PropertyBool',internal=True)
_makeProp('LockRotationZ','App::PropertyBool',internal=True,default=True)
_makeProp('Angle','App::PropertyAngle',getter=propGetValue)

_AngleProps = [
_makeProp('LockAngle','App::PropertyBool',
        doc='Enforce an angle offset defined as yaw-pitch-roll angle of the\n'
            'second plane performed in the order of x-y-z'),
_makeProp('Angle','App::PropertyFloat',
        doc='The rotation angle of the second plane about its z-axis.\n'
            'You need to enable LockAngle for this to take effect.'),
_makeProp('AnglePitch','App::PropertyAngle',getter=propGetValue,
        doc='Rotation angle of the second plane about its y-axis.\n'
            'You need to enable LockAngle for this to take effect.'),
_makeProp('AngleRoll','App::PropertyAngle',getter=propGetValue,
        doc='Rotation angle of the second plane about its x-axis\n'
            'You need to enable LockAngle for this to take effect.'),
]

_makeProp('Ratio','App::PropertyFloat',default=1.0)
_makeProp('Difference','App::PropertyFloat')
_makeProp('Diameter','App::PropertyDistance',getter=propGetValue,default=10.0)
_makeProp('Radius','App::PropertyDistance',getter=propGetValue,default=5.0)
_makeProp('Supplement','App::PropertyBool',
        'If True, then the angle is calculated as 180-angle')
_makeProp('AtEnd','App::PropertyBool',
        'If True, then tangent at the end point, or else at the start point')

_ordinal = ('1st', '2nd', '3rd', '4th', '5th', '6th', '7th')

def cstrName(obj):
    #  return '{}<{}>'.format(objName(obj),Constraint.getTypeName(obj))
    return objName(obj)


class Base(with_metaclass(Constraint, object)):
    _id = -1
    _activeWithElement = False
    _entityDef = ()
    _workplane = False
    _props = []
    _toolbarName = 'Assembly3 Constraints'
    _toolbarVisible = True
    _iconName = 'Assembly_ConstraintGeneral.svg'
    _measure = False

    def __init__(self,_obj):
        pass

    @classmethod
    def init(cls,_obj):
        pass

    @classmethod
    def execute(cls,obj):
        if cls._measure:
            cls.init(obj)

    @classmethod
    def activate(cls):
        from .assembly import AsmConstraint
        msg = '"{}" command exception'.format(cls.getName())
        if not cls._measure:
            msg = 'constraint ' + msg
        guilogger.report(msg, AsmConstraint.make, cls._id)

    @classmethod
    def checkActive(cls):
        from .assembly import AsmConstraint
        if not Constraint._selInfo:
            Constraint._selInfo = guilogger.catchTrace(
                    'selection "{}" exception'.format(
                        cls.getName()), AsmConstraint.getSelection, cls._id)
        info = Constraint._selInfo
        if not info:
            return False
        if cls._activeWithElement and not info.Elements:
            return False
        return True

    @classmethod
    def getPropertyInfoList(cls):
        return cls._props

    @classmethod
    def constraintFunc(cls,obj,solver,name=None):
        try:
            if not name:
                name = getattr(cls,'_cstrFuncName','add'+cls.getName())
            return getattr(solver.system,name)
        except AttributeError:
            logger.warn('{} not supported in solver "{}"',
                cstrName(obj),solver.system.getName())

    @classmethod
    def getEntityDef(cls,elements,checkCount,obj=None):
        entities = cls._entityDef
        if len(elements) == len(entities):
            return entities
        if cls._workplane and len(elements)==len(entities)+1:
            return list(entities) + [_w]
        if not checkCount and len(elements)<len(entities):
            return entities[:len(elements)]
        if not obj:
            name = cls.getName()
        else:
            name += cstrName(obj)
        if len(elements)<len(entities):
            msg = entities[len(elements)](None,None,None,None)
            raise RuntimeError('Constraint "{}" requires the {} element to be'
                    ' {}'.format(cls.getName(), _ordinal[len(elements)], msg))
        raise RuntimeError('Constraint {} has too many elements, expecting '
            'only {}'.format(name,len(entities)))

    @classmethod
    def check(cls,elements,checkCount=False):
        entities = cls.getEntityDef(elements,checkCount)
        for i,e in enumerate(entities):
            info = elements[i]
            msg = e(None,info.Part,info.Subname,info.Shape)
            if not msg:
                continue
            if i == len(cls._entityDef):
                raise RuntimeError('Constraint "{}" requires an optional {} '
                    'element to be a planar face for defining a '
                    'workplane'.format(cls.getName(), _ordinal[i], msg))
            raise RuntimeError('Constraint "{}" requires the {} element to be'
                    ' {}'.format(cls.getName(), _ordinal[i], msg))

    @classmethod
    def getIcon(cls,obj):
        return utils.getIcon(cls,Constraint.isDisabled(obj),_iconPath)

    @classmethod
    def getEntities(cls,obj,solver,retAll=False):
        '''maps fcad element shape to entities'''
        elements = obj.Proxy.getElements()
        entities = cls.getEntityDef(elements,True,obj)
        ret = []
        for e,o in zip(entities,elements):
            info = o.Proxy.getInfo()
            partInfo = solver.getPartInfo(info)
            ret.append(e(solver,partInfo,info.Subname,info.Shape,retAll=retAll))

        if cls._workplane and len(elements)==len(cls._entityDef):
            if solver.system.sketchPlane:
                ret.append(solver.system.sketchPlane.entity)
            elif int(cls._workplane)>1:
                raise RuntimeError('Constraint "{}" requires a sketch plane '
                    'or a {} element to define a projection plane'.format(
                    cstrName(obj), _ordinal[len(elements)]))

        solver.system.log('{} entities: {}',cstrName(obj),ret)
        return ret

    @classmethod
    def prepare(cls,obj,solver):
        if cls._measure:
            return
        func = cls.constraintFunc(obj,solver)
        if not func:
            return
        params = cls.getPropertyValues(obj) + cls.getEntities(obj,solver)
        ret = func(*params,group=solver.group)
        solver.system.log('{}: {}',cstrName(obj),ret)
        return ret

    @classmethod
    def hasFixedPart(cls,_obj):
        return False

    @classmethod
    def getMenuText(cls):
        if cls._measure:
            return 'Create "{}"'.format(cls.getName())
        return 'Create "{}" constraint'.format(cls.getName())

    @classmethod
    def getToolTip(cls):
        tooltip = getattr(cls,'_tooltip',None)
        if not tooltip:
            return cls.getMenuText()
        return tooltip.format(cls.getName())

    @classmethod
    def GetResources(cls):
        if cls._measure:
            iconName = cls._iconName.replace('Constraint','Measure')
        else:
            iconName = cls._iconName
        return {'Pixmap':utils.addIconToFCAD(iconName,_iconPath),
                'MenuText':cls.getMenuText(),
                'ToolTip':cls.getToolTip()}


class Locked(Base):
    _id = 0
    _activeWithElement = True
    _iconName = 'Assembly_ConstraintLock.svg'
    _tooltip = 'Add a "{}" constraint to fix part(s). You must select a\n'\
               'geometry element of the part. If you fix a vertex or an edge\n'\
               'the part is still free to rotate around the vertex or edge.\n'\
               'Fixing a face will completely lock the part'

    @classmethod
    def getFixedParts(cls,_solver,obj):
        ret = []
        for e in obj.Proxy.getElements():
            info = e.Proxy.getInfo()
            if not utils.isVertex(info.Shape) and \
               not utils.isLinearEdge(info.Shape) and \
               not utils.isDraftCircle(info.Part):
                ret.append(info)
        return ret

    Info = namedtuple('AsmCstrTransformInfo', ('Part', 'Shape'))

    @classmethod
    def getFixedTransform(cls,obj):
        ret = []
        for e in obj.Proxy.getElements():
            info = e.Proxy.getInfo()
            if utils.isDraftObject(info.Part):
                continue
            shape = None
            if utils.isVertex(info.Shape) or \
               utils.isLinearEdge(info.Shape):
                shape = info.Shape
            ret.append(cls.Info(Part=info.Part,Shape=shape))
        return ret

    @classmethod
    def hasFixedPart(cls,obj):
        return len(obj.Proxy.getElements())>0

    @classmethod
    def lockElement(cls,info,solver):
        ret = []
        system = solver.system

        isVertex = utils.isVertex(info.Shape)
        if solver.isFixedElement(info.Part,info.Subname):
            return ret

        if not isVertex and utils.isDraftCircle(info.Part):
            if solver.sketchPlane:
                _c(solver,solver.getPartInfo(info),info.Subname,info.Shape)
            else:
                solver.getPartInfo(info,True,solver.group)
            solver.addFixedElement(info.Part,info.Subname)
            return ret

        if not isVertex and not utils.isLinearEdge(info.Shape):
            return ret

        partInfo = solver.getPartInfo(info)

        fixPoint = False
        if isVertex:
            names = [info.Subname]
            if utils.isDraftCircle(info.Part):
                _c(solver,partInfo,'Edge1',info.Shape)
                solver.addFixedElement(info.Part,'Edge1')
        elif utils.isDraftWire(info.Part):
            fixPoint = True
            names = utils.edge2VertexIndex(info.Part,info.Subname)
        else:
            names = [info.Subname+'.fp0', info.Subname+'.fp1']

        nameTag = partInfo.PartName + '.' + info.Subname

        for i,v in enumerate(utils.getVertexes(info.Shape)):
            surfix = '.fp{}'.format(i)
            system.NameTag = nameTag + surfix

            # Create an entity for the transformed constant point
            e1 = system.addPoint3dV(*info.Placement.multVec(v.Point))

            # Get the entity for the point expressed in variable parameters
            e2 = _p(solver,partInfo,names[i],v)
            solver.addFixedElement(info.Part,names[i])

            if i==0 or fixPoint:
                # We are fixing a vertex, or a linear edge. Either way, we
                # shall add a point coincidence constraint here.
                e0 = e1
                system.NameTag = nameTag + surfix
                if system.sketchPlane and utils.isDraftObject(info.Part):
                    w = system.sketchPlane.entity
                else:
                    w = 0
                e = system.addPointsCoincident(e1,e2,w,group=solver.group)
                system.log('{}: fix point {},{},{}',info.PartName,e,e1,e2)
            else:
                # The second point, so we are fixing a linear edge. We can't
                # add a second coincidence constraint, which will cause
                # over-constraint. We constraint the second point to be on
                # the line defined by the linear edge.
                #
                # First, get an entity of the transformed constant line
                system.NameTag = nameTag + '.fl'
                l = system.addLineSegment(e0,e1)
                system.NameTag = nameTag
                # Now, constraint the second variable point to the line
                e = system.addPointOnLine(e2,l,group=solver.group)
                system.log('{}: fix line {},{}',info.PartName,e,l)

            ret.append(e)

        return ret

    @classmethod
    def prepare(cls,obj,solver):
        ret = []
        for element in obj.Proxy.getElements():
            ret += cls.lockElement(element.Proxy.getInfo(),solver)
        return ret

    @classmethod
    def check(cls,elements,_checkCount=False):
        if not all([utils.isElement(info.Shape) for info in elements]):
            raise RuntimeError('Constraint "{}" requires all children to be '
                    'of element (Vertex, Edge or Face)'.format(cls.getName()))


class BaseMulti(Base):
    _id = -1
    _entityDef = (_wa,)

    @classmethod
    def onRegister(cls):
        assert(not cls._workplane)
        assert(len(cls._entityDef)<=2)

    @classmethod
    def check(cls,elements,checkCount=False):
        if cls._measure:
            super(BaseMulti,cls).check(elements,checkCount)
            return

        if checkCount and len(elements)<2:
            raise RuntimeError('Constraint "{}" requires at least two '
                'elements'.format(cls.getName()))
        count = min(len(elements),len(cls._entityDef))
        for i,entityDef in enumerate(cls._entityDef[:count]):
            info = elements[i]
            msg = entityDef(None,info.Part,info.Subname,info.Shape)
            if msg:
                raise RuntimeError('Constraint "{}" requires the {} element '
                    'to be of {}'.format(cls.getName(),_ordinal[i],msg))
        if len(elements)<=count:
            return
        i = len(cls._entityDef)
        for info in elements[i:]:
            msg = cls._entityDef[0](None,info.Part,info.Subname,info.Shape)
            if msg:
                raise RuntimeError('Constraint "{}" requires the {} element '
                    'onwards to all be of {}'.format(
                        cls.getName(),_ordinal[i],msg))

    @classmethod
    def prepare(cls,obj,solver):
        if cls._measure:
            return

        func = cls.constraintFunc(obj,solver);
        if not func:
            return
        props = cls.getPropertyValues(obj)
        ret = []

        if cls.canMultiply(obj):
            elements = obj.Proxy.getElements()
            if len(elements)<=1:
                logger.warn('{} not enough elements',cstrName(obj))
                return

            firstInfo = elements[0].Proxy.getInfo(expand=True)
            count = len(firstInfo)
            if not count:
                logger.warn('{} no first part shape',cstrName(obj))
                return

            dragPart = solver.getDragPart()
            dragIndex = -1
            if isinstance(dragPart,tuple) and \
               dragPart[0]==firstInfo[0].Part[0] and \
               solver.getArrayPartConstraintCount(dragPart)==1 and \
               dragPart[1] < count:
                dragIndex = dragPart[1]

            idx = 0
            for element in elements[1:]:
                updates = []
                info0Ref = None
                infoRef = None
                shapeRef = None
                refIdx = -1
                infos = element.Proxy.getInfo(expand=True)

                # make sure the dragging part is picked as reference for
                # coplanar shortcut updating
                if dragIndex>=0:
                    for i,info in enumerate(infos):
                        if idx+i >= count:
                            break
                        info0 = firstInfo[idx+i]
                        if info0.Part[1] == dragIndex:
                            dragIndex = -1
                            info0Ref = solver.getPartInfo(info0)
                            infoRef = solver.getPartInfo(info)
                            shapeRef = info.Shape
                            refIdx = i
                            break

                for i,info in enumerate(infos):
                    if idx >= count:
                        break
                    info0 = firstInfo[idx]
                    partInfo = solver.getPartInfo(info)

                    if solver.getArrayPartConstraintCount(info0.Part)!=1:
                        partInfo0 = solver.getPartInfo(info0)
                    elif not infoRef:
                        partInfo0 = solver.getPartInfo(info0)
                        info0Ref = partInfo0
                        infoRef = partInfo
                        shapeRef = info.Shape
                    elif i == refIdx:
                        partInfo0 = info0Ref
                    else:
                        # We can safely skip those coplanar edges if the
                        # part array element is involved in one and only one
                        # constraint (i.e. this one).
                        updates.append((info0,partInfo,info.Shape))
                        idx += 1
                        continue

                    e0 = cls._entityDef[0](
                            solver,partInfo0,info0.Subname,info0.Shape)
                    e = cls._entityDef[0](
                            solver,partInfo,info.Subname,info.Shape)
                    params = props + [e0,e]
                    solver.system.checkRedundancy(obj,partInfo0,partInfo)
                    h = func(*params,group=solver.group)
                    if isinstance(h,(list,tuple)):
                        ret += list(h)
                    else:
                        ret.append(h)
                    idx += 1

                if updates:
                    info0Ref.Update.append((infoRef,shapeRef,updates))

            return ret

        parts = set()
        ref = None
        elements = []

        for e in obj.Proxy.getElements():
            info = e.Proxy.getInfo()

            ################################################################
            # Note: Multiple elements from the same part makes sense in, e.g.
            # PointsOnCircle
            ################################################################
            #  if info.Part in parts:
            #      logger.warn('{} skip duplicate parts {}',
            #          cstrName(obj),info.PartName)
            #      continue

            parts.add(info.Part)
            if solver.isFixedPart(info.Part):
                if ref:
                    logger.warn('{} skip more than one fixed part {},{}',
                        cstrName(obj),info.PartName,ref.PartName)
                    continue
                ref = info
            elements.append(e)

        if len(elements)<=1:
            logger.warn('{} has no effective constraining element',
                    cstrName(obj))
            return

        e0 = None
        e = None
        info0 = None
        idx0 = 1 if len(cls._entityDef)>1 else 0
        for i,element in enumerate(elements):
            info = element.Proxy.getInfo()
            partInfo = solver.getPartInfo(info)
            if i==idx0:
                e0 = cls._entityDef[idx0](
                        solver,partInfo,info.Subname,info.Shape)
                info0 = partInfo
            else:
                e = cls._entityDef[0](solver,partInfo,info.Subname,info.Shape)
            if e0 and e:
                if idx0:
                    params = props + [e,e0]
                    solver.system.checkRedundancy(obj,partInfo,info0)
                else:
                    params = props + [e0,e]
                    solver.system.checkRedundancy(obj,info0,partInfo)
                h = func(*params,group=solver.group)
                if isinstance(h,(list,tuple)):
                    ret += list(h)
                else:
                    ret.append(h)
        return ret

class BaseCascade(BaseMulti):
    @classmethod
    def prepare(cls,obj,solver):
        if not getattr(obj,'Cascade',True):
            return super(BaseCascade,cls).prepare(obj,solver)
        func = cls.constraintFunc(obj,solver);
        if not func:
            return
        props = cls.getPropertyValues(obj)
        prev = None
        ret = []
        for e in obj.Proxy.getElements():
            info = e.Proxy.getInfo()
            if not prev or prev.Part==info.Part:
                prev = info
                continue
            prevInfo = solver.getPartInfo(prev)
            e1 = cls._entityDef[0](solver,prevInfo,prev.Subname,prev.Shape)
            partInfo = solver.getPartInfo(info)
            e2 = cls._entityDef[0](solver,partInfo,info.Subname,info.Shape)
            prev = info
            if solver.isFixedPart(info.Part):
                params = props + [e1,e2]
            else:
                params = props + [e2,e1]
            solver.system.checkRedundancy(obj,prevInfo,partInfo)
            h = func(*params,group=solver.group)
            if isinstance(h,(list,tuple)):
                ret += list(h)
            else:
                ret.append(h)

        if not ret:
            logger.warn('{} has no effective constraint',cstrName(obj))
        return ret


class PlaneAlignment(BaseCascade):
    _id = 37
    _iconName = 'Assembly_ConstraintAlignment.svg'
    _props = ['Cascade','Offset'] + _AngleProps
    _tooltip = \
        'Add a "{}" constraint to align planar faces of two or more parts.\n'\
        'The faces become coplanar or parallel with an optional distance'


class PlaneCoincident(BaseCascade):
    _id = 35
    _iconName = 'Assembly_ConstraintCoincidence.svg'
    _props = ['Multiply','Cascade','Offset','OffsetX','OffsetY'] + _AngleProps
    _tooltip = \
      'Add a "{}" constraint to conincide planar faces of two or more parts.\n'\
      'The faces are coincided at their centers with an optional distance.'


class Attachment(BaseCascade):
    _id = 45
    _iconName = 'Assembly_ConstraintAttachment.svg'
    _props = ['Multiply', 'Cascade']
    _tooltip = \
      'Add a "{}" constraint to attach two parts by the selected geometry\n'\
      'elements. This constraint completely fixes the parts relative to each\n'\
      'other.'
    _entityDef = (_wa_no_check,)


class AxialAlignment(BaseMulti):
    _id = 36
    _entityDef = (_lna,)
    _iconName = 'Assembly_ConstraintAxial.svg'
    _props = ['Multiply'] + _AngleProps
    _tooltip = 'Add a "{}" constraint to align edges/faces of two or\n'\
        'more parts. The constraint acceps linear edges, which become\n'\
        'colinear, and planar faces, which are aligned uses their surface\n'\
        'normal axis, and cylindrical face, which are aligned using the\n'\
        'axial direction. Different types of geometry elements can be mixed.'


class SameOrientation(BaseMulti):
    _id = 2
    _entityDef = (_n,)
    _iconName = 'Assembly_ConstraintOrientation.svg'
    _tooltip = 'Add a "{}" constraint to align faces of two or more parts.\n'\
        'The planes are aligned to have the same orientation (i.e. rotation)'


class MultiParallel(BaseMulti):
    _id = 291
    _entityDef = (_lw,)
    _iconName = 'Assembly_ConstraintMultiParallel.svg'
    _props = _AngleProps
    _tooltip = 'Add a "{}" constraint to make planar faces or linear edges\n'\
        'of two or more parts parallel.'


class Angle(Base):
    _id = 27
    _entityDef = (_ln,_ln)
    _workplane = True
    _props = ["Angle","Supplement"]
    _iconName = 'Assembly_ConstraintAngle.svg'
    _tooltip = \
        'Add a "{}" constraint to set the angle of planar faces or linear\n'\
        'edges of two parts.'

    @classmethod
    def init(cls,obj):
        infos = obj.Proxy.getElementsInfo()
        proj = None
        if len(infos) == 3:
            proj = infos[2].Placement.Rotation.multiply(
                    utils.getElementRotation(infos[2].Shape))
        obj.Angle = utils.getElementsAngle(infos[0].Shape,infos[1].Shape,
                infos[0].Placement,infos[1].Placement,proj)


class Perpendicular(Base):
    _id = 28
    _entityDef = (_lw,_lw)
    _workplane = True
    _iconName = 'Assembly_ConstraintPerpendicular.svg'
    _tooltip = \
        'Add a "{}" constraint to make planar faces or linear edges of two\n'\
        'parts perpendicular.'

    @classmethod
    def prepare(cls,obj,solver):
        system = solver.system
        e1,e2 = cls.getEntities(obj,solver)[:2]
        isPlane = isinstance(e1,PlaneInfo),isinstance(e2,PlaneInfo)
        if all(isPlane):
            ret = system.addPerpendicular(
                    e1.normal.entity,e2.normal.entity,group=solver.group)
        elif not any(isPlane):
            ret = system.addPerpendicular(e1,e2,group=solver.group)
        elif isPlane[0]:
            ret = system.addParallel(e1.normal.entity,e2,group=solver.group)
        else:
            ret = system.addParallel(e1,e2.normal.entity,group=solver.group)
        return ret


class PointsCoincident(Base):
    _id = 1
    _entityDef = (_p,_p)
    _workplane = True
    _iconName = 'Assembly_ConstraintPointCoincident.svg'
    _tooltips = 'Add a "{}" constraint to conincide two points in 2D or 3D'


class PointInPlane(BaseMulti):
    _id = 3
    _entityDef = (_p,_w)
    _iconName = 'Assembly_ConstraintPointInPlane.svg'
    _tooltip = 'Add a "{}" to constrain one or more point inside a plane.'


class PointOnLine(Base):
    _id = 4
    _entityDef = (_p,_lna)
    _workplane = True
    _iconName = 'Assembly_ConstraintPointOnLine.svg'
    _tooltip = 'Add a "{}" to constrain a point on to a line in 2D or 3D.'

    @classmethod
    def prepare(cls,obj,solver):
        if cls._measure:
            return
        func = cls.constraintFunc(obj,solver)
        if not func:
            return
        params = cls.getEntities(obj,solver)
        if isinstance(params[1], NormalInfo):
            params[1] = params[1].ln
        else:
            params[1] = params[1].entity
        params = cls.getPropertyValues(obj) + params
        ret = func(*params,group=solver.group)
        solver.system.log('{}: {}',cstrName(obj),ret)
        return ret


class PointsOnCircle(BaseMulti):
    _id = 26
    _entityDef = (_p,_c)
    _iconName = 'Assembly_ConstraintPointOnCircle.svg'
    _tooltip='Add a "{}" to constrain one or more points on to a clyndrical\n'\
             'surface defined by a cricle. Note that you must select a point\n'\
             '(any geometry element can define a point), and then select the\n'\
             'circle (or clyndrical surface), after which you can add more\n'\
             'points selection if you want.'
    _cstrFuncName = 'addPointOnCircle'


class PointsDistance(BaseCascade):
    _id = 44
    _entityDef = (_p,)
    _props = ["Cascade","Distance"]
    _iconName = 'Assembly_ConstraintPointsDistance.svg'
    _tooltip = 'Add a "{}" to constrain the distance of two or more points.'

    @classmethod
    def init(cls,obj):
        points = [ info.Placement.multVec(utils.getElementPos(info.Shape))
                    for info in obj.Proxy.getElementsInfo()[:2] ]
        obj.Distance = points[0].distanceToPoint(points[1])


class PointsPlaneDistance(BaseMulti):
    _id = 7
    _entityDef = (_p,_w)
    _props = ["Distance"]
    _iconName = 'Assembly_ConstraintPointPlaneDistance.svg'
    _tooltip='Add a "{}" to constrain the distance between one or more points '\
             'and a plane'
    _cstrFuncName = 'addPointPlaneDistance'

    @classmethod
    def init(cls,obj):
        infos = obj.Proxy.getElementsInfo()[:2]
        points = [ info.Placement.multVec(utils.getElementPos(info.Shape))
                   for info in infos ]
        rot = utils.getElementRotation(infos[1].Shape)
        axis = infos[1].Placement.Rotation.multVec(
                        rot.multVec(FreeCAD.Vector(0,0,1)))
        obj.Distance = points[0].distanceToPlane(points[1],axis)


class PointLineDistance(PointOnLine):
    _id = 8
    _props = ["Distance"]
    _iconName = 'Assembly_ConstraintPointLineDistance.svg'
    _tooltip='Add a "{}" to constrain the distance between a point '\
             'and a linear edge in 2D or 3D'

    @classmethod
    def init(cls,obj):
        infos = obj.Proxy.getElementsInfo()
        p1 = infos[0].Placement.multVec(utils.getElementPos(infos[0].Shape))
        p2 = infos[1].Placement.multVec(infos[1].Shape.Vertex1.Point)
        p3 = infos[1].Placement.multVec(infos[1].Shape.Vertex2.Point)
        if len(infos)==3:
            rot = infos[2].Placement.Rotation.multiply(
                    utils.getElementRotation(infos[2].Shape))
            p1,p2,p3 = utils.project2D(rot,p1,p2,p3)
        obj.Distance = p1.distanceToLine(p2,p3-p2)


class Symmetric(Base):
    _id = 48
    _entityDef = (_ln,_ln,_w)
    _props = ['LockRotationZ']
    _iconName = 'Assembly_ConstraintSymmetric.svg'
    _tooltip='Add a "{}" constraint to make geometry elements of two parts\n'\
            'symmetric about a plane. The supported elements are linear edge\n'\
            'and planar face'

    @classmethod
    def prepare(cls,obj,solver):
        func = cls.constraintFunc(obj,solver)
        func2 = cls.constraintFunc(obj,solver,'addPointsCoincident')
        if not func or not func2:
            return
        params = cls.getEntities(obj,solver,retAll=True)
        e0,e1,w = params[:3]
        ret = []
        ret.append(func(e0.p0,e1.p0,w.entity,group=solver.group))
        ret.append(func2(e0.p1,e1.p1,w.entity,group=solver.group))
        if obj.LockRotationZ:
            rot = w.normal.pla.Rotation.multiply(w.normal.rot)
            x1 = e0.pla.multVec(e0.vx)
            x2 = e1.pla.multVec(e1.vx)
            v1,v2 = utils.project2D(rot, x1, x2)
            if abs(v1.x-v2.x) < abs(v1.y-v2.y):
                func = cls.constraintFunc(obj,solver,'addPointsHorizontal')
            else:
                func = cls.constraintFunc(obj,solver,'addPointsVertical')
            if func:
                ret.append(func(e0.px, e1.px, w.entity, group=solver.group))
        solver.system.log('{}: {}',cstrName(obj),ret)
        return ret


class More(Base):
    _id = -2
    _iconName = 'Assembly_ConstraintMore.svg'
    _tooltip='Toggle toolbars for more constraints'

    @classmethod
    def activate(cls):
        gui.AsmCmdManager.toggleToolbars()

    @classmethod
    def checkActive(cls):
        return True


class Base2(Base):
    _id = -1
    _toolbarName = 'Assembly3 Constraints2'
    _toolbarVisible = False


class PointDistance(Base2):
    _id = 5
    _entityDef = (_p,_p)
    _workplane = True
    _props = ["Distance"]
    _iconName = 'Assembly_ConstraintPointDistance.svg'
    _tooltip = 'Add a "{}" to constrain the distance of two points in 2D or 3D.'
    _cstrFuncName = 'addPointsDistance'

    @classmethod
    def init(cls,obj):
        infos = obj.Proxy.getElementsInfo()
        ps = [ info.Placement.multVec(utils.getElementPos(info.Shape))
                   for info in infos ]
        if len(infos)==3:
            rot = infos[2].Placement.Rotation.multiply(
                    utils.getElementRotation(infos[2].Shape))
            ps[0],ps[1] = utils.project2D(rot,ps[0],ps[1])

        obj.Distance = ps[0].distanceToPoint(ps[1])


class EqualAngle(Base2):
    _id = 14
    _entityDef = (_ln,_ln,_ln,_ln)
    _workplane = True
    _props = ["Supplement"]
    _iconName = 'Assembly_ConstraintEqualAngle.svg'
    _tooltip='Add a "{}" to equate the angles between two lines or normals.'


class PointsSymmetric(Base2):
    _id = 16
    _entityDef = (_p,_p,_w)
    _workplane = True
    _iconName = 'Assembly_ConstraintPointsSymmetric.svg'
    _tooltip='Add a "{}" constraint to make two points symmetric about a plane.'
    _cstrFuncName = 'addSymmetric'


class SymmetricHorizontal(Base2):
    _id = 17
    _entityDef = (_p,_p)
    _workplane = 2


class SymmetricVertical(Base2):
    _id = 18
    _entityDef = (_p,_p)
    _workplane = 2


class SymmetricLine(Base2):
    _id = 19
    _entityDef = (_p,_p,_l)
    _workplane = 2
    _iconName = 'Assembly_ConstraintSymmetricLine.svg'
    _tooltip='Add a "{}" constraint to make two points symmetric about a line.'


class PointsHorizontal(Base2):
    _id = 21
    _entityDef = (_p,_p)
    _workplane = 2
    _iconName = 'Assembly_ConstraintPointsHorizontal.svg'
    _tooltip='Add a "{}" constraint to make two points horizontal with each\n'\
             'other when projected onto a plane.'


class PointsVertical(Base2):
    _id = 22
    _entityDef = (_p,_p)
    _workplane = 2
    _iconName = 'Assembly_ConstraintPointsVertical.svg'
    _tooltip='Add a "{}" constraint to make two points vertical with each\n'\
             'other when projected onto a plane.'


class LineHorizontal(Base2):
    _id = 23
    _entityDef = (_l,)
    _workplane = 2
    _iconName = 'Assembly_ConstraintLineHorizontal.svg'
    _tooltip='Add a "{}" constraint to make a line segment horizontal when\n'\
             'projected onto a plane.'


class LineVertical(Base2):
    _id = 24
    _entityDef = (_l,)
    _workplane = 2
    _iconName = 'Assembly_ConstraintLineVertical.svg'
    _tooltip='Add a "{}" constraint to make a line segment vertical when\n'\
             'projected onto a plane.'


class ArcLineTangent(Base2):
    _id = 30
    _entityDef = (_a,_l)
    _props = ["AtEnd"]
    _iconName = 'Assembly_ConstraintArcLineTangent.svg'
    _tooltip='Add a "{}" constraint to make a line tangent to an arc\n'\
             'at the start or end point of the arc.'


class BaseSketch(Base):
    _id = -1
    _toolbarName = 'Assembly3 Sketch Constraints'
    _toolbarVisible = False


class SketchPlane(BaseSketch):
    _id = 38
    _iconName = 'Assembly_ConstraintSketchPlane.svg'
    _tooltip='Add a "{0}" to define the work plane of any draft element\n'\
             'inside or following this constraint. Add an empty "{0}" to\n'\
             'undefine the previous work plane'

    @classmethod
    def getEntityDef(cls,elements,checkCount,obj=None):
        _ = checkCount
        _ = obj
        if not elements:
            # If no element, then this constraint serves the prupose of clearing
            # the current sketch plane
            return []

        # if there is any child element in this constraint, we expect the first
        # one to be a planar face or edge to define the work plane. The rest of
        # entities must be from some draft wire or circle/arc 
        #
        # Base.prepare() will call system.addSketchPlane() with all contained
        # element below. However, the default implementation, 
        # SystemExtension.addSketchPlane(),  only really uses the first one,
        # i.e. the one obtained by _wa(), i.e. a tuple of entities
        # (workplane,base,normal).

        return [_wa] + [_d]*(len(elements)-1)


class BaseDraftWire(BaseSketch):
    _id = -1

    @classmethod
    def check(cls,elements,checkCount=False):
        super(BaseDraftWire,cls).check(elements,checkCount)
        if not checkCount:
            return
        for info in elements:
            if utils.isDraftWire(info.Part):
                return
        raise RuntimeError('Constraint "{}" requires at least one linear edge '
                'from a none-subdivided Draft.Wire'.format(
                    cls.getName()))

class LineLength(BaseSketch):
    _id = 34
    _entityDef = (_dl,)
    _workplane = True
    _props = ["Length"]
    _iconName = 'Assembly_ConstraintLineLength.svg'
    _tooltip='Add a "{}" constrain the length of a none-subdivided Draft.Wire'

    @classmethod
    def init(cls,obj):
        info = obj.Proxy.getElementsInfo()[0]
        obj.Length = info.Shape.Edge1.Length

    @classmethod
    def prepare(cls,obj,solver):
        func = cls.constraintFunc(obj,solver,'addPointsDistance')
        if not func:
            return
        _,p0,p1 = cls.getEntities(obj,solver,retAll=True)[0]
        params = cls.getPropertyValues(obj) + [p0,p1]
        ret = func(*params,group=solver.group)
        solver.system.log('{}: {}',cstrName(obj),ret)
        return ret


class EqualLength(BaseDraftWire):
    _id = 9
    _entityDef = (_l,_l)
    _workplane = True
    _iconName = 'Assembly_ConstraintEqualLength.svg'
    _tooltip='Add a "{}" constraint to make two lines of the same length.'


class LengthRatio(BaseDraftWire):
    _id = 10
    _entityDef = (_l,_l)
    _workplane = True
    _props = ["Ratio"]
    _iconName = 'Assembly_ConstraintLengthRatio.svg'
    _tooltip='Add a "{}" to constrain the length ratio of two lines.'


class LengthDifference(BaseDraftWire):
    _id = 11
    _entityDef = (_l,_l)
    _workplane = True
    _props = ["Difference"]
    _iconName = 'Assembly_ConstraintLengthDifference.svg'
    _tooltip='Add a "{}" to constrain the length difference of two lines.'


class EqualLengthPointLineDistance(BaseSketch):
    _id = 12
    _entityDef = (_p,_l,_l)
    _workplane = True
    _iconName = 'Assembly_ConstraintLengthEqualPointLineDistance.svg'
    _tooltip='Add a "{}" to constrain the distance between a point and a\n' \
             'line to be the same as the length of a another line.'


class EqualLineArcLength(BaseSketch):
    _id = 15
    _entityDef = (_l,_a)
    _workplane = True
    _tooltip='Add a "{}" constraint to make a line of the same length as an arc'

    @classmethod
    def check(cls,elements,checkCount=False):
        super(EqualLineArcLength,cls).check(elements,checkCount)
        if not checkCount:
            return
        for i,info in enumerate(elements):
            if i:
                if utils.isDraftCircle(info.Part):
                    return
            elif utils.isDraftWire(info.Part):
                return
        raise RuntimeError('Constraint "{}" requires at least one '
            'non-subdivided Draft.Wire or one Draft.Circle'.format(
                cls.getName()))


class MidPoint(BaseSketch):
    _id = 20
    _entityDef = (_p,_l)
    _workplane = True
    _iconName = 'Assembly_ConstraintMidPoint.svg'
    _tooltip='Add a "{}" to constrain a point to the middle point of a line.'

    @classmethod
    def prepare(cls,obj,solver):
        func = cls.constraintFunc(obj,solver)
        if not func:
            return
        params = cls.getPropertyValues(obj) + cls.getEntities(obj,solver)
        # temparary fix of slvs.addMidPoint(), which should have made wrkpln
        # argument optional and defaults to 0
        if len(params)==2:
            params.append(0)
        ret = func(*params,group=solver.group)
        solver.system.log('{}: {}',cstrName(obj),ret)
        return ret


class Diameter(BaseSketch):
    _id = 25
    _entityDef = (_dc,)
    _props = ("Diameter",)
    _iconName = 'Assembly_ConstraintDiameter.svg'
    _tooltip='Add a "{}" to constrain the diameter of a circle/arc'


class EqualRadius(BaseSketch):
    _id = 33
    _entityDef = (_c,_c)
    _iconName = 'Assembly_ConstraintEqualRadius.svg'
    _tooltip='Add a "{}" constraint to make two circles/arcs of the same radius'

    @classmethod
    def check(cls,elements,checkCount=False):
        super(EqualRadius,cls).check(elements,checkCount)
        if not checkCount:
            return
        for info in elements:
            if utils.isDraftCircle(info.Part):
                return
        raise RuntimeError('Constraint "{}" requires at least one '
            'Draft.Circle'.format(cls.getName()))


class PointsProjectDistance(BaseSketch):
    _id = 6
    _entityDef = (_p,_p,_l)
    _props = ["Distance"]
    _iconName = 'Assembly_ConstraintPointsProjectDistance.svg'
    _tooltip = 'Add a "{}" to constrain the distance of two points\n' \
               'projected on a line.'

    @classmethod
    def init(cls,obj):
        infos = obj.Proxy.getElementsInfo()
        ps = [ info.Placement.multVec(utils.getElementPos(info.Shape))
                   for info in infos ]
        p3 = infos[2].Placement.multVec(infos[2].Shape.Vertex2.Point)
        p1,p2 = [ utils.projectToLine(p,ps[2],p3) for p in ps[:2] ]
        obj.Distance = p1.distanceToPoint(p2)


class EqualPointLineDistance(BaseSketch):
    _id = 13
    _entityDef = (_p,_l,_p,_l)
    _workplane = True
    _iconName = 'Assembly_ConstraintEqualPointLineDistance.svg'
    _tooltip='Add a "{}" to constrain the distance between a point and a\n'\
             'line to be the same as the distance between another point\n'\
             'and line.'


class Colinear(BaseSketch):
    _id = 39
    _entityDef = (_lna, _lna)
    _workplane = True
    _iconName = 'Assembly_ConstraintColinear.svg'
    _tooltip='Add a "{}" constraint to make to line colinear'


#  class CubicLineTangent(BaseSketch):
#      _id = 31
#
#
#  class CurvesTangent(BaseSketch):
#      _id = 32


class MeasurePoints(PointDistance):
    _id = 40
    _measure = True
    _tooltip = 'Add a "{}" to measure the distance of two points in 2D or 3D.'

class MeasurePointLine(PointLineDistance):
    _id = 41
    _measure = True
    _tooltip='Add a "{}" to measure the distance between a point and a\n'\
             'linear edge in 2D or 3D'

class MeasurePointPlane(PointsPlaneDistance):
    _id = 42
    _measure = True
    _tooltip='Add a "{}" to measure the distance between a point and a plane'

class MeasureAngle(Angle):
    _id = 43
    _measure = True
    _tooltip = 'Add a "{}" to measure the angle of planar faces or linear\n'\
        'edges of two parts.'

