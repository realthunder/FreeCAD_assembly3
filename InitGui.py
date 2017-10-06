import FreeCAD, FreeCADGui

class Assembly3Workbench(FreeCADGui.Workbench):
    import asm3
    MenuText = 'Assembly 3'
    Icon = asm3.utils.addIconToFCAD('AssemblyWorkbench.svg')

    def Activated(self):
        import asm3
        asm3.constraint.Observer.attach()

    def Deactivated(self):
        import asm3
        asm3.constraint.Observer.detach()

    def Initialize(self):
        import asm3
        cmds = asm3.gui.AsmCmdType.getInfo().TypeNames
        asm3.utils.logger.debug(cmds)
        self.appendToolbar('asm3',cmds)
        self.appendMenu('&Assembly3', cmds)
        self.appendToolbar('asm3 Constraint',
                    asm3.constraint.Constraint.CommandList)
        #  FreeCADGui.addPreferencePage(
        #          ':/assembly3/ui/assembly3_prefs.ui','Assembly3')

FreeCADGui.addWorkbench(Assembly3Workbench)
