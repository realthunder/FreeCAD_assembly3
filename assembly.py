import os
from collections import namedtuple,defaultdict
import FreeCAD, FreeCADGui, Part
from PySide import QtCore, QtGui
from . import utils, gui
from .utils import logger, objName
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
        obj = obj.getLinkedObject(True)
        if not writable:
            return obj.getLinkExtProperty(name)
        name = obj.getLinkExtPropertyName(name)
        if 'Immutable' in obj.getPropertyStatus(name):
            return default
        return getattr(obj,name)
    except Exception:
        return default

def setLinkProperty(obj,name,val):
    obj = obj.getLinkedObject(True)
    setattr(obj,obj.getLinkExtPropertyName(name),val)

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
        self.Object.setPropertyStatus('VisibilityList','Output')

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

        parts = set(obj.Group)
        derived = obj.DerivedFrom.getLinkedObject(True).Proxy.getPartGroup()
        self.derivedParts = derived.Group
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
        if obj.Removing or FreeCAD.isRestoring():
            return
        if prop == 'DerivedFrom':
            self.checkDerivedParts()
        elif prop == 'Group':
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

    def canDropObjectEx(self,obj,_owner,_subname,_elements):
        return isTypeOf(obj,Assembly, True) or not isTypeOf(obj,AsmBase)

    def canDragObject(self,_obj):
        return True

    def canDragObjects(self):
        return True

    def canDragAndDropObject(self,_obj):
        return True

    def onDelete(self,_vobj,_subs):
        return False

    def canDelete(self,_obj):
        return True

    def showParts(self):
        vobj = self.ViewObject
        obj = vobj.Object
        if not hasattr(obj,'Shape'):
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


