from collections import namedtuple
from PySide.QtCore import Qt
from PySide.QtGui import QIcon, QPainter, QPixmap
import FreeCAD, FreeCADGui
import asm3.utils as utils
import asm3.slvs as slvs
from asm3.utils import logger, objName

import os
iconPath = os.path.join(utils.iconPath,'constraints')
pixmapDisabled = QPixmap(os.path.join(
    iconPath,'Assembly_ConstraintDisabled.svg'))
iconSize = (16,16)

def cstrName(obj):
    return '{}<{}>'.format(objName(obj),obj.Type)

PropertyInfo = namedtuple('AsmPropertyInfo',
        ('Name','Type','Group','Doc','Enum','Getter'))

_propInfo = {}

def _propGet(obj,prop):
    return getattr(obj,prop)

def _propGetValue(obj,prop):
    return getattr(getattr(obj,prop),'Value')

def _makePropInfo(name,tp,doc='',enum=None,getter=_propGet,group='Constraint'):
    _propInfo[name] = PropertyInfo(name,tp,group,doc,enum,getter)

_makePropInfo('Distance','App::PropertyDistance',getter=_propGetValue)
_makePropInfo('Offset','App::PropertyDistance',getter=_propGetValue)
_makePropInfo('Cascade','App::PropertyBool')
_makePropInfo('Angle','App::PropertyAngle',getter=_propGetValue)
_makePropInfo('Ratio','App::PropertyFloat')
_makePropInfo('Difference','App::PropertyFloat')
_makePropInfo('Diameter','App::PropertyFloat')
_makePropInfo('Radius','App::PropertyFloat')
_makePropInfo('Supplement','App::PropertyBool',
        'If True, then the second angle is calculated as 180-angle')
_makePropInfo('AtEnd','App::PropertyBool',
        'If True, then tangent at the end point, or else at the start point')

_ordinal = ['1st', '2nd', '3rd', '4th', '5th', '6th', '7th' ]

Types = []
TypeMap = {}
TypeNameMap = {}

class ConstraintType(type):
    def __init__(cls, name, bases, attrs):
        super(ConstraintType,cls).__init__(name,bases,attrs)
        if cls._id >= 0:
            if cls._id in TypeMap:
                raise RuntimeError(
                        'Duplicate constriant type id {}'.format(cls._id))
            if not cls.slvsFunc():
                return

            if cls._props:
                for i,prop in enumerate(cls._props):
                    try:
                        cls._props[i] = _propInfo[prop]
                    except AttributeError:
                        raise RuntimeError('Unknonw property "{}" in '
                            'constraint type "{}"'.format(prop,cls.getName()))
            TypeMap[cls._id] = cls
            TypeNameMap[cls.getName()] = cls
            cls._idx = len(Types)
            logger.debug('register constraint "{}":{},{}'.format(
                cls.getName(),cls._id,cls._idx))
            Types.append(cls)


# PartName: text name of the part
# Placement: the original placement of the part
# Params: 7 parameters that defines the transformation of this part
# RParams: 7 parameters that defines the rotation transformation of this part
# Workplane: a tuple of three entity handles, that is the workplane, the origin
#            point, and the normal. The workplane, defined by the origin and
#            norml, is essentially the XY reference plane of the part.
# EntityMap: string -> entity handle map, for caching
# Group: transforming entity group handle
# X: a point entity (1,0,0) rotated by this part's placement 
# Y: a point entity (0,1,0) rotated by this part's placement 
# Z: a point entity (0,0,1) rotated by this part's placement 
PartInfo = namedtuple('SolverPartInfo', 
        ('PartName','Placement','Params','RParams','Workplane','EntityMap',
            'Group', 'X','Y','Z'))

def _p(solver,partInfo,key,shape):
    'return a slvs handle of a transformed point derived from "shape"'
    if not solver:
        if utils.hasCenter(shape):
            return
        return 'a vertex or circular edge/face'
    key += '.p'
    h = partInfo.EntityMap.get(key,None)
    if h:
        logger.debug('cache {}: {}'.format(key,h))
    else:
        v = utils.getElementPos(shape)
        system = solver.system
        e = system.addPoint3dV(*v)
        h = system.addTransform(e,*partInfo.Params,group=partInfo.Group)
        logger.debug('{}: {},{}, {}, {}'.format(key,h,partInfo.Group,e,v))
        partInfo.EntityMap[key] = h
    return h

