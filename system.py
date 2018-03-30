import os
from .constraint import cstrName
from .utils import getIcon, syslogger as logger, objName, project2D
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
_makePropInfo('AutoRelax','App::PropertyBool')

class SystemBase(object):
    __metaclass__ = System
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

    def setOrientation(self,h,lockAngle,angle,n1,n2,nx1,nx2,group):
        if lockAngle and not angle:
            h.append(self.addSameOrientation(n1,n2,group=group))
        else:
            h.append(self.addParallel(n1,n2,group=group))
            if lockAngle:
                h.append(self.addAngle(angle,False,nx1,nx2,group=group))
        return h

    def reportRedundancy(self,warn=False):
        msg = '{} between {} and {}'.format(cstrName(self.cstrObj),
                self.firstInfo.PartName, self.secondInfo.PartName)
        if warn:
            logger.warn('skip redundant ' + msg)
        else:
            logger.info('auto relax ' + msg)

    def countConstraints(self,increment,count,*names):
        first,second = self.firstInfo,self.secondInfo
        if not first or not second:
            return
        ret = 0
        for name in names:
            cstrs = first.CstrMap.get(second.Part,{}).get(name,None)
            if not cstrs:
                if increment:
                    cstrs = second.CstrMap.setdefault(
                                first.Part,{}).setdefault(name,[])
                else:
                    cstrs = second.CstrMap.get(first.Part,{}).get(name,[])
            if increment:
                cstrs += [None]*increment
            ret += len(cstrs)
            if count and ret >= count:
                if ret>count:
                    self.reportRedundancy(True)
                    return -1
                else:
                    self.reportRedundancy()
        return ret

    def addPlaneCoincident(self,d,lockAngle,angle,e1,e2,group=0):
        if not group:
            group = self.GroupHandle
        w1,p1,n1 = e1[:3]
        _,p2,n2 = e2[:3]
        n1,nx1 = n1[:2]
        n2,nx2 = n2[:2]
        h = []
        count = self.countConstraints(2 if lockAngle else 1,2,'Coincident')
        if count<0:
            return
        if not lockAngle and count==2:
            # if there is already some other plane coincident constraint set for
            # this pair of parts, we reduce this second constraint to either a
            # points horizontal or vertical constraint, i.e. reduce the
            # constraining DOF down to 1.
            #
            # We project the initial points to the first element plane, and
            # check for differences in x and y components of the points to
            # determine whether to use horizontal or vertical constraint.
            v1,v2 = project2D(self.firstInfo.EntityMap[n1][0],
                              self.firstInfo.EntityMap[p1][0],
                              self.secondInfo.EntityMap[p2][0])
            if abs(v1.x-v2.x) < abs(v1.y-v2.y):
                h.append(self.addPointsHorizontal(p1,p2,w1,group=group))
            else:
                h.append(self.addPointsVertical(p1,p2,w1,group=group))
            return h
        if d:
            h.append(self.addPointPlaneDistance(d,p2,w1,group=group))
            h.append(self.addPointsCoincident(p1,p2,w1,group=group))
        else:
            h.append(self.addPointsCoincident(p1,p2,group=group))
        return self.setOrientation(h,lockAngle,angle,n1,n2,nx1,nx2,group)

    def addPlaneAlignment(self,d,lockAngle,angle,e1,e2,group=0):
        if not group:
            group = self.GroupHandle
        w1,_,n1 = e1[:4]
        _,p2,n2 = e2[:4]
        n1,nx1 = n1[:2]
        n2,nx2 = n2[:2]
        h = []
        if self.relax:
            count = self.countConstraints(2 if lockAngle else 1,3,'Alignment')
            if count<0:
                return
        else:
            count = 0
        if d:
            h.append(self.addPointPlaneDistance(d,p2,w1,group=group))
        else:
            h.append(self.addPointInPlane(p2,w1,group=group))
        if count<=2:
            if count==2 and not lockAngle:
                self.reportRedundancy()
            h.append(self.setOrientation(h,lockAngle,angle,n1,n2,nx1,nx2,group))
        return h

    def addAxialAlignment(self,lockAngle,angle,e1,e2,group=0):
        if not group:
            group = self.GroupHandle
        count = self.countConstraints(0,2,'Coincident')
        if count<0:
            return
        if count:
            return self.addPlaneCoincident(False,0,e1,e2,group)
        w1,p1,n1 = e1[:3]
        _,p2,n2 = e2[:3]
        n1,nx1 = n1[:2]
        n2,nx2 = n2[:2]
        h = []
        h.append(self.addPointsCoincident(p1,p2,w1,group=group))
        return self.setOrientation(h,lockAngle,angle,n1,n2,nx1,nx2,group)

    def addMultiParallel(self,lockAngle,angle,e1,e2,group=0):
        h = []
        isPlane = isinstance(e1,list),isinstance(e2,list)
        if all(isPlane):
            return self.setOrientation(
                    h,lockAngle,angle,e1[2],e2[2],e1[3],e2[3],group);
        if not any(isPlane):
            h.append(self.addParallel(e1,e2,group=group))
        elif isPlane[0]:
            h.append(self.addPerpendicular(e1[2],e2,group=group))
        else:
            h.append(self.addPerpendicular(e1,e2[2],group=group))
        return h

    def addColinear(self,e1,e2,wrkpln=0,group=0):
        h = []
        h.append(self.addParallel(e1[0],e2,wrkpln=wrkpln,group=group))
        h.append(self.addPointOnLine(e1[1],e2,wrkpln=wrkpln,group=group))
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
