import os
from .utils import getIcon, syslogger as logger, objName
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
            return proxy.getSystem(obj)

    @classmethod
    def isConstraintSupported(mcs,obj,cstrName):
        if cstrName == 'Locked':
            return True
        proxy = mcs.getProxy(obj)
        if proxy:
            return proxy.isConstraintSupported(cstrName)

def _makePropInfo(name,tp,doc=''):
    PropertyInfo(System,name,tp,doc,group='Solver')

_makePropInfo('Verbose','App::PropertyBool')

class SystemBase(object):
    __metaclass__ = System
    _id = 0
    _props = ['Verbose']

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

    def addSketchPlane(self,*args,**kargs):
        _ = kargs
        self.sketchPlane = args[0] if args else None
        return self.sketchPlane

    def addPlaneCoincident(self,d,lockAngle,angle,e1,e2,group=0):
        if not group:
            group = self.GroupHandle
        d = abs(d)
        _,p1,n1,nx1 = e1
        w2,p2,n2,nx2 = e2
        h = []
        if d>0.0:
            h.append(self.addPointPlaneDistance(d,p1,w2,group=group))
            h.append(self.addPointsCoincident(p1,p2,w2,group=group))
        else:
            h.append(self.addPointsCoincident(p1,p2,group=group))
        h.append(self.addParallel(n1,n2,group=group))
        if lockAngle:
            h.append(self.addAngle(angle,False,nx1,nx2,group=group))
        return h

    def addPlaneAlignment(self,d,lockAngle,angle,e1,e2,group=0):
        if not group:
            group = self.GroupHandle
        d = abs(d)
        _,p1,n1,nx1 = e1
        w2,_,n2,nx2 = e2
        h = []
        if d>0.0:
            h.append(self.addPointPlaneDistance(d,p1,w2,group=group))
        else:
            h.append(self.addPointInPlane(p1,w2,group=group))
        h.append(self.addParallel(n1,n2,group=group))
        if lockAngle:
            h.append(self.addAngle(angle,False,nx1,nx2,group=group))
        return h

    def addAxialAlignment(self,lockAngle,angle,e1,e2,group=0):
        if not group:
            group = self.GroupHandle
        _,p1,n1,nx1 = e1
        w2,p2,n2,nx2 = e2
        h = []
        h.append(self.addPointsCoincident(p1,p2,w2,group=group))
        h.append(self.addParallel(n1,n2,group=group))
        if lockAngle:
            h.append(self.addAngle(angle,False,nx1,nx2,group=group))
        return h

    def addMultiParallel(self,lockAngle,angle,e1,e2,group=0):
        h = []
        h.append(self.addParallel(e1,e2,group=group))
        if lockAngle:
            h.append(self.addAngle(angle,False,e1,e2,group=group))
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
