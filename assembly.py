import os
from collections import namedtuple,defaultdict
import FreeCAD, FreeCADGui, Part
from PySide import QtCore, QtGui
from . import utils, gui
from .utils import mainlogger as logger, objName
from .constraint import Constraint, cstrName
from .system import System

def isTypeOf(obj,tp,resolve=False):
    if not obj:
        return False
    if not tp:
        return True
    if resolve:
        obj = obj.getLinkedObject(True)
    return isinstance(getattr(obj,'Proxy',None),tp)

def checkType(obj,tp,resolve=False):
    if not isTypeOf(obj,tp,resolve):
        raise TypeError('Expect object {} to be of type "{}"'.format(
                objName(obj),tp.__name__))

def getProxy(obj,tp):
    checkType(obj,tp)
    return obj.Proxy

def getLinkProperty(obj,name,default=None,writable=False):
    try:
        #  obj = obj.getLinkedObject(True)
        if not writable:
            return obj.getLinkExtProperty(name)
        name = obj.getLinkExtPropertyName(name)
        if 'Immutable' in obj.getPropertyStatus(name):
            return default
        return getattr(obj,name)
    except Exception:
        return default

def setLinkProperty(obj,name,val):
    #  obj = obj.getLinkedObject(True)
    setattr(obj,obj.getLinkExtPropertyName(name),val)

def flattenSubname(obj,subname):
    '''
    Falttern any AsmPlainGroups inside subname path. Only the first encountered
    assembly along the subname path is considered
    '''

    func = getattr(obj,'flattenSubname',None)
    if not func:
        return subname
    return func(subname)

def flattenLastSubname(obj,subname,last=None):
    '''
    Falttern any AsmPlainGroups inside subname path. Only the last encountered
    assembly along the subname path is considered
    '''
    if not last:
        last = Assembly.find(obj,subname,
                relativeToChild=True,recursive=True)[-1]
    return subname[:-len(last.Subname)] \
            + flattenSubname(last.Object,last.Subname)

def expandSubname(obj,subname):
    func = getattr(obj,'expandSubname',None)
    if not func:
        return subname
    return func(subname)

def flattenGroup(obj):
    group = getattr(obj,'LinkedChildren',None)
    if group is None:
        return obj.Group
    return group

def editGroup(obj,children,notouch=None):
    change = None
    if 'Immutable' in obj.getPropertyStatus('Group'):
        change = '-Immutable'
        revert = 'Immutable'

    parent = getattr(obj,'_Parent',None)
    if parent and 'Touched' in parent.State:
        parent = None

    if not hasattr(obj,'NoTouch'):
        notouch = False
    elif notouch is None:
        if (isTypeOf(parent,AsmConstraintGroup) or \
                isTypeOf(obj,AsmConstraintGroup)):
            # the order inside constraint group actually matters, so do not
            # engage no touch
            parent = None
        else:
            notouch = not obj.NoTouch

    if notouch:
        obj.NoTouch = True
    block = gui.AsmCmdManager.AutoRecompute
    if block:
        gui.AsmCmdManager.AutoRecompute = False
    try:
        if change:
            obj.setPropertyStatus('Group',change)
        obj.Group = children
    finally:
        if change:
            obj.setPropertyStatus('Group',revert)
        if block:
            gui.AsmCmdManager.AutoRecompute = True
        if notouch:
            obj.NoTouch = False
        if parent:
            parent.purgeTouched()

def setupSortMenu(menu,func,func2):
    action = QtGui.QAction(QtGui.QIcon(),"Sort A~Z",menu)
    QtCore.QObject.connect(action,QtCore.SIGNAL("triggered()"),func)
    menu.addAction(action)
    action = QtGui.QAction(QtGui.QIcon(),"Sort Z~A",menu)
    QtCore.QObject.connect(
            action,QtCore.SIGNAL("triggered()"),func2)
    menu.addAction(action)

def sortChildren(obj,reverse):
    group = [ (o,o.Label) for o in obj.Group ]
    group = sorted(group,reverse=reverse,key=lambda x:x[1])
    touched = 'Touched' in obj.State
    FreeCAD.setActiveTransaction('Sort children')
    try:
        editGroup(obj, [o[0] for o in group])
        FreeCAD.closeActiveTransaction()
    except Exception:
        FreeCAD.closeActiveTransaction(True)
        raise
    if not touched:
        obj.purgeTouched()

def resolveAssembly(obj):
    '''Try various ways to obtain an assembly from the input object

    obj can be a link, a proxy, a child group of an assembly, or simply an
    assembly
    '''
    func = getattr(obj,'getLinkedObject',None)
    if func:
        obj = func(True)
    proxy = getattr(obj,'Proxy',None)
    if proxy:
        obj = proxy
    if isinstance(obj,Assembly):
        return obj
    func = getattr(obj,'getAssembly',None)
    if func:
        return func()
    raise TypeError('cannot resolve assembly from {}'.format(obj))


# For faking selection obtained from Gui.getSelectionEx()
Selection = namedtuple('AsmSelection',('Object','SubElementNames'))

_IgnoredProperties = set(['VisibilityList','Visibility',
    'Label','_LinkRecomputed'])

class AsmBase(object):
    def __init__(self):
        self.Object = None

    def __getstate__(self):
        return

    def __setstate__(self,_state):
        return

    def attach(self,obj):
        obj.addExtension('App::LinkBaseExtensionPython', None)
        self.linkSetup(obj)

    def linkSetup(self,obj):
        assert getattr(obj,'Proxy',None)==self
        self.Object = obj
        return

    def getViewProviderName(self,_obj):
        return 'Gui::ViewProviderLinkPython'

    def onDocumentRestored(self, obj):
        self.linkSetup(obj)


class ViewProviderAsmBase(object):
    def __init__(self,vobj):
        vobj.Visibility = False
        vobj.Proxy = self
        self.attach(vobj)

    def replaceObject(self,_new,_old):
        return False

    def canAddToSceneGraph(self):
        return False

    def attach(self,vobj):
        if hasattr(self,'ViewObject'):
            return
        self.ViewObject = vobj
        vobj.signalChangeIcon()
        vobj.setPropertyStatus('Visibility','Hidden')

    def __getstate__(self):
        return None

    def __setstate__(self, _state):
        return None

    _iconName = None

    @classmethod
    def getIcon(cls):
        if cls._iconName:
            return utils.getIcon(cls)

    def canDropObjects(self):
        return True

    def canDragObjects(self):
        return False

    def canDragAndDropObject(self,_obj):
        return False


class ViewProviderAsmOnTop(ViewProviderAsmBase):
    def __init__(self,vobj):
        vobj.OnTopWhenSelected = 2
        super(ViewProviderAsmOnTop,self).__init__(vobj)


class AsmGroup(AsmBase):
    def linkSetup(self,obj):
        super(AsmGroup,self).linkSetup(obj)
        obj.configLinkProperty(
                'VisibilityList',LinkMode='GroupMode',ElementList='Group')
        self.groupSetup()

    def groupSetup(self):
        self.Object.setPropertyStatus('GroupMode','-Immutable')
        self.Object.GroupMode = 1 # auto delete children
        self.Object.setPropertyStatus('GroupMode',
                    ('Hidden','Immutable','Transient'))
        self.Object.setPropertyStatus('Group',('Hidden','Immutable'))
        # 'PartialTrigger' is just for silencing warning when partial load
        self.Object.setPropertyStatus('VisibilityList',
                ('Output','PartialTrigger','NoModify'))

    def attach(self,obj):
        obj.addProperty("App::PropertyLinkList","Group","Base",'')
        obj.addProperty("App::PropertyBoolList","VisibilityList","Base",'')
        obj.addProperty("App::PropertyEnumeration","GroupMode","Base",'')
        super(AsmGroup,self).attach(obj)


class ViewProviderAsmGroup(ViewProviderAsmBase):
    def claimChildren(self):
        return self.ViewObject.Object.Group

    def doubleClicked(self, _vobj):
        return False

    def canDropObject(self,_child):
        return False


class ViewProviderAsmGroupOnTop(ViewProviderAsmGroup):
    def __init__(self,vobj):
        vobj.OnTopWhenSelected = 2
        super(ViewProviderAsmGroupOnTop,self).__init__(vobj)


class AsmPartGroup(AsmGroup):
    def __init__(self,parent):
        self.parent = getProxy(parent,Assembly)
        self.derivedParts = None
        super(AsmPartGroup,self).__init__()

    def getSubObjects(self,obj,_reason):
        # Deletion order problem may cause exception here. Just silence it
        try:
            return [ '{}.'.format(o.Name) for o in flattenGroup(obj) ]
        except Exception:
            pass

    def linkSetup(self,obj):
        super(AsmPartGroup,self).linkSetup(obj)
        if not hasattr(obj,'DerivedFrom'):
            obj.addProperty('App::PropertyLink','DerivedFrom','Base','')
        self.derivedParts = None

    def checkDerivedParts(self):
        if self.getAssembly().Object.Freeze:
            return

        obj = self.Object
        if not isTypeOf(obj.DerivedFrom,Assembly,True):
            self.derivedParts = None
            return

        parts = set(obj.LinkedObject)
        derived = obj.DerivedFrom.getLinkedObject(True).Proxy.getPartGroup()
        self.derivedParts = derived.LinkedObject
        newParts = obj.Group
        vis = list(obj.VisibilityList)
        touched = False
        for o in self.derivedParts:
            if o in parts:
                continue
            touched = True
            newParts.append(o)
            vis.append(True if derived.isElementVisible(o.Name) else False)
        if touched:
            obj.Group = newParts
            obj.setPropertyStatus('VisibilityList','-Immutable')
            obj.VisibilityList = vis
            obj.setPropertyStatus('VisibilityList','Immutable')

    def getAssembly(self):
        return self.parent

    def groupSetup(self):
        pass

    def canLoadPartial(self,_obj):
        return 1 if self.getAssembly().frozen else 0

    def onChanged(self,obj,prop):
        if obj.Removing or FreeCAD.isRestoring() :
            return
        if obj.Document and getattr(obj.Document,'Transacting',False):
            return
        if prop == 'DerivedFrom':
            self.checkDerivedParts()
        elif prop in ('Group','_ChildCache'):
            parent = getattr(self,'parent',None)
            if parent and not self.parent.Object.Freeze:
                relationGroup = parent.getRelationGroup()
                if relationGroup:
                    relationGroup.Proxy.getRelations(True)

    @staticmethod
    def make(parent,name='Parts'):
        obj = parent.Document.addObject("Part::FeaturePython",name,
                    AsmPartGroup(parent),None,True)
        obj.setPropertyStatus('Placement',('Output','Hidden'))
        obj.setPropertyStatus('Shape','Output')
        ViewProviderAsmPartGroup(obj.ViewObject)
        obj.purgeTouched()
        return obj


class ViewProviderAsmPartGroup(ViewProviderAsmGroup):
    _iconName = 'Assembly_Assembly_Part_Tree.svg'

    def replaceObject(self,new,old):
        return self.Object.replaceObject(new,old)

    def canDropObjectEx(self,obj,_owner,_subname,_elements):
        return isTypeOf(obj,Assembly, True) or not isTypeOf(obj,AsmBase)

    def dropObjectEx(self,vobj,obj,_owner,_subname,_elements):
        me = vobj.Object
        if AsmPlainGroup.tryMove(obj,me):
            return obj.Name+'.'
        me.setLink({-1:obj})
        return me.Group[-1].Name + '.'

    def _drop(self,obj,owner,subname,elements):
        me = self.ViewObject.Object
        group = me.Group
        self.ViewObject.dropObject(obj,owner,subname,elements)
        return [ o for o in me.Group if o not in group ]

    def canDragObject(self,_obj):
        return True

    def canDragObjects(self):
        return True

    def canDragAndDropObject(self,obj):
        return not AsmPlainGroup.contains(self.ViewObject.Object,obj)

    def onDelete(self,_vobj,_subs):
        return False

    def canDelete(self,_obj):
        return True

    def showParts(self):
        vobj = self.ViewObject
        obj = vobj.Object
        if not obj.isDerivedFrom('Part::FeaturePython'):
            return
        assembly = obj.Proxy.getAssembly().Object
        if not assembly.ViewObject.ShowParts and \
           (assembly.Freeze or (assembly.BuildShape!=BuildShapeNone and \
                                assembly.BuildShape!=BuildShapeCompound)):
            mode = 1
        else:
            mode = 0
        if not vobj.ChildViewProvider:
            if not mode:
                return
            vobj.ChildViewProvider = 'PartGui::ViewProviderPartExt'
            cvp = vobj.ChildViewProvider
            if not cvp.MapTransparency:
                cvp.MapTransparency = True
            if not cvp.MapFaceColor:
                cvp.MapFaceColor = True
            cvp.ForceMapColors = True
        vobj.DefaultMode = mode

    def replaceObject(self,oldObj,newObj):
        res = self.ViewObject.replaceObject(oldObj,newObj)
        if res<=0:
            return res
        for obj in oldObj.InList:
            if isTypeOf(obj,AsmElement):
                link = obj.LinkedObject
                if isinstance(link,tuple):
                    obj.setLink(newObj,link[1])
                else:
                    obj.setLink(newObj)
        return 1


class AsmVersion(object):
    def __init__(self,v=None):
        self.value = 0
        self.childVersion = v
        self._childVersion = v
        self.updated = False

    def update(self,v):
        self.updated = False
        if self.childVersion!=v:
            self._childVersion = v
            self.updated = True
            return True
        return not gui.AsmCmdManager.SmartRecompute

    def commit(self):
        if self.updated:
            self.childVersion = self._childVersion
            self.value += 1
            self.updated = False


