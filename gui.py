from future.utils import with_metaclass
import FreeCAD, FreeCADGui
from asm3.utils import logger,objName,addIconToFCAD
from asm3.assembly import Assembly,AsmConstraint
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
            cmd.deactive()

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


class AsmCmdType(ProxyType):
    def register(cls):
        super(AsmCmdType,cls).register()
        if cls._id >= 0:
            FreeCADGui.addCommand(cls.getName(),cls())

class AsmCmdBase(with_metaclass(AsmCmdType,object)):
    _id = -1
    _active = True

    @classmethod
    def getName(cls):
        return 'asm3'+cls.__name__[3:]

    @classmethod
    def GetResources(cls):
        return {
            'Pixmap':addIconToFCAD(cls._iconName),
            'MenuText':cls.getMenuText(),
            'ToolTip':cls.getToolTip()
        }

    @classmethod
    def getMenuText(cls):
        return cls._menuText

    @classmethod
    def getToolTip(cls):
        return getattr(cls,'_tooltip',cls.getMenuText())

    @classmethod
    def IsActive(cls):
        if cls._active and cls._id>=0 and FreeCAD.ActiveDocument:
            return True

    @classmethod
    def checkActive(cls):
        pass

    @classmethod
    def deactive(cls):
        pass

class AsmCmdNew(AsmCmdBase):
    _id = 0
    _menuText = 'Create assembly'
    _iconName = 'Assembly_New_Assembly.svg'

    def Activated(self):
        Assembly.make()

class AsmCmdSolve(AsmCmdBase):
    _id = 1
    _menuText = 'Solve constraints'
    _iconName = 'AssemblyWorkbench.svg'

    def Activated(self):
        import asm3.solver as solver
        solver.solve()

class AsmCmdMove(AsmCmdBase):
    _id = 2
    _menuText = 'Move part'
    _iconName = 'Assembly_Move.svg'

    def Activated(self):
        pass

