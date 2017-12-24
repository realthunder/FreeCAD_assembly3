from collections import OrderedDict
import FreeCAD, FreeCADGui
from .utils import objName,addIconToFCAD,guilogger as logger
from .proxy import ProxyType
from .FCADLogger import FCADLogger

class SelectionObserver:
    def __init__(self, cmds):
        self._attached = False
        self.cmds = cmds

    def onChanged(self):
        for cmd in self.cmds:
            cmd.checkActive()

    def addSelection(self,*_args):
        self.onChanged()

    def removeSelection(self,*_args):
        self.onChanged()

    def setSelection(self,*_args):
        self.onChanged()

    def clearSelection(self,*_args):
        for cmd in self.cmds:
            cmd.onClearSelection()

    def attach(self):
        logger.trace('attach selection aboserver {}'.format(self._attached))
        if not self._attached:
            FreeCADGui.Selection.addObserver(self)
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

    @classmethod
    def checkActive(cls):
        cls._active = True

    @classmethod
    def GetResources(cls):
        return {
            'Pixmap':addIconToFCAD(cls._iconName),
            'MenuText':cls.getMenuText(),
            'ToolTip':cls.getToolTip()
        }


class AsmCmdNew(AsmCmdBase):
    _id = 0
    _menuText = 'Create assembly'
    _iconName = 'Assembly_New_Assembly.svg'

    @classmethod
    def Activated(cls):
        from . import assembly
        assembly.Assembly.make()

class AsmCmdSolve(AsmCmdBase):
    _id = 1
    _menuText = 'Solve constraints'
    _iconName = 'AssemblyWorkbench.svg'

    @classmethod
    def Activated(cls):
        from . import solver
        logger.report('command "{}" exception'.format(cls.getName()),
                solver.solve)


class AsmCmdMove(AsmCmdBase):
    _id = 2
    _menuText = 'Move part'
    _iconName = 'Assembly_Move.svg'
    _useCenterballDragger = True

    @classmethod
    def Activated(cls):
        from . import assembly
        assembly.movePart(cls._useCenterballDragger)

    @classmethod
    def checkActive(cls):
        from . import assembly
        cls._active = assembly.canMovePart()

    @classmethod
    def onClearSelection(cls):
        cls._active = False

class AsmCmdAxialMove(AsmCmdMove):
    _id = 3
    _menuText = 'Axial move part'
    _iconName = 'Assembly_AxialMove.svg'
    _useCenterballDragger = False

class AsmCmdCheckable(AsmCmdBase):
    _id = -2
    _saveParam = False

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
            v = cls.getParam('Bool',cls.getAttributeName(),False)
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

class AsmCmdAutoRecompute(AsmCmdCheckable):
    _id = 5
    _menuText = 'Auto recompute'
    _iconName = 'Assembly_AutoRecompute.svg'
    _saveParam = True

class AsmCmdAddWorkplane(AsmCmdBase):
    _id = 8
    _menuText = 'Add workplane'
    _iconName = 'Assembly_Add_Workplane.svg'

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
    def Activated(cls):
        from . import assembly
        assembly.AsmWorkPlane.make()


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
        obj,parent,_ = FreeCADGui.Selection.resolveObject(
                sels[0].Object, sels[0].SubElementNames[0])
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
