from collections import OrderedDict
import FreeCAD, FreeCADGui
from .utils import getElementPos,objName,addIconToFCAD,guilogger as logger
from .proxy import ProxyType
from .FCADLogger import FCADLogger

class SelectionObserver:
    def __init__(self):
        self._attached = False
        self.cmds = []
        self.elements = dict()
        self.attach()
        self.busy = False;

    def setCommands(self,cmds):
        self.cmds = cmds

    def onChanged(self):
        for cmd in self.cmds:
            cmd.checkActive()

    def _setElementVisible(self,obj,subname,vis):
        sobj = obj.getSubObject(subname,1)
        from .assembly import isTypeOf,AsmConstraint,\
                AsmElement,AsmElementLink
        if isTypeOf(sobj,(AsmElement,AsmElementLink)):
            res = sobj.Proxy.parent.Object.isElementVisible(sobj.Name)
            if res and vis:
                return False
            sobj.Proxy.parent.Object.setElementVisible(sobj.Name,vis)
        elif isTypeOf(sobj,AsmConstraint):
            vis = [vis] * len(sobj.Group)
            sobj.setPropertyStatus('VisibilityList','-Immutable')
            sobj.VisibilityList = vis
            sobj.setPropertyStatus('VisibilityList','Immutable')
        else:
            return
        if vis:
            FreeCADGui.Selection.updateSelection(vis,obj,subname)

    def setElementVisible(self,docname,objname,subname,vis,presel=False):
        if not AsmCmdManager.AutoElementVis:
            self.elements.clear()
            return
        doc = FreeCAD.getDocument(docname)
        if not doc:
            return
        obj = doc.getObject(objname)
        if not obj:
            return
        key = (docname,objname,subname)
        val = None
        if not vis:
            val = self.elements.get(key,None)
            if val is None or (presel and val):
                return
        if logger.catchWarn('',self._setElementVisible,
                obj,subname,vis) is False and presel:
            return
        if not vis:
            self.elements.pop(key,None)
        elif not presel:
            self.elements[key] = True
        else:
            self.elements.setdefault(key,False)

    def resetElementVisible(self):
        elements = list(self.elements)
        self.elements.clear()
        for docname,objname,subname in elements:
            doc = FreeCAD.getDocument(docname)
            if not doc:
                continue
            obj = doc.getObject(objname)
            if not obj:
                continue
            logger.catchWarn('',self._setElementVisible,obj,subname,False)

    def addSelection(self,docname,objname,subname,_pos):
        self.onChanged()
        self.setElementVisible(docname,objname,subname,True)

    def removeSelection(self,docname,objname,subname):
        self.onChanged()
        self.setElementVisible(docname,objname,subname,False)

    def setPreselection(self,docname,objname,subname):
        self.setElementVisible(docname,objname,subname,True,True)

    def removePreselection(self,docname,objname,subname):
        self.setElementVisible(docname,objname,subname,False,True)

    def setSelection(self,*_args):
        self.onChanged()
        if AsmCmdManager.AutoElementVis:
            self.resetElementVisible()
            for sel in FreeCADGui.Selection.getSelectionEx('*',False):
                for sub in sel.SubElementNames:
                    self.setElementVisible(sel.Object.Document.Name,
                            sel.Object.Name,sub,True)

    def clearSelection(self,*_args):
        for cmd in self.cmds:
            cmd.onClearSelection()
        self.resetElementVisible()

    def attach(self):
        logger.trace('attach selection aboserver {}'.format(self._attached))
        if not self._attached:
            FreeCADGui.Selection.addObserver(self,False)
            self._attached = True
            self.onChanged()

    def detach(self):
        logger.trace('detach selection aboserver {}'.format(self._attached))
        if self._attached:
            FreeCADGui.Selection.removeObserver(self)
            self._attached = False
            self.clearSelection('')


class AsmCmdManager(ProxyType):
    Toolbars = OrderedDict()
    Menus = OrderedDict()
    _defaultMenuGroupName = '&Assembly3'

    @classmethod
    def register(mcs,cls):
        if cls._id < 0:
            return
        super(AsmCmdManager,mcs).register(cls)
        FreeCADGui.addCommand(cls.getName(),cls)
        if cls._toolbarName:
            mcs.Toolbars.setdefault(cls._toolbarName,[]).append(cls)
        if cls._menuGroupName is not None:
            name = cls._menuGroupName
            if not name:
                name = mcs._defaultMenuGroupName
            mcs.Menus.setdefault(name,[]).append(cls)

    def getParamGroup(cls):
        return FreeCAD.ParamGet(
                'User parameter:BaseApp/Preferences/Mod/Assembly3')

    def getParam(cls,tp,name,default=None):
        return getattr(cls.getParamGroup(),'Get'+tp)(name,default)

    def setParam(cls,tp,name,v):
        getattr(cls.getParamGroup(),'Set'+tp)(name,v)

    def workbenchActivated(cls):
        pass

    def workbenchDeactivated(cls):
        pass

    def getContextMenuName(cls):
        if cls.IsActive() and cls._contextMenuName:
            return cls._contextMenuName

    def getName(cls):
        return 'asm3'+cls.__name__[3:]

    def getMenuText(cls):
        return cls._menuText

    def getToolTip(cls):
        return getattr(cls,'_tooltip',cls.getMenuText())

    def IsActive(cls):
        if cls._id<0 or not FreeCAD.ActiveDocument:
            return False
        if cls._active is None:
            cls.checkActive()
        return cls._active

    def onClearSelection(cls):
        pass

