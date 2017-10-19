import FreeCAD, FreeCADGui
from collections import OrderedDict

class Assembly3Workbench(FreeCADGui.Workbench):
    import asm3
    MenuText = 'Assembly 3'
    Icon = asm3.utils.addIconToFCAD('AssemblyWorkbench.svg')

    def __init__(self):
        self.observer = None

    def Activated(self):
        self.observer.attach()
        from asm3.gui import AsmCmdManager
        for cmd in AsmCmdManager.getInfo().Types:
            cmd.workbenchActivated()

    def Deactivated(self):
        self.observer.detach()
        from asm3.gui import AsmCmdManager
        for cmd in AsmCmdManager.getInfo().Types:
            cmd.workbenchDeactivated()

    def Initialize(self):
        from asm3.gui import AsmCmdManager,SelectionObserver
        cmdSet = set()
        for name,cmds in AsmCmdManager.Toolbars.items():
            cmdSet.update(cmds)
            self.appendToolbar(name,[cmd.getName() for cmd in cmds])
        for name,cmds in AsmCmdManager.Menus.items():
            cmdSet.update(cmds)
            self.appendMenu(name,[cmd.getName() for cmd in cmds])
        self.observer = SelectionObserver(cmdSet)
        #  FreeCADGui.addPreferencePage(
        #          ':/assembly3/ui/assembly3_prefs.ui','Assembly3')

    def ContextMenu(self, _recipient):
        from asm3.gui import AsmCmdManager
        menus = OrderedDict()
        for cmd in AsmCmdManager.getInfo().Types:
            name = cmd.getContextMenuName()
            if name:
                menus.setdefault(name,[]).append(cmd.getName())
        for name,cmds in menus.items():
            self.appendContextMenu(name,cmds)

FreeCADGui.addWorkbench(Assembly3Workbench)
