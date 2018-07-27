import FreeCAD, FreeCADGui

from .utils import logger
try:
    from . import sys_slvs
except ImportError as e:
    logger.debug('failed to import slvs: {}'.format(e))
try:
    from . import sys_sympy
except ImportError as e:
    logger.debug('failed to import sympy: {}'.format(e))
    import sys
    if not 'freecad.asm3.sys_slvs' in sys.modules:
        logger.warn('no solver backend found')

class Assembly3Workbench(FreeCADGui.Workbench):
    from . import utils
    MenuText = 'Assembly 3'
    Icon = utils.addIconToFCAD('AssemblyWorkbench.svg')

    from .gui import SelectionObserver
    _observer = SelectionObserver()

    def __init__(self):
        self.docObserver = None

    def Activated(self):
        FreeCAD.addDocumentObserver(self.docObserver)
        from .gui import AsmCmdManager
        for cmd in AsmCmdManager.getInfo().Types:
            cmd.workbenchActivated()

    def Deactivated(self):
        FreeCAD.removeDocumentObserver(self.docObserver)
        from .gui import AsmCmdManager
        for cmd in AsmCmdManager.getInfo().Types:
            cmd.workbenchDeactivated()

    def Initialize(self):
        from .mover import AsmDocumentObserver
        from .gui import AsmCmdManager
        AsmCmdManager.init()
        cmdSet = set()
        for name,cmds in AsmCmdManager.Toolbars.items():
            cmdSet.update(cmds)
            self.appendToolbar(name,[cmd.getName() for cmd in cmds])
        self.appendToolbar('Assembly3 Selection', ["Std_SelBack",
            "Std_SelForward","Std_LinkSelectLinked","Std_LinkSelectLinkedFinal",
            "Std_LinkSelectAllLinks","Std_TreeSelectAllInstances"])
        for name,cmds in AsmCmdManager.Menus.items():
            cmdSet.update(cmds)
            self.appendMenu(name,[cmd.getName() for cmd in cmds])
        self._observer.setCommands(cmdSet)
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
        logger.catch('',self._contextMenu)

FreeCADGui.addWorkbench(Assembly3Workbench)