def _n(solver,partInfo,key,shape,retAll=False):
    'return a slvs handle of a transformed normal quaterion derived from shape'
    if not solver:
        if utils.isPlanar(shape):
            return
        return 'an edge or face with a surface normal'
    key += '.n'
    h = partInfo.EntityMap.get(key,None)
    if h:
        logger.debug('cache {}: {}'.format(key,h))
    else:
        system = solver.system
        params = [ system.addParamV(n) for n in utils.getElementNormal(shape) ]
        e = system.addNormal3d(*params)
        h = system.addTransform(e,*partInfo.Params,group=partInfo.Group)
        h = [h,e,params]
        logger.debug('{}: {},{}'.format(key,h,partInfo.Group))
        partInfo.EntityMap[key] = h
    return h if retAll else h[0]

def _l(solver,partInfo,key,shape,retAll=False):
    'return a pair of slvs handle of the end points of an edge in "shape"'
    if not solver:
        if utils.isLinearEdge(shape):
            return
        return 'a linear edge'
    key += '.l'
    h = partInfo.EntityMap.get(key,None)
    if h:
        logger.debug('cache {}: {}'.format(key,h))
    else:
        system = solver.system
        v = shape.Edges[0].Vertexes
        p1 = system.addPoint3dV(*v[0].Point)
        p2 = system.addPoint3dV(*v[-1].Point)
        h = system.addLineSegment(p1,p2,group=partInfo.Group)
        h = (h,p1,p2)
        logger.debug('{}: {},{}'.format(key,h,partInfo.Group))
        partInfo.EntityMap[key] = h
    return h if retAll else h[0]

def _ln(solver,partInfo,key,shape,retAll=False):
    'return a slvs handle for either a line or a normal depends on the shape'
    if not solver:
        if utils.isLinearEdge(shape) or utils.isPlanar(shape):
            return
        return 'a linear edge or edge/face with planar surface'
    if utils.isLinearEdge(shape):
        return _l(solver,partInfo,key,shape,retAll)
    return _n(solver,partInfo,key,shape)

def _w(solver,partInfo,key,shape,retAll=False):
    'return a slvs handle of a transformed plane/workplane from "shape"'
    if not solver:
        if utils.isPlanar(shape):
            return
        return 'an edge/face with a planar surface'

    key2 = key+'.w'
    h = partInfo.EntityMap.get(key2,None)
    if h:
        logger.debug('cache {}: {}'.format(key,h))
    else:
        p = _p(solver,partInfo,key,shape)
        n = _n(solver,partInfo,key,shape)
        h = solver.system.addWorkplane(p,n,group=partInfo.Group)
        h = (h,p,n)
        logger.debug('{}: {},{}'.format(key,h,partInfo.Group))
        partInfo.EntityMap[key2] = h
    return h if retAll else h[0]

def _wa(solver,partInfo,key,shape):
    return _w(solver,partInfo,key,shape,True)

def _c(solver,partInfo,key,shape,requireArc=False):
    'return a slvs handle of a transformed circle/arc derived from "shape"'
    if not solver:
        r = utils.getElementCircular(shape)
        if not r or (requireArc and not isinstance(r,list,tuple)):
            return
        return 'an cicular arc edge' if requireArc else 'a circular edge'
    key2 = key+'.c'
    h = partInfo.EntityMap.get(key2,None)
    if h:
        logger.debug('cache {}: {}'.format(key,h))
    else:
        h = _w(solver,partInfo,key,shape,True)
        r = utils.getElementCircular(shape)
        if not r:
            raise RuntimeError('shape is not cicular')
        if isinstance(r,(list,tuple)):
            l = _l(solver,partInfo,key,shape,True)
            h += l[1:]
            h = solver.system.addArcOfCircleV(*h,group=partInfo.Group)
        elif requireArc:
            raise RuntimeError('shape is not an arc')
        else:
            h = h[1:]
            h.append(solver.addDistanceV(r))
            h = solver.system.addCircle(*h,group=partInfo.Group)
        logger.debug('{}: {},{} {}'.format(key,h,partInfo.Group,r))
        partInfo.EntityMap[key2] = h
    return h

