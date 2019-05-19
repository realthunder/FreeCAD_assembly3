import os
import FreeCAD
from .deps import with_metaclass
from .constraint import cstrName, PlaneInfo, NormalInfo
from .utils import getIcon, syslogger as logger, objName, project2D, getNormal
from .proxy import ProxyType, PropertyInfo

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


class SystemExtension(object):
    def __init__(self):
        super(SystemExtension,self).__init__()
        self.NameTag = ''
        self.sketchPlane = None
        self.cstrObj = None
        self.firstInfo = None
        self.secondInfo = None
        self.relax = False

    def checkRedundancy(self,obj,firstInfo,secondInfo):
        self.cstrObj,self.firstInfo,self.secondInfo=obj,firstInfo,secondInfo

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

    def reportRedundancy(self,warn=False):
        msg = '{} between {} and {}'.format(cstrName(self.cstrObj),
                self.firstInfo.PartName, self.secondInfo.PartName)
        if warn:
            logger.warn('skip redundant {}', msg, frame=1)
        else:
            logger.debug('auto relax {}', msg, frame=1)

    def _countConstraints(self,increment,limit,*names):
        first,second = self.firstInfo,self.secondInfo
        if not first or not second:
            return []
        for name in names:
            cstrs = first.CstrMap.get(second.Part,{}).get(name,None)
            if not cstrs:
                if increment:
                    cstrs = second.CstrMap.setdefault(
                                first.Part,{}).setdefault(name,[])
                else:
                    cstrs = second.CstrMap.get(first.Part,{}).get(name,[])
            cstrs += [None]*increment
            count = len(cstrs)
            if limit and count>=limit:
                self.reportRedundancy(count>limit)
        return cstrs

    def countConstraints(self,increment,limit,*names):
        count = len(self._countConstraints(increment,limit,*names))
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
            # this pair of parts, we reduce this second constraint to either a
            # points horizontal or vertical constraint, i.e. reduce the
            # constraining DOF down to 1.
            #
            # We project the initial points to the first element plane, and
            # check for differences in x and y components of the points to
            # determine whether to use horizontal or vertical constraint.
            rot = pln1.normal.pla.Rotation.multiply(pln1.normal.rot)
            v1 = pln1.normal.pla.multVec(pln1.origin.vector)
            v2 = pln2.normal.pla.multVec(v)
            v1,v2 = project2D(rot, v1, v2)
            if abs(v1.x-v2.x) < abs(v1.y-v2.y):
                h.append(self.addPointsHorizontal(
                    pln1.origin.entity, e, pln1.entity, group=group))
            else:
                h.append(self.addPointsVertical(
                    pln1.origin.entity, e, pln1.entity, group=group))
            return h

        h.append(self.addPointsCoincident(pln1.origin.entity, e, group=group))

        return self.setOrientation(h, lockAngle, yaw, pitch, roll,
                                   pln1.normal, pln2.normal, group)

    def addAttachment(self, pln1, pln2, group=0):
        return self.addPlaneCoincident(0,0,0,False,0,0,0, pln1, pln2, group)

    def addPlaneAlignment(self,d,lockAngle,yaw,pitch,roll,pln1,pln2,group=0):
        if not group:
            group = self.GroupHandle
        h = []
        if self.relax:
            dof = 2 if lockAngle else 1
            cstrs = self._countConstraints(dof,3,'Alignment')
            count = len(cstrs)
            if count > 3:
                return
            if count == 1:
                cstrs[0] = pln1.entity
        else:
            count = 0
            cstrs = None

        if d:
            h.append(self.addPointPlaneDistance(
                d, pln2.origin.entity, pln1.entity, group=group))
        else:
            h.append(self.addPointInPlane(
                pln2.origin.entity, pln1.entity,group=group))
        if count<=2:
            n1,n2 = pln1.normal,pln2.normal
            if count==2 and not lockAngle:
                self.reportRedundancy()
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
