import FreeCAD, FreeCADGui

from .utils import mainlogger as logger
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

    from .mover import AsmDocumentObserver
    _DocObserver = AsmDocumentObserver()

    def __init__(self):
        pass

    def Activated(self):
        from .gui import AsmCmdManager
        AsmCmdManager.WorkbenchActivated = True
        for cmd in AsmCmdManager.getInfo().Types:
            cmd.workbenchActivated()

    def Deactivated(self):
        from .gui import AsmCmdManager
        AsmCmdManager.WorkbenchActivated = False
        for cmd in AsmCmdManager.getInfo().Types:
            cmd.workbenchDeactivated()

    def Initialize(self):
        from .gui import AsmCmdManager,AsmCmdGotoRelation,\
                         AsmCmdGotoLinked, AsmCmdGotoLinkedFinal
        AsmCmdManager.init()
        cmdSet = set()
        for name,cmds in AsmCmdManager.Toolbars.items():
            cmdSet.update(cmds)
            self.appendToolbar(name,[cmd.getName() for cmd in cmds])
        self.appendToolbar('Assembly3 Navigation', ["Std_SelBack",
            "Std_SelForward",AsmCmdGotoRelation.getName(),
            AsmCmdGotoLinked.getName(), AsmCmdGotoLinkedFinal.getName(),
            "Std_LinkSelectAllLinks","Std_TreeSelectAllInstances"])
        for name,cmds in AsmCmdManager.Menus.items():
            cmdSet.update(cmds)
            self.appendMenu(name,[cmd.getName() for cmd in cmds])
        self._observer.setCommands(cmdSet)
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