def _a(solver,partInfo,key,shape):
    return _c(solver,partInfo,key,shape,True)


class Base:
    __metaclass__ = ConstraintType

    _id = -1
    _entityDef = []
    _workplane = False
    _props = []
    _func = None
    _icon = None
    _iconDisabled = None
    _iconName = 'Assembly_ConstraintGeneral.svg'

    def __init__(self,obj):
        if obj._Type != self._id:
            if self._id < 0:
                raise RuntimeError('invalid constraint type {} id: '
                    '{}'.format(self.__class__,self._id))
            obj._Type = self._id
        props = obj.PropertiesList
        for prop in self.__class__._props:
            if prop.Name not in props:
                obj.addProperty(prop.Type,prop.Name,prop.Group,prop.Doc)
                if prop.Enum:
                    setattr(obj,prop.Name,prop.Enum)
            else:
                obj.setPropertyStatus(prop.Name,'-Hidden')

    @classmethod
    def getName(cls):
        return cls.__name__

    @classmethod
    def slvsFunc(cls):
        try:
            if not cls._func:
                cls._func = getattr(slvs.System,'add'+cls.getName())
            return cls._func
        except AttributeError:
            logger.error('Invalid slvs constraint "{}"'.format(cls.getName()))

    @classmethod
    def getEntityDef(cls,group,checkCount,obj=None):
        entities = cls._entityDef
        if len(group) != len(entities):
            if not checkCount and len(group)<len(entities):
                return entities[:len(group)]
            if cls._workplane and len(group)==len(entities)+1:
                entities = list(entities)
                entities.append(_w)
            else:
                if not obj:
                    name = cls.getName()
                else:
                    name += cstrName(obj)
                raise RuntimeError('Constraint {} has wrong number of '
                    'elements {}, expecting {}'.format(
                        name,len(group),len(entities)))
        return entities

    @classmethod
    def check(cls,group):
        entities = cls.getEntityDef(group,False)
        for i,e in enumerate(entities):
            o = group[i]
            msg = e(None,None,None,o)
            if not msg:
                continue
            if i == len(cls._entityDef):
                raise RuntimeError('Constraint {} requires the optional {} '
                    'element to be a planar face for defining a '
                    'workplane'.format(cls.getName(), _ordinal[i], msg))
            raise RuntimeError('Constraint {} requires the {} element to be'
                    ' {}'.format(cls.getName(), _ordinal[i], msg))

    @classmethod
    def getIcon(cls,obj):
        if not cls._icon:
            cls._icon = QIcon(os.path.join(iconPath,cls._iconName))
        if not obj.Disabled:
            return cls._icon
        if not cls._iconDisabled:
            pixmap = cls._icon.pixmap(*iconSize,mode=QIcon.Disabled)
            icon = QIcon(pixmapDisabled)
            icon.paint(QPainter(pixmap),
                    0,0,iconSize[0],iconSize[1],Qt.AlignCenter)
            cls._iconDisabled = QIcon(pixmap)
        return cls._iconDisabled

    @classmethod
    def detach(cls,obj):
        logger.debug('detaching {}'.format(cstrName(obj)))
        obj.Proxy._cstr = None
        for prop in cls._props:
            #  obj.setPropertyStatus(prop.Name,'Hidden')
            obj.removeProperty(prop.Name)

    def onChanged(self,obj,prop):
        pass

    @classmethod
    def getEntities(cls,obj,solver):
        '''maps fcad element shape to slvs entities'''
        ret = []
        for prop in cls._props:
            ret.append(prop.Getter(obj,prop.Name))

        elements = obj.Proxy.getElements()
        entities = cls.getEntityDef(elements,True,obj)
        for e,o in zip(entities,elements):
            info = o.Proxy.getInfo()
            partInfo = solver.getPartInfo(info)
            ret.append(e(solver,partInfo,info.Subname,info.Shape))
        logger.debug('{} entities: {}'.format(cstrName(obj),ret))
        return ret

    @classmethod
    def prepare(cls,obj,solver):
        e = cls.getEntities(obj,solver)
        h = cls._func(solver.system,*e,group=solver.group)
        logger.debug('{} constraint: {}'.format(cstrName(obj),h))