class AsmElement(AsmBase):
    def __init__(self,parent):
        self.version = None
        self._initializing = True
        self.parent = getProxy(parent,AsmElementGroup)
        super(AsmElement,self).__init__()

    #  def getLinkedObject(self,*_args):
    #      pass

    def linkSetup(self,obj):
        super(AsmElement,self).linkSetup(obj)
        if not hasattr(obj,'Offset'):
            obj.addProperty("App::PropertyPlacement","Offset"," Link",'')
        if not hasattr(obj,'Placement'):
            obj.addProperty("App::PropertyPlacement","Placement"," Link",'')
        obj.setPropertyStatus('Placement','Hidden')
        if not hasattr(obj,'LinkTransform'):
            obj.addProperty("App::PropertyBool","LinkTransform"," Link",'')
            obj.LinkTransform = True
        if not hasattr(obj,'Detach'):
            obj.addProperty('App::PropertyBool','Detach', ' Link','')
        obj.setPropertyStatus('LinkTransform',['Immutable','Hidden'])
        obj.setPropertyStatus('LinkedObject','ReadOnly')
        obj.configLinkProperty('LinkedObject','Placement','LinkTransform')

        parent = getattr(obj,'_Parent',None)
        if parent:
            self.parent = parent.Proxy

        AsmElement.migrate(obj)

        self.version = AsmVersion()

    def canLoadPartial(self,_obj):
        return 1 if self.getAssembly().frozen else 0

    @staticmethod
    def migrate(obj):
        # To avoid over dependency, we no longer link to PartGroup, but to the
        # child part object directly
        link = obj.LinkedObject
        if not isinstance(link,tuple):
            return
        if isTypeOf(link[0],AsmPartGroup):
            logger.debug('migrate {}',objName(obj))
            sub = link[1]
            dot = sub.find('.')
            sobj = link[0].getSubObject(sub[:dot+1],1)
            touched = 'Touched' in obj.State
            obj.setLink(sobj,sub[dot+1:])
            if not touched:
                obj.purgeTouched()

    def attach(self,obj):
        obj.addProperty("App::PropertyXLink","LinkedObject"," Link",'')
        obj.addProperty("App::PropertyLinkHidden","_Parent"," Link",'')
        obj._Parent = self.parent.Object
        obj.setPropertyStatus('_Parent',('Hidden','Immutable'))
        super(AsmElement,self).attach(obj)

    def getViewProviderName(self,_obj):
        return ''

    def canLinkProperties(self,_obj):
        return False

    def allowDuplicateLabel(self,_obj):
        return True

    def onBeforeChangeLabel(self,obj,label):
        parent = getattr(self,'parent',None)
        if parent and not getattr(self,'_initializing',False):
            return parent.onChildLabelChange(obj,label)

    def autoName(self,obj):
        oldLabel = getattr(obj,'OldLabel',None)
        for link in FreeCAD.getLinksTo(obj,False):
            if isTypeOf(link,AsmElementLink):
                link.Label = obj.Label
            elif isTypeOf(link,AsmElement):
                if link.Label == link.Name:
                    if link.Label.startswith('_') and \
                       not obj.Label.startswith('_'):
                        link.Label = '_' + obj.Label
                    else:
                        link.Label = obj.Label
                    continue

                if not oldLabel:
                    continue

                if link.Label.startswith(oldLabel):
                    prefix = obj.Label
                    postfix = link.Label[len(oldLabel):]
                elif link.Label.startswith('_'+oldLabel):
                    prefix = '_' + obj.Label
                    postfix = link.Label[len(oldLabel)+1:]
                else:
                    continue
                try:
                    int(postfix)
                    # ignore all digits postfix
                    link.Label = prefix
                except Exception:
                    link.Label = prefix + postfix

    def onChanged(self,obj,prop):
        parent = getattr(self,'parent',None)
        if not parent or obj.Removing or FreeCAD.isRestoring():
            return
        if obj.Document and getattr(obj.Document,'Transacting',False):
            if prop == 'Label':
                parent.Object.cacheChildLabel()
            return
        if prop=='Offset':
            self.updatePlacement()
            return
        elif prop == 'Label':
            self.autoName(obj)
            # have to call cacheChildLabel() later, because those label
            # referenced links is only auto corrected after onChanged()
            parent.Object.cacheChildLabel()

        if prop not in _IgnoredProperties and \
           not Constraint.isDisabled(parent.Object):
            Assembly.autoSolve(obj,prop)

    def execute(self,obj):
        if not obj.isDerivedFrom('Part::FeaturePython'):
            self.version.value += 1
            return False

        if obj.Detach:
            self.updatePlacement()
            return True

        info = None
        try:
            info = getElementInfo(self.getAssembly().getPartGroup(),
                                  self.getElementSubname())
        except Exception:
            self.updatePlacement()
            raise

        if not getattr(obj,'Radius',None):
            shape = Part.Shape(info.Shape).copy()
        else:
            if isinstance(info.Part,tuple):
                parentShape = Part.getShape(info.Part[2], info.Subname,
                        transform=info.Part[3], needSubElement=False)
            else:
                parentShape = Part.getShape(info.Part, info.Subname,
                        transform=False, needSubElement=False)
            found = False
            shapes = [info.Shape]
            pla = info.Shape.Placement
            for edge in parentShape.Edges:
                if not info.Shape.isCoplanar(edge) or \
                    not utils.isSameValue(
                        utils.getElementCircular(edge,True),obj.Radius):
                    continue
                edge = edge.copy()
                if not found and utils.isSamePlacement(pla,edge.Placement):
                    found = True
                    # make sure the direct referenced edge is the first one
                    shapes[0] = edge
                else:
                    shapes.append(edge)
            shape = shapes

        # Make a compound to contain shape's part-local-placement. A second
        # level compound will be made inside updatePlacement() to contain the
        # part's placement.
        shape = Part.makeCompound(shape)
        shape.ElementMap = info.Shape.ElementMap
        self.updatePlacement(info.Placement,shape)
        return True

    def updatePlacement(self,pla=None,shape=None):
        obj = self.Object
        if not shape:
            # If the shape is not given, we simply obtain the shape inside our
            # own "Shape" property
            shape = obj.Shape
            if not shape or shape.isNull():
                return
            # De-compound to obtain the original shape in our coordinate system
            shape = shape.SubShapes[0]

            # Call getElementInfo() to obtain part's placement only. We don't
            # need the shape here, in order to handle even with missing
            # down-stream element
            info = getElementInfo(self.getAssembly().getPartGroup(),
                        self.getElementSubname(),False,True)
            pla = info.Placement

        if obj.Offset.isIdentity():
            objPla = FreeCAD.Placement()
        else:
            if hasattr(obj,'Radius'):
                s = shape.SubShapes[0]
            else:
                s = shape
            # obj.Offset is in the element shape's coordinate system, we need to
            # transform it to the assembly coordinate system
            mat = pla.multiply(utils.getElementPlacement(s)).toMatrix()
            objPla = FreeCAD.Placement(mat*obj.Offset.toMatrix()*mat.inverse())

        # Update the shape with its owner Part's current placement
        shape.Placement = pla

        # Make a compound to contain the part's placement. There may be
        # additional placement for this element which is updated below
        shape = Part.makeCompound(shape)
        obj.Shape = shape
        obj.Placement = objPla

        # unfortunately, we can't easily check two shapes are the same
        self.version.value += 1

    def getAssembly(self):
        return self.parent.parent

    def getSubElement(self):
        link = self.Object.LinkedObject
        if isinstance(link,tuple):
            return link[1].split('.')[-1]
        return ''

    def getSubName(self):
        link = self.Object.LinkedObject
        if not link:
            raise RuntimeError('Invalid element "{}"'.format(
                objName(self.Object)))
        if not isinstance(link,tuple):
            return link.Name + '.'
        return link[0].Name + '.' + link[1]

    def getElementSubname(self,recursive=False):
        '''
        Recursively resolve the geometry element link relative to the parent
        assembly's part group
        '''

        subname = self.getSubName()
        if not recursive:
            return subname

        link = self.Object.LinkedObject
        if not isinstance(link,tuple):
            raise RuntimeError('Borken element link')
        obj = link[0].getSubObject(link[1],1)
        if not obj:
            raise RuntimeError('Borken element link')
        if not isTypeOf(obj,AsmElement):
            # If not pointing to another element, then assume we are directly
            # pointing to the geometry element, just return as it is, which is a
            # subname relative to the parent assembly part group
            return subname

        childElement = obj.Proxy

        # If pointing to another element in the child assembly, first pop two
        # names in the subname reference, i.e. element label and element group
        # name
        idx = subname.rfind('.',0,subname.rfind('.',0,-1))
        subname = subname[:idx+1]

        # append the child assembly part group name, and recursively call into
        # child element
        return subname+'2.'+childElement.getElementSubname(True)

    # Element: optional, if none, then a new element will be created if no
    #          pre-existing. Or else, it shall be the element to be amended
    # Group: the immediate child object of an assembly (i.e. ConstraintGroup,
    #        ElementGroup, or PartGroup)
    # Subname: the subname reference relative to 'Group'
    Selection = namedtuple('AsmElementSelection',('Element','Group','Subname',
                                'SelObj', 'SelSubname'))

    @staticmethod
    def getSelections():
        'Parse Gui.Selection for making one or more elements'

        sels = FreeCADGui.Selection.getSelectionEx('',False)
        if not sels:
            raise RuntimeError('no selection')
        if not sels[0].SubElementNames:
            raise RuntimeError('no sub-object in selection')
        if len(sels)>1:
            raise RuntimeError('too many selection')

        hierarchies = []
        assembly = None
        element = None
        selObj = sels[0].Object
        selSubname = None
        for sub in sels[0].SubElementNames:
            path = Assembly.findChildren(selObj,sub)
            if not path:
                raise RuntimeError('no assembly in selection {}.{}'.format(
                    objName(selObj),sub))
            if not path[-1].Object or \
               path[-1].Subname.index('.')+1==len(path[-1].Subname):
                if assembly:
                    raise RuntimeError('invalid selection')
                assembly = path[-1].Assembly
                selSubname = sub[:-len(path[-1].Subname)]
                continue

            elif isTypeOf(path[-1].Object,AsmElementGroup) and \
                (not element or len(element)>len(path)):
                if element:
                    hierarchies.append(element)
                element = path
                continue

            hierarchies.append(path)

        if not hierarchies:
            if not element:
                raise RuntimeError('no element selection')
            hierarchies.append(element)
            element = None

        if element:
            if len(hierarchies)>1:
                raise RuntimeError('too many selections')
            element = element[-1].Assembly.getSubObject(element[-1].Subname,1)
            if not isTypeOf(element,AsmElement):
                element = None

        if not assembly:
            path = hierarchies[0]
            assembly = path[0].Assembly
            selSubname = sels[0].SubElementNames[0][:-len(path[0].Subname)]
        for i,hierarchy in enumerate(hierarchies):
            for path in hierarchy:
                if path.Assembly == assembly:
                    sub = path.Subname[path.Subname.index('.')+1:]
                    hierarchies[i] = AsmElement.Selection(
                                                    Element=element,
                                                    Group=path.Object,
                                                    Subname=sub,
                                                    SelObj=selObj,
                                                    SelSubname=selSubname)
                    break
            else:
                raise RuntimeError('parent assembly mismatch')
        return hierarchies

    @classmethod
    def create(cls,name,elements):
        if elements.Proxy.getAssembly().Object.Freeze:
            raise RuntimeError('Cannot create new element in frozen assembly')
        element = elements.Document.addObject("Part::FeaturePython",
                                name,cls(elements),None,True)
        ViewProviderAsmElement(element.ViewObject)
        return element

    @staticmethod
    def make(selection=None,name='Element',undo=False,
             radius=None,allowDuplicate=False):
        '''Add/get/modify an element with the given selected object'''
        if not selection:
            sels = AsmElement.getSelections()
            if len(sels)==1:
                ret = [AsmElement.make(sels[0],name,undo,radius,allowDuplicate)]
            else:
                if undo:
                    FreeCAD.setActiveTransaction('Assembly create element')
                try:
                    ret = []
                    for sel in sels:
                        ret.append(AsmElement.make(
                            sel,name,False,radius,allowDuplicate))
                    if undo:
                        FreeCAD.closeActiveTransaction()
                    if not ret:
                        return
                except Exception:
                    if undo:
                        FreeCAD.closeActiveTransaction(True)
                    raise

            FreeCADGui.Selection.pushSelStack()
            FreeCADGui.Selection.clearSelection()
            for obj in ret:
                if sels[0].SelSubname:
                    subname = sels[0].SelSubname
                else:
                    subname = ''
                subname += '1.{}.'.format(obj.Name)
                FreeCADGui.Selection.addSelection(sels[0].SelObj,subname)
            FreeCADGui.Selection.pushSelStack()
            FreeCADGui.runCommand('Std_TreeSelection')
            return ret

        group = selection.Group
        subname = flattenSubname(selection.Group,selection.Subname)

        if isTypeOf(group,AsmElementGroup):
            # if the selected object is an element of the owner assembly, simply
            # return that element
            element = group.getSubObject(subname,1)
            if not isTypeOf(element,AsmElement):
                raise RuntimeError('Invalid element reference {}.{}'.format(
                    group.Name,subname))
            if not allowDuplicate:
                return element
            group = element.getAssembly().getPartGroup()
            subname = element.getSubName()

        elif isTypeOf(group,AsmConstraintGroup):
            # if the selected object is an element link of a constraint of the
            # current assembly, then try to import its linked element if it is
            # not already imported
            link = group.getSubObject(subname,1)
            if not isTypeOf(link,AsmElementLink):
                raise RuntimeError('Invalid element link {}.{}'.format(
                    group.Name,subname))
            ref = link.LinkedObject
            if not isinstance(ref,tuple):
                if not isTypeOf(ref,AsmElement):
                    raise RuntimeError('broken element link {}.{}'.format(
                        group.Name,subname))
                return ref
            if ref[1][0]=='$':
                # this means the element is in the current assembly already
                element = link.getLinkedObject(False)
                if not isTypeOf(element,AsmElement):
                    raise RuntimeError('broken element link {}.{}'.format(
                        group.Name,subname))
                return element

            subname = ref[1]
            group = group.Proxy.getAssembly().getPartGroup()

        elif isTypeOf(group,AsmPartGroup):
            # If the selection come from the part group, first check for any
            # intermediate child assembly
            ret = Assembly.find(group,subname)
            if not ret:
                # If no child assembly in 'subname', simply assign the link as
                # it is, after making sure it is referencing an sub-element
                if not utils.isElement((group,subname)):
                    raise RuntimeError( 'Element must reference a geometry '
                        'element {}.{}'.format(objName(group),subname))
            else:
                # In case there are intermediate assembly inside subname, we'll
                # recursively export the element in child assemblies first, and
                # then import that element to the current assembly.
                sel = AsmElement.Selection(SelObj=None,SelSubname=None,
                        Element=None, Group=ret.Object, Subname=ret.Subname)
                element = AsmElement.make(sel,radius=radius)
                radius=None

                # now generate the subname reference

                # This give us reference to child assembly's immediate child
                # without trailing dot.
                prefix = subname[:-len(ret.Subname)-1]

                # Pop the immediate child name
                prefix = prefix[:prefix.rfind('.')]

                # Finally, generate the subname, by combining the prefix with
                # the element group index (i.e. the 1 below) and the linked
                # element label
                subname = '{}.1.${}.'.format(prefix,element.Label)

        else:
            raise RuntimeError('Invalid selection {}.{}'.format(
                objName(group),subname))

        element = selection.Element

        subname = flattenSubname(group,subname)
        dot = subname.find('.')
        sobj = group.getSubObject(subname[:dot+1],1)
        if not sobj:
            raise RuntimeError('invalid link {}.{}'.format(
                objName(group),subname))
        try:
            if undo:
                FreeCAD.setActiveTransaction('Assembly change element' \
                        if element else 'Assembly create element')

            elements = group.Proxy.getAssembly().getElementGroup()
            idx = -1
            if not element:
                if not allowDuplicate:
                    # try to search the element group for an existing element
                    for e in flattenGroup(elements):
                        if not e.Offset.isIdentity():
                            continue
                        sub = logger.catch('',e.Proxy.getSubName)
                        if sub!=subname:
                            continue
                        r = getattr(e,'Radius',None)
                        if (not radius and not r) or radius==r:
                            return e
                element = AsmElement.create(name,elements)
                if radius:
                    element.addProperty('App::PropertyFloat','Radius','','')
                    element.Radius = radius
                elements.setLink({idx:element})
                elements.setElementVisible(element.Name,False)
                element.Proxy._initializing = False
                elements.cacheChildLabel()

            element.setLink(sobj,subname[dot+1:])
            element.recompute()
            if undo:
                FreeCAD.closeActiveTransaction()
        except Exception:
            if undo:
                FreeCAD.closeActiveTransaction(True)
            raise
        return element


class ViewProviderAsmElement(ViewProviderAsmOnTop):
    _iconName = 'Assembly_Assembly_Element.svg'
    _iconDisabledName = 'Assembly_Assembly_ElementDetached.svg'

    def __init__(self,vobj):
        vobj.addProperty('App::PropertyBool',
                'ShowCS','','Show coordinate cross')
        vobj.ShapeColor = self.getDefaultColor()
        vobj.PointColor = self.getDefaultColor()
        vobj.LineColor = self.getDefaultColor()
        vobj.Transparency = 50
        vobj.LineWidth = 4
        vobj.PointSize = 4
        self.axisNode = None
        self.transNode = None
        super(ViewProviderAsmElement,self).__init__(vobj)

    def attach(self,vobj):
        super(ViewProviderAsmElement,self).attach(vobj)
        vobj.OnTopWhenSelected = 2
        self.setupAxis()

    def getDefaultColor(self):
        return (60.0/255.0,1.0,1.0)

    def canDropObjectEx(self,_obj,owner,subname,elements):
        if not owner:
            return False
        if not elements and not utils.isElement((owner,subname)):
            return False
        proxy = self.ViewObject.Object.Proxy
        return proxy.getAssembly().getPartGroup()==owner

    def dropObjectEx(self,vobj,_obj,owner,subname,elements):
        if not elements:
            elements = ['']
        for element in elements:
            AsmElement.make(AsmElement.Selection(
                SelObj=None, SelSubname=None, Element=vobj.Object,
                Group=owner, Subname=subname+element),undo=True)

    def doubleClicked(self,_vobj):
        from . import mover
        return mover.movePart()

    def getIcon(self):
        return utils.getIcon(self.__class__,
                getattr(self.ViewObject.Object,'Detach',False))

    def updateData(self,_obj,prop):
        vobj = getattr(self,'ViewObject',None)
        if not vobj or FreeCAD.isRestoring():
            return
        if prop == 'Detach':
            vobj.signalChangeIcon()
        elif prop in ('Placement','Shape','Radius'):
            self.setupAxis()

    _AxisOrigin = None

    def showCS(self):
        vobj = getattr(self,'ViewObject',None)
        if not vobj or hasattr(vobj.Object,'Radius'):
            return
        if getattr(vobj,'ShowCS',False) or\
                gui.AsmCmdManager.ShowElementCS:
            return True
        return utils.isInfinite(vobj.Object.Shape)

    def getElementPicked(self,pp):
        vobj = self.ViewObject
        if self.showCS():
            axis = self._AxisOrigin
            if axis:
                sub = axis.getElementPicked(pp)
                if sub:
                    return sub
        return vobj.getElementPicked(pp)

    def getDetailPath(self,subname,path,append):
        vobj = self.ViewObject
        node = getattr(self,'axisNode',None)
        if node:
            cdx = vobj.RootNode.findChild(node)
            if cdx >= 0:
                length = path.getLength()
                if append:
                    path.append(vobj.RootNode)
                elif path.getLength():
                    # pop the mode switch node, because we have our onw switch
                    # to control axis visibility
                    path.truncate(path.getLength()-1)
                path.append(node)
                path.append(node.getChild(0))
                ret = self._AxisOrigin.getDetailPath(subname,path)
                if ret:
                    return ret;
                path.truncate(length)
        return vobj.getDetailPath(subname,path,append)

    @classmethod
    def getAxis(cls):
        axis = cls._AxisOrigin
        if not axis:
            axis = FreeCADGui.AxisOrigin()
            axis.Labels = {'X':'','Y':'','Z':''}
            cls._AxisOrigin = axis
        return axis.Node

    def setupAxis(self):
        vobj = getattr(self,'ViewObject', None)
        if not vobj:
            return
        switch = getattr(self,'axisNode',None)
        if not self.showCS():
            if switch:
                switch.whichChild = -1
            return

        if not switch:
            from pivy import coin
            switch = coin.SoSwitch()
            node = coin.SoType.fromName('SoFCSelectionRoot').createInstance()
            switch.addChild(node)
            trans = coin.SoTransform()
            node.addChild(trans)
            node.addChild(ViewProviderAsmElement.getAxis())
            self.axisNode = switch
            self.transNode = trans
            vobj.RootNode.addChild(switch)
        switch.whichChild = 0

        pla = vobj.Object.Placement.inverse().multiply(
                utils.getElementPlacement(vobj.Object.Shape))
        self.transNode.translation.setValue(pla.Base)
        self.transNode.rotation.setValue(pla.Rotation.Q)

    def onChanged(self,_vobj,prop):
        if prop == 'ShowCS':
            self.setupAxis()


class AsmElementSketch(AsmElement):
    def __init__(self,obj,parent):
        super(AsmElementSketch,self).__init__(parent)
        obj.Proxy = self
        self.attach(obj)

    def linkSetup(self,obj):
        super(AsmElementSketch,self).linkSetup(obj)
        obj.setPropertyStatus('Placement',('Hidden','-Immutable'))

    @classmethod
    def create(cls,name,parent):
        element = parent.Document.addObject("Part::FeaturePython", name)
        cls(element,parent)
        ViewProviderAsmElementSketch(element.ViewObject)
        return element

    def execute(self,obj):
        shape = utils.getElementShape(obj.LinkedObject)
        obj.Placement = shape.Placement
        obj.Shape = shape
        return False

    def getSubObject(self,obj,subname,retType,mat,transform,depth):
        link = obj.LinkedObject
        if isinstance(link,tuple) and \
           (not subname or subname==link[1]):
            ret = link[0].getSubObject(subname,retType,mat,transform,depth+1)
            if ret == link[0]:
                ret = obj
            elif isinstance(ret,(tuple,list)):
                ret = list(ret)
                ret[0] = obj
            return ret


