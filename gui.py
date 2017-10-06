from future.utils import with_metaclass
import FreeCAD, FreeCADGui
from asm3.utils import logger,objName,addIconToFCAD
from asm3.assembly import Assembly,AsmConstraint
from asm3.proxy import ProxyType

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
        if FreeCAD.ActiveDocument and cls._active:
            return True

class AsmCmdNew(AsmCmdBase):
    _id = 0
    _menuText = 'Create a new assembly'
    _iconName = 'Assembly_New_Assembly.svg'

    def Activated(self):
        Assembly.make()

class AsmCmdSolve(AsmCmdBase):
    _id = 1
    _menuText = 'Solve the constraints of assembly(s)'
    _iconName = 'AssemblyWorkbench.svg'

    def Activated(self):
        import asm3.solver as solver
        solver.solve()


class AsmCmdMove(AsmCmdBase):
    _id = 2
    _menuText = 'Move assembly'
    _iconName = 'Assembly_Move.svg'

    def Activated(self):
        pass

