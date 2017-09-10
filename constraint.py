from collections import namedtuple
import FreeCAD, FreeCADGui
import asm3.utils as utils
import asm3.slvs as slvs
from asm3.utils import logger, objName

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
            if cls.slvsFunc():
                TypeMap[cls._id] = cls
                TypeNameMap[cls.getName()] = cls
                cls._idx = len(Types)
                logger.debug('register constraint "{}":{},{}'.format(
                    cls.getName(),cls._id,cls._idx))
                Types.append(cls)


# PartName: text name of the part
# Placement: the original placement of the part
# Params: 7 parameters that defines the transformation
# Workplane: a tuple of three entity handles, that is the workplane, the origin
#            point, and the normal. The workplane, defined by the origin and
#            norml, is essentially the XY reference plane of the part.
# EntityMap: string -> entity handle map, for caching
PartInfo = namedtuple('SolverPartInfo', 
        ('PartName','Placement','Params','Workplane','EntityMap'))

def _addEntity(etype,system,partInfo,key,shape):
    key += '.{}'.format(etype)
    h = partInfo.EntityMap.get(key,None)
    if h:
        logger.debug('cache {}: {}'.format(key,h))
        return h
    if etype == 'p': # point
        v = utils.getElementPos(shape)
        e = system.addPoint3dV(*v)
    elif etype == 'n': # normal
        v = utils.getElementNormal(shape)
        e = system.addNormal3dV(*v)
    else:
        raise RuntimeError('unknown entity type {}'.format(etype))
    h = system.addTransform(e,*partInfo.Params)
    logger.debug('{}: {},{}, {}'.format(key,h,e,v))
    partInfo.EntityMap[key] = h
    return h

def _p(system,partInfo,key,shape):
    'return a slvs handle of a transformed point derived from "shape"'
    if not system:
        if utils.hasCenter(shape):
            return
        return 'a vertex or circular edge/face'
    return _addEntity('p',system,partInfo,key,shape)

def _n(system,partInfo,key,shape):
    'return a slvs handle of a transformed normal derived from "shape"'
    if not system:
        if utils.isAxisOfPlane(shape):
            return
        return 'an edge or face with a surface normal'
    return _addEntity('n',system,partInfo,key,shape)

def _l(system,partInfo,key,shape,retAll=False):
    'return a pair of slvs handle of the end points of an edge in "shape"'
    if not system:
        if utils.isLinearEdge(shape):
            return
        return 'a linear edge'
    key += '.l'
    h = partInfo.EntityMap.get(key,None)
    if h:
        logger.debug('cache {}: {}'.format(key,h))
    else:
        v = shape.Edges[0].Vertexes
        p1 = system.addPoint3dV(*v[0].Point)
        p2 = system.addPoint3dV(*v[-1].Point)
        h = system.addLine(p1,p2)
        h = (h,p1,p2)
        logger.debug('{}: {}'.format(key,h))
        partInfo.EntityMap[key] = h
    return h if retAll else h[0]

def _w(system,partInfo,key,shape,retAll=False):
    'return a slvs handle of a transformed plane/workplane from "shape"'
    if not system:
        if utils.isAxisOfPlane(shape):
            return
        return 'an edge or face with a planar surface'

    key2 = key+'.w'
    h = partInfo.EntityMap.get(key2,None)
    if h:
        logger.debug('cache {}: {}'.format(key,h))
    else:
        p = _p(system,partInfo,key,shape)
        n = _n(system,partInfo,key,shape)
        h = system.addWorkplane(p,n)
        h = (h,p,n)
        logger.debug('{}: {}'.format(key,h))
        partInfo.EntityMap[key2] = h
    return h if retAll else h[0]

def _c(system,partInfo,key,shape,requireArc=False):
    'return a slvs handle of a transformed circle/arc derived from "shape"'
    if not system:
        r = utils.getElementCircular(shape)
        if not r or (requireArc and not isinstance(r,list,tuple)):
            return
        return 'an cicular arc edge' if requireArc else 'a circular edge'
    key2 = key+'.c'
    h = partInfo.EntityMap.get(key2,None)
    if h:
        logger.debug('cache {}: {}'.format(key,h))
    else:
        h = _w(system,partInfo,key,shape,True)
        r = utils.getElementCircular(shape)
        if not r:
            raise RuntimeError('shape is not cicular')
        if isinstance(r,(list,tuple)):
            l = _l(system,partInfo,key,shape,True)
            h += l[1:]
            h = system.addArcOfCircleV(*h)
        elif requireArc:
            raise RuntimeError('shape is not an arc')
        else:
            h = h[1:]
            h.append(system.addDistanceV(r))
            h = system.addCircle(*h)
        logger.debug('{}: {}, {}'.format(key,h,r))
        partInfo.EntityMap[key2] = h
    return h