class ViewProviderAsmElementSketch(ViewProviderAsmElement):
    def getIcon(self):
        return ":/icons/Sketcher_Sketch.svg"

    def getDetail(self,_name):
        pass

    def getElement(self,_det):
        link = self.ViewObject.Object.LinkedObject
        if isinstance(link,tuple):
            subs = link[1].split('.')
            if subs:
                return subs[-1]
        return ''

    def updateData(self,obj,prop):
        _ = obj
        _ = prop


ElementInfo = namedtuple('AsmElementInfo', ('Parent','SubnameRef','Part',
    'PartName','Placement','Object','Subname','Shape'))

def getElementInfo(parent,subname,
        checkPlacement=False,shape=None,recursive=False):
    '''Return a named tuple containing the part object element information

    Parameters:

        parent: the parent document object, either an assembly, or a part group

        subname: subname reference to the part element (i.e. edge, face, vertex)

        shape: caller can pass in a pre-obtained element shape. The shape is
        assumed to be in the assembly coordinate space. This function will then
        transform the shape into the its owner part's coordinate space.  If
        'shape' is not given, then the output shape will be obtained through
        'parent' and 'subname'

    Return a named tuple with the following fields:

    Parent: set to the input parent object

    SubnameRef: set to the input subname reference

    Part: either the part object, or a tuple(array,idx,element,collapsed) to
          refer to an element in an link array,

    PartName: a string name for the part

    Placement: the placement of the part

    Object: the object that owns the element. In case 'Part' is an assembly, the
    element owner will always be some (grand)child of the 'Part'

    Subname: the subname reference to the element owner object. The reference is
    relative to the 'Part', i.e. Object = Part.getSubObject(subname), or if
    'Part' is a tuple, Object = Part[0].getSubObject(str(Part[1]) + '.' +
    subname)

    Shape: Part.Shape of the linked element. The shape's placement is relative
    to the owner Part.
    '''

    subnameRef = subname
    parentSave = parent

    if isTypeOf(parent,Assembly,True):
        idx = subname.index('.')
        parent = parent.getSubObject(subname[:idx+1],1)
        subname = subname[idx+1:]

    if isTypeOf(parent,(AsmElementGroup,AsmConstraintGroup)):
        child = parent.getSubObject(subname,1)
        if not isTypeOf(child,(AsmElement,AsmElementLink)):
            raise RuntimeError('Invalid sub-object {}, {}'.format(
                objName(parent), subname))
        subname = child.Proxy.getElementSubname(recursive)
        partGroup = parent.Proxy.getAssembly().getPartGroup()

    elif isTypeOf(parent,AsmPartGroup):
        partGroup = parent
    else:
        raise RuntimeError('{} is not Assembly or PartGroup'.format(
            objName(parent)))

    subname = flattenSubname(partGroup,subname)
    names = subname.split('.')
    part = partGroup.getSubObject(names[0]+'.',1)
    if not part:
        raise RuntimeError('Invalid sub-object {}, {}'.format(
            objName(parent), subnameRef))
    partSaved = part

    transformShape = True if isinstance(shape,Part.Shape) else False

    # For storing the placement of the movable part
    pla = None
    # For storing the actual geometry object of the part, in case 'part' is
    # a link
    obj = None

    if not isTypeOf(part,Assembly,True):

        # special treatment of link array (i.e. when ElementCount!=0), we
        # allow the array element to be moveable by the solver
        if getLinkProperty(part,'ElementCount'):

            # Handle old element reference before this link is expanded to
            # array.
            if not names[1]:
                names[1] = '0'
                names.append('')
            elif len(names) == 2:
                names.insert(1,'0')

            # store both the part (i.e. the link array), and the array
            # element object
            part = (part,part.getSubObject(names[1]+'.',1))
            if not part[1]:
                raise RuntimeError('Cannot find part array element {}.{}.',
                                  part.Name,names[1])

            # trim the subname to be after the array element
            subname = '.'.join(names[2:])
            if not shape:
                shape=utils.getElementShape((part[1],subname))

            # There are two states of an link array.
            if getLinkProperty(part[0],'ElementList'):
                # a) The elements are expanded as individual objects, i.e
                # when ElementList has members, then the moveable Placement
                # is a property of the array element.
                pla = part[0].Placement.multiply(part[1].Placement)
                obj = part[1].getLinkedObject(False)
                partName = objName(part[1])
                idx = int(partName.split('_i')[-1])
                part = (part[0],idx,part[1],False)
            else:
                plaList = getLinkProperty(part[0],'PlacementList',None,True)
                if plaList:
                    # b) The elements are collapsed. Then the moveable Placement
                    # is stored inside link object's PlacementList property.
                    obj = part[1]
                    try:
                        if names[1] == part[1].Name:
                            idx = 0
                        else:
                            idx = int(names[1].split('_i')[-1])
                        # we store the array index instead, in order to modified
                        # Placement later when the solver is done. Also because
                        # that when the elements are collapsed, there is really
                        # no element object here.
                        part = (part[0],idx,part[1],True)
                        pla = part[0].Placement.multiply(plaList[idx])
                    except ValueError:
                        raise RuntimeError('invalid array subname of element '
                            '{}: {}'.format(objName(parent),subnameRef))

                    partName = '{}.{}.'.format(objName(part[0]),idx)

    if not obj:
        part = partSaved
        # Here means, either the 'part' is an assembly or it is a non array
        # object. We trim the subname reference to be relative to the part
        # object.  And obtain the shape before part's Placement by setting
        # 'transform' to False
        if checkPlacement and not hasattr(part,'Placement'):
            raise RuntimeError('part has no placement')
        subname = '.'.join(names[1:])
        if not shape:
            shape = utils.getElementShape((part,subname))
        if not shape:
            raise RuntimeError('Failed to get geometry element from '
                '{}.{}'.format(objName(part),subname))
        pla = getattr(part,'Placement',FreeCAD.Placement())
        obj = part.getLinkedObject(False)
        partName = part.Name

    if transformShape:
        # Copy and transform shape. We have to copy the shape here to work
        # around of obscure OCCT edge transformation bug
        shape.transformShape(pla.toMatrix().inverse(),True)

    return ElementInfo(Parent = parentSave,
                    SubnameRef = subnameRef,
                    Part = part,
                    PartName = partName,
                    Placement = pla.copy(),
                    Object = obj,
                    Subname = subname,
                    Shape = shape)


class AsmElementLink(AsmBase):
    def __init__(self,parent):
        super(AsmElementLink,self).__init__()
        self.version = None
        self.info = None
        self.infos = []
        self.part = None
        self.parent = getProxy(parent,AsmConstraint)
        self.multiply = False

    def linkSetup(self,obj):
        super(AsmElementLink,self).linkSetup(obj)
        parent = getattr(obj,'_Parent',None)
        if parent:
            self.parent = parent.Proxy
        obj.setPropertyStatus('LinkedObject','ReadOnly')
        if not hasattr(obj,'Offset'):
            obj.addProperty("App::PropertyPlacement","Offset"," Link",'')
        if not hasattr(obj,'Placement'):
            obj.addProperty("App::PropertyPlacement","Placement"," Link",'')
            obj.setPropertyStatus('Placement','Hidden')
        if not hasattr(obj,'LinkTransform'):
            obj.addProperty("App::PropertyBool","LinkTransform"," Link",'')
            obj.LinkTransform = True
            obj.setPropertyStatus('LinkTransform',['Immutable','Hidden'])
        obj.configLinkProperty('LinkedObject','Placement','LinkTransform')
        if hasattr(obj,'Count'):
            obj.configLinkProperty('PlacementList',
                    'ShowElement',ElementCount='Count')
        self.info = None
        self.infos = []
        self.part = None
        self.multiply = False

        self.version = AsmVersion()

    def migrate(self,obj):
        link = obj.LinkedObject
        if not isinstance(link,tuple):
            return
        touched = 'Touched' in obj.State
        if isTypeOf(link[0],(AsmPartGroup,AsmElementGroup)):
            owner = link[0]
            subname = link[1]
        else:
            owner = self.getAssembly().getPartGroup()
            subname = '{}.{}'.format(link[0].Name,link[1])
        logger.catchDebug('migrate ElementLink',self.setLink,owner,subname)
        if not touched:
            obj.purgeTouched()

    def childVersion(self,linked,mat):
        if not isTypeOf(linked,AsmElement):
            return None
        obj = self.Object
        return (getattr(obj,'Count',0),
                linked,
                linked.Proxy.version.value,
                obj.Offset,
                mat,
                getattr(obj,'PlacementList',None))

    def attach(self,obj):
        obj.addProperty("App::PropertyXLink","LinkedObject"," Link",'')
        obj.addProperty("App::PropertyLinkHidden","_Parent"," Link",'')
        obj._Parent = self.parent.Object
        obj.setPropertyStatus('_Parent',('Hidden','Immutable'))
        super(AsmElementLink,self).attach(obj)

    def canLinkProperties(self,_obj):
        return False

    def allowDuplicateLabel(self,_obj):
        return True

    def execute(self,obj):
        link = obj.LinkedObject
        if isinstance(link,tuple):
            subname = link[1]
            link = link[0]
        else:
            subname = ''
        linked,mat = link.getSubObject(subname,1,FreeCAD.Matrix())
        if linked and linked.Label != linked.Name:
            obj.Label = linked.Label

        info = None
        if getattr(obj,'Count',None):
            info = self.getInfo(True)

        version = self.childVersion(linked,mat)
        if not self.version.update(version):
            logger.debug('skip {}, {}, {}',
                objName(obj),self.version.childVersion,version)
            return
        logger.debug('not skip {}, {}',objName(obj),version)

        if not info:
            info = self.getInfo(True)
        relationGroup = self.getAssembly().getRelationGroup()
        if relationGroup and (not self.part or self.part!=info.Part):
            oldPart = self.part
            self.part = info.Part
            relationGroup.Proxy.update(
                    self.parent.Object,oldPart,info.Part,info.PartName)
        self.version.commit()
        return False

    _MyIgnoredProperties = _IgnoredProperties | \
            set(('Count','PlacementList'))

    def onChanged(self,obj,prop):
        if obj.Removing or \
           not getattr(self,'parent',None) or \
           FreeCAD.isRestoring():
            return
        elif obj.Document and getattr(obj.Document,'Transacting',False):
            self.infos *= 0 # clear the list
            self.info = None
            return
        elif prop == 'Count':
            self.infos *= 0 # clear the list
            self.info = None
            return
        elif prop == 'Offset':
            self.getInfo(True)
            return
        elif prop == 'NoExpand':
            cstr = self.parent.Object
            if obj!=cstr.Group[0] \
                    and cstr.Multiply \
                    and obj.LinkedObject:
                self.setLink(self.getAssembly().getPartGroup(),
                        self.getElementSubname(True))
            return
        elif prop == 'Label':
            if obj.Document and getattr(obj.Document,'Transacting',False):
                return
            link = getattr(obj,'LinkedObject',None)
            if isinstance(link,tuple):
                linked = link[0].getSubObject(link[1],1)
            else:
                linked = link
            if linked and linked.Label != obj.Label:
                linked.Label = obj.Label
                # in case there is label duplication, AsmElement will auto
                # re-lable it.
                obj.Label = linked.Label
            return
        elif prop == 'AutoCount':
            if obj.AutoCount and hasattr(obj,'ShowElement'):
                self.parent.checkMultiply()
        if prop not in self._MyIgnoredProperties and \
           not Constraint.isDisabled(self.parent.Object):
            Assembly.autoSolve(obj,prop)

    def getAssembly(self):
        return self.parent.parent.parent

    def getElementSubname(self,recursive=False):
        'Resolve element link subname'

        #  AsmElementLink is used by constraint to link to a geometry link. It
        #  does so by indirectly linking to an AsmElement object belonging to
        #  the same parent or child assembly. AsmElement is also a link, which
        #  again links to another AsmElement of a child assembly or the actual
        #  geometry element of a child feature. This function is for resolving
        #  the AsmElementLink's subname reference to the actual part object
        #  subname reference relative to the parent assembly's part group

        link = self.Object.LinkedObject
        if not isinstance(link,tuple):
            linked = link
        else:
            linked = link[0].getSubObject(link[1],1)
        if not linked:
            raise RuntimeError('broken link')
        element = getProxy(linked,AsmElement)
        assembly = element.getAssembly()
        if assembly == self.getAssembly():
            return element.getElementSubname(recursive)

        # The reference is stored inside this ElementLink. We need the
        # sub-assembly name, which is the name before the first dot. This name
        # may be different from the actual assembly object's name, in case where
        # the assembly is accessed through a link. And the sub-assembly may be
        # inside a link array, which we don't know for sure. But we do know that
        # the last two names are element group and element label. So just pop
        # two names. The -3 below is to account for the last ending '.'
        ref = [link[0].Name] + link[1].split('.')[:-3]
        return '{}.2.{}'.format('.'.join(ref),
                element.getElementSubname(recursive))

    def setLink(self,owner,subname,checkOnly=False,multiply=False):
        obj = self.Object
        cstr = self.parent.Object
        elements = flattenGroup(cstr)
        radius = None
        if (multiply or Constraint.canMultiply(cstr)) and \
           obj!=elements[0] and \
           not getattr(obj,'NoExpand',None):

            info = getElementInfo(owner,subname)

            radius = utils.getElementCircular(info.Shape,True)
            if radius and not checkOnly and not hasattr(obj,'NoExpand'):
                touched = 'Touched' in obj.State
                obj.addProperty('App::PropertyBool','NoExpand','',
                        'Disable auto inclusion of coplanar edges '\
                        'with the same radius')
                if len(elements)>2 and getattr(elements[-2],'NoExpand',None):
                    obj.NoExpand = True
                    radius = None
                if not touched:
                    obj.purgeTouched()
            if radius:
                if isinstance(info.Part,tuple):
                    parentShape = Part.getShape(info.Part[2], info.Subname,
                            transform=info.Part[3], needSubElement=False)
                else:
                    parentShape = Part.getShape(info.Part, info.Subname,
                            transform=False, needSubElement=False)
                count = 0
                for edge in parentShape.Edges:
                    if not info.Shape.isCoplanar(edge) or \
                        not utils.isSameValue(
                            utils.getElementCircular(edge,True),radius):
                        continue
                    count += 1
                    if count > 1:
                        break
                if count<=1:
                    radius = None

        if checkOnly:
            return True

        #####################################################################
        # Note: we no longer link directly to sub-assembly's Element any more.
        # Instead, We always link through local element, to make it easy for
        # user to recover missing elements in case it happens
        #####################################################################

        sel = AsmElement.Selection(SelObj=None, SelSubname=None,
                Element=None, Group=owner, Subname=subname)
        element = AsmElement.make(sel,radius=radius,name='_Element')

        for sibling in elements:
            if sibling == obj:
                continue
            if sibling.LinkedObject == element:
                raise RuntimeError('duplicate element link {} in constraint '
                    '{}'.format(objName(sibling),objName(cstr)))
        obj.setLink(element)
        if obj.Label!=obj.Name and element.Label.startswith('_Element'):
            if not obj.Label.startswith('_'):
                element.Label = '_' + obj.Label
            else:
                element.Label = obj.Label
        obj.Label = element.Label

    def getInfo(self,refresh=False,expand=False):
        if not refresh and self.info is not None:
            return self.infos if expand else self.info

        self.info = None
        self.infos = []
        obj = getattr(self,'Object',None)
        if not obj:
            return

        linked = obj.LinkedObject
        if isinstance(linked,tuple):
            subname = linked[1]
            linked = linked[0]
        else:
            subname = ''
        shape = Part.getShape(linked,subname,
                    needSubElement=True,noElementMap=True)
        self.info = getElementInfo(self.getAssembly().getPartGroup(),
                        self.getElementSubname(),shape=shape)
        info = self.info

        if obj.Offset.isIdentity():
            if not obj.Placement.isIdentity():
                obj.Placement = FreeCAD.Placement()
        else:
            # obj.Offset is in the element shape's coordinate system, we need to
            # transform it to the assembly coordinate system
            mShape = utils.getElementPlacement(info.Shape).toMatrix()
            mOffset = obj.Offset.toMatrix()
            mat = info.Placement.toMatrix()*mShape
            pla = FreeCAD.Placement(mat*mOffset*mat.inverse())
            if not utils.isSamePlacement(obj.Placement,pla):
                obj.Placement = pla
            info.Shape.transformShape(mShape*mOffset*mShape.inverse())

            info = ElementInfo(Parent = info.Parent,
                               SubnameRef = info.SubnameRef,
                               Part = info.Part,
                               PartName = info.PartName,
                               Placement = info.Placement,
                               Object = info.Object,
                               Subname = '{}.{}'.format(
                                   info.Subname,hash(str(obj.Offset))),
                               Shape = info.Shape)
            self.info = info

        parent = self.parent.Object
        if not Constraint.canMultiply(parent):
            self.multiply = False
            self.infos.append(info)
            return self.infos if expand else self.info

        self.multiply = True
        if obj == parent.Group[0]:
            if not isinstance(info.Part,tuple) or \
               getLinkProperty(info.Part[0],'ElementCount')!=obj.Count:
                self.infos.append(info)
                return self.infos if expand else self.info
            infos = []
            offset = info.Placement.inverse()
            plaList = []
            for i in xrange(obj.Count):
                part = info.Part
                if part[3]:
                    pla = getLinkProperty(part[0],'PlacementList')[i]
                    part = (part[0],i,part[2],part[3])
                else:
                    sobj = part[0].getSubObject(str(i)+'.',1)
                    pla = sobj.Placement
                    part = (part[0],i,sobj,part[3])
                pla = part[0].Placement.multiply(pla)
                plaList.append(pla.multiply(offset))
                infos.append(ElementInfo(
                               Parent = info.Parent,
                               SubnameRef = info.SubnameRef,
                               Part=part,
                               PartName = '{}.{}'.format(objName(part[0]),i),
                               Placement = pla,
                               Object = info.Object,
                               Subname = info.Subname,
                               Shape = info.Shape))
            obj.PlacementList = plaList
            self.infos = infos
            return infos if expand else info

        for i,edge in enumerate(info.Shape.Edges):
            self.infos.append(ElementInfo(
                            Parent = info.Parent,
                            SubnameRef = info.SubnameRef,
                            Part = info.Part,
                            PartName = info.PartName,
                            Placement = info.Placement,
                            Object = info.Object,
                            Subname = '{}_{}'.format(info.Subname,i),
                            Shape = edge))

        return self.infos if expand else self.info

    MakeInfo = namedtuple('AsmElementLinkMakeInfo',
            ('Constraint','Owner','Subname'))

    @staticmethod
    def make(info,name='ElementLink'):
        link = info.Constraint.Document.addObject("App::FeaturePython",
                    name,AsmElementLink(info.Constraint),None,True)
        ViewProviderAsmElementLink(link.ViewObject)
        info.Constraint.setLink({-1:link})
        link.Proxy.setLink(info.Owner,info.Subname)
        if gui.AsmCmdManager.AutoElementVis:
            info.Constraint.setElementVisible(link.Name,False)
        return link