class AsmElement(AsmBase):
    def __init__(self,parent):
        self._initializing = True
        self.parent = getProxy(parent,AsmElementGroup)
        super(AsmElement,self).__init__()

    def getLinkedObject(self,*_args):
        pass

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

    def attach(self,obj):
        obj.addProperty("App::PropertyXLink","LinkedObject"," Link",'')
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

    def onChanged(self,obj,prop):
        parent = getattr(self,'parent',None)
        if not parent or obj.Removing or FreeCAD.isRestoring():
            return
        if prop=='Offset':
            self.updatePlacement()
            return
        elif prop == 'Label':
            parent.Object.cacheChildLabel()
        if prop not in _IgnoredProperties and \
           not Constraint.isDisabled(parent.Object):
            Assembly.autoSolve(obj,prop)

    def execute(self,obj):
        info = None
        if not obj.Detach and hasattr(obj,'Shape'):
            info = getElementInfo(self.getAssembly().getPartGroup(),
                                  self.getElementSubname())
            mat = info.Placement.toMatrix()
            if not getattr(obj,'Radius',None):
                shape = Part.Shape(info.Shape)
                shape.transformShape(mat,True)
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
                    edge.transformShape(mat,True)
                    if not found and utils.isSamePlacement(pla,edge.Placement):
                        found = True
                        # make sure the direct referenced edge is the first one
                        shapes[0] = edge
                    else:
                        shapes.append(edge)
                shape = shapes

            # make a compound to keep the shape's transformation
            shape = Part.makeCompound(shape)
            shape.ElementMap = info.Shape.ElementMap
            obj.Shape = shape

        self.updatePlacement(info)
        return False

    def updatePlacement(self,info=None):
        obj = self.Object
        if obj.Offset.isIdentity():
            obj.Placement = FreeCAD.Placement()
        else:
            if not info:
                info = getElementInfo(self.getAssembly().getPartGroup(),
                                      self.getElementSubname())
            # obj.Offset is in the element shape's coordinate system, we need to
            # transform it to the assembly coordinate system
            mat = utils.getElementPlacement(info.Shape).toMatrix()
            mat = info.Placement.toMatrix()*mat
            obj.Placement = FreeCAD.Placement(
                                mat*obj.Offset.toMatrix()*mat.inverse())

    def getAssembly(self):
        return self.parent.parent

    def getSubElement(self):
        link = self.Object.LinkedObject
        if isinstance(link,tuple):
            return link[1].split('.')[-1]
        return ''

    def getSubName(self):
        link = self.Object.LinkedObject
        if not isinstance(link,tuple):
            raise RuntimeError('Invalid element link "{}"'.format(
                objName(self.Object)))
        return link[1]

    def getElementSubname(self,recursive=False):
        '''
        Recursively resolve the geometry element link relative to the parent
        assembly's part group
        '''

        subname = self.getSubName()
        if not recursive:
            return subname

        obj = self.Object.LinkedObject
        if isinstance(obj,tuple):
            obj = obj[0]
        if not obj or obj == self.Object:
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
        return subname+childElement.getAssembly().getPartGroup().Name+'.'+\
                childElement.getElementSubname(True)

    # Element: optional, if none, then a new element will be created if no
    #          pre-existing. Or else, it shall be the element to be amended
    # Group: the immediate child object of an assembly (i.e. ConstraintGroup,
    #        ElementGroup, or PartGroup)
    # Subname: the subname reference realtive to 'Group'
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
            element = element[-1].Assembly.getSubObject(
                                    element[-1].Subname,retType=1)
            if not isTypeOf(element,AsmElement):
                element = None

        if not assembly:
            path = hierarchies[0]
            assembly = path[0].Assembly
            selSubname = sels[0].SubElementNames[0][:-len(path[0].Subname)]
        for i,hierarchy in enumerate(hierarchies):
            for path in hierarchy:
                if path.Assembly == assembly:
                    hierarchies[i] = AsmElement.Selection(
                        Element=element,Group=path.Object,
                        Subname=path.Subname[path.Subname.index('.')+1:],
                        SelObj=selObj, SelSubname=selSubname)
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
        subname = selection.Subname

        if isTypeOf(group,AsmElementGroup):
            # if the selected object is an element of the owner assembly, simply
            # return that element
            element = group.getSubObject(subname,1)
            if not isTypeOf(element,AsmElement):
                raise RuntimeError('Invalid element reference {}.{}'.format(
                    group.Name,subname))
            if not allowDuplicate:
                return element
            group,subname = element.LinkedObject

        if isTypeOf(group,AsmConstraintGroup):
            # if the selected object is an element link of a constraint of the
            # current assembly, then try to import its linked element if it is
            # not already imported
            link = group.getSubObject(subname,1)
            if not isTypeOf(link,AsmElementLink):
                raise RuntimeError('Invalid element link {}.{}'.format(
                    group.Name,subname))
            ref = link.LinkedObject
            if not isinstance(ref,tuple):
                raise RuntimeError('Invalid link reference {}.{}'.format(
                    group.Name,subname))
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
                        'element {} {}'.format(objName(group),subname))
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
                prefix = subname[:len(subname)-len(ret.Subname)-1]

                # Pop the immediate child name, and replace it with child
                # assembly's element group name
                prefix = prefix[:prefix.rfind('.')+1] + \
                    resolveAssembly(ret.Assembly).getElementGroup().Name

                subname = '{}.${}.'.format(prefix,element.Label)

        else:
            raise RuntimeError('Invalid selection {}.{}'.format(
                group.Name,subname))

        element = selection.Element

        sobj = group.getSubObject(subname,1)
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
                    for e in elements.Group:
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
            element.setLink(group,subname)
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

    def __init__(self,vobj):
        vobj.ShapeColor = self.getDefaultColor()
        vobj.PointColor = self.getDefaultColor()
        vobj.LineColor = self.getDefaultColor()
        vobj.Transparency = 50
        vobj.LineWidth = 4
        vobj.PointSize = 4
        super(ViewProviderAsmElement,self).__init__(vobj)

    def attach(self,vobj):
        super(ViewProviderAsmElement,self).attach(vobj)
        vobj.OnTopWhenSelected = 2

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
    realtive to the 'Part', i.e. Object = Part.getSubObject(subname), or if
    'Part' is a tuple, Object = Part[0].getSubObject(str(Part[1]) + '.' +
    subname)

    Shape: Part.Shape of the linked element. The shape's placement is relative
    to the owner Part.
    '''

    subnameRef = subname

    names = subname.split('.')
    if isTypeOf(parent,Assembly,True):
        partGroup = None
        child = parent.getSubObject(names[0]+'.',1)
        if isTypeOf(child,(AsmElementGroup,AsmConstraintGroup)):
            child = parent.getSubObject(subname,1)
            if not child:
                raise RuntimeError('Invalid sub-object {}, {}'.format(
                    objName(parent), subname))
            if not isTypeOf(child,(AsmElement,AsmElementLink)):
                raise RuntimeError('{} cannot be moved'.format(objName(child)))
            subname = child.Proxy.getElementSubname(recursive)
            names = subname.split('.')
            partGroup = parent.Proxy.getPartGroup()

        elif isTypeOf(child,AsmPartGroup):
            partGroup = child
            names = names[1:]
            subname = '.'.join(names)

        if not partGroup:
            raise RuntimeError('Invalid sub-object {}, {}'.format(
                objName(parent), subname))

    elif isTypeOf(parent,AsmPartGroup):
        partGroup = parent
    else:
        raise RuntimeError('{} is not Assembly or PartGroup'.format(
            objName(parent)))

    part = partGroup.getSubObject(names[0]+'.',1)
    if not part:
        raise RuntimeError('Invalid sub-object {}, {}'.format(
            objName(parent), subnameRef))

    transformShape = True if shape else False

    # For storing the placement of the movable part
    pla = None
    # For storing the actual geometry object of the part, in case 'part' is
    # a link
    obj = None

    if not isTypeOf(part,Assembly,True):

        # special treatment of link array (i.e. when ElementCount!=0), we
        # allow the array element to be moveable by the solver
        if getLinkProperty(part,'ElementCount'):
            if not names[1]:
                names[1] = '0'
                names.append('')

            # store both the part (i.e. the link array), and the array
            # element object
            part = (part,part.getSubObject(names[1]+'.',1))

            # trim the subname to be after the array element
            subname = '.'.join(names[2:])

            # There are two states of an link array.
            if getLinkProperty(part[0],'ElementList'):
                # a) The elements are expanded as individual objects, i.e
                # when ElementList has members, then the moveable Placement
                # is a property of the array element. So we obtain the shape
                # before 'Placement' by setting 'transform' set to False.
                if not shape:
                    shape=utils.getElementShape(
                            (part[1],subname),transform=False)
                pla = part[0].Placement.multiply(part[1].Placement)
                obj = part[1].getLinkedObject(False)
                partName = part[1].Name
                idx = int(partName.split('_i')[-1])
                part = (part[0],idx,part[1],False)
            else:
                plaList = getLinkProperty(part[0],'PlacementList',None,True)
                if plaList:
                    # b) The elements are collapsed. Then the moveable Placement
                    # is stored inside link object's PlacementList property. So,
                    # the shape obtained below is already before 'Placement',
                    # i.e. must set 'transform' to True.
                    if not shape:
                        shape=utils.getElementShape(
                                (part[1],subname),transform=True)
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

                    partName = '{}.{}.'.format(part[0].Name,idx)

    if not obj:
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
            raise RuntimeError('cannot get geometry element from {}.{}'.format(
                part.Name,subname))
        pla = getattr(part,'Placement',FreeCAD.Placement())
        obj = part.getLinkedObject(False)
        partName = part.Name

    if transformShape:
        # Copy and transform shape. We have to copy the shape here to work
        # around of obscure OCCT edge transformation bug
        shape.transformShape(pla.toMatrix().inverse(),True)

    return ElementInfo(Parent = parent,
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
        self.info = None
        self.infos = []
        self.part = None
        self.parent = getProxy(parent,AsmConstraint)
        self.multiply = False

    def linkSetup(self,obj):
        super(AsmElementLink,self).linkSetup(obj)
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

    def attach(self,obj):
        obj.addProperty("App::PropertyXLink","LinkedObject"," Link",'')
        super(AsmElementLink,self).attach(obj)

    def canLinkProperties(self,_obj):
        return False

    def execute(self,_obj):
        info = self.getInfo(True)
        relationGroup = self.getAssembly().getRelationGroup()
        if relationGroup and (not self.part or self.part!=info.Part):
            oldPart = self.part
            self.part = info.Part
            relationGroup.Proxy.update(
                    self.parent.Object,oldPart,info.Part,info.PartName)
        return False

    _MyIgnoredProperties = _IgnoredProperties | \
            set(('AcountCount','PlacementList'))

    def onChanged(self,obj,prop):
        if obj.Removing or \
           not getattr(self,'parent',None) or \
           FreeCAD.isRestoring():
            return
        if prop == 'Count':
            self.infos *= 0 # clear the list
            self.info = None
            return
        if prop == 'NoExpand':
            cstr = self.parent.Object
            if obj!=cstr.Group[0] and cstr.Multiply and obj.LinkedObject:
                self.setLink(self.getAssembly().getPartGroup(),
                        self.getElementSubname(True))
            return
        if prop == 'Offset':
            self.getInfo(True)
            return
        if prop not in self._MyIgnoredProperties and \
           not Constraint.isDisabled(self.parent.Object):
            Assembly.autoSolve(obj,prop)

    def getAssembly(self):
        return self.parent.parent.parent

    def getElementSubname(self,recursive=False):
        'Resolve element link subname'

        #  AsmElementLink is used by constraint to link to a geometry link. It
        #  does so by indirectly linking to an AsmElement object belonging to
        #  the same parent assembly. AsmElement is also a link, which again
        #  links to another AsmElement of a child assembly or the actual
        #  geometry element of a child feature. This function is for resolving
        #  the AsmElementLink's subname reference to the actual part object
        #  subname reference relative to the parent assembly's part group

        link = self.Object.LinkedObject
        linked = link[0].getSubObject(link[1],retType=1)
        if not linked:
            raise RuntimeError('Element link broken')
        element = getProxy(linked,AsmElement)
        assembly = element.getAssembly()
        if assembly == self.getAssembly():
            return element.getElementSubname(recursive)

        # The reference stored inside this ElementLink. We need the sub-assembly
        # name, which is the name before the first dot. This name may be
        # different from the actual assembly object's name, in case where the
        # assembly is accessed through a link. And the sub-assembly may be
        # inside a link array, which we don't know for sure. But we do know that
        # the last two names are element group and element label. So just pop
        # two names.
        ref = self.Object.LinkedObject[1]
        prefix = ref[0:ref.rfind('.',0,ref.rfind('.',0,-1))]
        return '{}.{}.{}'.format(prefix, assembly.getPartGroup().Name,
                element.getElementSubname(recursive))

    def setLink(self,owner,subname,checkOnly=False,multiply=False):
        obj = self.Object
        cstr = self.parent.Object
        elements = cstr.Group
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

        # check if there is any sub-assembly in the reference
        ret = Assembly.find(owner,subname)
        if not ret:
            # if not, add/get an element in our own element group
            sel = AsmElement.Selection(SelObj=None, SelSubname=None,
                    Element=None, Group=owner, Subname=subname)
            element = AsmElement.make(sel,radius=radius)
            owner = element.Proxy.parent.Object
            subname = '${}.'.format(element.Label)
        else:
            # if so, add/get an element from the sub-assembly
            sel = AsmElement.Selection(SelObj=None, SelSubname=None,
                    Element=None, Group=ret.Object, Subname=ret.Subname)
            element = AsmElement.make(sel,radius=radius)
            owner = owner.Proxy.getAssembly().getPartGroup()

            # This give us reference to child assembly's immediate child
            # without trailing dot.
            prefix = subname[:len(subname)-len(ret.Subname)-1]

            # Pop the immediate child name, and replace it with child
            # assembly's element group name
            prefix = prefix[:prefix.rfind('.')+1] + \
                resolveAssembly(ret.Assembly).getElementGroup().Name

            subname = '{}.${}.'.format(prefix, element.Label)

        for sibling in elements:
            if sibling == obj:
                continue
            linked = sibling.LinkedObject
            if isinstance(linked,tuple) and \
               linked[0]==owner and linked[1]==subname:
                raise RuntimeError('duplicate element link {} in constraint '
                    '{}'.format(objName(sibling),objName(cstr)))
        obj.setLink(owner,subname)

    def getInfo(self,refresh=False,expand=False):
        if not refresh and self.info is not None:
            return self.infos if expand else self.info

        self.info = None
        self.infos *= 0 # clear the list
        obj = getattr(self,'Object',None)
        if not obj:
            return

        linked = obj.LinkedObject
        if not isinstance(linked,tuple) or not linked[0]:
            raise RuntimeError('Element link borken')

        shape = Part.getShape(linked[0],linked[1],
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
                    sobj = part[0].getSubObject(str(i)+'.',retType=1)
                    pla = sobj.Placement
                    part = (part[0],i,sobj,part[3])
                pla = part[0].Placement.multiply(pla)
                plaList.append(pla.multiply(offset))
                infos.append(ElementInfo(Parent = info.Parent,
                               SubnameRef = info.SubnameRef,
                               Part=part,
                               PartName = '{}.{}'.format(part[0].Name,i),
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

def setPlacement(part,pla):
    ''' called by solver after solving to adjust the placement.

        part: obtained by AsmConstraint.getInfo().Part pla: the new placement
    '''
    if isinstance(part,tuple):
        pla = part[0].Placement.inverse().multiply(pla)
        if part[3]:
            setLinkProperty(part[0],'PlacementList',{part[1]:pla})
        else:
            part[2].Placement = pla
    else:
        part.Placement = pla

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
        obj = self.ViewObject.Object
        msg = 'Cannot drop to AsmElementLink {}'.format(objName(obj))
        if logger.catchTrace(msg, obj.Proxy.setLink,owner,subname,True):
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
        logger.err('Constraint type "{}" is not supported by '
                'solver "{}"'.format(Constraint.getTypeName(obj),
                    System.getTypeName(assembly)))
        Constraint.setDisable(obj)

    def onChanged(self,obj,prop):
        if not obj.Removing and prop not in _IgnoredProperties:
            if prop == Constraint.propMultiply() and not FreeCAD.isRestoring():
                self.checkMultiply()
            Constraint.onChanged(obj,prop)
            Assembly.autoSolve(obj,prop)

    def linkSetup(self,obj):
        self.elements = None
        super(AsmConstraint,self).linkSetup(obj)
        group = obj.Group
        for o in group:
            getProxy(o,AsmElementLink).parent = self
        if gui.AsmCmdManager.AutoElementVis:
            obj.setPropertyStatus('VisibilityList','-Immutable')
            obj.VisibilityList = [False]*len(group)
            obj.setPropertyStatus('VisibilityList','Immutable')
            obj.setPropertyStatus('VisibilityList','NoModify')
        Constraint.attach(obj)
        obj.recompute()

    def checkMultiply(self):
        obj = self.Object
        if not obj.Multiply:
            return
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
            else:
                count += elementCount
                shapes.append(info.Shape.getElement(name))

        for i,e in enumerate(children[1:]):
            shape = shapes[i]
            if not shape or not e.Proxy.infos:
                continue
            for j,e2 in enumerate(children[i+2:]):
                shape2 = shapes[i+j+1]
                if not shape2 or not e2.Proxy.infos:
                    continue
                if shape.isCoplanar(shape2):
                    e.Proxy.infos += e2.Proxy.infos
                    e2.Proxy.infos = []

        firstChild = children[0]
        info = firstChild.Proxy.getInfo()
        if not isinstance(info.Part,tuple):
            raise RuntimeError('Expect part {} to be an array for'
                'constraint multiplication'.format(info.PartName))

        touched = 'Touched' in firstChild.State
        if not hasattr(firstChild,'Count'):
            firstChild.addProperty("App::PropertyInteger","Count",'','')
            firstChild.setPropertyStatus('Count',('ReadOnly','Output'))
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
            if getLinkProperty(info.Part[0],'ElementCount',None,True) is None:
                firstChild.AutoCount = False
            else:
                partTouched = 'Touched' in info.Part[0].State
                setLinkProperty(info.Part[0],'ElementCount',count)
                if not partTouched:
                    info.Part[0].purgeTouched()

        if not firstChild.AutoCount:
            count = getLinkProperty(info.Part[0],'ElementCount')

        if firstChild.Count != count:
            firstChild.Count = count

        if not touched and 'Touched' in firstChild.State:
            firstChild.Proxy.getInfo(True)
            # purge touched to avoid recomputation multi-pass
            firstChild.purgeTouched()

    def execute(self,obj):
        if not getattr(self,'_initializing',False) and\
           getattr(self,'parent',None):
            self.checkSupport()
            if Constraint.canMultiply(obj):
                self.checkMultiply()
            self.getElements(True)
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
        group = obj.Group
        if Constraint.canMultiply(obj):
            firstInfo = group[0].Proxy.getInfo(expand=True)
            if not firstInfo:
                raise RuntimeError('invalid first element')
            elements.append(group[0])
            for o in group[1:]:
                info = o.Proxy.getInfo(expand=True)
                if not info:
                    continue
                elementInfo += info
                elements.append(o)
            for info in zip(firstInfo,elementInfo[:len(firstInfo)]):
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
                for o in cstr.Group:
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
        if sel.Constraint:
            if undo:
                FreeCAD.setActiveTransaction('Assembly change constraint')
            cstr = sel.Constraint
        else:
            if undo:
                FreeCAD.setActiveTransaction('Assembly create constraint')
            constraints = sel.Assembly.Proxy.getConstraintGroup()
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
                cstr.VisibilityList = [False]*len(cstr.Group)
                cstr.setPropertyStatus('VisibilityList','Immutable')

            cstr.Proxy._initializing = False

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
                subname += sel.Assembly.Proxy.getConstraintGroup().Name + \
                        '.' + cstr.Name + '.'
                FreeCADGui.Selection.addSelection(sel.SelObject,subname)
                FreeCADGui.Selection.pushSelStack()
                FreeCADGui.runCommand('Std_TreeSelection')
            return cstr

        except Exception as e:
            logger.debug('failed to make constraint: {}'.format(e))
            if undo:
                FreeCAD.closeActiveTransaction(True)
            raise

    @staticmethod
    def makeMultiply(checkOnly=False):
        sels = FreeCADGui.Selection.getSelection()
        if not len(sels)==1 or not isTypeOf(sels[0],AsmConstraint):
            raise RuntimeError('Must select a constraint')
        cstr = sels[0]
        multiplied = Constraint.canMultiply(cstr)
        if multiplied is None:
            raise RuntimeError('Constraint do not support multiplication')

        elements = cstr.Proxy.getElements()
        if len(elements)<=1:
            raise RuntimeError('Constraint must have more than one element')

        info = elements[0].Proxy.getInfo()
        if not isinstance(info.Part,tuple) or info.Part[1]!=0:
            raise RuntimeError('Constraint multiplication requires the first '
                    'element to be from the first element of a link array')

        try:
            if not checkOnly:
                FreeCAD.setActiveTransaction("Assembly constraint multiply")

            partGroup = cstr.Proxy.getAssembly().getPartGroup()

            if multiplied:
                subs = elements[0].Proxy.getElementSubname(True).split('.')
                infos0 = []
                for i in xrange(elements[0].Count):
                    subs[1] = str(i)
                    infos0.append((partGroup,'.'.join(subs)))
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
                if checkOnly:
                    return True
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

            for elementLink in elements[1:]:
                subname = elementLink.Proxy.getElementSubname(True)
                elementLink.Proxy.setLink(
                        partGroup,subname,checkOnly,multiply=True)
            if not checkOnly:
                cstr.Multiply = True
                FreeCAD.closeActiveTransaction()
            return True
        except Exception:
            if not checkOnly:
                FreeCAD.closeActiveTransaction(True)
            raise


class ViewProviderAsmConstraint(ViewProviderAsmGroup):
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
        for o in obj.Group:
            cstr = getProxy(o,AsmConstraint)
            if cstr:
                cstr.parent = self
                obj.recompute()

    def onChanged(self,obj,prop):
        if obj.Removing or FreeCAD.isRestoring():
            return
        if prop not in _IgnoredProperties:
            System.onChanged(obj,prop)
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

    def canDropObjects(self):
        return False

    def canDelete(self,_obj):
        return True

    def onDelete(self,_vobj,_subs):
        return False


class AsmElementGroup(AsmGroup):
    def __init__(self,parent):
        self.parent = getProxy(parent,Assembly)
        super(AsmElementGroup,self).__init__()

    def linkSetup(self,obj):
        super(AsmElementGroup,self).linkSetup(obj)
        for o in obj.Group:
            getProxy(o,AsmElement).parent = self
        obj.cacheChildLabel()
        if gui.AsmCmdManager.AutoElementVis:
            obj.setPropertyStatus('VisibilityList','NoModify')

    def getAssembly(self):
        return self.parent

    def onChildLabelChange(self,obj,label):
        names = set()
        for o in self.Object.Group:
            if o != obj:
                names.add(o.Name)
        if label not in names:
            return
        for i,c in enumerate(reversed(label)):
            if not c.isdigit():
                if i:
                    label = label[:-i]
                break;
        i=0
        while True:
            i=i+1;
            newLabel = '{}{03d}'.format(label,i);
            if newLabel!=obj.Label and newLabel not in names:
                return newLabel

    @staticmethod
    def make(parent,name='Elements'):
        obj = parent.Document.addObject("App::FeaturePython",name,
                        AsmElementGroup(parent),None,True)
        ViewProviderAsmElementGroup(obj.ViewObject)
        obj.purgeTouched()
        return obj


class ViewProviderAsmElementGroup(ViewProviderAsmGroup):
    _iconName = 'Assembly_Assembly_Element_Tree.svg'

    def canDropObjectEx(self,_obj,owner,subname,elements):
        if not owner:
            return False
        if not elements and not utils.isElement((owner,subname)):
            return False
        proxy = self.ViewObject.Object.Proxy
        return proxy.getAssembly().getPartGroup()==owner

    def dropObjectEx(self,vobj,_obj,owner,subname,elements):
        sels = FreeCADGui.Selection.getSelectionEx('*',False)
        if len(sels)==1 and \
           len(sels[0].SubElementNames)==1 and \
           sels[0].Object.getSubObject(
                   sels[0].SubElementNames[0],1)==vobj.Object:
            sel = sels[0]
        else:
            sel = None
        FreeCADGui.Selection.clearSelection()
        if not elements:
            elements = ['']
        for element in elements:
            obj = AsmElement.make(AsmElement.Selection(
                SelObj=None, SelSubname=None,
                Element=None, Group=owner, Subname=subname+element))
            if obj and sel:
                FreeCADGui.Selection.addSelection(sel.Object,
                        sel.SubElementNames[0]+obj.Name+'.')

    def onDelete(self,_vobj,_subs):
        return False

    def canDelete(self,_obj):
        return True


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
        for part in self.getAssembly().getPartGroup().Group:
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
            logger.error('invalid relation of part array: '+str(e))

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
            logger.warn('Cannot find relation of part {}'.format(partName))
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
        sub = Part.splitSubname(subname)[0].split('.')
        sobj = obj.getSubObject(subname,retType=1)
        if isTypeOf(sobj,AsmElementLink):
            sobj = sobj.parent.Object
            sub = sub[:-2]
        else:
            sub = sub[:-1]
        if not isTypeOf(sobj,AsmConstraint):
            return
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
        info = moveInfo.ElementInfo
        if info.Subname:
            subs = moveInfo.SelSubname[:-len(info.Subname)]
        else:
            subs = moveInfo.SelSubname
        subs = subs.split('.')
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
        for cstr in self.getAssembly().getConstraintGroup().Group:
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
    _Timer = QtCore.QTimer()
    _TransID = 0
    _PartMap = {} # maps part to assembly
    _PartArrayMap = {} # maps array part to assembly
    _ScheduleTimer = QtCore.QTimer()
    _PendingRemove = []
    _PendingReload = defaultdict(set)

    def __init__(self):
        self.parts = set()
        self.partArrays = set()
        self.constraints = None
        self.frozen = False
        self.deleting = False
        super(Assembly,self).__init__()

    def getSubObjects(self,_obj,reason):
        # Deletion order problem may cause exception here. Just silence it
        try:
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
        return gui.AsmCmdManager.AutoRecompute and \
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
        if force or cls.canAutoSolve():
            if not cls._Timer.isSingleShot():
                cls._Timer.setSingleShot(True)
                cls._Timer.timeout.connect(Assembly.onSolverTimer)
            cls._TransID = FreeCAD.getActiveTransaction()
            logger.debug('auto solve scheduled on change of {}.{}'.format(
                objName(obj),prop),frame=1)
            cls._Timer.start(300)

    @classmethod
    def cancelAutoSolve(cls):
        logger.debug('cancel auto solve',frame=1)
        cls._Timer.stop()

    @classmethod
    def onSolverTimer(cls):
        if not cls.canAutoSolve():
            return
        from . import solver
        trans = cls._TransID and cls._TransID==FreeCAD.getActiveTransaction()
        if not trans:
            cls._TransID = 0
            FreeCAD.setActiveTransaction('Assembly auto recompute')
        if not logger.catch('solver exception when auto recompute',
                solver.solve, FreeCAD.ActiveDocument.Objects, True):
            if not trans:
                FreeCAD.closeActiveTransaction(True)
        else:
            if not trans:
                FreeCAD.closeActiveTransaction()

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
    def onSchedule(cls):
        for doc in FreeCAD.listDocuments().values():
            if doc.Recomputing:
                cls._ScheduleTimer.start(50)
                return
        for name,onames in cls._PendingReload.items():
            doc = FreeCADGui.reload(name)
            if not doc:
                break
            for oname in onames:
                obj = doc.getObject(oname)
                if getattr(obj,'Freeze',None):
                    obj.Freeze = False
        cls._PendingReload.clear()

        for doc,names in cls._PendingRemove:
            try:
                for name in names:
                    try:
                        doc.removeObject(name)
                    except Exception:
                        pass
            except Exception:
                pass
        cls._PendingRemove = []

    def onSolverChanged(self):
        for obj in self.getConstraintGroup().Group:
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
        if hasattr(partGroup,'Shape'):
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
            if hasattr(partGroup, 'Shape'):
                partGroup.Shape = Part.Shape()
            return

        group = partGroup.Group

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

        if hasattr(partGroup,'Shape'):
            if obj.Freeze or obj.BuildShape!=BuildShapeCompound:
                partGroup.Shape = shape
                shape.Tag = partGroup.ID
            else:
                partGroup.Shape = Part.Shape()

        shape.Placement = obj.Placement
        obj.Shape = shape

    def attach(self, obj):
        obj.addProperty("App::PropertyEnumeration","BuildShape","Base",'')
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
        self.getRelationGroup()

        self.frozen = obj.Freeze
        if self.frozen or hasattr(partGroup,'Shape'):
            shape = Part.Shape(partGroup.Shape)
            shape.Placement = obj.Placement
            shape.Tag = obj.ID
            obj.Shape = shape
        if obj.Shape.isNull() and \
             obj.BuildShape == BuildShapeCompound:
            self.buildShape()

    def onChanged(self, obj, prop):
        if obj.Removing or \
           not getattr(self,'Object',None) or \
           FreeCAD.isRestoring():
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
        for o in cstrGroup.Group:
            checkType(o,AsmConstraint)
            if Constraint.isDisabled(o):
                logger.debug('skip constraint {}'.format(cstrName(o)))
                continue
            if not System.isConstraintSupported(self.Object,
                       Constraint.getTypeName(o)):
                logger.debug('skip unsupported constraint '
                    '{}'.format(cstrName(o)))
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
            obj.purgeTouched()
            if undo:
                FreeCAD.closeActiveTransaction()
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


class ViewProviderAssembly(ViewProviderAsmGroup):
    _iconName = 'Assembly_Assembly_Frozen_Tree.svg'

    def __init__(self,vobj):
        self._movingPart = None
        super(ViewProviderAssembly,self).__init__(vobj)

    def attach(self,vobj):
        super(ViewProviderAssembly,self).attach(vobj)
        if not hasattr(vobj,'ShowParts'):
            vobj.addProperty("App::PropertyBool","ShowParts"," Link")

    def canAddToSceneGraph(self):
        return True

    def onDelete(self,vobj,_subs):
        assembly = vobj.Object.Proxy
        for o in assembly.getPartGroup().Group:
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
        partGroup.dropObject(obj,owner,subname)
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
        self.__class__._Busy = False
        if getattr(self,'_movingPart',None):
            FreeCAD.closeActiveTransaction()
            return True

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

    def onFinishRestoring(self):
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
                objs.append(sel.Object)
                continue
            for sub in sel.SubElementNames:
                elements.append((sel.Object,sub))
                objs.append(sel.Object.getSubObject(sub,1))
        if len(elements) > 2:
            raise RuntimeError('Too many selection')
        elif len(elements)==2:
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
                PartGroup = assembly.Proxy.getPartGroup(),
                Shape = shape,
                Placement = pla,
                BoundBox = bbox)

    @staticmethod
    def make(sels=None,name=None, tp=0, undo=True):
        info = AsmWorkPlane.getSelection(sels)
        doc = info.PartGroup.Document
        if undo:
            FreeCAD.setActiveTransaction('Assembly create workplane')
        try:
            logger.debug('make {}'.format(tp))
            if tp == 3:
                obj = None
                for o in info.PartGroup.Group:
                    if o.TypeId == 'App::Origin':
                        obj = o
                        break
                if not obj:
                    if not name:
                        name = 'Origin'
                    obj = doc.addObject('App::Origin',name)
                    info.PartGroup.setLink({-1:obj})

                info.PartGroup.recompute(True)
                shape = Part.getShape(info.PartGroup)
                if not shape.isNull():
                    bbox = shape.BoundBox
                    if bbox.isValid():
                        obj.ViewObject.Size = tuple([
                            max(abs(a),abs(b)) for a,b in (
                                (bbox.XMin,bbox.XMax),
                                (bbox.YMin,bbox.YMax),
                                (bbox.ZMin,bbox.ZMax)) ])
            else:
                if not name:
                    name = 'Workplane'
                obj = doc.addObject('Part::FeaturePython',name)
                AsmWorkPlane(obj)
                ViewProviderAsmWorkPlane(obj.ViewObject)
                if tp==1:
                    pla = FreeCAD.Placement(info.Placement.Base,
                        FreeCAD.Rotation(FreeCAD.Vector(0,1,0),-90))
                elif tp==2:
                    pla = FreeCAD.Placement(info.Placement.Base,
                        FreeCAD.Rotation(FreeCAD.Vector(1,0,0),90))
                else:
                    pla = info.Placement

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
