import os
from collections import namedtuple
import FreeCAD, FreeCADGui
import asm3
import asm3.utils as utils
from asm3.utils import logger, objName
from asm3.constraint import Constraint, cstrName
from asm3.system import System

def setupUndo(doc,undoDocs,name):
    if undoDocs is None:
        return
    if doc.HasPendingTransaction or doc in undoDocs:
        return
    if not name:
        name = 'Assembly solve'
    doc.openTransaction(name)
    undoDocs.add(doc)

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

    def attach(self,vobj):
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
        vobj.OnTopWhenSelected = True
        super(ViewProviderAsmOnTop,self).__init__(vobj)


class AsmGroup(AsmBase):
    def linkSetup(self,obj):
        super(AsmGroup,self).linkSetup(obj)
        obj.configLinkProperty(
                'VisibilityList',LinkMode='GroupMode',ElementList='Group')
        self.groupSetup()

    def groupSetup(self):
        self.Object.GroupMode = 1 # auto delete children
        self.Object.setPropertyStatus('GroupMode','Hidden')
        self.Object.setPropertyStatus('GroupMode','Immutable')
        self.Object.setPropertyStatus('GroupMode','Transient')
        self.Object.setPropertyStatus('Group','Hidden')
        self.Object.setPropertyStatus('Group','Immutable')

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
    def attach(self,vobj):
        super(ViewProviderAsmGroupOnTop,self).attach(vobj)
        vobj.OnTopWhenSelected = True


class AsmPartGroup(AsmGroup):
    def __init__(self,parent):
        self.parent = getProxy(parent,Assembly)
        super(AsmPartGroup,self).__init__()

    def getAssembly(self):
        return self.parent

    def groupSetup(self):
        pass

    @staticmethod
    def make(parent,name='Parts'):
        obj = parent.Document.addObject("App::FeaturePython",name,
                    AsmPartGroup(parent),None,True)
        ViewProviderAsmPartGroup(obj.ViewObject)
        obj.purgeTouched()
        return obj


class ViewProviderAsmPartGroup(ViewProviderAsmGroup):
    _iconName = 'Assembly_Assembly_Part_Tree.svg'

    def onDelete(self,_obj,_subs):
        return False

    def canDropObjectEx(self,obj,_owner,_subname):
        return isTypeOf(obj,Assembly, True) or not isTypeOf(obj,AsmBase)

    def canDragObject(self,_obj):
        return True

    def canDragObjects(self):
        return True

    def canDragAndDropObject(self,_obj):
        return True


class AsmElement(AsmBase):
    def __init__(self,parent):
        self._initializing = True
        self.shape = None
        self.parent = getProxy(parent,AsmElementGroup)
        super(AsmElement,self).__init__()

    def linkSetup(self,obj):
        super(AsmElement,self).linkSetup(obj)
        obj.configLinkProperty('LinkedObject')
        #  obj.setPropertyStatus('LinkedObject','Immutable')
        obj.setPropertyStatus('LinkedObject','ReadOnly')

    def attach(self,obj):
        obj.addProperty("App::PropertyXLink","LinkedObject"," Link",'')
        super(AsmElement,self).attach(obj)

    def canLinkProperties(self,_obj):
        return False

    def allowDuplicateLabel(self,_obj):
        return True

    def onBeforeChangeLabel(self,obj,label):
        parent = getattr(self,'parent',None)
        if parent and not getattr(self,'_initializing',False):
            return parent.onChildLabelChange(obj,label)

    def onChanged(self,_obj,prop):
        parent = getattr(self,'parent',None)
        if parent and \
           not getattr(self,'_initializing',False) and \
           prop=='Label':
            parent.Object.cacheChildLabel()

    def execute(self,_obj):
        self.getShape(True)
        return False

    def getShape(self,refresh=False):
        if not refresh:
            ret = getattr(self,'shape',None)
            if ret:
                return ret
        self.shape = None
        self.shape = self.Object.getSubObject('')
        return self.shape

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

    def getElementSubname(self):
        '''
        Resolve the geometry element link relative to the parent assembly's part
        group
        '''

        subname = self.getSubName()
        obj = self.Object.getLinkedObject(False)
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
                childElement.getElementSubname()

    # Element: optional, if none, then a new element will be created if no
    #          pre-existing. Or else, it shall be the element to be amended
    # Group: the immediate child object of an assembly (i.e. ConstraintGroup,
    #        ElementGroup, or PartGroup)
    # Subname: the subname reference realtive to 'Group'
    Selection = namedtuple('AsmElementSelection',('Element','Group','Subname'))

    @staticmethod
    def getSelection():
        '''
        Parse Gui.Selection for making an element

        If there is only one selection, then the selection must refer to a sub
        element of some part object of an assembly. We shall create a new
        element beloning to the top-level assembly

        If there are two selections, then first one shall be either the
        element group or an individual element. The second selection shall
        be a sub element belong to a child assembly of the parent assembly of
        the first selected element/element group
        '''
        sels = FreeCADGui.Selection.getSelectionEx('',False)
        if not sels:
            return
        if len(sels)>1:
            raise RuntimeError(
                    'The selections must have a common (grand)parent assembly')

        sel = sels[0]
        subs = list(sel.SubElementNames)
        if not subs:
            raise RuntimeError('no sub object in selection')
        if len(subs)>2:
            raise RuntimeError('At most two selection is allowed.\n'
                'The first selection must be a sub element belonging to some '
                'assembly. The optional second selection must be an element '
                'belonging to the same assembly of the first selection')
        if len(subs)==2:
            if len(subs[0])<len(subs[1]):
                subs = [subs[1],subs[2]]

        if subs[0][-1] == '.':
            subElement = utils.deduceSelectedElement(sel.Object,subs[0])
            if not subElement:
                raise RuntimeError('no sub element (face, edge, vertex) in '
                        '{}.{}'.format(sel.Object.Name,subs[0]))
            subs[0] += subElement

        link = Assembly.findPartGroup(sel.Object,subs[0])
        if not link:
            raise RuntimeError(
                    'Selected sub element does not belong to an assembly')

        element = None
        if len(subs)>1:
            ret = Assembly.findElementGroup(sel.Object,subs[1])
            if not ret:
                raise RuntimeError('The second selection must be an element')

            if ret.Assembly != link.Assembly:
                raise RuntimeError(
                        'The two selections must belong to the same assembly')

            element = ret.Object.getSubObject(ret.Subname,1)
            if not isTypeOf(element,AsmElement):
                raise RuntimeError('The second selection must be an element')

        return AsmElement.Selection(Element=element, Group=link.Object,
                                    Subname=link.Subname+subElement)

    @staticmethod
    def make(selection=None,name='Element'):
        '''Add/get/modify an element with the given selected object'''
        if not selection:
            selection = AsmElement.getSelection()

        group = selection.Group
        subname = selection.Subname

        if isTypeOf(group,AsmElementGroup):
            # if the selected object is an element of the owner assembly, simply
            # return that element
            element = group.getSubObject(subname,1)
            if not isTypeOf(element,AsmElement):
                raise RuntimeError('Invalid element reference {}.{}'.format(
                    group.Name,subname))
            return element

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
            group = group.getAssembly().getPartGroup()

        elif isTypeOf(group,AsmPartGroup):
            # If the selection come from the part group, first check for any
            # intermediate child assembly
            ret = Assembly.find(group,subname)
            if not ret:
                # If no child assembly in 'subname', simply assign the link as
                # it is, after making sure it is referencing an sub-element
                if not subname or subname[-1]=='.':
                    raise RuntimeError(
                            'Element must reference a geometry element')
            else:
                # In case there are intermediate assembly inside subname, we'll
                # recursively export the element in child assemblies first, and
                # then import that element to the current assembly.
                sel = AsmElement.Selection(
                        Element=None, Group=ret.Object, Subname=ret.Subname)
                element = AsmElement.make(sel)

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
        if not element:
            elements = group.Proxy.getAssembly().getElementGroup()
            # try to search the element group for an existing element
            for e in elements.Group:
                sub = logger.catch('',e.Proxy.getSubName)
                if sub == subname:
                    return e
            element = elements.Document.addObject("App::FeaturePython",
                    name,AsmElement(elements),None,True)
            ViewProviderAsmElement(element.ViewObject)
            elements.setLink({-1:element})
            elements.setElementVisible(element.Name,False)
            element.Proxy._initializing = False
            elements.cacheChildLabel()

        element.setLink(group,subname)
        return element