def setPlacement(part,pla,purgeTouched=False):
    ''' called by solver after solving to adjust the placement.

        part: obtained by AsmConstraint.getInfo().Part pla: the new placement
        pla: new placement
        purgeTouched: set to True to not touch object
    '''
    if not isinstance(part,tuple):
        if purgeTouched:
            obj = part
            touched = 'Touched' in obj.State
        part.Placement = pla
    else:
        pla = part[0].Placement.inverse().multiply(pla)
        if part[3]:
            if purgeTouched:
                obj = part[0]
                touched = 'Touched' in obj.State
            setLinkProperty(part[0],'PlacementList',{part[1]:pla})
        else:
            if purgeTouched:
                obj = part[2]
                touched = 'Touched' in obj.State
            part[2].Placement = pla
    if purgeTouched and not touched:
        obj.purgeTouched()


def showPart(partGroup,part,show=True,purgeTouched=True):
    if not isinstance(part,tuple):
        parent = partGroup
        name = part.Name
    else:
        parent = part[0]
        name = str(part[1])
    if purgeTouched:
        touched = 'Touched' in parent.State
    parent.setElementVisible(name,show)
    if purgeTouched and not touched:
        parent.purgeTouched()


class ViewProviderAsmElementLink(ViewProviderAsmOnTop):
    def __init__(self,vobj):
        vobj.OverrideMaterial = True
        vobj.ShapeMaterial.DiffuseColor = self.getDefaultColor()
        vobj.ShapeMaterial.EmissiveColor = self.getDefaultColor()
        super(ViewProviderAsmElementLink,self).__init__(vobj)

    def attach(self,vobj):
        super(ViewProviderAsmElementLink,self).attach(vobj)
        vobj.OnTopWhenSelected = 2

    def claimChildren(self):
        return []

    def getDefaultColor(self):
        return (1.0,60.0/255.0,60.0/255.0)

    def doubleClicked(self,_vobj):
        from . import mover
        return mover.movePart()

    def canDropObjectEx(self,_obj,owner,subname,elements):
        if len(elements)>1 or not owner:
            return False
        elif elements:
            subname += elements[0]
        me = self.ViewObject.Object
        msg = 'Cannot drop to AsmElementLink {}'.format(objName(me))
        if logger.catchTrace(msg, me.Proxy.setLink,owner,subname,True):
            return True
        return False

    def dropObjectEx(self,vobj,_obj,owner,subname,elements):
        if len(elements)>1:
            return
        elif elements:
            subname += elements[0]
        vobj.Object.Proxy.setLink(owner,subname)


class AsmConstraint(AsmGroup):

    def __init__(self,parent):
        self.prevOrder = []
        self.version = None
        self._initializing = True
        self.elements = None
        self.parent = getProxy(parent,AsmConstraintGroup)
        super(AsmConstraint,self).__init__()

    def getAssembly(self):
        return self.parent.parent

    def checkSupport(self):
        # this function maybe called during document restore, hence the
        # extensive check below
        obj = getattr(self,'Object',None)
        if not obj:
            return
        if Constraint.isDisabled(obj):
           return
        parent = getattr(self,'parent',None)
        if not parent:
            return
        parent = getattr(parent,'parent',None)
        if not parent:
            return
        assembly = getattr(parent,'Object',None)
        if not assembly or \
           System.isConstraintSupported(assembly,Constraint.getTypeName(obj)):
            return
        logger.error('Constraint type "{}" is not supported by '
                'solver "{}"',Constraint.getTypeName(obj),
                    System.getTypeName(assembly))
        Constraint.setDisable(obj)

    def onChanged(self,obj,prop):
        if obj.Document and getattr(obj.Document,'Transacting',False):
            Constraint.onChanged(obj,prop)
            return
        if not obj.Removing and prop not in _IgnoredProperties:
            if prop == Constraint.propMultiply() and not FreeCAD.isRestoring():
                self.checkMultiply()
                self.elements = None
            Constraint.onChanged(obj,prop)
            Assembly.autoSolve(obj,prop)

    def childVersion(self):
        return [(o,o.Proxy.version.value) \
                for o in flattenGroup(self.Object)]

    def linkSetup(self,obj):
        parent = getattr(obj,'_Parent',None)
        if parent:
            self.parent = parent.Proxy
        self.elements = None
        super(AsmConstraint,self).linkSetup(obj)
        Constraint.attach(obj)
        self.version = AsmVersion()

    def attach(self,obj):
        obj.addProperty("App::PropertyLinkHidden","_Parent"," Link",'')
        obj._Parent = self.parent.Object
        obj.setPropertyStatus('_Parent',('Hidden','Immutable'))
        super(AsmConstraint,self).attach(obj)

    def checkMultiply(self):
        obj = self.Object
        if not obj.Multiply:
            return

        if getattr(obj,'Cascade',False):
            obj.Cascade = False

        children = obj.Group
        if len(children)<=1:
            return
        count = 0
        shapes = []
        # count the total edges for multiplication
        for e in children[1:]:
            touched = 'Touched' in e.State
            info = e.Proxy.getInfo(not e.Proxy.multiply)
            if not touched:
                e.purgeTouched()
            if info.Shape.countElement('Face'):
                elementCount = 1
                name = 'Face1'
            else:
                elementCount = info.Shape.countElement('Edge')
                name = 'Edge1'
            if not elementCount:
                shapes.append(None)
                e.Proxy.infos = []
            else:
                count += elementCount
                shapes.append(info.Shape.getElement(name))

        # merge elements that are coplanar
        poses = []
        infos = []
        elements = []
        for i,e in enumerate(children[1:]):
            e.Proxy._refPla = None
            shape = shapes[i]
            if not shape:
                continue
            for j,e2 in enumerate(children[i+2:]):
                shape2 = shapes[i+j+1]
                if not shape2:
                    continue
                if shape.isCoplanar(shape2):
                    e.Proxy.infos += e2.Proxy.infos
                    e2.Proxy.infos = []
            for info in e.Proxy.infos:
                elements.append(e.Proxy)
                infos.append(info)
                poses.append(info.Placement.multVec(
                                utils.getElementPos(info.Shape)))

        # Multiply the part object owning the first element, i.e. change its
        # element count

        firstChild = children[0]
        info = firstChild.Proxy.getInfo()
        if not isinstance(info.Part,tuple):
            raise RuntimeError('Expect part {} to be an array for '
                'constraint multiplication'.format(info.PartName))

        touched = 'Touched' in firstChild.State
        if not hasattr(firstChild,'Count'):
            firstChild.addProperty("App::PropertyInteger","Count",'','')
            firstChild.setPropertyStatus('Count','ReadOnly')
            firstChild.addProperty("App::PropertyBool","AutoCount",'',
                    'Auto change part count to match constraining elements')
            firstChild.AutoCount = True
            firstChild.addProperty("App::PropertyPlacementList",
                    "PlacementList",'','')
            firstChild.setPropertyStatus('PlacementList','Output')
            firstChild.addProperty("App::PropertyBool","ShowElement",'','')
            firstChild.setPropertyStatus('ShowElement',('Hidden','Immutable'))
            firstChild.configLinkProperty('PlacementList',
                    'ShowElement',ElementCount='Count')

        if firstChild.AutoCount:
            oldCount = getLinkProperty(info.Part[0],'ElementCount',None,True)
            if oldCount is None:
                firstChild.AutoCount = False
            elif oldCount < count:
                partTouched = 'Touched' in info.Part[0].State
                setLinkProperty(info.Part[0],'ElementCount',count)
                if not partTouched:
                    info.Part[0].purgeTouched()

        if not firstChild.AutoCount:
            oldCount = getLinkProperty(info.Part[0],'ElementCount')
            if count > oldCount:
                count = oldCount

        if firstChild.Count != count:
            firstChild.Count = count
            firstChild.recompute()

        if not touched and 'Touched' in firstChild.State:
            # purge touched to avoid recomputation multi-pass
            firstChild.purgeTouched()

        # To solve the problem of element index reordering, we shall reorder the
        # links array infos by its proximity to the corresponding constraining
        # element shape

        offset = FreeCAD.Vector(getattr(obj,'OffsetX',0),
                                getattr(obj,'Offset&',0),
                                getattr(obj,'Offset',0))
        poses = poses[:count]
        infos0 = firstChild.Proxy.getInfo(expand=True)[:count]

        used = [-1]*count
        order = [None]*count
        prev = getattr(self,'prevOrder',[])
        distances = [10]*count
        distMap = []
        finished = 0
        refPla = None

        for i,info0 in enumerate(infos0):
            pos0 = info0.Placement.multVec(
                    utils.getElementPos(info0.Shape)-offset)
            if i<len(prev) and prev[i]<count:
                j = prev[i]
                if used[i]<0 and not order[j] and \
                   pos0.distanceToPoint(poses[j]) < 1e-7:
                    distances[i] = 0
                    if not elements[i]._refPla:
                        pla = infos[j].Placement.multiply(
                                utils.getElementPlacement(infos[j].Shape))
                        pla = pla.inverse().multiply(info.Placement)
                        elements[i]._refPla = pla
                        if not refPla:
                            refPla = pla
                    used[i] = j
                    order[j] = info0
                    finished += 1
                    continue
            for j,pos in enumerate(poses):
                if order[j]:
                    continue
                d = pos0.distanceToPoint(pos)
                if used[i]<0 and d < 1e-7:
                    distances[i] = 0
                    if not elements[i]._refPla:
                        pla = infos[j].Placement.multiply(
                                utils.getElementPlacement(infos[j].Shape))
                        pla = pla.inverse().multiply(info.Placement)
                        elements[i]._refPla = pla
                        if not refPla:
                            refPla = pla
                    used[i] = j
                    order[j] = info0
                    finished += 1
                    break
                distMap.append((d,i,j))

        count -= finished
        if count:
            distMap.sort()
            logger.debug('distance map: {}',len(distMap))
            for d in distMap:
                logger.debug(d)
            for d,i,j in distMap:
                if used[i]>=0 or order[j]:
                    continue
                distances[i] = d
                used[i] = j
                order[j] = infos0[i]
                count -= 1
                if not count:
                    break

        firstChild.Proxy.infos = order
        self.prevOrder = used

        # now for thos instances that are 'out of place', lets assign some
        # initial placement

        partGroup = self.getAssembly().getPartGroup()
        touched = False
        for i,info0 in enumerate(infos0):
            if not distances[i]:
                continue
            j = used[i]
            info = infos[j]

            # check if the instance is too far off the pairing element
            p0 = utils.getElementPlacement(info0.Shape)
            p0.Base -= offset
            pla0 = info0.Placement.multiply(p0)
            pla = info.Placement.multiply(
                    utils.getElementPlacement(info.Shape))
            if distances[i]<=5 and \
               abs(utils.getElementsAngle(pla.Rotation,pla0.Rotation))<45:
                # if not too far off, just show it and let solver align it
                showPart(partGroup,info0.Part)
                continue

            ref = elements[i]._refPla
            if not ref:
                ref = refPla
            if ref:
                pla = pla.multiply(ref)
            else:
                pla = info0.Placement.multiply(pla.multiply(pla0.inverse()))
            showPart(partGroup,info0.Part)
            touched = True
            setPlacement(info0.Part,pla,True)

        if touched:
            firstChild.Proxy.getInfo(True)
            firstChild.purgeTouched()

    def execute(self,obj):
        if not getattr(self,'_initializing',False) and\
           getattr(self,'parent',None):
            self.checkSupport()
            if not self.version.update(self.childVersion()):
                return
            if Constraint.canMultiply(obj):
                self.checkMultiply()
            self.getElements(True)
            Constraint.execute(obj)
            self.version.commit()
        return False

    def getElements(self,refresh=False):
        if refresh:
            self.elements = None
        obj = getattr(self,'Object',None)
        if not obj:
            return
        ret = getattr(self,'elements',None)
        if ret or Constraint.isDisabled(obj):
            return ret

        elementInfo = []
        elements = []
        group = flattenGroup(obj)
        if Constraint.canMultiply(obj):
            firstInfo = group[0].Proxy.getInfo(expand=True)
            count = len(firstInfo)
            if not count:
                raise RuntimeError('invalid first element')
            elements.append(group[0])
            for o in group[1:]:
                infos = o.Proxy.getInfo(expand=True)
                if not infos:
                    continue
                elements.append(o)
                if count <= len(infos):
                    infos = infos[:count]
                    elementInfo += infos
                    break
                elementInfo += infos

            for info in zip(firstInfo,elementInfo):
                Constraint.check(obj,info,True)
        else:
            for o in group:
                checkType(o,AsmElementLink)
                info = o.Proxy.getInfo()
                if not info:
                    return
                elementInfo.append(info)
                elements.append(o)
            Constraint.check(obj,elementInfo,True)
        self.elements = elements
        return self.elements

    def getElementsInfo(self):
        return [ e.Proxy.getInfo() for e in self.getElements() ]

    Selection = namedtuple('AsmConstraintSelection',
                ('SelObject','SelSubname','Assembly','Constraint','Elements'))

    @staticmethod
    def getSelection(typeid=0,sels=None):
        '''
        Parse Gui.Selection for making a constraint

        The selected elements must all belong to the same immediate parent
        assembly.
        '''
        if not sels:
            sels = FreeCADGui.Selection.getSelectionEx('',False)
        if not sels:
            raise RuntimeError('no selection')
        if len(sels)>1:
            raise RuntimeError(
                    'The selections must have a common (grand)parent assembly')
        sel = sels[0]
        subs = sel.SubElementNames
        if not subs:
            subs = ['']

        cstr = None
        elements = []
        elementInfo = []
        assembly = None
        selSubname = None
        infos = []
        # first pass, collect hierarchy information, and find active assemble to
        # use, i.e. which assembly to constraint
        for sub in subs:
            sobj = sel.Object.getSubObject(sub,1)
            if not sobj:
                raise RuntimeError('Cannot find sub-object {}.{}'.format(
                    sel.Object.Name,sub))
            ret = Assembly.find(sel.Object,sub,
                    recursive=True,relativeToChild=False,keepEmptyChild=True)
            if not ret:
                raise RuntimeError('Selection {}.{} is not from an '
                    'assembly'.format(sel.Object.Name,sub))

            infos.append((sub,sobj,ret))

            if isTypeOf(sobj,Assembly,True):
                assembly = ret[-1].Assembly
                if sub:
                    selSubname = sub
            elif isTypeOf(sobj,(AsmConstraintGroup,AsmConstraint)):
                assembly = ret[-1].Assembly
                selSubname = sub[:-len(ret[-1].Subname)]
            elif not assembly:
                assembly = ret[0].Assembly
                selSubname = sub[:-len(ret[0].Subname)]

        # second pass, collect element information
        for sub,sobj,ret in infos:
            found = None
            for r in ret:
                if r.Assembly == assembly:
                    found = r
                    break
            if not found:
                raise RuntimeError('Selection {}.{} is not from the target '
                    'assembly {}'.format(
                        sel.Object.Name,sub,objName(assembly)))

            if isTypeOf(sobj,Assembly,True) or \
               isTypeOf(sobj,AsmConstraintGroup):
                continue

            if isTypeOf(sobj,AsmConstraint):
                if cstr:
                    raise RuntimeError('more than one constraint selected')
                cstr = sobj
                continue

            # because we call Assembly.find() above with relativeToChild=False,
            # we shall adjust the element subname by popping the first '.'
            sub = found.Subname
            sub = sub[sub.index('.')+1:]
            if sub[-1] == '.' and \
               not isTypeOf(sobj,(AsmElement,AsmElementLink)):
                # Too bad, its a full selection, let's guess the sub-element
                if not utils.isElement((found.Object,sub)):
                    raise RuntimeError('no sub-element (face, edge, vertex) in '
                        '{}.{}'.format(found.Object.Name,sub))
                subElement = utils.deduceSelectedElement(found.Object,sub)
                if subElement:
                    sub += subElement

            elements.append((found.Object,sub))

            elementInfo.append(getElementInfo(
                assembly,found.Object.Name+'.'+sub))

        if not Constraint.isDisabled(cstr) and not Constraint.canMultiply(cstr):
            if cstr:
                typeid = Constraint.getTypeID(cstr)
                check = []
                for o in flattenGroup(cstr):
                    check.append(o.Proxy.getInfo())
                elementInfo = check + elementInfo

            Constraint.check(typeid,elementInfo)

        return AsmConstraint.Selection(SelObject=sel.Object,
                                       SelSubname=selSubname,
                                       Assembly = assembly,
                                       Constraint = cstr,
                                       Elements = elements)

    @staticmethod
    def make(typeid,sel=None,name='Constraint',undo=True):
        if not sel:
            sel = AsmConstraint.getSelection(typeid)
        assembly = resolveAssembly(sel.Assembly)
        if sel.Constraint:
            if undo:
                FreeCAD.setActiveTransaction('Assembly change constraint')
            cstr = sel.Constraint
        else:
            if undo:
                FreeCAD.setActiveTransaction('Assembly create constraint')
            constraints = assembly.getConstraintGroup()
            cstr = constraints.Document.addObject("App::FeaturePython",
                    name,AsmConstraint(constraints),None,True)
            ViewProviderAsmConstraint(cstr.ViewObject)
            constraints.setLink({-1:cstr})
            Constraint.setTypeID(cstr,typeid)
            cstr.Label = Constraint.getTypeName(cstr)

        try:
            for e in sel.Elements:
                AsmElementLink.make(AsmElementLink.MakeInfo(cstr,*e))
            logger.catchDebug('init constraint', Constraint.init,cstr)

            if gui.AsmCmdManager.AutoElementVis:
                cstr.setPropertyStatus('VisibilityList','-Immutable')
                cstr.VisibilityList = [False]*len(flattenGroup(cstr))
                cstr.setPropertyStatus('VisibilityList','Immutable')

            cstr.Proxy._initializing = False

            if Constraint.canMultiply(cstr):
                cstr.recompute(True)

            if undo:
                FreeCAD.closeActiveTransaction()
                undo = False

            if sel.SelObject:
                FreeCADGui.Selection.pushSelStack()
                FreeCADGui.Selection.clearSelection()
                if sel.SelSubname:
                    subname = sel.SelSubname
                else:
                    subname = ''
                subname += assembly.getConstraintGroup().Name + \
                        '.' + cstr.Name + '.'
                FreeCADGui.Selection.addSelection(sel.SelObject,subname)
                FreeCADGui.Selection.pushSelStack()
                FreeCADGui.runCommand('Std_TreeSelection')
            return cstr

        except Exception as e:
            logger.debug('failed to make constraint: {}',e)
            if undo:
                FreeCAD.closeActiveTransaction(True)
            raise

    @staticmethod
    def makeMultiply(checkOnly=False):
        sel = FreeCADGui.Selection.getSelectionEx('*',0)
        if len(sel)!=1 or len(sel[0].SubElementNames)!=1:
            raise RuntimeError('Too many selections')

        sel = sel[0]
        cstr = sel.Object.getSubObject(sel.SubElementNames[0],1)
        if not isTypeOf(cstr,AsmConstraint):
            raise RuntimeError('Must select a constraint')

        multiplied = Constraint.canMultiply(cstr)
        if multiplied is None:
            raise RuntimeError('Constraint do not support multiplication')

        elements = cstr.Proxy.getElements()
        if len(elements)<2:
            raise RuntimeError('Constraint must have more than one element')

        if checkOnly:
            return True

        try:
            FreeCAD.setActiveTransaction("Assembly constraint multiply")

            info = elements[0].Proxy.getInfo()
            if not isinstance(info.Part,tuple):
                # The first element must be an link array in order to get
                # multiplied. 

                #First, check if it is a link (with element count)
                if getLinkProperty(info.Part,'ElementCount') is None:
                    # No. So we replace it with a link with command
                    # Std_LinkReplace, which requires a select of the object
                    # to be replaced first. So construct the selection path
                    # by replacing the last two subnames (i.e.
                    # Constraints.Constraint) with PartGroup.PartName

                    subs = flattenSubname(sel.Object,sel.SubElementNames[0])
                    subs = subs.split('.')
                    # The last entry is for sub-element name (e.g. Edge1,
                    # Face2), which should be empty
                    subs[-1] = ''
                    subs[-2] = info.Part.Name
                    subs[-3] = '2'
                    subs = '.'.join(subs)
                    # remember last selection
                    FreeCADGui.Selection.pushSelStack()
                    FreeCADGui.Selection.clearSelection()
                    FreeCADGui.Selection.addSelection(sel.Object,subs)

                    FreeCADGui.Selection.pushSelStack()
                    FreeCADGui.runCommand('Std_LinkReplace')
                    # restore the last selection
                    FreeCADGui.runCommand('Std_SelBack')

                    info = elements[0].Proxy.getInfo(True)
                    # make sure the replace command works
                    if getLinkProperty(info.Part,'ElementCount') is None:
                        raise RuntimeError('Failed to replace "{}" with a '
                            'link'.format(info.PartName))

                # Let's first make an single element array without showing
                # its element object, which will make the linked object
                # grouped under the link rather than floating under tree
                # view root
                setLinkProperty(info.Part,'ShowElement',False)
                try:
                    setLinkProperty(info.Part,'ElementCount',1)
                except Exception:
                    raise RuntimeError('Failed to change element count of '
                        '{}'.format(info.PartName))

            partGroup = cstr.Proxy.getAssembly().getPartGroup()

            cstr.recompute(True)

            if not multiplied:
                for elementLink in elements[1:]:
                    subname = elementLink.Proxy.getElementSubname(True)
                    elementLink.Proxy.setLink(
                            partGroup,subname,checkOnly,multiply=True)
                cstr.Multiply = True
            else:
                # Here means the constraint is already multiplied, expand it to
                # multiple individual constraints
                elements = cstr.Proxy.getElements()
                infos0 = [(partGroup,'{}.{}.{}'.format(info.Part[0].Name,
                                                       info.Part[1],
                                                       info.Subname)) \
                          for info in elements[0].Proxy.getInfo(expand=True)]
                infos = []
                for element in elements[1:]:
                    if element.NoExpand:
                        infos.append(element.LinkedObject)
                        continue
                    info = element.Proxy.getInfo()
                    subs = Part.splitSubname(
                            element.Proxy.getElementSubname(True))
                    if isinstance(info.Part,tuple):
                        subs[0] = '{}.{}'.format(info.Part[1],subs[0])
                    parentShape = Part.getShape(
                            partGroup,subs[0],noElementMap=True)
                    subShape = parentShape.getElement(subs[2])
                    radius = utils.getElementCircular(subShape,True)
                    for i,edge in enumerate(parentShape.Edges):
                        if subShape.isCoplanar(edge) and \
                            utils.isSameValue(
                                utils.getElementCircular(edge,True),radius):
                            subs[2] = 'Edge{}'.format(i+1)
                            subs[1] = parentShape.getElementName(subs[2])
                            if subs[1] == subs[2]:
                                subs[1] = ''
                            infos.append((partGroup,Part.joinSubname(*subs)))
                assembly = cstr.Proxy.getAssembly().Object
                typeid = Constraint.getTypeID(cstr)
                for info in zip(infos0,infos[:len(infos0)]):
                    sel = AsmConstraint.Selection(SelObject=None,
                                                  SelSubname=None,
                                                  Assembly = assembly,
                                                  Constraint = None,
                                                  Elements = info)
                    newCstr = AsmConstraint.make(typeid,sel,undo=False)
                    Constraint.copy(cstr,newCstr)
                    for element,target in zip(elements,newCstr.Group):
                        target.Offset = element.Offset
                cstr.Document.removeObject(cstr.Name)

            FreeCAD.closeActiveTransaction()
            return True
        except Exception:
            FreeCAD.closeActiveTransaction(True)
            raise


