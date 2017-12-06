import FreeCAD, FreeCADGui

from .utils import logger
try:
    from . import sys_slvs
except ImportError as e:
    logger.error('failed to import slvs: {}'.format(e))
try:
    from . import sys_sympy
except ImportError as e:
    logger.error('failed to import sympy: {}'.format(e))

class Assembly3Workbench(FreeCADGui.Workbench):
    from . import utils
    MenuText = 'Assembly 3'
    Icon = utils.addIconToFCAD('AssemblyWorkbench.svg')

    def __init__(self):
        self.observer = None
        self.docObserver = None

    def Activated(self):
        self.observer.attach()
        FreeCAD.addDocumentObserver(self.docObserver)
        from .gui import AsmCmdManager
        for cmd in AsmCmdManager.getInfo().Types:
            cmd.workbenchActivated()

    def Deactivated(self):
        self.observer.detach()
        FreeCAD.removeDocumentObserver(self.docObserver)
        from .gui import AsmCmdManager
        for cmd in AsmCmdManager.getInfo().Types:
            cmd.workbenchDeactivated()

    def Initialize(self):
        from .assembly import AsmDocumentObserver
        from .gui import AsmCmdManager,SelectionObserver
        cmdSet = set()
        for name,cmds in AsmCmdManager.Toolbars.items():
            cmdSet.update(cmds)
            self.appendToolbar(name,[cmd.getName() for cmd in cmds])
        for name,cmds in AsmCmdManager.Menus.items():
            cmdSet.update(cmds)
            self.appendMenu(name,[cmd.getName() for cmd in cmds])
        self.observer = SelectionObserver(cmdSet)
        self.docObserver = AsmDocumentObserver()
        #  FreeCADGui.addPreferencePage(
        #          ':/assembly3/ui/assembly3_prefs.ui','Assembly3')

    def _contextMenu(self):
        from .gui import AsmCmdManager
        from collections import OrderedDict
        menus = OrderedDict()
        for cmd in AsmCmdManager.getInfo().Types:
            name = cmd.getContextMenuName()
            if name:
                menus.setdefault(name,[]).append(cmd.getName())
        for name,cmds in menus.items():
            self.appendContextMenu(name,cmds)

    def ContextMenu(self, _recipient):
        from .utils import logger
        logger.catch('',self._contextMenu)

FreeCADGui.addWorkbench(Assembly3Workbench)