def _a(system,partInfo,key,shape):
    return _c(system,partInfo,key,shape,True)


_PropertyDistance = ('Value','Distance','PropertyDistance','Constraint')
_PropertyAngle = ('Value','Angle','PropertyAngle','Constraint')
_PropertyRatio = (None,'Ratio','PropertyFloat','Constraint')
_PropertyDifference = (None,'Difference','PropertyFloat','Constraint')
_PropertyDiameter = (None,'Diameter','PropertyFloat','Constraint')
_PropertyRadius = (None,'Radius','PropertyFloat','Constraint')
_PropertySupplement = (None,'Supplement','PropertyBool','Constraint',
        'If True, then the second angle is calculated as 180-angle')
_PropertyAtEnd = (None,'AtEnd','PropertyBool','Constraint',
        'If True, then tangent at the end point, or else at the start point')

_ordinal = ['1st', '2nd', '3rd', '4th', '5th', '6th', '7th' ]

class Base:
    __metaclass__ = ConstraintType

    _id = -1
    _entities = []
    _workplane = False
    _props = []
    _func = None

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
    def getEntityDef(cls,group,checkCount,name=None):
        entities = cls._entities
        if len(group) != len(entities):
            if not checkCount and len(group)<len(entities):
                return entities[:len(group)]
            if cls._workplane and len(group)==len(entities)+1:
                entities = list(entities)
                entities.append(_w)
            else:
                if not name:
                    name = cls.getName()
                else:
                    name += ' of type "{}"'.format(cls.getName)
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
            if i == len(cls._entities):
                raise RuntimeError('Constraint {} requires the optional {} '
                    'element to be a planar face for defining a '
                    'workplane'.format(cls.getName(), _ordinal[i], msg))
            raise RuntimeError('Constraint {} requires the {} element to be'
                    ' {}'.format(cls.getName(), _ordinal[i], msg))

    def __init__(self,obj,_props):
        if obj._Type != self._id:
            if self._id < 0:
                raise RuntimeError('invalid constraint type {} id: '
                    '{}'.format(self.__class__,self._id))
            obj._Type = self._id
        for prop in self.__class__._props:
            obj.addProperty(*prop[1:])

    @classmethod
    def detach(cls,obj):
        for prop in cls._props:
            obj.removeProperty(prop[1])

    def onChanged(self,obj,prop):
        pass

    @classmethod
    def getEntities(cls,obj,solver):
        '''maps fcad element shape to slvs entities'''
        ret = []
        for prop in cls._props:
            v = getattr(obj,prop[1])
            if prop[0]:
                v = getattr(v,prop[0])()
            ret.append(v)

        elements = obj.Proxy.getElements()
        entities = cls.getEntityDef(elements,True,objName(obj))
        ret = []
        for e,o in zip(entities,elements):
            info = o.Proxy.getInfo()
            partInfo = solver.getPartInfo(info)
            ret.append(e(solver.system,partInfo,info.Subname,info.Shape))
        logger.debug('{}: {}, {}'.format(objName(obj),obj.Type,ret))
        return ret

    @classmethod
    def prepare(cls,obj,solver):
        e = cls.getEntities(obj,solver)
        cls._func(solver.system,*e,group=solver.group)


class Disabled(Base):
    _id = 0
    _func = True

    @classmethod
    def prepare(cls,_obj,_solver):
        pass


class PointsCoincident(Base):
    _id = 1
    _entities = (_p,_p)
    _workplane = True


class SameOrientation(Base):
    _id = 2
    _entities = (_n,_n)


class PointInPlane(Base):
    _id = 3
    _entities = (_p,_w)


class PointOnLine(Base):
    _id = 4
    _entities = (_p,_l)
    _workplane = True


class PointsDistance(Base):
    _id = 5
    _entities = (_p,_p)
    _workplane = True
    _props = [_PropertyDistance]


class PointsProjectDistance(Base):
    _id = 6
    _entities = (_p,_p,_l)
    _props = [_PropertyDistance]