class ViewProviderAsmConstraint(ViewProviderAsmGroup):

    def setupContextMenu(self,vobj,menu):
        obj = vobj.Object
        action = QtGui.QAction(QtGui.QIcon(),
                "Enable" if obj.Disabled else "Disable", menu)
        QtCore.QObject.connect(
                action,QtCore.SIGNAL("triggered()"),self.toggleDisable)
        menu.addAction(action)

    def toggleDisable(self):
        obj = self.ViewObject.Object
        FreeCAD.setActiveTransaction('Toggle constraint')
        try:
            obj.Disabled = not obj.Disabled
            FreeCAD.closeActiveTransaction()
        except Exception:
            FreeCAD.closeActiveTransaction(True)
            raise

    def attach(self,vobj):
        super(ViewProviderAsmConstraint,self).attach(vobj)
        vobj.OnTopWhenSelected = 2

    def getIcon(self):
        return Constraint.getIcon(self.ViewObject.Object)

    def _getSelection(self,owner,subname,elements):
        if not owner:
            raise RuntimeError('no owner')
        parent = getattr(owner.Proxy,'parent',None)
        if isinstance(parent,AsmConstraintGroup):
            # This can happen when we are dropping another element link from the
            # same constraint group, in which case, 'owner' here will be the
            # parent constraint of the dropping element link
            subname = owner.Name + '.' + subname
            owner = parent.Object
            parent = parent.parent # ascend to the parent assembly
        if not isinstance(parent,Assembly):
            raise RuntimeError('not from the same assembly {},{}'.format(
                objName(owner),parent))
        subname = owner.Name + '.' + subname
        obj = self.ViewObject.Object
        mysub = parent.getConstraintGroup().Name + '.' + obj.Name + '.'
        sel = []
        if not elements:
            elements = ['']
        elements = [subname+element for element in elements]
        elements.append(mysub)
        sel = [Selection(Object=parent.Object,SubElementNames=elements)]
        typeid = Constraint.getTypeID(obj)
        return AsmConstraint.getSelection(typeid,sel)

    def canDropObjectEx(self,_obj,owner,subname,elements):
        cstr = self.ViewObject.Object
        if logger.catchTrace('Cannot drop to AsmConstraint '
            '{}'.format(cstr),self._getSelection,owner,subname,elements):
            return True
        return False

    def dropObjectEx(self,_vobj,_obj,owner,subname,elements):
        sel = self._getSelection(owner,subname,elements)
        cstr = self.ViewObject.Object
        typeid = Constraint.getTypeID(cstr)
        sel = AsmConstraint.Selection(SelObject=None,
                                    SelSubname=None,
                                    Assembly=sel.Assembly,
                                    Constraint=cstr,
                                    Elements=sel.Elements)
        AsmConstraint.make(typeid,sel,undo=False)

    def canDelete(self,_obj):
        return True


class AsmConstraintGroup(AsmGroup):
    def __init__(self,parent):
        self.parent = getProxy(parent,Assembly)
        super(AsmConstraintGroup,self).__init__()

    def getAssembly(self):
        return self.parent

    def canLoadPartial(self,_obj):
        return 2 if self.getAssembly().frozen else 0

    def linkSetup(self,obj):
        super(AsmConstraintGroup,self).linkSetup(obj)
        if not hasattr(obj,'_Version'):
            obj.addProperty("App::PropertyInteger","_Version","Base",'')
            obj.setPropertyStatus('_Version',['Hidden','Output'])

    def onChanged(self,obj,prop):
        if obj.Removing or FreeCAD.isRestoring():
            return
        if obj.Document and getattr(obj.Document,'Transacting',False):
            return
        if prop not in _IgnoredProperties:
            Assembly.autoSolve(obj,prop)

    @staticmethod
    def make(parent,name='Constraints'):
        obj = parent.Document.addObject("App::FeaturePython",name,
                AsmConstraintGroup(parent),None,True)
        ViewProviderAsmConstraintGroup(obj.ViewObject)
        obj.purgeTouched()
        return obj


class ViewProviderAsmConstraintGroup(ViewProviderAsmGroup):
    _iconName = 'Assembly_Assembly_Constraints_Tree.svg'

    def canDelete(self,_obj):
        return True

    def onDelete(self,_vobj,_subs):
        return False

    def updateData(self,obj,prop):
        if prop == 'Group':
            vis = len(obj.Group)!=0
            vobj = obj.ViewObject
            if vis != vobj.ShowInTree:
                vobj.ShowInTree = vis

    def canDropObjectEx(self,obj,_owner,_subname,_elements):
        return AsmPlainGroup.contains(self.ViewObject.Object,obj)

    def dropObjectEx(self,_vobj,obj,_owner,_subname,_elements):
        AsmPlainGroup.tryMove(obj,self.ViewObject.Object)


class AsmElementGroup(AsmGroup):
    def __init__(self,parent):
        self.parent = getProxy(parent,Assembly)
        super(AsmElementGroup,self).__init__()

    def linkSetup(self,obj):
        super(AsmElementGroup,self).linkSetup(obj)
        obj.cacheChildLabel()
        # 'PartialTrigger' is just for silencing warning when partial load
        self.Object.setPropertyStatus('VisibilityList', 'PartialTrigger')

    def getAssembly(self):
        return self.parent

    def onChildLabelChange(self,obj,label):
        names = set()
        label = label.replace('.','_')
        for o in flattenGroup(self.Object):
            if o != obj:
                names.add(o.Label)
        if label not in names:
            return label
        for i,c in enumerate(reversed(label)):
            if not c.isdigit():
                if i:
                    label = label[:-i]
                break;
        i=0
        while True:
            i=i+1;
            newLabel = '{}{:03d}'.format(label,i);
            if newLabel!=obj.Label and newLabel not in names:
                return newLabel
        return label

    @staticmethod
    def make(parent,name='Elements'):
        obj = parent.Document.addObject("App::FeaturePython",name,
                        AsmElementGroup(parent),None,True)
        ViewProviderAsmElementGroup(obj.ViewObject)
        obj.purgeTouched()
        return obj


class ViewProviderAsmElementGroup(ViewProviderAsmGroup):
    _iconName = 'Assembly_Assembly_Element_Tree.svg'

    def setupContextMenu(self,_vobj,menu):
        setupSortMenu(menu,self.sort,self.sortReverse)

    def sortReverse(self):
        sortChildren(self.ViewObject.Object,True)

    def sort(self):
        sortChildren(self.ViewObject.Object,False)

    def canDropObjectEx(self,obj,owner,subname,elements):
        if AsmPlainGroup.contains(self.ViewObject.Object,obj):
            return True
        if not owner:
            return False
        if not elements and not utils.isElement((owner,subname)):
            return False
        proxy = self.ViewObject.Object.Proxy
        return proxy.getAssembly().getPartGroup()==owner

    def dropObjectEx(self,vobj,obj,owner,subname,elements):
        if AsmPlainGroup.tryMove(obj,self.ViewObject.Object):
            return

        sels = FreeCADGui.Selection.getSelectionEx('*',False)
        if len(sels)==1 and \
           len(sels[0].SubElementNames)==1 and \
           sels[0].Object.getSubObject(
                   sels[0].SubElementNames[0],1)==vobj.Object:
            sel = sels[0]
        else:
            sel = None
        FreeCADGui.Selection.clearSelection()
        res = self._drop(obj,owner,subname,elements)
        if sel:
            for element in res:
                FreeCADGui.Selection.addSelection(sel.Object,
                        sel.SubElementNames[0]+element.Name+'.')

    def _drop(self,obj,owner,subname,elements):
        if not elements:
            elements = ['']
        res = []
        for element in elements:
            obj = AsmElement.make(AsmElement.Selection(
                SelObj=None, SelSubname=None,
                Element=None, Group=owner, Subname=subname+element))
            if obj:
                res.append(obj)
        return res

    def onDelete(self,_vobj,_subs):
        return False

    def canDelete(self,obj):
        return isTypeOf(obj,AsmPlainGroup)