class AsmCmdBase(object):
    __metaclass__ = AsmCmdManager
    _id = -1
    _active = None
    _toolbarName = 'Assembly3'
    _menuGroupName = ''
    _contextMenuName = 'Assembly'
    _accel = None

    @classmethod
    def checkActive(cls):
        cls._active = True

    @classmethod
    def GetResources(cls):
        ret = {
            'Pixmap':addIconToFCAD(cls._iconName),
            'MenuText':cls.getMenuText(),
            'ToolTip':cls.getToolTip()
        }
        if cls._accel:
            ret['Accel'] = cls._accel
        return ret

class AsmCmdNew(AsmCmdBase):
    _id = 0
    _menuText = 'Create assembly'
    _iconName = 'Assembly_New_Assembly.svg'
    _accel = 'A, N'

    @classmethod
    def Activated(cls):
        from . import assembly
        assembly.Assembly.make()

class AsmCmdSolve(AsmCmdBase):
    _id = 1
    _menuText = 'Solve constraints'
    _iconName = 'AssemblyWorkbench.svg'
    _accel = 'A, S'

    @classmethod
    def Activated(cls):
        from . import solver
        FreeCAD.setActiveTransaction('Assembly solve')
        logger.report('command "{}" exception'.format(cls.getName()),
                solver.solve)
        FreeCAD.closeActiveTransaction()


class AsmCmdMove(AsmCmdBase):
    _id = 2
    _menuText = 'Move part'
    _iconName = 'Assembly_Move.svg'
    _useCenterballDragger = True
    _accel = 'A, M'

    @classmethod
    def Activated(cls):
        from . import mover
        mover.movePart(cls._useCenterballDragger)

    @classmethod
    def checkActive(cls):
        from . import mover
        cls._active = mover.canMovePart()

    @classmethod
    def onClearSelection(cls):
        cls._active = False

class AsmCmdAxialMove(AsmCmdMove):
    _id = 3
    _menuText = 'Axial move part'
    _iconName = 'Assembly_AxialMove.svg'
    _useCenterballDragger = False
    _accel = 'A, A'

class AsmCmdCheckable(AsmCmdBase):
    _id = -2
    _saveParam = False
    _defaultValue = False

    @classmethod
    def getAttributeName(cls):
        return cls.__name__[6:]

    @classmethod
    def getChecked(cls):
        return getattr(cls.__class__,cls.getAttributeName())

    @classmethod
    def setChecked(cls,v):
        setattr(cls.__class__,cls.getAttributeName(),v)
        if cls._saveParam:
            cls.setParam('Bool',cls.getAttributeName(),v)

    @classmethod
    def onRegister(cls):
        if cls._saveParam:
            v = cls.getParam('Bool',cls.getAttributeName(),cls._defaultValue)
        else:
            v = False
        cls.setChecked(v)

    @classmethod
    def GetResources(cls):
        ret = super(AsmCmdCheckable,cls).GetResources()
        ret['Checkable'] = cls.getChecked()
        return ret

    @classmethod
    def Activated(cls,checked):
        cls.setChecked(True if checked else False)

class AsmCmdTrace(AsmCmdCheckable):
    _id = 4
    _menuText = 'Trace part move'
    _iconName = 'Assembly_Trace.svg'

    _object = None
    _subname = None

    @classmethod
    def Activated(cls,checked):
        super(AsmCmdTrace,cls).Activated(checked)
        if not checked:
            cls._object = None
            return
        sel = FreeCADGui.Selection.getSelectionEx('',False)
        if len(sel)==1:
            subs = sel[0].SubElementNames
            if len(subs)==1:
                cls._object = sel[0].Object
                cls._subname = subs[0]
                logger.info('trace {}.{}'.format(
                    cls._object.Name,cls._subname))
                return
        logger.info('trace moving element')

    @classmethod
    def getPosition(cls):
        if not cls._object:
            return
        try:
            if cls._object.Document != FreeCAD.ActiveDocument:
                cls._object = None
            return getElementPos((cls._object,cls._subname))
        except Exception:
            cls._object = None

class AsmCmdAutoRecompute(AsmCmdCheckable):
    _id = 5
    _menuText = 'Auto recompute'
    _iconName = 'Assembly_AutoRecompute.svg'
    _saveParam = True

