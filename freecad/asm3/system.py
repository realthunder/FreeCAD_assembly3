import os, sys
import FreeCAD
try:
    from six import with_metaclass
except ImportError:
    from .deps import with_metaclass
from .constraint import cstrName, PlaneInfo, NormalInfo
from .utils import getIcon, syslogger as logger, objName, project2D, getNormal
from .proxy import ProxyType, PropertyInfo

from FreeCAD import Qt
translate = Qt.translate
QT_TRANSLATE_NOOP = Qt.QT_TRANSLATE_NOOP

class System(ProxyType):
    'solver system meta class'

    _typeID = '_SolverType'
    _typeEnum = 'SolverType'
    _propGroup = 'Solver'
    _iconName = 'Assembly_Assembly_Tree.svg'

    @classmethod
    def setDefaultTypeID(mcs,obj,name=None):
        if not name:
            info = mcs.getInfo()
            idx = 1 if len(info.TypeNames)>1 else 0
            name = info.TypeNames[idx]
        super(System,mcs).setDefaultTypeID(obj,name)

    @classmethod
    def unknownType(mcs, _obj):
        if not 'freecad.asm3.sys_slvs' in sys.modules:
            from . import install_prompt
            install_prompt.check_slvs()
            try:
                from . import sys_slvs
                return True
            except ImportError as e:
                pass

    @classmethod
    def setTypeName(mcs,obj,tp):
        setattr(obj,mcs._typeEnum,tp)

    @classmethod
    def getIcon(mcs,obj):
        func = getattr(mcs.getProxy(obj),'getIcon',None)
        if func:
            icon = func(obj)
            if icon:
                return icon
        return getIcon(mcs,mcs.isDisabled(obj))

    @classmethod
    def isDisabled(mcs,obj):
        proxy = mcs.getProxy(obj)
        return not proxy or proxy.isDisabled(obj)

    @classmethod
    def isTouched(mcs,obj):
        proxy = mcs.getProxy(obj)
        return proxy and proxy.isTouched(obj)

    @classmethod
    def touch(mcs,obj,touched=True):
        proxy = mcs.getProxy(obj)
        if proxy:
            proxy.touch(obj,touched)

    @classmethod
    def onChanged(mcs,obj,prop):
        proxy = mcs.getProxy(obj)
        if proxy:
            proxy.onChanged(obj,prop)
        if super(System,mcs).onChanged(obj,prop):
            obj.Proxy.onSolverChanged()

    @classmethod
    def getSystem(mcs,obj):
        proxy = mcs.getProxy(obj)
        if proxy:
            system = proxy.getSystem(obj)
            if isinstance(system,SystemExtension):
                system.relax = obj.AutoRelax
            return system

    @classmethod
    def isConstraintSupported(mcs,obj,name):
        if name == 'Locked':
            return True
        proxy = mcs.getProxy(obj)
        if proxy:
            return proxy.isConstraintSupported(name)

def _makePropInfo(name,tp,doc='',default=None):
    PropertyInfo(System,name,tp,doc,group='Solver',default=default)

_makePropInfo('Verbose','App::PropertyBool')
_makePropInfo('AutoRelax','App::PropertyBool',default=True)

class SystemBase(with_metaclass(System, object)):
    _id = 0
    _props = ['Verbose','AutoRelax']

    def __init__(self,obj):
        self._touched = True
        self.verbose = obj.Verbose
        self.log = logger.info if self.verbose else logger.debug
        super(SystemBase,self).__init__()

    @classmethod
    def getPropertyInfoList(cls):
        return cls._props

    @classmethod
    def getName(cls):
        return 'None'

    def isConstraintSupported(self,_cstrName):
        return True

    def isDisabled(self,_obj):
        return True

    def isTouched(self,_obj):
        return getattr(self,'_touched',True)

    def touch(self,_obj,touched=True):
        self._touched = touched

    def onChanged(self,obj,prop):
        if prop == 'Verbose':
            self.verbose = obj.Verbose
            self.log = logger.info if obj.Verbose else logger.debug

def _cstrKey(cstrType, firstPart, secondPart):
    if firstPart > secondPart:
        return (cstrType, secondPart, firstPart)
    else:
        return (cstrType, firstPart, secondPart)