class Locked(Base):
    _id = 0
    _func = True
    _iconName = 'Assembly_ConstraintLock.svg'

    @classmethod
    def prepare(cls,obj,solver):
        for e in obj.Proxy.getElements():
            solver.addFixedPart(e.Proxy.getInfo())

    @classmethod
    def check(cls,_group):
        pass

class BaseMulti(Base):
    _id = -1
    _func = True
    _entityDef = [_wa]

    @classmethod
    def check(cls,group):
        if len(group)<2:
            raise RuntimeError('Constraint {} requires at least two '
                'elements'.format(cls.getName()))
        for o in group:
            msg = cls._entityDef[0](None,None,None,o)
            if msg:
                raise RuntimeError('Constraint {} requires all the element '
                    'to be of {}'.format(cls.getName()))
        return

    @classmethod
    def prepare(cls,obj,solver):
        parts = set()
        ref = None
        elements = []
        for e in obj.Proxy.getElements():
            info = e.Proxy.getInfo()
            if info.Part in parts:
                logger.warn('{} skip duplicate parts {}'.format(
                    cstrName(obj),info.PartName))
                continue
            parts.add(info.Part)
            if solver.isFixedPart(info):
                if ref:
                    logger.warn('{} skip more than one fixed part {}'.format(
                        cstrName(obj),info.PartName))
                    continue
                ref = info
                elements.insert(0,e)
            else:
                elements.append(e)
        if len(elements)<=1:
            logger.warn('{} has no effective constraint'.format(cstrName(obj)))
            return
        e0 = None
        for e in elements:
            info = e.Proxy.getInfo()
            partInfo = solver.getPartInfo(info)
            if not e0:
                e0 = cls._entityDef[0](solver,partInfo,info.Subname,info.Shape)
            else:
                e = cls._entityDef[0](solver,partInfo,info.Subname,info.Shape)
                cls.prepareElements(obj,solver,e0,e)


class BaseCascade(BaseMulti):
    @classmethod
    def prepare(cls,obj,solver):
        if not getattr(obj,'Cascade',True):
            super(BaseCascade,cls).prepare(obj,solver)
            return
        prev = None
        count = 0
        for e in obj.Proxy.getElements():
            info = e.Proxy.getInfo()
            if not prev or prev.Part==info.Part:
                prev = info
                continue
            count += 1
            prevInfo = solver.getPartInfo(prev)
            e1 = cls._entityDef[0](solver,prevInfo,prev.Subname,prev.Shape)
            partInfo = solver.getPartInfo(info)
            e2 = cls._entityDef[0](solver,partInfo,info.Subname,info.Shape)
            prev = info
            if solver.isFixedPart(info):
                e2,e1 = e1,e2
            cls.prepareElements(obj,solver,e1,e2)
        if not count:
            logger.warn('{} has no effective constraint'.format(cstrName(obj)))


class PlaneCoincident(BaseCascade):
    _id = 35
    _iconName = 'Assembly_ConstraintCoincidence.svg'
    _props = ["Offset", 'Cascade']

    @classmethod
    def prepareElements(cls,obj,solver,e1,e2):
        system = solver.system
        d = abs(obj.Offset.Value)
        _,p1,n1 = e1
        w2,p2,n2 = e2
        if d>0.0:
            h = system.addPointPlaneDistance(d,p1,w2,group=solver.group)
            logger.debug('{}: point plane distance {},{},{}'.format(
                cstrName(obj),h,p1,w2,d))
            h = system.addPointsCoincident(p1,p2,w2,group=solver.group)
            logger.debug('{}: points conincident {},{},{}'.format(
                cstrName(obj),h,p1,p2,w2))
        else:
            h = system.addPointsCoincident(p1,p2,group=solver.group)
            logger.debug('{}: points conincident {},{},{}'.format(
                cstrName(obj),h,p1,p2))
        h = system.addParallel(n1,n2,group=solver.group)
        logger.debug('{}: parallel {},{},{}'.format(cstrName(obj),h,n1,n2))