class AsmRelationGroup(AsmBase):
    def __init__(self,parent):
        self.relations = {}
        self.parent = getProxy(parent,Assembly)
        super(AsmRelationGroup,self).__init__()

    def attach(self,obj):
        # AsmRelationGroup do not install LinkBaseExtension
        # obj.addExtension('App::LinkBaseExtensionPython', None)

        obj.addProperty('App::PropertyLinkList','Group','')
        obj.setPropertyStatus('Group','Hidden')
        obj.addProperty('App::PropertyLink','Constraints','')
        # this is to make sure relations are recomputed after all constraints
        obj.Constraints = self.parent.getConstraintGroup()
        obj.setPropertyStatus('Constraints',('Hidden','Immutable'))
        self.linkSetup(obj)

    def getViewProviderName(self,_obj):
        return ''

    def linkSetup(self,obj):
        super(AsmRelationGroup,self).linkSetup(obj)
        for o in obj.Group:
            o.Proxy.parent = self
            if o.Count:
                for child in o.Group:
                    if isTypeOf(child,AsmRelation):
                        child.Proxy.parent = o.Proxy

    def getAssembly(self):
        return self.parent

    def hasChildElement(self,_obj):
        return True

    def isElementVisible(self,obj,element):
        child = obj.Document.getObject(element)
        if not child or not getattr(child,'Part',None):
            return 0
        return self.parent.getPartGroup().isElementVisible(child.Part.Name)

    def setElementVisible(self,obj,element,vis):
        child = obj.Document.getObject(element)
        if not child or not getattr(child,'Part',None):
            return 0
        return self.parent.getPartGroup().setElementVisible(child.Part.Name,vis)

    def canLoadPartial(self,_obj):
        return 2 if self.getAssembly().frozen else 0

    def getRelations(self,refresh=False):
        if not refresh and getattr(self,'relations',None):
            return self.relations
        obj = self.Object
        self.relations = {}
        for o in obj.Group:
            if o.Part:
                self.relations[o.Part] = o
        group = []
        relations = self.relations.copy()
        touched = False
        new = []
        for part in self.getAssembly().getPartGroup().LinkedChildren:
            o = relations.get(part,None)
            if not o:
                touched = True
                new.append(AsmRelation.make(obj,part))
                group.append(new[-1])
                self.relations[part] = new[-1]
            else:
                group.append(o)
                relations.pop(part)

        if relations or touched:
            obj.Group = group
            obj.purgeTouched()

        removes = []
        for k,o in relations.items():
            self.relations.pop(k)
            if o.Count:
                for child in o.Group:
                    if isTypeOf(child,AsmRelation):
                        removes.append(child.Name)
            try:
                # This could fail if the object is already deleted due to
                # undo/redo
                removes.append(o.Name)
            except Exception:
                pass

        Assembly.scheduleDelete(obj.Document,removes)

        for o in new:
            o.Proxy.getConstraints()

        return self.relations

    def findRelation(self,part):
        relations = self.getRelations()
        if not isinstance(part,tuple):
            return relations.get(part,None)

        relation = relations.get(part[0],None)
        if not relation:
            return
        if part[1]>=relation.Count:
            relation.recompute()
        group = relation.Group
        try:
            relation = group[part[1]]
            checkType(relation,AsmRelation)
            return relation
        except Exception as e:
            logger.error('invalid relation of part array: {}',e)

    def update(self,cstr,oldPart,newPart,partName):
        relation = self.findRelation(oldPart)
        if relation:
            try:
                group = relation.Group
                group.remove(cstr)
                relation.Group = group
            except ValueError:
                pass
        relation = self.findRelation(newPart)
        if not relation:
            logger.warn('Cannot find relation of part {}',partName)
        elif cstr not in relation.Group:
            relation.Group = {-1:cstr}

    @staticmethod
    def make(parent,name='Relations'):
        obj = parent.Document.addObject("App::FeaturePython",name,
                    AsmRelationGroup(parent),None,True)
        ViewProviderAsmRelationGroup(obj.ViewObject)
        obj.Label = name
        obj.purgeTouched()
        return obj

    @staticmethod
    def gotoRelationOfConstraint(obj,subname):
        sobj = obj.getSubObject(subname,1)
        if not isTypeOf(sobj,AsmConstraint):
            return
        subname = flattenLastSubname(obj,subname)
        sub = Part.splitSubname(subname)[0].split('.')
        sub = sub[:-1]
        sub[-2] = '3'
        sub[-1] = ''
        sub = '.'.join(sub)
        subs = []
        relationGroup = sobj.Proxy.getAssembly().getRelationGroup(True)
        for relation in relationGroup.Proxy.getRelations().values():
            for o in relation.Group:
                if isTypeOf(o,AsmRelation):
                    found = False
                    for child in o.Group:
                        if child == sobj:
                            subs.append('{}{}.{}.{}.'.format(
                                sub,relation.Name,o.Name,child.Name))
                            found = True
                            break
                    if found:
                        continue
                elif o == sobj:
                    subs.append('{}{}.{}.'.format(sub,relation.Name,o.Name))

        if subs:
            FreeCADGui.Selection.pushSelStack()
            FreeCADGui.Selection.clearSelection()
            FreeCADGui.Selection.addSelection(obj,subs)
            FreeCADGui.Selection.pushSelStack()
            FreeCADGui.runCommand('Std_TreeSelection')

    @staticmethod
    def gotoRelation(moveInfo):
        if not moveInfo:
            return

        subname = moveInfo.SelSubname
        info = moveInfo.ElementInfo
        sobj = moveInfo.SelObj.getSubObject(moveInfo.SelSubname,1)

        if isTypeOf(sobj,AsmConstraint):
            AsmRelationGroup.gotoRelationOfConstraint(
                    moveInfo.SelObj, moveInfo.SelSubname)
            return

        if len(moveInfo.HierarchyList)>1 and \
                isTypeOf(sobj,(AsmElement,AsmElementLink)):
            hierarchy = moveInfo.HierarchyList[-1]
            info = getElementInfo(hierarchy.Object, hierarchy.Subname)
        else:
            hierarchy = moveInfo.Hierarchy

        if not info.Subname:
            subname = flattenLastSubname(moveInfo.SelObj,subname,hierarchy)
            subs = subname.split('.')
        elif moveInfo.SelSubname.endswith(info.Subname):
            subname = flattenLastSubname(
                    moveInfo.SelObj,subname[:-len(info.Subname)])
            subs = subname.split('.')
        else:
            subname = flattenLastSubname(moveInfo.SelObj,subname,hierarchy)
            subs = subname.split('.')
            if isTypeOf(sobj,AsmElementLink):
                subs = subs[:-3]
            elif isTypeOf(sobj,AsmElement):
                subs = subs[:-2]
            else:
                raise RuntimeError('Invalid selection {}.{}, {}'.format(
                    objName(moveInfo.SelObj),moveInfo.SelSubname,subname))
            if isinstance(info.Part,tuple):
                subs += ['','','']
            else:
                subs += ['','']

        relationGroup = resolveAssembly(info.Parent).getRelationGroup(True)
        if isinstance(info.Part,tuple):
            part = info.Part[0]
        else:
            part = info.Part
        relation = relationGroup.Proxy.findRelation(part)
        if not relation:
            return
        if isinstance(info.Part,tuple):
            if len(subs)<4:
                subs.append('')
            subs[-4] = '3'
            subs[-3] = relation.Name
            subs[-2] = relation.Group[info.Part[1]].Name
        else:
            subs[-3] = '3'
            subs[-2] = relation.Name
        FreeCADGui.Selection.pushSelStack()
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(moveInfo.SelObj,'.'.join(subs))
        FreeCADGui.Selection.pushSelStack()
        FreeCADGui.runCommand('Std_TreeSelection')


class ViewProviderAsmRelationGroup(ViewProviderAsmBase):
    _iconName = 'Assembly_Assembly_Relation_Tree.svg'

    def canDropObjects(self):
        return False

    def claimChildren(self):
        return self.ViewObject.Object.Group

    def onDelete(self,vobj,_subs):
        obj = vobj.Object
        relations = obj.Group
        obj.Group = []
        for o in relations:
            if o.Count:
                group = o.Group
                o.Group = []
                for child in group:
                    if isTypeOf(child,AsmRelation):
                        child.Document.removeObject(child.Name)
            o.Document.removeObject(o.Name)
        return True


class AsmRelation(AsmBase):
    def __init__(self,parent):
        self.parent = getProxy(parent,(AsmRelationGroup,AsmRelation))
        super(AsmRelation,self).__init__()

    def linkSetup(self,obj):
        super(AsmRelation,self).linkSetup(obj)
        obj.configLinkProperty(LinkedObject = 'Part')

    def attach(self,obj):
        obj.addProperty("App::PropertyLink","Part"," Link",'')
        obj.setPropertyStatus('Part','ReadOnly')
        obj.addProperty("App::PropertyInteger","Count"," Link",'')
        obj.setPropertyStatus('Count','Hidden')
        obj.addProperty("App::PropertyInteger","Index"," Link",'')
        obj.setPropertyStatus('Index','Hidden')
        obj.addProperty('App::PropertyLinkList','Group','')
        obj.setPropertyStatus('Group','Hidden')
        super(AsmRelation,self).attach(obj)

    def getSubObject(self,obj,subname,retType,mat,transform,depth):
        if not subname or subname[0]==';':
            return False
        idx = subname.find('.')
        if idx<0:
            return False
        name = subname[:idx]
        for o in obj.Group:
            if o.Name == name:
                return o.getSubObject(subname[idx+1:],
                        retType,mat,transform,depth+1)

    def getAssembly(self):
        return self.parent.getAssembly()

    def updateLabel(self):
        obj = self.Object
        if obj.Part:
            obj.Label = obj.Part.Label

    def execute(self,obj):
        part = obj.Part
        if not part:
            return False

        if not isinstance(self.parent,AsmRelationGroup):
            return False

        count = getLinkProperty(part,'ElementCount',0)
        remove = []
        if obj.Count > count:
            group = obj.Group
            remove = [o.Name for o in group[count:]]
            obj.Group = group[:count]
            Assembly.scheduleDelete(obj.Document,remove)
            obj.Count = count
            self.getConstraints()
        elif obj.Count < count:
            new = []
            for i in xrange(obj.Count,count):
                new.append(AsmRelation.make(obj,(part,i)))
            obj.Count = count
            obj.Group = obj.Group[:obj.Count]+new
            for o in new:
                o.Proxy.getConstraints()

        return False

    def allowDuplicateLabel(self,_obj):
        return True

    def hasChildElement(self,_obj):
        return True

    def _getGroup(self):
        if isinstance(self.parent,AsmRelation):
            return self.parent.Object.Part
        return self.getAssembly().getConstraintGroup()

    def isElementVisible(self,obj,element):
        if not obj.Part:
            return
        child = obj.Document.getObject(element)
        if isTypeOf(child,AsmRelation):
            group = obj.Part
            element = str(child.Index)
        else:
            group = self.getAssembly().getConstraintGroup()
        return group.isElementVisible(element)

    def setElementVisible(self,obj,element,vis):
        if not obj.Part:
            return
        child = obj.Document.getObject(element)
        if isTypeOf(child,AsmRelation):
            group = obj.Part
            element = str(child.Index)
        else:
            group = self.getAssembly().getConstraintGroup()
        return group.setElementVisible(element,vis)

    def redirectSubName(self,obj,subname,_topParent,child):
        if not obj.Part:
            return
        if isinstance(self.parent,AsmRelation):
            subname = subname.split('.')
            if not child:
                subname[-3] = self.getAssembly().getPartGroup().Name
                subname[-2] = obj.Part.Name
                subname[-1] = str(obj.Index)
                subname.append('')
            else:
                subname[-3] = self.getAssembly().getConstraintGroup().Name
                subname[-2] = ''
                subname = subname[:-1]
        elif not child:
            subname = subname.split('.')
            subname[-2] = self.getAssembly().getPartGroup().Name
            subname[-1] = obj.Part.Name
            subname.append('')
        elif isTypeOf(child,AsmConstraint):
            subname = subname.split('.')
            subname[-2] = self.getAssembly().getConstraintGroup().Name
        else:
            return
        return '.'.join(subname)

    def getConstraints(self):
        obj = self.Object
        if obj.Count or not obj.Part:
            return
        if isinstance(self.parent,AsmRelation):
            part = (obj.Part,obj.Index)
        else:
            part = obj.Part
        group = []
        for cstr in flattenGroup(self.getAssembly().getConstraintGroup()):
            for element in cstr.Group:
                info = element.Proxy.getInfo()
                if isinstance(info.Part,tuple):
                    infoPart = info.Part[:2]
                else:
                    infoPart = info.Part
                if infoPart==part:
                    group.append(cstr)
                    break
        obj.Group = group
        obj.purgeTouched()

    @staticmethod
    def make(parent,part,name='Relation'):
        obj = parent.Document.addObject("App::FeaturePython",name,
                    AsmRelation(parent),None,True)
        ViewProviderAsmRelation(obj.ViewObject)
        if isinstance(part,tuple):
            obj.setLink(part[0])
            obj.Index = part[1]
            obj.Label = str(part[1])
        else:
            obj.setLink(part)
            obj.Label = part.Label
        obj.recompute()
        obj.setPropertyStatus('Index','Immutable')
        obj.purgeTouched()
        return obj


class ViewProviderAsmRelation(ViewProviderAsmBase):

    def canDropObjects(self):
        return False

    def onDelete(self,_vobj,_subs):
        return False

    def canDelete(self,_obj):
        return True

    def claimChildren(self):
        return self.ViewObject.Object.Group


BuildShapeNone = 'None'
BuildShapeCompound = 'Compound'
BuildShapeFuse = 'Fuse'
BuildShapeCut = 'Cut'
BuildShapeCommon = 'Common'
BuildShapeNames = (BuildShapeNone,BuildShapeCompound,
        BuildShapeFuse,BuildShapeCut,BuildShapeCommon)

