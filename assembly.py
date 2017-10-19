import os
from collections import namedtuple
import FreeCAD, FreeCADGui
import asm3
import asm3.utils as utils
from asm3.utils import logger, objName
from asm3.constraint import Constraint
from asm3.system import System

def setupUndo(doc,undoDocs,name):
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
        raise TypeError('Expect object "{}" to be of type "{}"'.format(
                objName(obj),tp.__name__))

def getProxy(obj,tp):
    checkType(obj,tp)
    return obj.Proxy

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

    def onChanged(self,_obj,_prop):
        pass

class ViewProviderAsmBase(object):
    def __init__(self,vobj):
        vobj.Visibility = False
        vobj.Proxy = self
        self.attach(vobj)

    def attach(self,vobj):
        self.ViewObject = vobj
        vobj.signalChangeIcon()

    def __getstate__(self):
        return None

    def __setstate__(self, _state):
        return None

    _iconName = None

    @classmethod
    def getIcon(cls):
        if cls._iconName:
            return utils.getIcon(cls)


class AsmGroup(AsmBase):
    def linkSetup(self,obj):
        super(AsmGroup,self).linkSetup(obj)
        obj.configLinkProperty(
                'VisibilityList',LinkMode='GroupMode',ElementList='Group')
        self.setGroupMode()

    def setGroupMode(self):
        self.Object.GroupMode = 1 # auto delete children
        self.Object.setPropertyStatus('GroupMode','Hidden')
        self.Object.setPropertyStatus('GroupMode','Immutable')
        self.Object.setPropertyStatus('GroupMode','Transient')

    def attach(self,obj):
        obj.addProperty("App::PropertyLinkList","Group","Base",'')
        obj.addProperty("App::PropertyBoolList","VisibilityList","Base",'')
        obj.addProperty("App::PropertyEnumeration","GroupMode","Base",'')
        super(AsmGroup,self).attach(obj)


class ViewProviderAsmGroup(ViewProviderAsmBase):
    def claimChildren(self):
        return self.ViewObject.Object.Group

    def doubleClicked(self):
        return False


class AsmPartGroup(AsmGroup):
    def __init__(self,parent):
        self.parent = getProxy(parent,Assembly)
        super(AsmPartGroup,self).__init__()

    def setGroupMode(self):
        pass

    @staticmethod
    def make(parent,name='Parts'):
        obj = parent.Document.addObject("App::FeaturePython",name,
                    AsmPartGroup(parent),None,True)
        ViewProviderAsmPartGroup(obj.ViewObject)
        obj.purgeTouched()
        return obj


class ViewProviderAsmPartGroup(ViewProviderAsmBase):
    _iconName = 'Assembly_Assembly_Part_Tree.svg'

    def onDelete(self,_obj,_subs):
        return False

    def canDropObject(self,obj):
        return isTypeOf(obj,Assembly) or not isTypeOf(obj,AsmBase)

    def canDropObjects(self):
        return True