# For skipping invalid constraints
_DummyCstrList = [None] * 6

class SystemExtension(object):
    def __init__(self):
        super(SystemExtension,self).__init__()
        self.NameTag = ''
        self.sketchPlane = None
        self.cstrObj = None
        self.firstInfo = None
        self.secondInfo = None
        self.relax = False
        self.coincidences = {}
        self.cstrMap = {}
        self.elementCstrMap = {}
        self.elementMap = {}
        self.firstElement = None
        self.secondElement = None

    def checkRedundancy(self,obj,firstInfo,secondInfo,firstElement,secondElement):
        self.cstrObj,self.firstInfo,self.secondInfo=obj,firstInfo,secondInfo
        self.firstElement = firstElement
        self.secondElement = secondElement

    def addSketchPlane(self,*args,**kargs):
        _ = kargs
        self.sketchPlane = args[0] if args else None
        return self.sketchPlane

    def setOrientation(self,h,lockAngle,yaw,pitch,roll,n1,n2,group):
        if not lockAngle:
            h.append(self.addParallel(n1.entity,n2.entity,group=group))
            return h
        if not yaw and not pitch and not roll:
            n = n2.entity
        else:
            rot = n2.rot.multiply(FreeCAD.Rotation(yaw,pitch,roll))
            e = self.addNormal3dV(*getNormal(rot))
            n = self.addTransform(e,*n2.params,group=group)
        h.append(self.addSameOrientation(n1.entity,n,group=group))
        return h

    def reportRedundancy(self,firstPart=None,secondPart=None,count=0,limit=0,implicit=False):
        if implicit:
            logger.msg(translate('asm3', 'redundant implicit constraint {} between {} and {}, {}'),
                    cstrName(self.cstrObj),
                    firstPart if firstPart else self.firstInfo.PartName,
                    secondPart if secondPart else self.secondInfo.PartName,
                    count,
                    frame=1)
        elif count > limit:
            logger.warn(translate('asm3', 'skip redundant constraint {} between {} and {}, {}'),
                    cstrName(self.cstrObj),
                    firstPart if firstPart else self.firstInfo.PartName,
                    secondPart if secondPart else self.secondInfo.PartName,
                    count,
                    frame=1)
        else:
            logger.msg(translate('asm3', 'auto relax constraint {} between {} and {}, {}'),
                    cstrName(self.cstrObj),
                    firstPart if firstPart else self.firstInfo.PartName,
                    secondPart if secondPart else self.secondInfo.PartName,
                    count,
                    frame=1)

    def _populateConstraintMap(
            self,cstrType,firstElement,secondElement,increment,limit,item,implicit):

        firstPart = self.elementMap[firstElement]
        secondPart = self.elementMap[secondElement]
        if firstPart == secondPart:
            return _DummyCstrList

        # A constraint may contain elements belong to more than two parts.  For
        # example, for a constraint with elements from part A, B, C, we'll
        # expand it into two constraints for parts AB and AC. However, we must
        # also count the implicit constraint between B and C.
        #
        # self.cstrMap is a map for counting constraints of the same type
        # between pairs of parts. The count is used for checking redundancy and
        # auto relaxing. The map is keyed using
        #
        #       tuple(cstrType, firstPartName, secondPartName)
        #
        # and the value is a list. The item of this list is constraint defined
        # (e.g.  PlaineAilgnment stores a plane entity as item for auto
        # relaxing) , the length of this list is use as the constraint count to
        # be used later to decide how to auto relax the constraint.
        #
        # See the following link for difficulties on auto relaxing with implicit
        # constraints. Right now there is no search performed. So the auto relax
        # may fail. And the user is required to manually reorder constraints and
        # the elements within to help the solver.
        #
        # https://github.com/realthunder/FreeCAD_assembly3/issues/403#issuecomment-757400349

        key = _cstrKey(cstrType,firstPart,secondPart)
        cstrs = self.cstrMap.setdefault(key, [])
        cstrs += [item]*increment
        count = len(cstrs)
        if increment and count>=limit:
            self.reportRedundancy(firstPart, secondPart, count, limit, implicit)
        return cstrs

    def _countConstraints(self,increment,limit,cstrType,item=None):
        first, second = self.firstInfo, self.secondInfo
        if not first or not second:
            return []

        firstElement, secondElement = self.firstElement, self.secondElement

        if firstElement == secondElement:
            return _DummyCstrList

        self.elementMap[firstElement] = first.PartName
        self.elementMap[secondElement] = second.PartName

        # When counting implicit constraints (see comments in
        # _populateConstraintMap() above), we must also make sure to count them
        # if and only if they are originated from the same element, i.e.  both
        # AB and AC involving the same element of A. This will be true if the
        # those constraints are expanded by us, but may not be so if the user
        # created them.
        #
        # self.elementCstrMap is a map keyed using tuple(cstrType, elementName),
        # with value of a set of all element names that is involved with the the
        # same type of constraint. This set is shared by all element entries in
        # the map.

        firstSet = self.elementCstrMap.setdefault((cstrType, firstElement), set())
        if not firstSet:
            firstSet.add(firstElement)
        secondSet = self.elementCstrMap.setdefault((cstrType, secondElement),firstSet)

        res = _DummyCstrList

        if firstSet is not secondSet:
            # If the secondSet is different, we shall merge them, and count the
            # implicit constraints between the elements of first and second set.
            for element in secondSet:
                self.elementCstrMap[(cstrType, element)] = firstSet
                is_second = element == secondElement
                for e in firstSet:
                    implicit = not is_second or e != firstElement
                    cstrs = self._populateConstraintMap(
                        cstrType,e,element,increment,limit,item,implicit)
                    if not implicit:
                        # save the result (i.e. the explicit constraint pair of
                        # the give first and second element) for return
                        res = cstrs
            firstSet |= secondSet
        elif secondElement not in firstSet:
            # Here means the entry of the secondElement is newly created, count
            # the implicit constraints between all elements in the set to the
            # secondElement.
            for e in firstSet:
                implicit = e != firstElement
                cstrs = self._populateConstraintMap(
                    cstrType,e,secondElement,increment,limit,item,implicit)
                if not implicit:
                    res = cstrs
            firstSet.add(secondElement)

        if res is _DummyCstrList:
            self.reportRedundancy(count=len(res), limit=limit)
        return res

    def countConstraints(self,increment,limit,name):
        count = len(self._countConstraints(increment,limit,name))
        if count>limit:
            return -1
        return count

    def addPlaneCoincident(
            self, d, dx, dy, lockAngle, yaw, pitch, roll, pln1, pln2, group=0):
        if not group:
            group = self.GroupHandle
        h = []

        count=self.countConstraints(2 if lockAngle else 1,2,'Coincident')
        if count < 0:
            return

        if count == 1:
            self.coincidences[(self.firstInfo.Part, self.secondInfo.Part)] = pln1
            self.coincidences[(self.secondInfo.Part, self.firstInfo.Part)] = pln2

        if d or dx or dy:
            dx,dy,d = pln2.normal.rot.multVec(FreeCAD.Vector(dx,dy,d))
            v = pln2.origin.vector+FreeCAD.Vector(dx,dy,d)
            e = self.addTransform(
                    self.addPoint3dV(*v),*pln2.origin.params,group=group)
        else:
            v = pln2.origin.vector
            e = pln2.origin.entity

        if not lockAngle and count==2:
            # if there is already some other plane coincident constraint set for
            # this pair of parts, we reduce this second constraint to a 2D
            # PointOnLine. The line is formed by the first part's two elements
            # in the previous and the current constraint. The point is taken
            # from the element of the second part of the current constraint.
            # The projection plane is taken from the element of the first part
            # of the current constraint.
            #
            # This 2D PointOnLine effectively reduce the second PlaneCoincidence
            # constraining DOF down to 1.
            prev = self.coincidences.get(
                    (self.firstInfo.Part, self.secondInfo.Part))
            ln = self.addLineSegment(prev.origin.entity,
                    pln1.origin.entity, group=self.firstInfo.Group)
            h.append(self.addPointOnLine(
                pln2.origin.entity, ln, pln1.entity, group=group))
            return h

        h.append(self.addPointsCoincident(pln1.origin.entity, e, group=group))

        return self.setOrientation(h, lockAngle, yaw, pitch, roll,
                                   pln1.normal, pln2.normal, group)

    def addAttachment(self, pln1, pln2, group=0):
        return self.addPlaneCoincident(0,0,0,True,0,0,0, pln1, pln2, group)

    def addPlaneAlignment(self,d,lockAngle,yaw,pitch,roll,pln1,pln2,group=0):
        if not group:
            group = self.GroupHandle
        h = []
        if self.relax:
            dof = 2 if lockAngle else 1
            cstrs = self._countConstraints(dof,3,'Alignment',item=pln1.entity)
            count = len(cstrs)
            if count > 3:
                return
        else:
            count = 0

        if d:
            h.append(self.addPointPlaneDistance(
                d, pln2.origin.entity, pln1.entity, group=group))
        else:
            h.append(self.addPointInPlane(
                pln2.origin.entity, pln1.entity,group=group))
        if count<=2:
            n1,n2 = pln1.normal,pln2.normal
            if count==2 and not lockAngle:
                self.reportRedundancy(count=count, limit=count)
                h.append(self.addParallel(n2.entity,n1.entity,cstrs[0],group))
            else:
                self.setOrientation(h,lockAngle,yaw,pitch,roll,n1,n2,group)
        return h

    def addAxialAlignment(self,lockAngle,yaw,pitch,roll,ln1,ln2,group=0):
        if not group:
            group = self.GroupHandle
        h = []
        if not isinstance(ln1,NormalInfo):
            if not isinstance(ln2,NormalInfo):
                lockAngle = False
            else:
                ln1,ln2 = ln2,ln1

        count = self.countConstraints(2 if lockAngle else 1,2,'Axial')
        if count < 0:
            return
        relax = count==2 and not lockAngle
        if isinstance(ln2,NormalInfo):
            ln = ln2.ln
            if not relax:
                h = self.setOrientation(
                        h,lockAngle,yaw,pitch,roll,ln1,ln2,group)
        else:
            ln = ln2.entity
            if not relax:
                h.append(self.addParallel(ln1.entity,ln,group=group))
        h.append(self.addPointOnLine(ln1.p0,ln,group=group))
        return h

    def addMultiParallel(self,lockAngle,yaw,pitch,raw,e1,e2,group=0):
        if not group:
            group = self.GroupHandle
        h = []
        isPlane = isinstance(e1,PlaneInfo),isinstance(e2,PlaneInfo)
        if all(isPlane):
            return self.setOrientation(h, lockAngle, yaw, pitch, raw,
                                       e1.normal, e2.normal, group);
        if not any(isPlane):
            h.append(self.addParallel(e1, e2, group=group))
        elif isPlane[0]:
            h.append(self.addPerpendicular(e1.normal.entity, e2, group=group))
        else:
            h.append(self.addPerpendicular(e1, e2.normal.entity, group=group))
        return h

    def addColinear(self,l1,l2,wrkpln=0,group=0):
        h = []
        if isinstance(l1,NormalInfo):
            pt = l1.p0
            l1 = l1.ln
        else:
            pt = l1.p0
            l1 = l1.entity
        if isinstance(l2,NormalInfo):
            l2 = l2.ln
        else:
            l2 = l2.entity
        h.append(self.addParallel(l1,l2,wrkpln=wrkpln,group=group))
        h.append(self.addPointOnLine(pt,l2,wrkpln=wrkpln,group=group))
        return h

    def addPlacement(self,pla,group=0):
        q = pla.Rotation.Q
        base = pla.Base
        nameTagSave = self.NameTag
        nameTag = nameTagSave+'.' if nameTagSave else 'pla.'
        ret = []
        for n,v in (('x',base.x),('y',base.y),('z',base.z),
                ('qw',q[3]),('qx',q[0]),('qy',q[1]),('qz',q[2])):
            self.NameTag = nameTag+n
            ret.append(self.addParamV(v,group))
        self.NameTag = nameTagSave
        return ret