class ViewProviderAsmElement(ViewProviderAsmOnTop):
    def __init__(self,vobj):
        vobj.OverrideMaterial = True
        vobj.ShapeMaterial.DiffuseColor = self.getDefaultColor()
        vobj.ShapeMaterial.EmissiveColor = self.getDefaultColor()
        vobj.DrawStyle = 1
        vobj.LineWidth = 4
        vobj.PointSize = 8
        super(ViewProviderAsmElement,self).__init__(vobj)

    def getDefaultColor(self):
        return (60.0/255.0,1.0,1.0)

    def canDropObjectEx(self,_obj,owner,subname):
        if not subname:
            return False
        proxy = self.ViewObject.Object.Proxy
        return proxy.getAssembly().getPartGroup()==owner

    def dropObjectEx(self,vobj,_obj,owner,subname):
        AsmElement.make(AsmElement.Selection(Element=vobj.Object,
            Group=owner, Subname=subname))


PartInfo = namedtuple('AsmPartInfo', ('Parent','SubnameRef','Part',
    'PartName','Placement','Object','Subname','Shape'))

def getPartInfo(parent, subname):
    '''Return a named tuple containing the part object element information

    Parameters:

    parent: the parent document object, either an assembly, or a part group

    subname: subname reference to the part element (i.e. edge, face, vertex)

    Return a named tuple with the following fields:

    Parent: set to the input parent object

    SubnameRef: set to the input subname reference

    Part: either the part object, or a tuple(obj, idx) to refer to an element in
    an link array,

    PartName: a string name for the part

    Placement: the placement of the part

    Object: the object that owns the element. In case 'Part' is an assembly, we
    the element owner will always be some (grand)child of the 'Part'

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
        child = parent.getSubObject(names[0]+'.',1)
        if not child:
            raise RuntimeError('Invalid sub object {}, {}'.format(
                objName(parent), subname))

        if isTypeOf(child,AsmElementGroup):
            raise RuntimeError('Element object cannot be moved directly')

        if isTypeOf(child,AsmConstraintGroup):
            child = parent.getSubObject(subname,1)
            if not child:
                raise RuntimeError('Invalid sub object {}, {}'.format(
                    objName(parent), subname))
            if not isTypeOf(child,AsmElementLink):
                raise RuntimeError('{} cannot be moved'.format(objName(child)))
            return child.Proxy.getInfo()

        partGroup = child
        names = names[1:]
        subname = '.'.join(names)

    elif isTypeOf(parent,AsmPartGroup):
        partGroup = parent
    else:
        raise RuntimeError('{} is not Assembly or PartGroup'.format(
            objName(parent)))

    part = partGroup.getSubObject(names[0]+'.',1)
    if not part:
        raise RuntimeError('Invalid sub object {}, {}'.format(
            objName(parent), subnameRef))

    # For storing the shape of the element with proper transformation
    shape = None
    # For storing the placement of the movable part
    pla = None
    # For storing the actual geometry object of the part, in case 'part' is
    # a link
    obj = None

    if not isTypeOf(part,Assembly,True):
        getter = getattr(part.getLinkedObject(True),
                'getLinkExtProperty',None)

        # special treatment of link array (i.e. when ElementCount!=0), we
        # allow the array element to be moveable by the solver
        if getter and getter('ElementCount'):

            # store both the part (i.e. the link array), and the array
            # element object
            part = (part,part.getSubObject(names[1]+'.',1))

            # trim the subname to be after the array element
            sub = '.'.join(names[2:])

            # There are two states of an link array. 
            if getter('ElementList'):
                # a) The elements are expanded as individual objects, i.e
                # when ElementList has members, then the moveable Placement
                # is a property of the array element. So we obtain the shape
                # before 'Placement' by setting 'transform' set to False.
                shape=part[1].getSubObject(sub,transform=False)
                pla = part[1].Placement
                obj = part[0].getLinkedObject(False)
                partName = part[1].Name
            else:
                # b) The elements are collapsed. Then the moveable Placement
                # is stored inside link object's PlacementList property. So,
                # the shape obtained below is already before 'Placement',
                # i.e. no need to set 'transform' to False.
                shape=part[1].getSubObject(sub)
                obj = part[1]
                try:
                    idx = names[1].split('_i')[-1]
                    # we store the array index instead, in order to modified
                    # Placement later when the solver is done. Also because
                    # that when the elements are collapsed, there is really
                    # no element object here.
                    part = (part[0],int(idx),part[1])
                    pla = part[0].PlacementList[idx]
                except ValueError:
                    raise RuntimeError('invalid array subname of element {}: '
                        '{}'.format(objName(parent),subnameRef))

                partName = '{}.{}.'.format(part[0].Name,idx)

            subname = sub

    if not shape:
        # Here means, either the 'part' is an assembly or it is a non array
        # object. We trim the subname reference to be relative to the part
        # object.  And obtain the shape before part's Placement by setting
        # 'transform' to False
        subname = '.'.join(names[1:])
        shape = part.getSubObject(subname,transform=False)
        pla = part.Placement
        obj = part.getLinkedObject(False)
        partName = part.Name

    return PartInfo(Parent = parent,
                    SubnameRef = subnameRef,
                    Part = part,
                    PartName = partName,
                    Placement = pla.copy(),
                    Object = obj,
                    Subname = subname,
                    Shape = shape.copy())


class AsmElementLink(AsmBase):
    def __init__(self,parent):
        super(AsmElementLink,self).__init__()
        self.info = None
        self.parent = getProxy(parent,AsmConstraint)

    def linkSetup(self,obj):
        super(AsmElementLink,self).linkSetup(obj)
        obj.configLinkProperty('LinkedObject')
        #  obj.setPropertyStatus('LinkedObject','Immutable')
        obj.setPropertyStatus('LinkedObject','ReadOnly')

    def attach(self,obj):
        obj.addProperty("App::PropertyXLink","LinkedObject"," Link",'')
        super(AsmElementLink,self).attach(obj)

    def canLinkProperties(self,_obj):
        return False

    def execute(self,_obj):
        self.getInfo(True)
        return False

    def getAssembly(self):
        return self.parent.parent.parent

    def getElementSubname(self):
        'Resolve element link subname'

        #  AsmElementLink is used by constraint to link to a geometry link. It
        #  does so by indirectly linking to an AsmElement object belonging to
        #  the same parent assembly. AsmElement is also a link, which again
        #  links to another AsmElement of a child assembly or the actual
        #  geometry element of a child feature. This function is for resolving
        #  the AsmElementLink's subname reference to the actual part object
        #  subname reference relative to the parent assembly's part group

        linked = self.Object.getLinkedObject(False)
        if not linked or linked == self.Object:
            raise RuntimeError('Element link broken')
        element = getProxy(linked,AsmElement)
        assembly = element.getAssembly()
        if assembly == self.getAssembly():
            return element.getElementSubname()

        # The reference stored inside this ElementLink. We need the sub assembly
        # name, which is the name before the first dot. This name may be
        # different from the actual assembly object's name, in case where the
        # assembly is accessed through a link. And the sub assembly may be
        # inside a link array, which we don't know for sure. But we do know that
        # the last two names are element group and element label. So just pop
        # two names.
        ref = self.Object.LinkedObject[1]
        prefix = ref[0:ref.rfind('.',0,ref.rfind('.',0,-1))]
        return '{}.{}.{}'.format(prefix, assembly.getPartGroup().Name,
                element.getElementSubname())

    def setLink(self,owner,subname):
        # check if there is any sub assembly in the reference
        ret = Assembly.find(owner,subname)
        if not ret:
            # if not, add/get an element in our own element group
            sel = AsmElement.Selection(Element=None, Group=owner,
                                       Subname=subname)
            element = AsmElement.make(sel)
            owner = element.Proxy.parent.Object
            subname = '${}.'.format(element.Label)
        else:
            # if so, add/get an element from the sub assembly
            sel = AsmElement.Selection(Element=None, Group=ret.Object,
                                       Subname=ret.Subname)
            element = AsmElement.make(sel)
            owner = owner.Proxy.getAssembly().getPartGroup()

            # This give us reference to child assembly's immediate child
            # without trailing dot.
            prefix = subname[:len(subname)-len(ret.Subname)-1]

            # Pop the immediate child name, and replace it with child
            # assembly's element group name
            prefix = prefix[:prefix.rfind('.')+1] + \
                resolveAssembly(ret.Assembly).getElementGroup().Name

            subname = '{}.${}.'.format(prefix, element.Label)

        for sibling in self.parent.Object.Group:
            if sibling == self.Object:
                continue
            linked = sibling.LinkedObject
            if isinstance(linked,tuple) and \
               linked[0]==owner and linked[1]==subname:
                raise RuntimeError('duplicate element link {} in constraint '
                    '{}'.format(objName(sibling),objName(self.parent.Object)))
        self.Object.setLink(owner,subname)

    def getInfo(self,refresh=False):
        if not refresh:
            ret = getattr(self,'info',None)
            if ret:
                return ret
        self.info = None
        if not getattr(self,'Object',None):
            return
        self.info = getPartInfo(self.getAssembly().getPartGroup(),
                self.getElementSubname())
        return self.info

    @staticmethod
    def setPlacement(part,pla,undoDocs,undoName):
        '''
        called by solver after solving to adjust the placement.
        
        part: obtained by AsmConstraint.getInfo().Part
        pla: the new placement
        '''
        if isinstance(part,tuple):
            if isinstance(part[1],int):
                setupUndo(part[0].Document,undoDocs,undoName)
                part[0].PlacementList = {part[1]:pla}
            else:
                setupUndo(part[1].Document,undoDocs,undoName)
                part[1].Placement = pla
        else:
            setupUndo(part.Document,undoDocs,undoName)
            part.Placement = pla

    MakeInfo = namedtuple('AsmElementLinkMakeInfo',
            ('Constraint','Owner','Subname'))

    @staticmethod
    def make(info,name='ElementLink'):
        link = info.Constraint.Document.addObject("App::FeaturePython",
                    name,AsmElementLink(info.Constraint),None,True)
        ViewProviderAsmElementLink(link.ViewObject)
        info.Constraint.setLink({-1:link})
        link.Proxy.setLink(info.Owner,info.Subname)
        return link

def setPlacement(part,pla,undoDocs,undoName=None):
    AsmElementLink.setPlacement(part,pla,undoDocs,undoName)


class ViewProviderAsmElementLink(ViewProviderAsmOnTop):
    def doubleClicked(self,_vobj):
        return movePart()

    def canDropObjectEx(self,_obj,owner,subname):
        if logger.catchTrace('Cannot drop to AsmLink {}'.format(
            objName(self.ViewObject.Object)),
            self.ViewObject.Object.Proxy.prepareLink,
            owner, subname, True):
            return True
        return False

    def dropObjectEx(self,vobj,_obj,owner,subname):
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
        raise RuntimeError('Constraint type "{}" is not supported by '
                'solver "{}"'.format(Constraint.getTypeName(obj),
                    System.getTypeName(assembly)))

    def onChanged(self,obj,prop):
        if Constraint.onChanged(obj,prop):
            obj.recompute()

    def linkSetup(self,obj):
        self.elements = None
        super(AsmConstraint,self).linkSetup(obj)
        obj.setPropertyStatus('VisibilityList','Output')
        for o in obj.Group:
            getProxy(o,AsmElementLink).parent = self
        Constraint.attach(obj)
        obj.recompute()

    def execute(self,_obj):
        if not getattr(self,'_initializing',False) and\
           getattr(self,'parent',None):
            self.checkSupport()
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
        shapes = []
        elements = []
        for o in obj.Group:
            checkType(o,AsmElementLink)
            info = o.Proxy.getInfo()
            if not info:
                return
            shapes.append(info.Shape)
            elements.append(o)
        Constraint.check(obj,shapes,True)
        self.elements = elements
        return self.elements

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
        subs = sels[0].SubElementNames
        if not subs:
            raise RuntimeError('no sub-object in selection')
        if len(subs)>2:
            raise RuntimeError('too many selection')
        if len(subs)==2:
            sobj = sels[0].Object.getSubObject(subs[1],1)
            if isTypeOf(sobj,Assembly,True) or \
               isTypeOf(sobj,(AsmConstraintGroup,AsmConstraint)):
                subs = (subs[1],subs[0])

        sel = sels[0]
        cstr = None
        elements = []
        assembly = None
        selSubname = None
        for sub in subs:
            sobj = sel.Object.getSubObject(sub,1)
            if not sobj:
                raise RuntimeError('Cannot find sub-object {}.{}'.format(
                    sel.Object.Name,sub))
            ret = Assembly.find(sel.Object,sub,
                    recursive=True,relativeToChild=False)
            if not ret:
                raise RuntimeError('Selection {}.{} is not from an '
                    'assembly'.format(sel.Object.Name,sub))

            # check if the selection is a constraint group or a constraint
            if isTypeOf(sobj,Assembly,True) or \
               isTypeOf(sobj,(AsmConstraintGroup,Assembly,AsmConstraint)):
                if assembly:
                    raise RuntimeError('no element selection')
                assembly = ret[-1].Assembly
                selSubname = sub[:-len(ret[-1].Subname)]
                if isTypeOf(sobj,AsmConstraint):
                    cstr = sobj
                continue

            if not assembly:
                assembly = ret[0].Assembly
                selSubname = sub[:-len(ret[0].Subname)]
                found = ret[0]
            else:
                found = None
                for r in ret:
                    if r.Assembly == assembly:
                        found = r
                        break
                if not found:
                    raise RuntimeError('Selection {}.{} is not from the target '
                        'assembly {}'.format(
                            sel.Object.Name,sub,objName(assembly)))

            # because we call Assembly.find() above with relativeToChild=False,
            # we shall adjust the element subname by popping the first '.'
            sub = found.Subname
            sub = sub[sub.index('.')+1:]
            if sub[-1] == '.' and \
               not isTypeOf(sobj,Assembly,True) and \
               not isTypeOf(sobj,(AsmConstraint,AsmConstraintGroup,
                                  AsmElement,AsmElementLink)):
                # Too bad, its a full selection, let's guess the sub element
                subElement = utils.deduceSelectedElement(found.Object,sub)
                if not subElement:
                    raise RuntimeError('no sub element (face, edge, vertex) in '
                        '{}.{}'.format(found.Object.Name,sub))
                sub += subElement

            elements.append((found.Object,sub))

        if not Constraint.isDisabled(cstr):
            if cstr:
                typeid = Constraint.getTypeID(cstr)
                check = [o.Proxy.getInfo().Shape for o in cstr.Group] + elements
            else:
                check = elements
            Constraint.check(typeid,check)

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
            cstr = sel.Constraint
            if undo:
                doc = cstr.Document
                doc.openTransaction('Assembly change constraint')
        else:
            constraints = sel.Assembly.Proxy.getConstraintGroup()
            if undo:
                doc = constraints.Document
                doc.openTransaction('Assembly make constraint')
            cstr = constraints.Document.addObject("App::FeaturePython",
                    name,AsmConstraint(constraints),None,True)
            proxy = ViewProviderAsmConstraint(cstr.ViewObject)
            logger.debug('cstr viewobject {},{},{},{}'.format(
                id(proxy),id(cstr.ViewObject.Proxy),
                id(proxy.ViewObject),id(cstr.ViewObject)))
            constraints.setLink({-1:cstr})
            Constraint.setTypeID(cstr,typeid)

        try:
            for e in sel.Elements:
                AsmElementLink.make(AsmElementLink.MakeInfo(cstr,*e))
            cstr.Proxy._initializing = False
            if cstr.recompute() and asm3.gui.AsmCmdManager.AutoRecompute:
                logger.catch('solver exception when auto recompute',
                        asm3.solver.solve, sel.Assembly, undo=undo)
            if undo:
                doc.commitTransaction()

            if sel.SelObject:
                FreeCADGui.Selection.clearSelection()
                subname = sel.SelSubname
                if subname:
                    subname += '.'
                subname += sel.Assembly.Proxy.getConstraintGroup().Name + \
                        '.' + cstr.Name + '.'
                FreeCADGui.Selection.addSelection(sel.SelObject,subname)
                FreeCADGui.runCommand('Std_TreeSelection')
            return cstr

        except Exception:
            if undo:
                doc.abortTransaction()
            raise


class ViewProviderAsmConstraint(ViewProviderAsmGroup):
    def __init__(self,vobj):
        vobj.OverrideMaterial = True
        vobj.ShapeMaterial.DiffuseColor = self.getDefaultColor()
        vobj.ShapeMaterial.EmissiveColor = self.getDefaultColor()
        super(ViewProviderAsmConstraint,self).__init__(vobj)

    def getDefaultColor(self):
        return (1.0,60.0/255.0,60.0/255.0)

    def getIcon(self):
        return Constraint.getIcon(self.ViewObject.Object)

    def _getSelection(self,owner,subname):
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
            raise RuntimeError('not from the same assembly')
        subname = owner.Name + '.' + subname
        obj = self.ViewObject.Object
        mysub = parent.getConstraintGroup().Name + '.' + obj.Name + '.'
        sel = [Selection(Object=parent.Object,SubElementNames=[subname,mysub])]
        typeid = Constraint.getTypeID(obj)
        return AsmConstraint.getSelection(typeid,sel)

    def canDropObjectEx(self,_obj,owner,subname):
        cstr = self.ViewObject.Object
        if logger.catchTrace('Cannot drop to AsmConstraint {}'.format(cstr),
                self._getSelection,owner,subname):
            return True
        return False

    def dropObjectEx(self,_vobj,_obj,owner,subname):
        sel = self._getSelection(owner,subname)
        cstr = self.ViewObject.Object
        typeid = Constraint.getTypeID(cstr)
        sel = AsmConstraint.Selection(SelObject=None,
                                      SelSubname=None,
                                      Assembly=sel.Assembly,
                                      Constraint=cstr,
                                      Elements=sel.Elements)
        AsmConstraint.make(typeid,sel,undo=False)


class AsmConstraintGroup(AsmGroup):
    def __init__(self,parent):
        self.parent = getProxy(parent,Assembly)
        super(AsmConstraintGroup,self).__init__()

    def getAssembly(self):
        return self.parent

    def linkSetup(self,obj):
        super(AsmConstraintGroup,self).linkSetup(obj)
        obj.setPropertyStatus('VisibilityList','Output')
        for o in obj.Group:
            cstr = getProxy(o,AsmConstraint)
            if cstr:
                cstr.parent = self
                obj.recompute()

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


class AsmElementGroup(AsmGroup):
    def __init__(self,parent):
        self.parent = getProxy(parent,Assembly)
        super(AsmElementGroup,self).__init__()

    def linkSetup(self,obj):
        super(AsmElementGroup,self).linkSetup(obj)
        obj.setPropertyStatus('VisibilityList','Output')
        for o in obj.Group:
            getProxy(o,AsmElement).parent = self
        obj.cacheChildLabel()

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
                label = label[:i+1]
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

    def onDelete(self,_obj,_subs):
        return False

    def canDropObjectEx(self,_obj,owner,subname):
        if not subname:
            return False
        proxy = self.ViewObject.Object.Proxy
        return proxy.getAssembly().getPartGroup()==owner

    def dropObjectEx(self,_vobj,_obj,owner,subname):
        AsmElement.make(AsmElement.Selection(
            Element=None, Group=owner, Subname=subname))


BuildShapeNone = 'None'
BuildShapeCompound = 'Compound'
BuildShapeFuse = 'Fuse'
BuildShapeCut = 'Cut'
BuildShapeNames = (BuildShapeNone,BuildShapeCompound,
        BuildShapeFuse,BuildShapeCut)

class Assembly(AsmGroup):
    def __init__(self):
        self.constraints = None
        super(Assembly,self).__init__()

    def execute(self,obj):
        self.constraints = None
        self.buildShape()
        System.touch(obj)
        obj.ViewObject.Proxy.onExecute()
        return False # return False to call LinkBaseExtension::execute()

    def onSolverChanged(self,setup=False):
        for obj in self.getConstraintGroup().Group:
            # setup==True usually means we are restoring, so try to restore the
            # non-touched state if possible, since recompute() below will touch
            # the constraint object
            touched = not setup or 'Touched' in obj.State
            obj.recompute()
            if not touched:
                obj.purgeTouched()

    def buildShape(self):
        import Part
        obj = self.Object
        if obj.BuildShape == BuildShapeNone:
            obj.Shape = Part.Shape()
            return

        shape = []
        partGroup = self.getPartGroup(obj)
        group = partGroup.Group
        if not group:
            raise RuntimeError('no parts')
        if obj.BuildShape == BuildShapeCut:
            shape = Part.getShape(group[0]).Solids
            if not shape:
                raise RuntimeError('First part has no solid')
            if len(shape)>1:
                shape = [shape[0].fuse(shape[1:])]
            group = group[1:]

        for o in group:
            if obj.isElementVisible(o.Name):
                shape += Part.getShape(o).Solids
        if not shape:
            raise RuntimeError('No solids found in parts')
        if len(shape) == 1:
            obj.Shape = shape[0]
        elif obj.BuildShape == BuildShapeFuse:
            obj.Shape = shape[0].fuse(shape[1:])
        elif obj.BuildShape == BuildShapeCut:
            if len(shape)>2:
                obj.Shape = shape[0].cut(shape[1].fuse(shape[2:]))
            else:
                obj.Shape = shape[0].cut(shape[1])
        else:
            obj.Shape = Part.makeCompound(shape)

    def attach(self, obj):
        obj.addProperty("App::PropertyEnumeration","BuildShape","Base",'')
        obj.BuildShape = BuildShapeNames
        super(Assembly,self).attach(obj)

    def linkSetup(self,obj):
        obj.configLinkProperty('Placement')
        super(Assembly,self).linkSetup(obj)
        obj.setPropertyStatus('VisibilityList','Output')
        System.attach(obj)
        self.onChanged(obj,'BuildShape')

        # make sure all children are there, first constraint group, then element
        # group, and finally part group. Call getPartGroup below will make sure
        # all groups exist. The order of the group is important to make sure
        # correct rendering and picking behavior
        self.getPartGroup(True)

        self.onSolverChanged(True)

    def onChanged(self, obj, prop):
        if prop == 'BuildShape':
            if not obj.BuildShape or obj.BuildShape == BuildShapeCompound:
                obj.setPropertyStatus('Shape','-Transient')
            else:
                obj.setPropertyStatus('Shape','Transient')
            return
        System.onChanged(obj,prop)

    def getConstraintGroup(self, create=False):
        obj = self.Object
        try:
            ret = obj.Group[0]
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
        self.constraints = None
        cstrGroup = self.getConstraintGroup()
        if not cstrGroup:
            return
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

    @staticmethod
    def make(doc=None,name='Assembly',undo=True):
        if not doc:
            doc = FreeCAD.ActiveDocument
            if not doc:
                raise RuntimeError('No active document')
        if undo:
            doc.openTransaction('Create assembly')
        try:
            obj = doc.addObject(
                    "Part::FeaturePython",name,Assembly(),None,True)
            ViewProviderAssembly(obj.ViewObject)
            obj.Visibility = True
            obj.purgeTouched()
            if undo:
                doc.commitTransaction()
        except Exception:
            if undo:
                doc.abortTransaction()
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
                ret = Assembly.find(sel.Object,subname,recursive=True)
                if ret:
                    objs.add(ret[-1].Assembly)
        return tuple(objs)

    @staticmethod
    def find(obj,subname,childType=None,
            recursive=False,relativeToChild=True,keepEmptyChild=False):
        '''
        Find the immediate child of the first Assembly referenced in 'subs'

        obj: the parent object

        subname: '.' separted sub-object reference, or string list of sub-object
                 names. Must contain no sub element name.

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
                raise RuntimeError('Cannot find sub object {}, '
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


class AsmMovingPart(object):
    def __init__(self,hierarchy,info):
        self.objs = [h.Assembly for h in reversed(hierarchy)]
        self.assembly = resolveAssembly(info.Parent)
        self.parent = info.Parent
        self.subname = info.SubnameRef
        self.undos = None
        self.part = info.Part

        fixed = Constraint.getFixedTransform(self.assembly.getConstraints())
        fixed = fixed.get(info.Part,None)
        self.fixedTransform = fixed
        if fixed and fixed.Shape:
            shape = fixed.Shape
        else:
            shape = info.Shape

        rot = utils.getElementRotation(shape)
        if not rot:
            # in case the shape has no normal, like a vertex, just use an empty
            # rotation, which means having the same rotation has the owner part.
            rot = FreeCAD.Rotation()

        hasBound = True
        if not utils.isVertex(shape):
            self.bbox = shape.BoundBox
        else:
            bbox = info.Object.ViewObject.getBoundingBox()
            if bbox.isValid():
                self.bbox = bbox
            else:
                logger.warn('empty bounding box of part {}'.format(
                    info.PartName))
                self.bbox = FreeCAD.BoundBox(0,0,0,5,5,5)
                hasBound = False

        pos = utils.getElementPos(shape)
        if not pos:
            if hasBound:
                pos = self.bbox.Center
            else:
                pos = shape.Placement.Base
        pla = FreeCAD.Placement(pos,rot)

        self.offset = pla.copy()
        self.offsetInv = pla.inverse()
        self.draggerPlacement = info.Placement.multiply(pla)
        self.tracePoint = self.draggerPlacement.Base
        self.trace = None

    def update(self):
        info = getPartInfo(self.parent,self.subname)
        self.part = info.Part
        pla = info.Placement.multiply(FreeCAD.Placement(self.offset))
        logger.trace('part move update {}: {}'.format(objName(self.parent),pla))
        self.draggerPlacement = pla
        if asm3.gui.AsmCmdManager.Trace and \
           self.tracePoint.isEqual(pla.Base,1e5):
            if not self.trace:
                self.trace = FreeCAD.ActiveDocument.addObject(
                    'Part::Polygon','AsmTrace')
                self.trace.Nodes = {-1:self.tracePoint}
            self.tracePoint = pla.Base
            self.trace.Nodes = {-1:pla.Base}
            self.trace.recompute()
        return pla

    _undoName = 'Assembly move'

    def move(self):
        obj = self.assembly.Object
        pla = obj.ViewObject.DraggingPlacement

        update = True
        if self.fixedTransform:
            fixed = self.fixedTransform
            movement = self.draggerPlacement.inverse().multiply(pla)
            if not fixed.Shape:
                # The moving part has completely fixed placement, so we move the
                # parent assembly instead
                pla = obj.Placement.multiply(movement)
                setPlacement(obj,pla,self.undos,self._undoName)
                update = False
            else:
                # fixed position, so reset translation
                movement.Base = FreeCAD.Vector()
                if not utils.isVertex(fixed.Shape):
                    yaw,_,_ = movement.Rotation.toEuler()
                    # when dragging with a fixed axis, we align the dragger Z
                    # axis with that fixed axis. So we shall only keep the yaw
                    # among the euler angles
                    movement.Rotation = FreeCAD.Rotation(yaw,0,0)
                pla = self.draggerPlacement.multiply(movement)

        if update:
            # obtain and update the part placement
            pla = pla.multiply(self.offsetInv)
            setPlacement(self.part,pla,self.undos,self._undoName)

        if not asm3.gui.AsmCmdManager.AutoRecompute:
            # AsmCmdManager.AutoRecompute means auto re-solve the system. The
            # recompute() call below is only for updating linked element and
            # stuff
            obj.recompute(True)
            return

        System.touch(obj)

        # calls asm3.solver.solve(obj) and redirect all the exceptions message
        # to logger only.
        logger.catch('solver exception when moving part',
                asm3.solver.solve,self.objs)

        # self.draggerPlacement, which holds the intended dragger placement, is
        # updated by the above solver call through the following chain, 
        #   solver.solve() -> (triggers dependent objects recompute when done)
        #   Assembly.execute() ->
        #   ViewProviderAssembly.onExecute() -> 
        #   AsmMovingPart.update()
        return self.draggerPlacement

def getMovingPartInfo():
    '''Extract information from current selection for part moving

    It returns a tuple containing the selected assembly hierarchy (obtained from
    Assembly.findChildren()), and AsmPartInfo of the selected child part object. 
    
    If there is only one selection, then the moving part will be one belong to
    the highest level assembly in selected hierarchy.

    If there are two selections, then one selection must be a parent assembly
    containing the other child object. The moving object will then be the
    immediate child part object of the owner assembly. The actual selected sub
    element, i.e. vertex, edge, face will determine the dragger placement
    '''

    sels = FreeCADGui.Selection.getSelectionEx('',False)
    if not sels:
        raise RuntimeError('no selection')

    if not sels[0].SubElementNames:
        raise RuntimeError('no sub object in selection')

    if len(sels)>1 or len(sels[0].SubElementNames)>2:
        raise RuntimeError('too many selection')

    ret = Assembly.findChildren(sels[0].Object,sels[0].SubElementNames[0])
    if not ret:
        raise RuntimeError('invalid selection {}, subname {}'.format(
            objName(sels[0].Object),sels[0].SubElementNames[0]))

    if len(sels[0].SubElementNames)==1:
        info = getPartInfo(ret[0].Assembly,ret[0].Subname)
        if not info:
            return
        return (ret, info)

    ret2 = Assembly.findChildren(sels[0].Object,sels[0].SubElementNames[1])
    if not ret2:
        raise RuntimeError('invalid selection {}, subname {}'.format(
            objName(sels[0].Object),sels[0].SubElementNames[1]))

    if len(ret) == len(ret2):
        if not ret2[-1].Object:
            ret,ret2 = ret2,ret
    elif len(ret) > len(ret2):
        ret,ret2 = ret2,ret

    assembly = ret[-1].Assembly
    for r in ret2:
        if assembly == r.Assembly:
            return (ret2, getPartInfo(r.Assembly,r.Subname))
    raise RuntimeError('not child parent selection')

def canMovePart():
    return logger.catchTrace('',getMovingPartInfo) is not None

def movePart(useCenterballDragger=None):
    ret = logger.catch('exception when moving part', getMovingPartInfo)
    if not ret:
        return False

    info = ret[1]
    doc = FreeCADGui.editDocument()
    if doc:
        doc.resetEdit()
    vobj = resolveAssembly(info.Parent).Object.ViewObject
    doc = info.Parent.ViewObject.Document
    if useCenterballDragger is not None:
        vobj.UseCenterballDragger = useCenterballDragger
    vobj.Proxy._movingPart = AsmMovingPart(*ret)
    return doc.setEdit(vobj,1)


class ViewProviderAssembly(ViewProviderAsmGroup):
    def __init__(self,vobj):
        self._movingPart = None
        super(ViewProviderAssembly,self).__init__(vobj)

    def _convertSubname(self,owner,subname):
        sub = subname.split('.')
        if not sub:
            return
        me = self.ViewObject.Object
        partGroup = me.Proxy.getPartGroup().ViewObject
        if sub == me.Name:
            return partGroup,partGroup,subname[len[sub]+1:]
        return partGroup,owner,subname

    def canDropObjectEx(self,obj,owner,subname):
        info = self._convertSubname(owner,subname)
        if not info:
            return False
        partGroup,owner,subname = info
        return partGroup.canDropObject(obj,owner,subname)

    def canDragAndDropObject(self,_obj):
        return True

    def dropObjectEx(self,_vobj,obj,owner,subname):
        info = self._convertSubname(owner,subname)
        if not info:
            return False
        partGroup,owner,subname = info
        partGroup.dropObject(obj,owner,subname)

    def getIcon(self):
        return System.getIcon(self.ViewObject.Object)

    def doubleClicked(self, _vobj):
        return movePart()

    def onExecute(self):
        if not getattr(self,'_movingPart',None):
            return

        pla = logger.catch('exception when update moving part',
                self._movingPart.update)
        if pla:
            self.ViewObject.DraggingPlacement = pla
        else:
            doc = FreeCADGui.editDocument()
            if doc:
                doc.resetEdit()

    def initDraggingPlacement(self):
        if not getattr(self,'_movingPart',None):
            return
        return (FreeCADGui.editDocument().EditingTransform,
                self._movingPart.draggerPlacement,
                self._movingPart.bbox)

    def onDragStart(self):
        self._movingPart.undos = set()

    def onDragMotion(self):
        return self._movingPart.move()

    def onDragEnd(self):
        for doc in self._movingPart.undos:
            doc.commitTransaction()

    def unsetEdit(self,_vobj,_mode):
        self._movingPart = None
        return False


class AsmWorkPlane(object):
    def __init__(self,obj):
        obj.addProperty("App::PropertyLength","Length","Base")
        obj.addProperty("App::PropertyLength","Width","Base")
        obj.Length = 10
        obj.Width = 10
        obj.Proxy = self

    def execute(self,obj):
        import Part
        if not obj.Length or not obj.Width:
            raise RuntimeError('invalid workplane size')
        obj.Shape = Part.makePlane(obj.Length,obj.Width)

    def __getstate__(self):
        return

    def __setstate__(self,_state):
        return

    Info = namedtuple('AsmWorkPlaneSelectionInfo',
            ('SelObj','SelSubname','PartGroup'))

    @staticmethod
    def getSelection(sels=None):
        if not sels:
            sels = FreeCADGui.Selection.getSelectionEx('',False)
        if len(sels)!=1 or len(sels[0].SubElementNames)>1:
            raise RuntimeError('too many selections')
        if sels[0].SubElementNames:
            sub = sels[0].SubElementNames[0]
        else:
            sub = ''
        ret = Assembly.find(sels[0].Object,sub,
                relativeToChild=False,keepEmptyChild=True)
        if not ret:
            raise RuntimeError('invalid selection')
        if ret.Subname:
            sub = sub[:-len(ret.Subname)]
        return AsmWorkPlane.Info(
                SelObj = sels[0].Object,
                SelSubname = sub,
                PartGroup = ret.Assembly.Proxy.getPartGroup())

    @staticmethod
    def make(sels=None,name='Workplane', undo=True):
        info = AsmWorkPlane.getSelection(sels)
        doc = info.PartGroup.Document
        if undo:
            doc.openTransaction('Assembly make workplane')
        try:
            obj = doc.addObject('Part::FeaturePython',name)
            AsmWorkPlane(obj)
            ViewProviderAsmWorkPlane(obj.ViewObject)
            bbox = info.PartGroup.ViewObject.getBoundingBox()
            if bbox.isValid():
                obj.Length = bbox.DiagonalLength*0.5
                obj.Width = obj.Length
            obj.recompute(True)
            info.PartGroup.setLink({-1:obj})
            doc.commitTransaction()

            FreeCADGui.Selection.clearSelection()
            FreeCADGui.Selection.addSelection(info.SelObj,
                info.SelSubname + info.PartGroup.Name + '.' + obj.Name + '.')
            FreeCADGui.runCommand('Std_TreeSelection')
            return obj
        except Exception:
            if undo:
                doc.abortTransaction()
            raise


class ViewProviderAsmWorkPlane(ViewProviderAsmBase):
    _iconName = 'Assembly_Workplane.svg'

    def __init__(self,vobj):
        vobj.Transparency = 50
        vobj.LineColor = (0.0,0.33,1.0,1.0)
        super(ViewProviderAsmWorkPlane,self).__init__(vobj)

    def canDropObjects(self):
        return False

    def getDisplayModes(self, _vobj):
        modes=[]
        return modes

    def setDisplayMode(self, mode):
        return mode
