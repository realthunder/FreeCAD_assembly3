import FreeCAD, FreeCADGui

class Assembly3Workbench(FreeCADGui.Workbench):
    import asm3
    MenuText = 'Assembly 3'
    Icon = asm3.utils.addIconToFCAD('AssemblyWorkbench.svg')

    def __init__(self):
        self.observer = None

    def Activated(self):
        self.observer.attach()

    def Deactivated(self):
        self.observer.detach()

    def Initialize(self):
        import asm3
        cmdInfo = asm3.gui.AsmCmdType.getInfo()
        cmds = cmdInfo.TypeNames
        asm3.utils.logger.debug(cmds)
        self.appendToolbar('asm3',cmds)
        self.appendMenu('&Assembly3', cmds)
        self.appendToolbar('asm3 Constraint',
                asm3.constraint.Constraint.CommandList)
        self.observer = asm3.gui.SelectionObserver(
                cmdInfo.Types + asm3.constraint.Constraint.Commands)
        #  FreeCADGui.addPreferencePage(
        #          ':/assembly3/ui/assembly3_prefs.ui','Assembly3')

    def ContextMenu(self, _recipient):
        import asm3
        cmds = []
        for cmd in asm3.gui.AsmCmdType.getInfo().Types:
            if cmd.IsActive:
                cmds.append(cmd.getName())
        if cmds:
            self.appendContextMenu('Assembly',cmds)

        cmds.clear()
        for cmd in asm3.constraint.Constraint.Commands:
            if cmd.IsActive:
                cmds.append(cmd.getName())
        if cmds:
            self.appendContextMenu('Constraint',cmds)

FreeCADGui.addWorkbench(Assembly3Workbench)