class Assembly(AsmGroup):
    _Busy = False
    _PartMap = {} # maps part to assembly
    _PartArrayMap = {} # maps array part to assembly
    _ScheduleTimer = QtCore.QTimer()
    _PendingReload = defaultdict(set)
    _PendingSolve = False

    def __init__(self):
        self.parts = set()
        self.partArrays = set()
        self.constraints = None
        self.frozen = False
        self.deleting = False
        super(Assembly,self).__init__()

    def getSubObjects(self,obj,reason):
        # Deletion order problem may cause exception here. Just silence it
        try:
            if reason:
                return [o.Name+'.' for o in obj.Group]
            partGroup = self.getPartGroup()
            return ['{}.{}'.format(partGroup.Name,name)
                        for name in partGroup.getSubObjects(reason)]
        except Exception:
            pass

    def _collectParts(self,oldParts,newParts,partMap):
        for part in newParts:
            try:
                oldParts.remove(part)
            except KeyError:
                partMap[part] = self
        for part in oldParts:
            del partMap[part]

    def execute(self,obj):
        if self.frozen:
            return True

        parts = set()
        partArrays = set()
        self.constraints = None

        self.buildShape()
        System.touch(obj)
        obj.ViewObject.Proxy.onExecute()

        # collect the part objects of this assembly
        for cstr in self.getConstraints():
            for element in cstr.Proxy.getElements():
                info = element.Proxy.getInfo()
                if isinstance(info.Part,tuple):
                    partArrays.add(info.Part[0])
                    parts.add(info.Part[0])
                else:
                    parts.add(info.Part)

        # Update the global part object list for auto solving
        #
        # Assembly._PartMap is used to track normal part object for change in
        # its 'Placement'
        #
        # Assembly._PartArrayMap is for tracking link array for change in its
        # 'PlacementList'

        self._collectParts(self.parts,parts,Assembly._PartMap)
        self.parts = parts
        self._collectParts(self.partArrays,partArrays,Assembly._PartArrayMap)
        self.partArrays = partArrays

        return False # return False to call LinkBaseExtension::execute()

    @classmethod
    def canAutoSolve(cls):
        from . import solver
        return gui.AsmCmdManager.WorkbenchActivated and \
               gui.AsmCmdManager.AutoRecompute and \
               FreeCADGui.ActiveDocument and \
               not FreeCADGui.ActiveDocument.Transacting and \
               not FreeCAD.isRestoring() and \
               not solver.isBusy() and \
               not ViewProviderAssembly.isBusy()

    @classmethod
    def checkPartChange(cls, obj, prop):
        if prop == 'Label':
            try:
                cls._PartMap.get(obj).getRelationGroup().\
                    Proxy.findRelation(obj).\
                    Proxy.updateLabel()
            except Exception:
                pass
            return

        if not cls.canAutoSolve() or prop in _IgnoredProperties:
            return
        assembly = None
        if prop == 'Placement':
            partMap = cls._PartMap
            assembly = partMap.get(obj,None)
        elif prop == 'PlacementList':
            partMap = cls._PartArrayMap
            assembly = partMap.get(obj,None)
        if assembly:
            try:
                # This will fail if assembly got deleted
                assembly.Object.Name
            except Exception:
                del partMap[obj]
            else:
                cls.autoSolve(obj,prop,True)

    @classmethod
    def autoSolve(cls,obj,prop,force=False):
        if obj.Document and getattr(obj.Document,'Transacting',False):
            cls.cancelAutoSolve()
            return
        if not force and cls._PendingSolve:
            return
        if force or cls.canAutoSolve():
            logger.debug('auto solve scheduled on change of {}.{}',
                objName(obj),prop,frame=1)
            cls._PendingSolve = True

    @classmethod
    def cancelAutoSolve(cls):
        logger.debug('cancel auto solve',frame=1)
        cls._PendingSolve = False

    @classmethod
    def doAutoSolve(cls):
        canSolve = cls.canAutoSolve()
        if cls._Busy or not canSolve:
            cls._PendingSolve = canSolve
            return

        cls.cancelAutoSolve()

        from . import solver
        logger.debug('start solving...')
        logger.catch('solver exception when auto recompute',
                solver.solve, FreeCAD.ActiveDocument.Objects, True)
        logger.debug('done solving')

    @classmethod
    def scheduleDelete(cls,doc,names):
        # FC core now support pending remove, so no need to schedule here
        for name in names:
            try:
                doc.removeObject(name)
            except Exception:
                pass

    @classmethod
    def scheduleReload(cls,obj):
        cls._PendingReload[obj.Document.Name].add(obj.Name)
        cls.schedule()

    @classmethod
    def schedule(cls):
        if not cls._ScheduleTimer.isSingleShot():
            cls._ScheduleTimer.setSingleShot(True)
            cls._ScheduleTimer.timeout.connect(Assembly.onSchedule)
        if not cls._ScheduleTimer.isActive():
            cls._ScheduleTimer.start(50)

    @classmethod
    def pauseSchedule(cls):
        cls._Busy = True
        cls._ScheduleTimer.stop()

    @classmethod
    def resumeSchedule(cls):
        cls._Busy = False
        cls.schedule()

    @classmethod
    def onSchedule(cls):
        for name,onames in cls._PendingReload.items():
            doc = FreeCADGui.reload(name)
            if not doc:
                break
            for oname in onames:
                obj = doc.getObject(oname)
                if getattr(obj,'Freeze',None):
                    obj.Freeze = False
        cls._PendingReload.clear()

    def onSolverChanged(self):
        for obj in self.getConstraintGroup().LinkedChildren:
            # setup==True usually means we are restoring, so try to restore the
            # non-touched state if possible, since recompute() below will touch
            # the constraint object
            touched = 'Touched' in obj.State
            obj.recompute()
            if not touched:
                obj.purgeTouched()

    def upgrade(self):
        'Upgrade old assembly objects to the new version'
        partGroup = self.getPartGroup()
        if partGroup.isDerivedFrom('Part::FeaturePython'):
            return
        partGroup.setPropertyStatus('GroupMode','-Immutable')
        partGroup.GroupMode = 0 # prevent auto delete children
        newPartGroup = AsmPartGroup.make(self.Object)
        newPartGroup.Group = partGroup.Group
        newPartGroup.setPropertyStatus('VisibilityList','-Immutable')
        newPartGroup.VisibilityList = partGroup.VisibilityList
        newPartGroup.setPropertyStatus('VisibilityList','Immutable')

        elementGroup = self.getElementGroup()
        vis = elementGroup.VisibilityList
        elements = []
        old = elementGroup.Group
        for element in old:
            copy = AsmElement.create('Element',elementGroup)
            link = element.LinkedObject
            if isinstance(link,tuple):
                copy.LinkedObject = (newPartGroup,link[1])
            copy.Label = element.Label
            copy.Proxy._initializing = False
            elements.append(copy)

        elementGroup.setPropertyStatus('Group','-Immutable')
        elementGroup.Group = elements
        elementGroup.setPropertyStatus('Group','Immutable')
        elementGroup.setPropertyStatus('VisibilityList','-Immutable')
        elementGroup.VisibilityList = vis
        elementGroup.setPropertyStatus('VisibilityList','Immutable')
        elementGroup.cacheChildLabel()

        for element in old:
            element.Document.removeObject(element.Name)

        self.Object.setLink({2:newPartGroup})

        # no need to remove the object as Assembly has group mode of AutoDelete
        #
        #  partGroup.Document.removeObject(partGroup.Name)

        elementGroup.recompute(True)

    def buildShape(self):
        obj = self.Object
        partGroup = self.getPartGroup()
        if not obj.Freeze and obj.BuildShape==BuildShapeNone:
            obj.Shape = Part.Shape();
            try:
                partGroup.Shape = Part.Shape()
            except Exception:
                pass
            return

        group = flattenGroup(partGroup)

        shapes = []
        if obj.BuildShape == BuildShapeCompound or \
           (obj.BuildShape==BuildShapeNone and obj.Freeze):
            for o in group:
                if partGroup.isElementVisible(o.Name):
                    shape = Part.getShape(o)
                    if not shape.isNull():
                        shapes.append(shape)
        else:
            # first shape is always included regardless of its visibility
            solids = Part.getShape(group[0]).Solids
            if solids:
                if len(solids)>1 and obj.BuildShape!=BuildShapeFuse:
                    shapes.append(solids[0].fuse(solids[1:]))
                else:
                    shapes += solids
                group = group[1:]
            for o in group:
                if partGroup.isElementVisible(o.Name):
                    shape = Part.getShape(o)
                    # in case the first part have solids, we only include
                    # subsequent part containing solid
                    if solids:
                        shapes += shape.Solids
                    else:
                        shapes += shape
        if not shapes:
            raise RuntimeError('No shape found in parts')
        if len(shapes) == 1:
            # hide shape placement, and get element mapping
            shape = Part.makeCompound(shapes)
        elif obj.BuildShape == BuildShapeFuse:
            shape = shapes[0].fuse(shapes[1:])
        elif obj.BuildShape == BuildShapeCut:
            shape = shapes[0].cut(shapes[1:])
        elif obj.BuildShape == BuildShapeCommon:
            shape = shapes[0].common(shapes[1:])
        else:
            shape = Part.makeCompound(shapes)

        try:
            if obj.Freeze or obj.BuildShape!=BuildShapeCompound:
                partGroup.Shape = shape
                shape.Tag = partGroup.ID
            else:
                partGroup.Shape = Part.Shape()
        except Exception:
            pass

        shape.Placement = obj.Placement
        obj.Shape = shape

    def attach(self, obj):
        obj.addProperty("App::PropertyEnumeration","BuildShape","Base",'')
        obj.addProperty("App::PropertyInteger","_Version","Base",'')
        obj.setPropertyStatus('_Version',['Hidden','Output'])
        obj._Version = 1
        obj.BuildShape = BuildShapeNames
        super(Assembly,self).attach(obj)

    def linkSetup(self,obj):
        self.parts = set()
        self.partArrays = set()
        obj.configLinkProperty('Placement')
        if not hasattr(obj,'ColoredElements'):
            obj.addProperty("App::PropertyLinkSubHidden",
                    "ColoredElements","Base",'')
        obj.setPropertyStatus('ColoredElements',('Hidden','Immutable'))
        obj.configLinkProperty('ColoredElements')
        if not hasattr(obj,'Freeze'):
            obj.addProperty('App::PropertyBool','Freeze','Base','')
        obj.setPropertyStatus('Freeze','PartialTrigger')
        super(Assembly,self).linkSetup(obj)
        obj.setPropertyStatus('Group','Output')
        System.attach(obj)

        # make sure all children are there, first constraint group, then element
        # group, and finally part group. Call getPartGroup below will make sure
        # all groups exist. The order of the group is important to make sure
        # correct rendering and picking behavior
        partGroup = self.getPartGroup(True)

        if not getattr(obj,'_Version',None):
            cstrGroup = self.getConstraintGroup().Proxy
            for o in flattenGroup(cstrGroup.Object):
                cstr = getProxy(o,AsmConstraint)
                cstr.parent = cstrGroup
                for oo in flattenGroup(o):
                    oo.Proxy.parent = cstr
            elementGroup = self.getElementGroup().Proxy
            for o in flattenGroup(elementGroup.Object):
                element = getProxy(o,AsmElement)
                element.parent = elementGroup

        self.getRelationGroup()

        self.frozen = obj.Freeze
        if not self.frozen:
            cstrGroup = self.getConstraintGroup()
            if cstrGroup._Version<=0:
                cstrGroup._Version = 1
                for cstr in flattenGroup(cstrGroup):
                    for link in flattenGroup(cstr):
                        link.Proxy.migrate(link)

        if self.frozen or partGroup.isDerivedFrom('Part::FeaturePython'):
            shape = Part.Shape(partGroup.Shape)
            shape.Placement = obj.Placement
            shape.Tag = obj.ID
            obj.Shape = shape
        if obj.Shape.isNull() and \
             obj.BuildShape == BuildShapeCompound:
            self.buildShape()

        System.touch(obj,False)

    def onChanged(self, obj, prop):
        if obj.Removing or \
           not getattr(self,'Object',None) or \
           FreeCAD.isRestoring():
            return
        if obj.Document and getattr(obj.Document,'Transacting',False):
            if prop == 'Freeze':
                self.frozen = obj.Freeze
            System.onChanged(obj,prop)
            return
        if prop == 'BuildShape':
            self.buildShape()
            return
        if prop == 'Freeze':
            if obj.Freeze == self.frozen:
                return
            if obj.Document.Partial:
                Assembly.scheduleReload(obj)
                return
            self.upgrade()
            if obj.BuildShape==BuildShapeNone:
                self.buildShape()
            elif obj.Freeze:
                self.getPartGroup().Shape = obj.Shape
            else:
                self.getPartGroup().Shape = Part.Shape()
            self.frozen = obj.Freeze
            return
        if prop!='Group' and prop not in _IgnoredProperties:
            System.onChanged(obj,prop)
            Assembly.autoSolve(obj,prop)

    def getConstraintGroup(self, create=False):
        obj = self.Object
        try:
            ret = obj.Group[0]
            if obj.Freeze:
                if not isTypeOf(ret,AsmConstraintGroup):
                    return
            else:
                checkType(ret,AsmConstraintGroup)
            parent = getattr(ret.Proxy,'parent',None)
            if not parent:
                ret.Proxy.parent = self
            elif parent!=self:
                raise RuntimeError('invalid parent of constraint group '
                    '{}'.format(objName(ret)))
            return ret
        except IndexError:
            if not create or obj.Group:
                raise RuntimeError('Invalid assembly')
            ret = AsmConstraintGroup.make(obj)
            obj.setLink({0:ret})
            return ret

    def getConstraints(self,refresh=False):
        if not refresh:
            ret = getattr(self,'constraints',None)
            if ret:
                return ret
        self.constraints = []
        cstrGroup = self.getConstraintGroup()
        if not cstrGroup:
            return []
        ret = []
        for o in flattenGroup(cstrGroup):
            checkType(o,AsmConstraint)
            if Constraint.isDisabled(o):
                logger.debug('skip constraint {}',cstrName(o))
                continue
            if not System.isConstraintSupported(self.Object,
                       Constraint.getTypeName(o)):
                logger.warn('skip unsupported constraint '
                    '{}',cstrName(o))
                continue
            ret.append(o)
        self.constraints = ret
        return self.constraints

    def getElementGroup(self,create=False):
        obj = self.Object
        if create:
            # make sure previous group exists
            self.getConstraintGroup(True)
        try:
            ret = obj.Group[1]
            checkType(ret,AsmElementGroup)
            parent = getattr(ret.Proxy,'parent',None)
            if not parent:
                ret.Proxy.parent = self
            elif parent!=self:
                raise RuntimeError('invalid parent of element group '
                    '{}'.format(objName(ret)))
            return ret
        except IndexError:
            if not create:
                raise RuntimeError('Missing element group')
            ret = AsmElementGroup.make(obj)
            obj.setLink({1:ret})
            return ret

    def getPartGroup(self,create=False):
        obj = self.Object
        if create:
            # make sure previous group exists
            self.getElementGroup(True)
        try:
            ret = obj.Group[2]
            checkType(ret,AsmPartGroup)
            parent = getattr(ret.Proxy,'parent',None)
            if not parent:
                ret.Proxy.parent = self
                ret.Proxy.checkDerivedParts()
            elif parent!=self:
                raise RuntimeError(
                        'invalid parent of part group {}'.format(objName(ret)))
            return ret
        except IndexError:
            if not create:
                raise RuntimeError('Missing part group')
            ret = AsmPartGroup.make(obj)
            obj.setLink({2:ret})
            return ret

    def getRelationGroup(self,create=False):
        obj = self.Object
        if create:
            # make sure previous group exists
            self.getPartGroup(True)
        try:
            ret = obj.Group[3]
            if obj.Freeze:
                if not isTypeOf(ret,AsmRelationGroup):
                    return
            else:
                checkType(ret,AsmRelationGroup)
            parent = getattr(ret.Proxy,'parent',None)
            if not parent:
                ret.Proxy.parent = self
            elif parent!=self:
                raise RuntimeError(
                    'invalid parent of relation group {}'.format(objName(ret)))
            return ret
        except IndexError:
            if create:
                ret = AsmRelationGroup.make(obj)
                touched = 'Touched' in obj.State
                obj.setLink({3:ret})
                if not touched:
                    obj.purgeTouched()
                return ret

    @staticmethod
    def addOrigin(partGroup, name=None):
        obj = None
        for o in flattenGroup(partGroup):
            if o.TypeId == 'App::Origin':
                obj = o
                break
        if not obj:
            if not name:
                name = 'Origin'
            obj = partGroup.Document.addObject('App::Origin',name)
            partGroup.setLink({-1:obj})

        partGroup.recompute(True)
        shape = Part.getShape(partGroup)
        if not shape.isNull():
            bbox = shape.BoundBox
            if bbox.isValid():
                obj.ViewObject.Size = tuple([
                    max(abs(a),abs(b)) for a,b in (
                        (bbox.XMin,bbox.XMax),
                        (bbox.YMin,bbox.YMax),
                        (bbox.ZMin,bbox.ZMax)) ])
        return obj

    @staticmethod
    def make(doc=None,name='Assembly',undo=True):
        if not doc:
            doc = FreeCAD.ActiveDocument
            if not doc:
                raise RuntimeError('No active document')
        if undo:
            FreeCAD.setActiveTransaction('Create assembly')
        try:
            obj = doc.addObject("Part::FeaturePython",name,Assembly(),None,True)
            obj.setPropertyStatus('Shape','Transient')
            ViewProviderAssembly(obj.ViewObject)
            obj.Visibility = True
            if gui.AsmCmdManager.AddOrigin:
                Assembly.addOrigin(obj.Proxy.getPartGroup())
            obj.purgeTouched()
            if undo:
                FreeCAD.closeActiveTransaction()
            FreeCADGui.Selection.pushSelStack()
            FreeCADGui.Selection.clearSelection()
            FreeCADGui.Selection.addSelection(obj)
            FreeCADGui.Selection.pushSelStack()
        except Exception:
            if undo:
                FreeCAD.closeActiveTransaction(True)
            raise
        return obj

    Info = namedtuple('AssemblyInfo',('Assembly','Object','Subname'))

    @staticmethod
    def getSelection(sels=None):
        'Find all assembly objects among the current selection'
        objs = set()
        if sels is None:
            sels = FreeCADGui.Selection.getSelectionEx('',False)
        for sel in sels:
            if not sel.SubElementNames:
                if isTypeOf(sel.Object,Assembly,True):
                    objs.add(sel.Object)
                continue
            for subname in sel.SubElementNames:
                ret = Assembly.find(sel.Object,subname,keepEmptyChild=True)
                if ret:
                    objs.add(ret.Assembly)
        return tuple(objs)

    @staticmethod
    def find(obj,subname,childType=None,
            recursive=False,relativeToChild=True,keepEmptyChild=False):
        '''
        Find the immediate child of the first Assembly referenced in 'subs'

        obj: the parent object

        subname: '.' separated sub-object reference, or string list of
        sub-object names. Must contain no sub-element name.

        childType: optional checking of the child type.

        recursive: If True, continue finding the child of the next assembly.

        relativeToChild: If True, the returned subname is realtive to the child
        object found, or else, it is relative to the assembly, i.e., including
        the child's name

        Return None if not found, or (assembly,child,sub), where 'sub' is the
        remaining sub name list. If recursive is True, then return a list of
        tuples
        '''
        assembly = None
        child = None
        if isTypeOf(obj,Assembly,True):
            assembly = obj
        subs = subname if isinstance(subname,list) else subname.split('.')
        i= 0
        for i,name in enumerate(subs[:-1]):
            sobj = obj.getSubObject(name+'.',1)
            if not sobj:
                raise RuntimeError('Cannot find sub-object {}, '
                    '{}'.format(objName(obj),name))
            obj = sobj
            if assembly and isTypeOf(obj,childType):
                child = obj
                break
            assembly = obj if isTypeOf(obj,Assembly,True) else None

        if not child:
            if keepEmptyChild and assembly:
                ret = Assembly.Info(Assembly=assembly,Object=None,Subname='')
                return [ret] if recursive else ret
            return

        ret = Assembly.Info(Assembly = assembly, Object = child,
            Subname = '.'.join(subs[i+1:] if relativeToChild else subs[i:]))

        if not recursive:
            return ret

        nret = Assembly.find(child, subs[i+1:], childType, recursive,
                relativeToChild, keepEmptyChild)
        if nret:
            return [ret] + nret
        return [ret]

    @staticmethod
    def findChildren(obj,subname,tp=None):
        return Assembly.find(obj,subname,tp,True,False,True)

    @staticmethod
    def findPartGroup(obj,subname='2.',recursive=False,relativeToChild=True):
        return Assembly.find(
                obj,subname,AsmPartGroup,recursive,relativeToChild)

    @staticmethod
    def findElementGroup(obj,subname='1.',relativeToChild=True):
        return Assembly.find(
                obj,subname,AsmElementGroup,False,relativeToChild)

    @staticmethod
    def findConstraintGroup(obj,subname='0.',relativeToChild=True):
        return Assembly.find(
                obj,subname,AsmConstraintGroup,False,relativeToChild)

    @staticmethod
    def fromLinkGroup(obj):
        block = gui.AsmCmdManager.AutoRecompute
        if block:
            gui.AsmCmdManager.AutoRecompute = False
        try:
            removes = set()
            table = {}
            asm = Assembly._fromLinkGroup(obj,table,removes)
            for o in removes:
                o.Document.removeObject(o.Name)
            asm.recompute(True)
            return asm
        finally:
            if block:
                gui.AsmCmdManager.AutoRecompute = True

    @staticmethod
    def _fromLinkGroup(obj,table,removes):
        mapped = table.get(obj,None)
        if mapped:
            return mapped

        if hasattr(obj,'Shape'):
            return obj

        linked = obj.getLinkedObject(False)
        if linked==obj and getattr(obj,'ElementCount',0):
            linked = obj.LinkedObject

        if linked != obj:
            mapped = Assembly._fromLinkGroup(linked,table,removes)
            if mapped != linked:
                obj.setLink(mapped)
            table[obj] = obj
            return obj

        children = []
        hiddens = []
        subs = obj.getSubObjects()
        for sub in subs:
            child,parent,childName,_ = obj.resolve(sub)
            if not child:
                logger.warn('failed to find sub object {}.{}'.format(
                    obj.Name,sub))
                continue
            asm = Assembly._fromLinkGroup(child,table,removes)
            children.append(asm)
            if not parent.isElementVisible(childName):
                hiddens.append(asm.Name)
            asm.Visibility = False

        asm = Assembly.make(obj.Document,undo=False)
        asm.Label = obj.Label
        asm.Placement = obj.Placement
        partGroup = asm.Proxy.getPartGroup()
        partGroup.setLink(children)
        for sub in hiddens:
            partGroup.setElementVisible(sub,False)
        table[obj] = asm
        removes.add(obj)
        return asm