class PlaneAlignment(BaseCascade):
    _id = 37
    _iconName = 'Assembly_ConstraintAlignment.svg'
    _props = ["Offset", 'Cascade']

    @classmethod
    def prepareElements(cls,obj,solver,e1,e2):
        system = solver.system
        d = abs(obj.Offset.Value)
        _,p1,n1 = e1
        w2,_,n2 = e2
        if d>0.0:
            h = system.addPointPlaneDistance(d,p1,w2,group=solver.group)
            logger.debug('{}: point plane distance {},{},{}'.format(
                cstrName(obj),h,p1,w2,d))
        else:
            h = system.addPointInPlane(p1,w2,group=solver.group)
            logger.debug('{}: point in plane {},{}'.format(
                cstrName(obj),h,p1,w2))
        h = system.addParallel(n1,n2,group=solver.group)
        logger.debug('{}: parallel {},{},{}'.format(cstrName(obj),h,n1,n2))


class AxialAlignment(BaseMulti):
    _id = 36
    _iconName = 'Assembly_ConstraintAxial.svg'

    @classmethod
    def prepareElements(cls,obj,solver,e1,e2):
        system = solver.system
        _,p1,n1 = e1
        w2,p2,n2 = e2
        h = system.addPointsCoincident(p1,p2,w2,group=solver.group)
        logger.debug('{}: points coincident {},{},{},{}'.format(
            cstrName(obj),h,p1,p2,w2))
        h = system.addParallel(n1,n2,group=solver.group)
        logger.debug('{}: parallel {},{},{}'.format(cstrName(obj),h,n1,n2))


class SameOrientation(BaseMulti):
    _id = 2
    _entityDef = [_n]
    _iconName = 'Assembly_ConstraintOrientation.svg'

    @classmethod
    def prepareElements(cls,obj,solver,n1,n2):
        h = solver.system.addSameOrientation(n1,n2,group=solver.group)
        logger.debug('{}: {} {},{},{}'.format(
            cstrName(obj),cls.getName(),h,n1,n2))


class Angle(Base):
    _id = 27
    _entityDef = (_ln,_ln)
    _workplane = True
    _props = ["Angle","Supplement"]
    _iconName = 'Assembly_ConstraintAngle.svg'


class Perpendicular(Base):
    _id = 28
    _entityDef = (_ln,_ln)
    _workplane = True
    _iconName = 'Assembly_ConstraintPerpendicular.svg'


class Parallel(Base):
    _id = 29
    _entityDef = (_ln,_ln)
    _workplane = True
    _iconName = 'Assembly_ConstraintParallel.svg'


class MultiParallel(BaseMulti):
    _id = 291
    _entityDef = [_ln]
    _iconName = 'Assembly_ConstraintMultiParallel.svg'

    @classmethod
    def prepareElements(cls,obj,solver,e1,e2):
        h = solver.system.addParallel(e1,e2,group=solver.group)
        logger.debug('{}: {} {},{},{}'.format(
            cstrName(obj),cls.getName(),h,e1,e2))


class PointsCoincident(Base):
    _id = 1
    _entityDef = (_p,_p)
    _workplane = True


class PointInPlane(Base):
    _id = 3
    _entityDef = (_p,_w)


class PointOnLine(Base):
    _id = 4
    _entityDef = (_p,_l)
    _workplane = True


class PointsDistance(Base):
    _id = 5
    _entityDef = (_p,_p)
    _workplane = True
    _props = ["Distance"]


class PointsProjectDistance(Base):
    _id = 6
    _entityDef = (_p,_p,_l)
    _props = ["Distance"]


class PointPlaneDistance(Base):
    _id = 7
    _entityDef = (_p,_w)
    _props = ["Distance"]


class PointLineDistance(Base):
    _id = 8
    _entityDef = (_p,_l)
    _workplane = True
    _props = ["Distance"]


class EqualLength(Base):
    _id = 9
    _entityDef = (_l,_l)
    _workplane = True


class LengthRatio(Base):
    _id = 10
    _entityDef = (_l,_l)
    _workplane = True
    _props = ["Ratio"]


class LengthDifference(Base):
    _id = 11
    _entityDef = (_l,_l)
    _workplane = True
    _props = ["Difference"]