class PointPlaneDistance(Base):
    _id = 7
    _entities = (_p,_w)
    _props = [_PropertyDistance]


class PointLineDistance(Base):
    _id = 8
    _entities = (_p,_l)
    _workplane = True
    _props = [_PropertyDistance]


class EqualLength(Base):
    _id = 9
    _entities = (_l,_l)
    _workplane = True


class LengthRatio(Base):
    _id = 10
    _entities = (_l,_l)
    _workplane = True
    _props = [_PropertyRatio]


class LengthDifference(Base):
    _id = 11
    _entities = (_l,_l)
    _workplane = True
    _props = [_PropertyDifference]


class EqualLengthPointLineDistance(Base):
    _id = 12
    _entities = (_p,_l,_l)
    _workplane = True


class EqualPointLineDistance(Base):
    _id = 13
    _entities = (_p,_l,_p,_l)
    _workplane = True


class EqualAngle(Base):
    _id = 14
    _entities = (_l,_l,_l,_l)
    _workplane = True
    _props = [_PropertySupplement]


class EqualLineArcLength(Base):
    _id = 15
    _entities = (_l,_a)
    _workplane = True


class Symmetric(Base):
    _id = 16
    _entities = (_p,_p,_w)
    _workplane = True


class SymmetricHorizontal(Base):
    _id = 17
    _entities = (_p,_p,_w)


class SymmetricVertical(Base):
    _id = 18
    _entities = (_p,_p,_w)


class SymmetricLine(Base):
    _id = 19
    _entities = (_p,_p,_l,_w)


class MidPoint(Base):
    _id = 20
    _entities = (_p,_p,_l)
    _workplane = True


class PointsHorizontal(Base):
    _id = 21
    _entities = (_p,_p)
    _workplane = True


class PointsVertical(Base):
    _id = 22
    _entities = (_p,_p)
    _workplane = True


class LineHorizontal(Base):
    _id = 23
    _entities = [_l]
    _workplane = True


class LineVertical(Base):
    _id = 24
    _entities = [_l]
    _workplane = True


class Diameter(Base):
    _id = 25
    _entities = [_c]
    _prop = [_PropertyDiameter]


class PointOnCircle(Base):
    _id = 26
    _entities = [_p,_c]


class Angle(Base):
    _id = 27
    _entities = (_l,_l)
    _workplane = True
    _props = [_PropertyAngle,_PropertySupplement]


class Perpendicular(Base):
    _id = 28
    _entities = (_l,_l)
    _workplane = True


class Parallel(Base):
    _id = 29
    _entities = (_l,_l)
    _workplane = True


class ArcLineTangent(Base):
    _id = 30
    _entities = (_c,_l)
    _props = [_PropertyAtEnd]


#  class CubicLineTangent(Base):
#      _id = 31
#
#
#  class CurvesTangent(Base):
#      _id = 32


class EqualRadius(Base):
    _id = 33
    _entities = (_c,_c)
    _props = [_PropertyRadius]


class WhereDragged(Base):
    _id = 34
    _entities = [_p]
    _workplane = True


TypeEnum = namedtuple('AsmConstraintEnum',
        (c.getName() for c in Types))(*range(len(Types)))

def attach(obj,checkType=True):
    props = None
    if checkType:
        props = obj.PropertiesList
        if not '_Type' in props:
            raise RuntimeError('Object "{}" has no _Type property'.format(
                objName(obj)))
        if 'Type' in props:
            raise RuntimeError('Object {} already as property "Type"'.format(
                objName(obj)))

        # The 'Type' property here is to let user select the type in property
        # editor. It is marked as 'transient' to avoid having to save the
        # enumeration value for each object.
        obj.addProperty("App::PropertyEnumeration","Type","Constraint",'',2)
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
        if cstr:
            cstr.detach(obj)
        if not props:
            props = obj.PropertiesList
        obj.Proxy._cstr = constraintType(obj,props)


def onChanged(obj,prop):
    if prop == 'Type':
        attach(obj,False)
        return
    elif prop == '_Type':
        obj.Type = TypeMap[obj._Type]._idx
        return
    cstr = getattr(obj.Proxy,'_cstr',None)
    if cstr:
        cstr.onChanged(obj,prop)


def check(tp,group):
    TypeMap[tp].check(group)

def prepare(cstr,solver):
    cstr.Proxy._cstr.prepare(cstr,solver)