class AsmElement(AsmBase):
    def __init__(self,parent):
        self.shape = None
        self.parent = getProxy(parent,AsmElementGroup)
        super(AsmElement,self).__init__()

    def linkSetup(self,obj):
        super(AsmElement,self).linkSetup(obj)
        obj.configLinkProperty('LinkedObject')
        obj.setPropertyStatus('LinkedObject','Immutable')
        obj.setPropertyStatus('LinkedObject','ReadOnly')

    def attach(self,obj):
        obj.addProperty("App::PropertyXLink","LinkedObject"," Link",'')
        super(AsmElement,self).attach(obj)

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

    def setLink(self,owner,subname):
        # subname must be relative to the part group object of the parent
        # assembly

        # check old linked object for auto re-label
        obj = self.Object
        linked = obj.getLinkedObject(False)
        if linked and linked!=obj:
            label = '{}_{}_Element'.format(linked.Label,self.getSubElement())
        else:
            label = ''

        obj.setLink(owner,subname)

        if obj.Label==obj.Name or obj.Label.startswith(label):
            linked = obj.getLinkedObject(False)
            if linked and linked!=obj:
                obj.Label = '{}_{}_Element'.format(
                        linked.Label,self.getSubElement())
            else:
                obj.Label = obj.Name

    Selection = namedtuple('AsmElementSelection',
            ('Assembly','Element','Subname'))

    @staticmethod
    def getSelection():
        '''
        Parse Gui.Selection for making a element

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
        subs = sel.SubElementNames
        if len(subs)>2:
            raise RuntimeError('At most two selection is allowed.\n'
                'The first selection must be a sub element belonging to some '
                'assembly. The optional second selection must be an element '
                'belonging to the same assembly of the first selection')

        subElement = subs[0].split('.')[-1]
        if not subElement:
            raise RuntimeError(
                'Please select a sub element belonging to some assembly')

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

        return AsmElement.Selection(Assembly = link.Assembly,
                                    Element = element,
                                    Subname = link.Subname+subElement)

    @staticmethod
    def make(selection=None,name='Element'):
        if not selection:
            selection = AsmElement.getSelection()
        assembly = getProxy(selection.Assembly,Assembly)
        element = selection.Element
        if not element:
            elements = assembly.getElementGroup()
            # try to search the element group for an existing element
            for e in elements.Group:
                if getProxy(e,AsmElement).getSubName() == selection.Subname:
                    return element
            element = elements.Document.addObject("App::FeaturePython",
                    name,AsmElement(elements),None,True)
            ViewProviderAsmElement(element.ViewObject)
            elements.setLink({-1:element})

        getProxy(element,AsmElement).setLink(
                assembly.getPartGroup(),selection.Subname)
        return element


class ViewProviderAsmElement(ViewProviderAsmBase):
    def attach(self,vobj):
        super(ViewProviderAsmElement,self).attach(vobj)
        vobj.OverrideMaterial = True
        vobj.ShapeMaterial.DiffuseColor = self.getDefaultColor()
        vobj.ShapeMaterial.EmissiveColor = self.getDefaultColor()
        vobj.DrawStyle = 1
        vobj.LineWidth = 4
        vobj.PointSize = 6

    def getDefaultColor(self):
        return (60.0/255.0,1.0,1.0)


class AsmElementLink(AsmBase):
    def __init__(self,parent):
        super(AsmElementLink,self).__init__()
        self.info = None
        self.parent = getProxy(parent,AsmConstraint)

    def linkSetup(self,obj):
        super(AsmElementLink,self).linkSetup(obj)
        obj.configLinkProperty('LinkedObject')
        obj.setPropertyStatus('LinkedObject','Immutable')
        obj.setPropertyStatus('LinkedObject','ReadOnly')

    def attach(self,obj):
        obj.addProperty("App::PropertyXLink","LinkedObject"," Link",'')
        super(AsmElementLink,self).attach(obj)

    def execute(self,obj):
        obj.ViewObject.Proxy.onExecute(self.getInfo(True))
        return False

    def getAssembly(self):
        return self.parent.parent.parent

    def getElement(self):
        linked = self.Object.getLinkedObject(False)
        if not linked:
            raise RuntimeError('Element link broken')
        if not isTypeOf(linked,AsmElement):
            raise RuntimeError('Invalid element type')
        return linked.Proxy

    def getSubName(self):
        link = self.Object.LinkedObject
        if not isinstance(link,tuple):
            raise RuntimeError('Invalid element link "{}"'.format(
                objName(self.Object)))
        return link[1]

    def getShapeSubName(self):
        element = self.getElement()
        assembly = element.getAssembly()
        if assembly == self.getAssembly():
            return element.getSubName()
        # pop two names from back (i.e. element group, element)
        subname = self.getSubName()
        sub = subname.split('.')[:-3]
        sub = '.'.join(sub) + '.' + assembly.getPartGroup().Name + \
              '.' + element.getSubName()
        logger.debug('shape subname {} -> {}'.format(subname,sub))
        return sub

    def prepareLink(self,owner,subname):
        assembly = self.getAssembly()
        sobj = owner.getSubObject(subname,1)
        if not sobj:
            raise RuntimeError('invalid element link {} broken: {}'.format(
                objName(owner),subname))
        if isTypeOf(sobj,AsmElementLink):
            # if it points to another AsElementLink that belongs the same
            # assembly, simply return the same link
            if sobj.Proxy.getAssembly() == assembly:
                return sobj.LinkedObject
            # If it is from another assembly (i.e. a nested assembly), convert
            # the subname reference by poping three names (constraint group,
            # constraint, element link) from the back, and then append with the
            # element link's own subname reference
            sub = subname.split('.')[:-4]
            sub = '.'.join(subname)+'.'+sobj.Proxy.getSubName()
            logger.debug('convert element link {} -> {}'.format(subname,sub))
            return (owner,sub)

        if isTypeOf(sobj,AsmElement):
            return (owner,subname)

        # try to see if the reference comes from some nested assembly
        ret = assembly.findChild(owner,subname,recursive=True)
        if not ret:
            # It is from a non assembly child part, then use our own element
            # group as the holder for elements
            ret = [Assembly.Info(assembly.Object,owner,subname)]

        if not isTypeOf(ret[-1].Object,AsmPartGroup):
            raise RuntimeError('Invalid element link ' + subname)

        # call AsmElement.make to either create a new element, or an existing
        # element if there is one
        element = AsmElement.make(AsmElement.Selection(
                    ret[-1].Assembly,None,ret[-1].Subname))
        if ret[-1].Assembly == assembly.Object:
            return (assembly.getElementGroup(),element.Name+'.')

        elementSub = ret[-1].Object.Name + '.' + ret[-1].Subname
        sub = subname[:-(len(elementSub)+1)] + '.' + \
            ret[-1].Assembly.Proxy.getElementGroup().Name + '.' + \
            element.Name + '.'
        logger.debug('generate new element {} -> {}'.format(subname,sub))
        return (owner,sub)

    def setLink(self,owner,subname):
        obj = self.Object
        obj.setLink(*self.prepareLink(owner,subname))
        linked = obj.getLinkedObject(False)
        if linked and linked!=obj:
            label = linked.Label.split('_')
            if label[-1].startswith('Element'):
                label[-1] = 'Link'
            obj.Label = '_'.join(label)
        else:
            obj.Label = obj.Name

    Info = namedtuple('AsmElementLinkInfo',
            ('Part','PartName','Placement','Object','Subname','Shape'))

    def getInfo(self,refresh=False):
        if not refresh:
            ret = getattr(self,'info',None)
            if ret:
                return ret
        self.info = None
        if not getattr(self,'Object',None):
            return
        assembly = self.getAssembly()
        subname = self.getShapeSubName()
        names = subname.split('.')
        partGroup = assembly.getPartGroup()

        part = partGroup.getSubObject(names[0]+'.',1)
        if not part:
            raise RuntimeError('Eelement link "{}" borken: {}'.format(
                objName(self.Object),subname))

        # For storing the shape of the element with proper transformation
        shape = None
        # For storing the placement of the movable part
        pla = None
        # For storing the actual geometry object of the part, in case 'part' is
        # a link
        obj = None

        if not isTypeOf(part,Assembly,True) and \
           not Constraint.isDisabled(self.parent.Object) and \
           not Constraint.isLocked(self.parent.Object):
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
                        raise RuntimeError('invalid array subname of element '
                            '{}: {}'.format(objName(self.Object),subname))

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

        self.info = AsmElementLink.Info(Part = part,
                                        PartName = partName,
                                        Placement = pla.copy(),
                                        Object = obj,
                                        Subname = subname,
                                        Shape = shape.copy())
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

    MakeInfo = namedtuple('AsmElementLinkSelection',
            ('Constraint','Owner','Subname'))

    @staticmethod
    def make(info,name='ElementLink'):
        element = info.Constraint.Document.addObject("App::FeaturePython",
                    name,AsmElementLink(info.Constraint),None,True)
        ViewProviderAsmElementLink(element.ViewObject)
        info.Constraint.setLink({-1:element})
        element.Proxy.setLink(info.Owner,info.Subname)
        return element

def setPlacement(part,pla,undoDocs,undoName=None):
    AsmElementLink.setPlacement(part,pla,undoDocs,undoName)

class AsmDraggingContext(object):
    def __init__(self,info):
        self.undos = None
        self.part = info.Part
        rot = utils.getElementRotation(info.Shape)
        if not rot:
            # in case the shape has no normal, like a vertex, just use an empty
            # rotation, which means having the same rotation has the owner part.
            rot = FreeCAD.Rotation()
        pla = FreeCAD.Placement(utils.getElementPos(info.Shape),rot)
        self.offset = FreeCAD.Placement(pla.toMatrix())
        self.offsetInv = FreeCAD.Placement(pla.toMatrix().inverse())
        self.placement = info.Placement.multiply(pla)
        self.tracePoint = self.placement.Base
        self.trace = None

    def update(self,info):
        self.part = info.Part
        pla = info.Placement.multiply(FreeCAD.Placement(self.offset))
        self.placement = pla
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


class ViewProviderAsmElementLink(ViewProviderAsmBase):
    def __init__(self,vobj):
        self._draggingContext = None
        super(ViewProviderAsmElementLink,self).__init__(vobj)

    def doubleClicked(self, vobj):
        return vobj.Document.setEdit(vobj,1)

    def onExecute(self,info):
        if not getattr(self,'_draggingContext',None):
            return
        self.ViewObject.DraggingPlacement = self._draggingContext.update(info)

    def initDraggingPlacement(self):
        info = self.ViewObject.Object.Proxy.getInfo()
        self._draggingContext = AsmDraggingContext(info)
        return (FreeCADGui.editDocument().EditingTransform,
                self._draggingContext.placement,
                info.Shape.BoundBox)

    def onDragStart(self):
        self._draggingContext.undos = set()

    def onDragMotion(self):
        ctx = self._draggingContext
        pla = self.ViewObject.DraggingPlacement.multiply(ctx.offsetInv)
        setPlacement(ctx.part,pla,ctx.undos, 'Assembly drag')

        from PySide import QtCore,QtGui

        obj = self.ViewObject.Object
        if QtGui.QApplication.keyboardModifiers() == QtCore.Qt.ControlModifier:
            obj.getLinkedObject(False).recompute()
            obj.recompute()
            return

        try:
            asm3.solver.solve(obj.Proxy.getAssembly().Object)
        except RuntimeError as e:
            logger.error(e)
        return ctx.placement

    def onDragEnd(self):
        for doc in self._draggingContext.undos:
            doc.commitTransaction()

    def unsetEdit(self,_vobj,_mode):
        self._draggingContext = None
        return False


class AsmConstraint(AsmGroup):

    def __init__(self,parent):
        self._initializing = True
        self.elements = None
        self.parent = getProxy(parent,AsmConstraintGroup)
        super(AsmConstraint,self).__init__()

    def checkSupport(self):
        # this function maybe called during document restore, hence the
        # extensive check below
        obj = getattr(self,'Object',None)
        if not obj:
            return
        if Constraint.isLocked(obj) or \
           Constraint.isDisabled(obj):
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
        super(AsmConstraint,self).onChanged(obj,prop)
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
        Constraint.check(obj,shapes)
        self.elements = elements
        return self.elements

    Selection = namedtuple('ConstraintSelection',
                    ('Assembly','Constraint','Elements'))

    @staticmethod
    def getSelection(typeid=0):
        '''
        Parse Gui.Selection for making a constraint

        The selected elements must all belong to the same immediate parent
        assembly. 
        '''
        sels = FreeCADGui.Selection.getSelectionEx('',False)
        if not sels:
            return
        if len(sels)>1:
            raise RuntimeError(
                    'The selections must have a common (grand)parent assembly')

        sel = sels[0]
        cstr = None
        elements = []
        assembly = None
        for sub in sel.SubElementNames:
            sobj = sel.Object.getSubObject(sub,1)
            ret = Assembly.findChild(sel.Object,sub,recursive=True)
            if not ret:
                raise RuntimeError('Selection {}.{} is not from an '
                    'assembly'.format(sel.Object.Name,sub))
            if not assembly:
                # check if the selection is a constraint group or a constraint
                if isTypeOf(sobj,AsmConstraintGroup):
                    assembly = ret[-1].Assembly
                    continue
                if isTypeOf(sobj,AsmConstraint):
                    cstr = sobj
                    assembly = ret[-1].Assembly
                    continue
                assembly = ret[0].Assembly

            found = None
            for r in ret:
                if r.Assembly == assembly:
                    found = r
                    break
            if not found:
                raise RuntimeError('Selection {}.{} is not from the target '
                    'assembly {}'.format(sel.Object.Name,sub,objName(assembly)))

            elements.append((found.Object,found.Subname))

        check = None
        if cstr and not Constraint.isDisabled(cstr):
            typeid = Constraint.getTypeID(cstr)
            info = cstr.Proxy.getInfo()
            check = [o.getShape() for o in info.Elements] + elements
        elif typeid:
            check = elements
        if check:
            Constraint.check(typeid,check)

        return AsmConstraint.Selection(Assembly = assembly,
                                       Constraint = cstr,
                                       Elements = elements)

    @staticmethod
    def make(typeid, selection=None, name='Constraint'):
        if not selection:
            selection = AsmConstraint.getSelection(typeid)
        if selection.Constraint:
            cstr = selection.Constraint
        else:
            constraints = selection.Assembly.Proxy.getConstraintGroup()
            cstr = constraints.Document.addObject("App::FeaturePython",
                    name,AsmConstraint(constraints),None,True)
            ViewProviderAsmConstraint(cstr.ViewObject)
            constraints.setLink({-1:cstr})
            Constraint.setTypeID(cstr,typeid)

        for e in selection.Elements:
            AsmElementLink.make(AsmElementLink.MakeInfo(cstr,*e))
        cstr.Proxy._initializing = False
        cstr.recompute()
        return cstr


class ViewProviderAsmConstraint(ViewProviderAsmGroup):
    def attach(self,vobj):
        super(ViewProviderAsmConstraint,self).attach(vobj)
        vobj.OverrideMaterial = True
        vobj.ShapeMaterial.DiffuseColor = self.getDefaultColor()
        vobj.ShapeMaterial.EmissiveColor = self.getDefaultColor()

    def getDefaultColor(self):
        return (1.0,60.0/255.0,60.0/255.0)

    def getIcon(self):
        return Constraint.getIcon(self.ViewObject.Object)


class AsmConstraintGroup(AsmGroup):
    def __init__(self,parent):
        self.parent = getProxy(parent,Assembly)
        super(AsmConstraintGroup,self).__init__()

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


class ViewProviderAsmConstraintGroup(ViewProviderAsmBase):
    _iconName = 'Assembly_Assembly_Constraints_Tree.svg'


class AsmElementGroup(AsmGroup):
    def __init__(self,parent):
        self.parent = getProxy(parent,Assembly)
        super(AsmElementGroup,self).__init__()

    def linkSetup(self,obj):
        super(AsmElementGroup,self).linkSetup(obj)
        obj.setPropertyStatus('VisibilityList','Output')
        for o in obj.Group:
            getProxy(o,AsmElement).parent = self

    @staticmethod
    def make(parent,name='Elements'):
        obj = parent.Document.addObject("App::FeaturePython",name,
                        AsmElementGroup(parent),None,True)
        ViewProviderAsmElementGroup(obj.ViewObject)
        obj.purgeTouched()
        return obj


class ViewProviderAsmElementGroup(ViewProviderAsmBase):
    _iconName = 'Assembly_Assembly_Element_Tree.svg'

    def onDelete(self,_obj,_subs):
        return False

    def canDragObject(self,_obj):
        return False

    def canDragObjects(self):
        return False

    def canDragAndDropObject(self,_obj):
        return False

    def canDropObjectEx(self,_obj,owner,subname):
        # check if is dropping a sub-element
        if subname.rfind('.')+1 == len(subname):
            return False
        return self.ViewObject.Object.Proxy.parent.getPartGroup()==owner

    def dropObjectEx(self,vobj,_obj,_owner,subname):
        AsmElement.make(AsmElement.Selection(
            vobj.Object.Proxy.parent.Object,None,subname))


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
        super(Assembly,self).onChanged(obj,prop)

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
                logger.debug('skip constraint "{}" type '
                    '{}'.format(objName(o),o.Type))
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
    def make(doc=None,name='Assembly'):
        if not doc:
            doc = FreeCAD.ActiveDocument
        obj = doc.addObject(
                "Part::FeaturePython",name,Assembly(),None,True)
        ViewProviderAssembly(obj.ViewObject)
        obj.Visibility = True
        obj.purgeTouched()
        return obj

    Info = namedtuple('AssemblyInfo',('Assembly','Object','Subname'))

    @staticmethod
    def find(sels=None):
        'Find all assembly objects among the current selection'
        objs = set()
        if sels is None:
            sels = FreeCADGui.Selection.getSelectionEx('',False)
        for sel in sels:
            if not sel.SubElementNames:
                if isTypeOf(sel.Object,Assembly):
                    objs.add(sel.Object)
                continue
            for subname in sel.SubElementNames:
                ret = Assembly.findChild(sel.Object,subname,recursive=True)
                if ret:
                    objs.add(ret[-1].Assembly)
        return tuple(objs)

    @staticmethod
    def findChild(obj,subname,childType=None,
            recursive=False,relativeToChild=True):
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
        idx = -1
        if isTypeOf(obj,Assembly,True):
            assembly = obj
        subs = subname if isinstance(subname,list) else subname.split('.')
        for i,name in enumerate(subs[:-1]):
            obj = obj.getSubObject(name+'.',1)
            if not obj:
                raise RuntimeError('Cannot find sub object {}'.format(name))
            if assembly and isTypeOf(obj,childType):
                child = obj
                if relativeToChild:
                    idx = i+1
                else:
                    idx = i
                break
            assembly = obj if isTypeOf(obj,Assembly,True) else None

        if not child:
            return

        subs = subs[idx:]
        ret = Assembly.Info(Assembly = assembly,
                            Object = child,
                            Subname = '.'.join(subs))
        if not recursive:
            return ret

        nret = Assembly.findChild(child,subs,childType,True)
        if nret:
            return [ret] + nret
        return [ret]

    @staticmethod
    def findPartGroup(obj,subname='2.',recursive=False,relativeToChild=True):
        return Assembly.findChild(
                obj,subname,AsmPartGroup,recursive,relativeToChild)

    @staticmethod
    def findElementGroup(obj,subname='1.',relativeToChild=True):
        return Assembly.findChild(
                obj,subname,AsmElementGroup,False,relativeToChild)

    @staticmethod
    def findConstraintGroup(obj,subname='0.',relativeToChild=True):
        return Assembly.findChild(
                obj,subname,AsmConstraintGroup,False,relativeToChild)


class ViewProviderAssembly(ViewProviderAsmGroup):

    def canDragObject(self,_child):
        return False

    def canDragObjects(self):
        return False

    @property
    def PartGroup(self):
        return self.ViewObject.Object.Proxy.getPartGroup()

    def canDropObject(self,obj):
        self.PartGroup.ViewObject.canDropObject(obj)

    def canDropObjects(self):
        return True

    def dropObjectEx(self,_vobj,obj,owner,subname):
        self.PartGroup.ViewObject.dropObject(obj,owner,subname)

    def getIcon(self):
        return System.getIcon(self.ViewObject.Object)