class AsmCmdAutoElementVis(AsmCmdCheckable):
    _id = 9
    _menuText = 'Auto element visibility'
    _iconName = 'Assembly_AutoElementVis.svg'
    _saveParam = True
    _defaultValue = True

    @classmethod
    def Activated(cls,checked):
        super(AsmCmdAutoElementVis,cls).Activated(checked)
        from .assembly import isTypeOf,AsmConstraint,\
            AsmElement,AsmElementLink,AsmElementGroup
        visible = not checked
        for doc in FreeCAD.listDocuments().values():
            for obj in doc.Objects:
                if isTypeOf(obj,(AsmConstraint,AsmElementGroup)):
                    obj.Visibility = False
                    if isTypeOf(obj,AsmConstraint):
                        obj.ViewObject.OnTopWhenSelected = 2 if checked else 0
                    obj.setPropertyStatus('VisibilityList',
                            'NoModify' if checked else '-NoModify')
                elif isTypeOf(obj,(AsmElementLink,AsmElement)):
                    obj.Visibility = False
                    vis = visible and not isTypeOf(obj,AsmElement)
                    obj.Proxy.parent.Object.setElementVisible(obj.Name,vis)
                    obj.ViewObject.OnTopWhenSelected = 2


class AsmCmdAddWorkplane(AsmCmdBase):
    _id = 8
    _menuText = 'Add workplane'
    _iconName = 'Assembly_Add_Workplane.svg'
    _toolbarName = None

    @classmethod
    def checkActive(cls):
        from . import assembly
        if logger.catchTrace('Add workplane selection',
                assembly.AsmWorkPlane.getSelection):
            cls._active = True
        else:
            cls._active = False

    @classmethod
    def onClearSelection(cls):
        cls._active = False

    @classmethod
    def Activated(cls,idx):
        from . import assembly
        assembly.AsmWorkPlane.make(tp=idx)


class AsmCmdAddWorkplaneXZ(AsmCmdAddWorkplane):
    _id = 10
    _menuText = 'Add XZ workplane'
    _iconName = 'Assembly_Add_WorkplaneXZ.svg'


class AsmCmdAddWorkplaneZY(AsmCmdAddWorkplane):
    _id = 11
    _menuText = 'Add ZY workplane'
    _iconName = 'Assembly_Add_WorkplaneZY.svg'


class AsmCmdAddWorkplaneGroup(AsmCmdAddWorkplane):
    _id = 12
    _toolbarName = AsmCmdBase._toolbarName
    _cmds = (AsmCmdAddWorkplane.getName(),
             AsmCmdAddWorkplaneXZ.getName(),
             AsmCmdAddWorkplaneZY.getName())

    @classmethod
    def GetCommands(cls):
        return cls._cmds


class AsmCmdUp(AsmCmdBase):
    _id = 6
    _menuText = 'Move item up'
    _iconName = 'Assembly_TreeItemUp.svg'

    @classmethod
    def getSelection(cls):
        from .assembly import isTypeOf, Assembly, AsmGroup
        sels = FreeCADGui.Selection.getSelectionEx('',False)
        if len(sels)!=1 or len(sels[0].SubElementNames)!=1:
            return
        ret= sels[0].Object.resolve(sels[0].SubElementNames[0])
        obj,parent = ret[0],ret[1]
        if isTypeOf(parent,Assembly) or not isTypeOf(parent,AsmGroup) or \
           len(parent.Group) <= 1:
            return
        return (obj,parent,sels[0].Object,sels[0].SubElementNames[0])

    @classmethod
    def checkActive(cls):
        cls._active = True if cls.getSelection() else False

    @classmethod
    def move(cls,step):
        ret = cls.getSelection()
        if not ret:
            return
        obj,parent,topParent,subname = ret
        children = parent.Group
        i = children.index(obj)
        j = i+step
        if j<0:
            j = len(children)-1
        elif j>=len(children):
            j = 0
        logger.debug('move {}:{} -> {}:{}'.format(
            i,objName(obj),j,objName(children[j])))
        FreeCAD.setActiveTransaction(cls._menuText)
        readonly = 'Immutable' in parent.getPropertyStatus('Group')
        if readonly:
            parent.setPropertyStatus('Group','-Immutable')
        parent.Group = {i:children[j],j:obj}
        if readonly:
            parent.setPropertyStatus('Group','Immutable')
        FreeCAD.closeActiveTransaction();
        # The tree view may deselect the item because of claimChildren changes,
        # so we restore the selection here
        FreeCADGui.Selection.addSelection(topParent,subname)

    @classmethod
    def onClearSelection(cls):
        cls._active = False

    @classmethod
    def Activated(cls):
        cls.move(-1)


class AsmCmdDown(AsmCmdUp):
    _id = 7
    _menuText = 'Move item down'
    _iconName = 'Assembly_TreeItemDown.svg'

    @classmethod
    def Activated(cls):
        cls.move(1)
