from collections import namedtuple
from asm3.utils import proxylogger as logger, objName

def propGet(self,obj):
    return getattr(obj,self.Name)

def propGetValue(self,obj):
    return getattr(getattr(obj,self.Name),'Value')

class PropertyInfo(object):
    'For holding information to create dynamic properties'

    def __init__(self,host,name,tp,doc='', enum=None,
            getter=propGet,group='Base',internal=False,duplicate=False):
        self.Name = name
        self.Type = tp
        self.Group = group
        self.Doc = doc
        self.Enum = enum
        self.get = getter.__get__(self,self.__class__)
        self.Internal = internal
        self.Key = host.addPropertyInfo(self,duplicate)

class ProxyType(type):
    '''
    Meta class for managing other "proxy" like classes whose instances can be
    dynamically attached to or detached from FCAD FeaturePython Proxy objects.
    In other word, it is meant for managing proxies of Proxies
    '''

    _typeID = '_ProxyType'
    _typeEnum = 'ProxyType'
    _propGroup = 'Base'
    _proxyName = '_proxy'
    _registry = {}

    Info = namedtuple('ProxyTypeInfo',
            ('Types','TypeMap','TypeNameMap','TypeNames','PropInfo'))

    @classmethod
    def getMetaName(mcs):
        return mcs.__name__

    @classmethod
    def getInfo(mcs):
        if not getattr(mcs,'_info',None):
            mcs._info = mcs.Info([],{},{},[],{})
            mcs._registry[mcs.getMetaName()] = mcs._info
        return mcs._info

    @classmethod
    def reload(mcs):
        info = mcs.getInfo()
        mcs._info = None
        for tp in info.Types:
            tp._idx = -1
            mcs.getInfo().Types.append(tp)
            mcs.register(tp)

    @classmethod
    def getType(mcs,tp):
        if isinstance(tp,basestring):
            return mcs.getInfo().TypeNameMap[tp]
        if not isinstance(tp,int):
            tp = mcs.getTypeID(tp)
        return mcs.getInfo().TypeMap[tp]

    @classmethod
    def getTypeID(mcs,obj):
        return getattr(obj,mcs._typeID,-1)

    @classmethod
    def setTypeID(mcs,obj,tp):
        setattr(obj,mcs._typeID,tp)

    @classmethod
    def getTypeName(mcs,obj):
        return getattr(obj,mcs._typeEnum,None)

    @classmethod
    def setTypeName(mcs,obj,tp):
        setattr(obj,mcs._typeEnum,tp)

    @classmethod
    def getProxy(mcs,obj):
        return getattr(obj.Proxy,mcs._proxyName,None)

    @classmethod
    def setProxy(mcs,obj):
        cls = mcs.getType(mcs.getTypeName(obj))
        proxy = mcs.getProxy(obj)
        if type(proxy) is not cls:
            logger.debug('attaching {}, {} -> {}'.format(
                objName(obj),type(proxy).__name__,cls.__name__),frame=1)
            if proxy:
                mcs.detach(obj)
            if mcs.getTypeID(obj) != cls._id:
                mcs.setTypeID(obj,cls._id)

            props = cls.getPropertyInfoList()
            if props:
                oprops = obj.PropertiesList
                for key in props:
                    prop = mcs.getPropertyInfo(key)
                    if prop.Name not in oprops:
                        obj.addProperty(prop.Type,prop.Name,prop.Group,prop.Doc)
                        if prop.Enum:
                            setattr(obj,prop.Name,prop.Enum)

            setattr(obj.Proxy,mcs._proxyName,cls(obj))
            obj.ViewObject.signalChangeIcon()
            return obj

    @classmethod
    def detach(mcs,obj,detachAll=False):
        proxy = mcs.getProxy(obj)
        if proxy:
            logger.debug('detaching {}<{}>'.format(objName(obj),
                proxy.__class__.__name__))
            for key in proxy.getPropertyInfoList():
                prop = mcs.getPropertyInfo(key)
                obj.removeProperty(prop.Name)
            callback = getattr(proxy,'onDetach',None)
            if callback:
                callback(obj)
            setattr(obj.Proxy,mcs._proxyName,None)

        if detachAll:
            obj.removeProperty(mcs._typeID)
            obj.removeProperty(mcs._typeEnum)

    @classmethod
    def setDefaultTypeID(mcs,obj,name=None):
        info = mcs.getInfo()
        if not name:
            name = info.TypeNames[0]
        mcs.setTypeID(obj,info.TypeNameMap[name]._id)

    @classmethod
    def attach(mcs,obj,checkType=True):
        info = mcs.getInfo()
        if not info.TypeNames:
            logger.error('"{}" has no registered types'.format(
                mcs.getMetaName()))
            return

        if checkType:
            if mcs._typeID not in obj.PropertiesList:
                obj.addProperty("App::PropertyInteger",
                        mcs._typeID,mcs._propGroup,'',0,False,True)
                mcs.setDefaultTypeID(obj)

            if mcs._typeEnum not in obj.PropertiesList:
                logger.debug('type enum {}, {}'.format(mcs._typeEnum,
                    mcs._propGroup))
                obj.addProperty("App::PropertyEnumeration",
                        mcs._typeEnum,mcs._propGroup,'',2)
            mcs.setTypeName(obj,info.TypeNames)

            idx = 0
            try:
                idx = mcs.getType(obj)._idx
            except KeyError:
                logger.warn('{} has unknown {} type {}'.format(
                    objName(obj),mcs.getMetaName(),mcs.getTypeID(obj)))
            mcs.setTypeName(obj,idx)

        return mcs.setProxy(obj)

    @classmethod
    def onChanged(mcs,obj,prop):
        if prop == mcs._typeEnum:
            if mcs.getProxy(obj):
                return mcs.attach(obj,False)
        elif prop == mcs._typeID:
            if mcs.getProxy(obj):
                cls = mcs.getType(mcs.getTypeID(obj))
                if mcs.getTypeName(obj)!=cls.getName():
                    mcs.setTypeName(obj,cls._idx)

    def __init__(cls, name, bases, attrs):
        super(ProxyType,cls).__init__(name,bases,attrs)
        mcs = cls.__class__
        mcs.register(cls)

    @classmethod
    def register(mcs,cls):
        '''
        Register a class to this meta class

        To make the registration automatic at the class definition time, simply
        set __metaclass__ of that class to ProxyType of its derived type. 

        It is defined as a meta class method in order for you to call this
        method directly to register an unrelated class
        '''
        cls._idx = -1
        mcs.getInfo().Types.append(cls)
        callback = getattr(cls,'onRegister',None)
        if callback:
            callback()
        if cls._id < 0:
            return
        info = mcs.getInfo()
        if cls._id in info.TypeMap:
            raise RuntimeError('Duplicate {} type id {}'.format(
                mcs.getMetaName(),cls._id))
        info.TypeMap[cls._id] = cls
        info.TypeNameMap[cls.getName()] = cls
        info.TypeNames.append(cls.getName())
        cls._idx = len(info.TypeNames)-1
        logger.trace('register {} "{}":{},{}'.format(
            mcs.getMetaName(),cls.getName(),cls._id,cls._idx))

    @classmethod
    def addPropertyInfo(mcs,info,duplicate):
        props = mcs.getInfo().PropInfo
        key = info.Name
        i = 1
        while key in props:
            if not duplicate:
                raise RuntimeError('Duplicate property "{}"'.format(info.Name))
            key = key+str(i)
            i = i+1
        props[key] = info
        return key

    @classmethod
    def getPropertyInfo(mcs,key):
        return mcs.getInfo().PropInfo[key]

    def getPropertyValues(cls,obj):
        props = []
        mcs = cls.__class__
        for key in cls.getPropertyInfoList():
            prop = mcs.getPropertyInfo(key)
            if not prop.Internal:
                props.append(prop.get(obj))
        return props

    def getPropertyInfoList(cls):
        return []

    def getName(cls):
        return cls.__name__