class EqualLengthPointLineDistance(Base):
    _id = 12
    _entityDef = (_p,_l,_l)
    _workplane = True


class EqualPointLineDistance(Base):
    _id = 13
    _entityDef = (_p,_l,_p,_l)
    _workplane = True


class EqualAngle(Base):
    _id = 14
    _entityDef = (_l,_l,_l,_l)
    _workplane = True
    _props = ["Supplement"]


class EqualLineArcLength(Base):
    _id = 15
    _entityDef = (_l,_a)
    _workplane = True


class Symmetric(Base):
    _id = 16
    _entityDef = (_p,_p,_w)
    _workplane = True


class SymmetricHorizontal(Base):
    _id = 17
    _entityDef = (_p,_p,_w)


class SymmetricVertical(Base):
    _id = 18
    _entityDef = (_p,_p,_w)


class SymmetricLine(Base):
    _id = 19
    _entityDef = (_p,_p,_l,_w)


class MidPoint(Base):
    _id = 20
    _entityDef = (_p,_p,_l)
    _workplane = True


class PointsHorizontal(Base):
    _id = 21
    _entityDef = (_p,_p)
    _workplane = True


class PointsVertical(Base):
    _id = 22
    _entityDef = (_p,_p)
    _workplane = True


class LineHorizontal(Base):
    _id = 23
    _entityDef = [_l]
    _workplane = True


class LineVertical(Base):
    _id = 24
    _entityDef = [_l]
    _workplane = True


class Diameter(Base):
    _id = 25
    _entityDef = [_c]
    _prop = ["Diameter"]


class PointOnCircle(Base):
    _id = 26
    _entityDef = [_p,_c]


class ArcLineTangent(Base):
    _id = 30
    _entityDef = (_c,_l)
    _props = ["AtEnd"]


#  class CubicLineTangent(Base):
#      _id = 31
#
#
#  class CurvesTangent(Base):
#      _id = 32


class EqualRadius(Base):
    _id = 33
    _entityDef = (_c,_c)
    _props = ["Radius"]


class WhereDragged(Base):
    _id = 34
    _entityDef = [_p]
    _workplane = True


TypeEnum = namedtuple('AsmConstraintEnum',
        (c.getName() for c in Types))(*range(len(Types)))

def attach(obj,checkType=True):
    if checkType:
        if 'Type' not in obj.PropertiesList:
            # The 'Type' property here is to let user select the type in
            # property editor. It is marked as 'transient' to avoid having to
            # save the enumeration value for each object.
            obj.addProperty("App::PropertyEnumeration","Type","Base",'',2)
        obj.Type = TypeEnum._fields
        idx = 0
        try:
            idx = TypeMap[obj._Type]._idx
        except AttributeError:
            logger.warn('{} has unknown constraint type {}'.format(
                objName(obj),obj._Type))
        obj.Type = idx

    constraintType = TypeNameMap[obj.Type]
    cstr = getattr(obj.Proxy,'_cstr',None)
    if type(cstr) is not constraintType:
        logger.debug('attaching {}, {} -> {}'.format(
            objName(obj),type(cstr).__name__,constraintType.__name__),frame=1)
        if cstr:
            cstr.detach(obj)
        obj.Proxy._cstr = constraintType(obj)
        obj.ViewObject.signalChangeIcon()


def onChanged(obj,prop):
    if prop == 'Type':
        if hasattr(obj.Proxy,'_cstr'):
            attach(obj,False)
        return
    elif prop == '_Type':
        if hasattr(obj,'Type'):
            obj.Type = TypeMap[obj._Type]._idx
        return
    elif prop == 'Disabled':
        obj.ViewObject.signalChangeIcon()
        return
    cstr = getattr(obj.Proxy,'_cstr',None)
    if cstr:
        cstr.onChanged(obj,prop)


def check(tp,group):
    TypeMap[tp].check(group)

def prepare(obj,solver):
    obj.Proxy._cstr.prepare(obj,solver)

def isLocked(obj):
    return not obj.Disabled and isinstance(obj.Proxy._cstr,Locked)

def getIcon(obj):
    cstr = getattr(obj.Proxy,'_cstr',None)
    if cstr:
        return cstr.getIcon(obj)