class ViewProviderAssembly(ViewProviderAsmGroup):
    _iconName = 'Assembly_Assembly_Frozen_Tree.svg'

    def __init__(self,vobj):
        self._movingPart = None
        super(ViewProviderAssembly,self).__init__(vobj)

    def setupContextMenu(self,vobj,menu):
        obj = vobj.Object
        action = QtGui.QAction(QtGui.QIcon(),
                "Unfreeze" if obj.Freeze else "Freeze", menu)
        QtCore.QObject.connect(
                action,QtCore.SIGNAL("triggered()"),self.toggleFreeze)
        menu.addAction(action)

    def toggleFreeze(self):
        obj = self.ViewObject.Object
        FreeCAD.setActiveTransaction(
                'Unfreeze assembly' if obj.Freeze else 'Freeze assembly')
        try:
            obj.Freeze = not obj.Freeze
            FreeCAD.closeActiveTransaction()
        except Exception:
            FreeCAD.closeActiveTransaction(True)
            raise

    def attach(self,vobj):
        super(ViewProviderAssembly,self).attach(vobj)
        if not hasattr(vobj,'ShowParts'):
            vobj.addProperty("App::PropertyBool","ShowParts"," Link")

    def canAddToSceneGraph(self):
        return True

    def onDelete(self,vobj,_subs):
        assembly = vobj.Object.Proxy
        for o in assembly.getPartGroup().LinkedChildren:
            if o.isDerivedFrom('App::Origin'):
                o.Document.removeObject(o.Name)
                break
        return True

    def canDelete(self,obj):
        return isTypeOf(obj,AsmRelationGroup)

    def _convertSubname(self,owner,subname):
        sub = subname.split('.')
        if not sub:
            return
        me = self.ViewObject.Object
        partGroup = me.Proxy.getPartGroup().ViewObject
        if sub[0] == me.Name:
            return partGroup,partGroup,subname[len(sub[0])+1:]
        return partGroup,owner,subname

    def canDropObjectEx(self,obj,owner,subname,_elements):
        info = self._convertSubname(owner,subname)
        if not info:
            return False
        partGroup,owner,subname = info
        return partGroup.canDropObject(obj,owner,subname)

    def canDragAndDropObject(self,_obj):
        return True

    def dropObjectEx(self,_vobj,obj,owner,subname,_elements):
        info = self._convertSubname(owner,subname)
        if not info:
            return False
        partGroup,owner,subname = info
        return '2.{}'.format(partGroup.dropObject(obj,owner,subname))

    def getDropPrefix(self):
        return '2.'

    def getIcon(self):
        if getattr(self.ViewObject.Object,'Freeze',False):
            return utils.getIcon(self.__class__)
        return System.getIcon(self.ViewObject.Object)

    def doubleClicked(self, vobj):
        from . import mover
        sel = FreeCADGui.Selection.getSelection('',0)
        if not sel:
            return False
        if sel[0].getLinkedObject(True) == vobj.Object:
            vobj = sel[0].ViewObject
            return vobj.Document.setEdit(vobj,1)
        if logger.catchDebug('',mover.movePart):
            return True
        return False

    def onExecute(self):
        if not getattr(self,'_movingPart',None):
            return

        pla = logger.catch('exception when update moving part',
                self._movingPart.update)
        if pla:
            self.ViewObject.DraggingPlacement = pla
            return

        # Must NOT call resetEdit() here. Because we are called through dragger
        # callback, meaning that we are called during coin node traversal.
        # resetEdit() will cause View3DInventorView to reset editing root node.
        # And disaster will happen when modifying coin node tree while
        # traversing.
        #
        #  doc = FreeCADGui.editDocument()
        #  if doc:
        #      doc.resetEdit()

    def initDraggingPlacement(self):
        if not getattr(self,'_movingPart',None):
            return True
        self._movingPart.begin()
        return (FreeCADGui.editDocument().EditingTransform,
                self._movingPart.draggerPlacement,
                self._movingPart.bbox)

    _Busy = False

    def onDragStart(self):
        Assembly.cancelAutoSolve();
        FreeCADGui.Selection.clearSelection()
        self.__class__._Busy = True
        if getattr(self,'_movingPart',None):
            FreeCAD.setActiveTransaction('Assembly move')
            return True

    def onDragMotion(self):
        if getattr(self,'_movingPart',None):
            self._movingPart.move()
            return True

    def onDragEnd(self):
        try:
            if getattr(self,'_movingPart',None):
                FreeCAD.closeActiveTransaction()
                return True
        finally:
            self.__class__._Busy = False

    def unsetEdit(self,_vobj,_mode):
        self._movingPart = None
        return False

    def showParts(self):
        proxy = self.ViewObject.Object.Proxy
        if proxy:
            proxy.getPartGroup().ViewObject.Proxy.showParts()

    def updateData(self,_obj,prop):
        if not hasattr(self,'ViewObject') or FreeCAD.isRestoring():
            return
        if prop=='Freeze':
            self.showParts()
            self.ViewObject.signalChangeIcon()
        elif prop=='BuildShape':
            self.showParts()

    def onChanged(self,_vobj,prop):
        if not hasattr(self,'ViewObject') or FreeCAD.isRestoring():
            return
        if prop=='ShowParts':
            self.showParts()

    def finishRestoring(self):
        self.showParts()

    @classmethod
    def isBusy(cls):
        return cls._Busy


class AsmWorkPlane(object):
    def __init__(self,obj):
        obj.addProperty("App::PropertyLength","Length","Base")
        obj.addProperty("App::PropertyLength","Width","Base")
        obj.addProperty("App::PropertyBool","Fixed","Base")
        obj.Fixed = True
        obj.Length = 10
        obj.Width = 10
        obj.Proxy = self

    def execute(self,obj):
        length = obj.Length.Value
        width = obj.Width.Value
        if not length:
            if not width:
                obj.Shape = Part.Vertex(FreeCAD.Vector())
            else:
                obj.Shape = Part.makeLine(FreeCAD.Vector(0,-width/2,0),
                        FreeCAD.Vector(0,width/2,0))
        elif not width:
            obj.Shape = Part.makeLine(FreeCAD.Vector(-length/2,0,0),
                    FreeCAD.Vector(length/2,0,0))
        else:
            obj.Shape = Part.makePlane(length,width,
                    FreeCAD.Vector(-length/2,-width/2,0))

    def __getstate__(self):
        return

    def __setstate__(self,_state):
        return

    Info = namedtuple('AsmWorkPlaneSelectionInfo',
            ('SelObj','SelSubname','PartGroup','Placement','Shape','BoundBox'))

    @staticmethod
    def getSelection(sels=None):
        if not sels:
            sels = FreeCADGui.Selection.getSelectionEx('',False)
        if not sels:
            raise RuntimeError('no selection')
        elements = []
        objs = []
        for sel in sels:
            if not sel.SubElementNames:
                elements.append((sel.Object,''))
                if len(elements) > 2:
                    raise RuntimeError('Too many selection')
                objs.append(sel.Object)
                continue
            for sub in sel.SubElementNames:
                elements.append((sel.Object,sub))
                if len(elements) > 2:
                    raise RuntimeError('Too many selection')
                objs.append(sel.Object.getSubObject(sub,1))
        if len(elements)==2:
            if isTypeOf(objs[0],Assembly,True):
                assembly = objs[0]
                selObj,sub = elements[0]
                element = elements[1]
            elif isTypeOf(objs[1],Assembly,True):
                assembly = objs[1]
                selObj,sub = elements[1]
                element = elements[0]
            else:
                raise RuntimeError('For two selections, one of the selections '
                        'must be of an assembly container')
            _,mat = selObj.getSubObject(sub,1,FreeCAD.Matrix())
            shape = utils.getElementShape(element,transform=True)
            bbox = shape.BoundBox
            pla = utils.getElementPlacement(shape,mat)
        else:
            shape = None
            element = elements[0]
            ret = Assembly.find(element[0],element[1],
                    relativeToChild=False,keepEmptyChild=True)
            if not ret:
                raise RuntimeError('Single selection must be an assembly or '
                        'an object inside of an assembly')
            assembly = ret.Assembly
            sub = element[1][:-len(ret.Subname)]
            selObj = element[0]
            if not ret.Subname:
                pla = FreeCAD.Placement()
                bbox = assembly.ViewObject.getBoundingBox()
            else:
                shape = utils.getElementShape((assembly,ret.Subname),
                                              transform=True)
                bbox = shape.BoundBox
                pla = utils.getElementPlacement(shape,
                        ret.Assembly.Placement.toMatrix())

        return AsmWorkPlane.Info(
                SelObj = selObj,
                SelSubname = sub,
                PartGroup = resolveAssembly(assembly).getPartGroup(),
                Shape = shape,
                Placement = pla,
                BoundBox = bbox)

    @staticmethod
    def make(info=None,name=None, tp=0, undo=True):
        if not info:
            info = AsmWorkPlane.getSelection()
        doc = info.PartGroup.Document
        if undo:
            FreeCAD.setActiveTransaction('Assembly create workplane')
        try:
            logger.debug('make {}',tp)
            if tp == 3:
                obj = Assembly.addOrigin(info.PartGroup,name)
            else:
                if tp==1:
                    pla = FreeCAD.Placement(info.Placement.Base,
                        FreeCAD.Rotation(FreeCAD.Vector(0,1,0),-90))
                elif tp==2:
                    pla = FreeCAD.Placement(info.Placement.Base,
                        FreeCAD.Rotation(FreeCAD.Vector(1,0,0),90))
                else:
                    pla = info.Placement

                if tp == 4:
                    if not name:
                        name = 'Placement'
                    obj = doc.addObject('App::Placement',name)
                elif not name:
                    name = 'Workplane'
                    obj = doc.addObject('Part::FeaturePython',name)
                    AsmWorkPlane(obj)
                    ViewProviderAsmWorkPlane(obj.ViewObject)
                    if utils.isVertex(info.Shape):
                        obj.Length = obj.Width = 0
                    elif utils.isLinearEdge(info.Shape):
                        if info.BoundBox.isValid():
                            obj.Length = info.BoundBox.DiagonalLength
                        obj.Width = 0
                        pla = FreeCAD.Placement(pla.Base,pla.Rotation.multiply(
                            FreeCAD.Rotation(FreeCAD.Vector(0,1,0),90)))
                    elif info.BoundBox.isValid():
                        obj.Length = obj.Width = info.BoundBox.DiagonalLength

                obj.Placement = pla

                obj.recompute(True)
                info.PartGroup.setLink({-1:obj})

            if undo:
                FreeCAD.closeActiveTransaction()

            FreeCADGui.Selection.clearSelection()
            FreeCADGui.Selection.addSelection(info.SelObj,
                info.SelSubname + info.PartGroup.Name + '.' + obj.Name + '.')
            FreeCADGui.runCommand('Std_TreeSelection')
            FreeCADGui.Selection.setVisible(True)
            return obj
        except Exception:
            if undo:
                FreeCAD.closeActiveTransaction(True)
            raise


class ViewProviderAsmWorkPlane(ViewProviderAsmBase):
    _iconName = 'Assembly_Workplane.svg'

    def __init__(self,vobj):
        vobj.Transparency = 50
        color = (0.0,0.33,1.0,1.0)
        vobj.LineColor = color
        vobj.PointColor = color
        vobj.OnTopWhenSelected = 1
        super(ViewProviderAsmWorkPlane,self).__init__(vobj)

    def canDropObjects(self):
        return False

    def getDisplayModes(self, _vobj):
        modes=[]
        return modes

    def setDisplayMode(self, mode):
        return mode


class AsmPlainGroup(object):
    def __init__(self,obj,parent):
        obj.addProperty("App::PropertyLinkHidden","_Parent"," Link",'')
        obj._Parent = parent
        obj.setPropertyStatus('_Parent',('Hidden','Immutable'))
        obj.Proxy = self

    def __getstate__(self):
        return

    def __setstate__(self,_state):
        return

    @staticmethod
    def getParentGroup(obj):
        for o in obj.InList:
            if isTypeOf(o,(AsmGroup,AsmPlainGroup)):
                return o

    @staticmethod
    def contains(parent,obj):
        return obj in getattr(parent,'_ChildCache',[])

    @staticmethod
    def tryMove(obj,toGroup):
        group = AsmPlainGroup.getParentGroup(obj)
        if not group or group is toGroup:
            return False
        if isTypeOf(group,AsmPlainGroup):
            parent = getattr(group,'_Parent', None)
        else:
            parent = group
        if isTypeOf(toGroup,AsmPlainGroup):
            if getattr(toGroup,'_Parent',None) is not parent:
                return False
        elif toGroup is not parent:
            return False
        children = group.Group
        children.remove(obj)
        editGroup(group,children)
        children = toGroup.Group
        children.append(obj)
        editGroup(toGroup,children)
        return True

    # SelObj: selected top object
    # SelSubname: subname refercing the last common parent of the selections
    # Parent: sub-group of the parent assembly
    # Group: immediate group of all selected objects, may or may not be the
    #        same as 'Parent'
    # Objects: selected objects
    Info = namedtuple('AsmPlainGroupSelectionInfo',
            ('SelObj','SelSubname','Parent','Group','Objects'))

    @staticmethod
    def getSelection(sels=None):
        if not sels:
            sels = FreeCADGui.Selection.getSelectionEx('',False)
        if not sels:
            raise RuntimeError('no selection')
        elif len(sels)>1:
            raise RuntimeError('Too many selection')
        sel = sels[0]
        if not sel.SubElementNames:
            raise RuntimeError('Invalid selection')

        parent = None
        subs = []
        for sub in sel.SubElementNames:
            h = Assembly.find(sel.Object,sub,recursive=True,
                    childType=(AsmConstraintGroup,AsmElementGroup,AsmPartGroup))
            if not h:
                raise RuntimeError("Invalid selection {}.{}".format(
                    objName(sel.Object),sub))
            h = h[-1]
            if not parent:
                parent = h.Object
                selSub = sub[:-len(h.Subname)]
            elif parent != h.Object:
                raise RuntimeError("Selection from different assembly")
            subs.append(h.Subname)

        if len(subs) == 1:
            group = parent
            common = ''
            sub = subs[0]
            end = len(sub)
            lastObj = None
            while True:
                index = sub.rfind('.',0,end)
                if index<0:
                    break
                end = index-1
                sobj = group.getSubObject(sub[:index+1],1)
                if not sobj:
                    raise RuntimeError('Sub object not found: {}.{}'.format(
                        objName(group),sub))
                if lastObj and isTypeOf(sobj,AsmPlainGroup):
                    group = sobj
                    selSub += sub[:index+1]
                    subs[0] = sub[index+1:]
                    break
                lastObj = sobj
        else:
            common = os.path.commonprefix(subs)
            idx = common.rfind('.')
            if idx<0:
                group = parent
                common = ''
            else:
                common = common[:idx+1]
                group = parent.getSubObject(common,1)
                if not group:
                    raise RuntimeError('Sub object not found: {}.{}'.format(
                        objName(parent),common))
                if not isTypeOf(group,AsmPlainGroup):
                    raise RuntimeError('Not from plain group')
                selSub += common
                subs = [ s[idx+1:] for s in subs ]
        objs = []
        for s in subs:
            sub = s[:s.index('.')+1]
            if not sub:
                raise RuntimeError('Invalid subname: {}.{}{}'.format(
                    objName(parent),common,s))
            sobj = group.getSubObject(sub,1)
            if not sobj:
                raise RuntimeError('Sub object not found: {}.{}'.format(
                    objName(group),sub))
            if sobj not in objs:
                objs.append(sobj)

        return AsmPlainGroup.Info(SelObj=sel.Object,
                                SelSubname=selSub,
                                Parent=parent,
                                Group=group,
                                Objects=objs)

    @staticmethod
    def make(sels=None,name=None, undo=True):
        info = AsmPlainGroup.getSelection(sels)
        doc = info.Parent.Document
        if undo:
            FreeCAD.setActiveTransaction('Assembly create group')
        try:
            if not name:
                name = 'Group'
            obj = doc.addObject('App::DocumentObjectGroupPython',name)
            AsmPlainGroup(obj,info.Parent)
            ViewProviderAsmPlainGroup(obj.ViewObject)
            group = info.Group.Group
            indices = [ group.index(o) for o in info.Objects ]
            indices.sort()
            child = group[indices[0]]
            group = [ o for o in info.Group.Group
                        if o not in info.Objects ]
            group.insert(indices[0],obj)

            notouch = indices[-1] == indices[0]+len(indices)-1
            editGroup(info.Group,group,notouch)
            obj.purgeTouched()
            editGroup(obj,info.Objects,notouch)

            if undo:
                FreeCAD.closeActiveTransaction()

            FreeCADGui.Selection.clearSelection()
            FreeCADGui.Selection.addSelection(info.SelObj,'{}{}.{}.'.format(
                info.SelSubname,obj.Name,child.Name))
            FreeCADGui.runCommand('Std_TreeSelection')
            return obj
        except Exception:
            if undo:
                FreeCAD.closeActiveTransaction(True)
            raise

class ViewProviderAsmPlainGroup(object):
    def __init__(self,vobj):
        vobj.Visibility = False
        vobj.Proxy = self
        self.attach(vobj)

    def attach(self,vobj):
        if hasattr(self,'ViewObject'):
            return
        self.ViewObject = vobj
        vobj.setPropertyStatus('Visibility','Hidden')

    def __getstate__(self):
        return None

    def __setstate__(self, _state):
        return None

    def onDelete(self,vobj,_subs):
        obj = vobj.Object
        group = AsmPlainGroup.getParentGroup(obj)
        if group:
            children = group.Group
            idx = children.index(obj)
            children = children[:idx] + obj.Group + children[idx+1:]
            editGroup(obj,[],True)
            editGroup(group,children,True)
        return True

    def setupContextMenu(self,_vobj,menu):
        setupSortMenu(menu,self.sort,self.sortReverse)

    def sortReverse(self):
        sortChildren(self.ViewObject.Object,True)

    def sort(self):
        sortChildren(self.ViewObject.Object,False)

    def canDragAndDropObject(self,_obj):
        return False

    def canDropObjects(self):
        return True

    def canDropObjectEx(self,obj,owner,subname,elements):
        parent = getattr(self.ViewObject.Object,'_Parent',None)
        if not parent:
            return False
        if AsmPlainGroup.contains(parent,obj):
            return True
        return parent.ViewObject.canDropObject(obj,owner,subname,elements)

    def dropObjectEx(self,vobj,obj,owner,subname,elements):
        if AsmPlainGroup.tryMove(obj,vobj.Object):
            return
        parent = getattr(vobj.Object,'_Parent',None)
        if not parent:
            return
        func = getattr(parent.ViewObject.Proxy,'_drop',None)
        if func:
            group = parent.Group
            children = func(obj,owner,subname,elements)
            children = vobj.Object.Group + children
            editGroup(parent,group)
            editGroup(vobj.Object,children)

