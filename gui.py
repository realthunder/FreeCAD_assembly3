from future.utils import with_metaclass
from collections import OrderedDict
import FreeCAD, FreeCADGui
import asm3
from asm3.utils import logger,objName,addIconToFCAD
from asm3.proxy import ProxyType

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
        if not self._attached:
            FreeCADGui.Selection.addObserver(self)
            self._attached = True
            self.onChanged()

    def detach(self):
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

    def GetResources(cls):
        return {
            'Pixmap':addIconToFCAD(cls._iconName),
            'MenuText':cls.getMenuText(),
            'ToolTip':cls.getToolTip()
        }

    def getMenuText(cls):
        return cls._menuText

    def getToolTip(cls):
        return getattr(cls,'_tooltip',cls.getMenuText())

    def IsActive(cls):
        if cls._active and cls._id>=0 and FreeCAD.ActiveDocument:
            return True

    def checkActive(cls):
        pass

    def onClearSelection(cls):
        pass

class AsmCmdBase(with_metaclass(AsmCmdManager,object)):
    _id = -1
    _active = True
    _toolbarName = 'Assembly3'
    _menuGroupName = ''
    _contextMenuName = 'Assembly'

class AsmCmdNew(AsmCmdBase):
    _id = 0
    _menuText = 'Create assembly'
    _iconName = 'Assembly_New_Assembly.svg'

    @classmethod
    def Activated(cls):
        asm3.assembly.Assembly.make()

class AsmCmdSolve(AsmCmdBase):
    _id = 1
    _menuText = 'Solve constraints'
    _iconName = 'AssemblyWorkbench.svg'

    @classmethod
    def Activated(cls):
        import asm3.solver as solver
        solver.solve()

class AsmCmdMove(AsmCmdBase):
    _id = 2
    _menuText = 'Move part'
    _iconName = 'Assembly_Move.svg'
    _useCenterballDragger = True

    @classmethod
    def getSelection(cls):
        from asm3.assembly import isTypeOf,AsmElementLink
        sels = FreeCADGui.Selection.getSelection()
        if len(sels)==1 and isTypeOf(sels[0],AsmElementLink):
            return sels[0].ViewObject

    @classmethod
    def Activated(cls):
        vobj = cls.getSelection()
        if vobj:
            doc = FreeCADGui.editDocument()
            if doc:
                doc.resetEdit()
            vobj.UseCenterballDragger = cls._useCenterballDragger
            vobj.doubleClicked()

    @classmethod
    def checkActive(cls):
        cls._active = True if cls.getSelection() else False

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
    _action = None
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
        cls.setParam('Bool',cls.getAttributeName(),v)

    @classmethod
    def onRegister(cls):
        if cls._saveParam:
            v = cls.getParam('Bool',cls.getAttributeName(),False)
        else:
            v = False
        cls.setChecked(v)

    @classmethod
    def workbenchActivated(cls):
        if cls._action:
            return
        from PySide import QtGui
        mw = FreeCADGui.getMainWindow()
        tb = mw.findChild(QtGui.QToolBar,cls._toolbarName)
        if not tb:
            logger.error('cannot find toolbar "{}"'.format(cls._toolbarName))
            return
        name = cls.getName()
        for action in tb.actions():
            if action.objectName() == name:
                action.setCheckable(True)
                action.setChecked(cls.getChecked())
                cls._action = action
                break
        if not cls._action:
            cls._active = False
            logger.error('cannot find action "{}"'.format(cls.getName()))
        else:
            cls._active = True
            return

    @classmethod
    def Activated(cls):
        if not cls._action:
            return
        checked = not cls.getChecked()
        cls.setChecked(checked)
        cls._action.setChecked(checked)

class AsmCmdTrace(AsmCmdCheckable):
    _id = 4
    _menuText = 'Trace part move'
    _iconName = 'Assembly_Trace.svg'

