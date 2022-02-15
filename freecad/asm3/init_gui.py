import FreeCAD, FreeCADGui
import sys, os
from . import gui

from FreeCAD import Qt
translate = Qt.translate
QT_TRANSLATE_NOOP = Qt.QT_TRANSLATE_NOOP

from .utils import mainlogger as logger
try:
    from . import sys_slvs
except ImportError as e:
    logger.debug('failed to import slvs: {}'.format(e))
    logger.warn(translate('asm3', 'no solver backend found'))

# Disable sympy/scipy solver for now, as the development is stalled
#
#  try:
#      from . import sys_sympy
#  except ImportError as e:
#      logger.debug('failed to import sympy: {}'.format(e))
#      import sys
#      if not 'freecad.asm3.sys_slvs' in sys.modules:
#          logger.warn(translate('asm3', 'no solver backend found'))

class Assembly3Workbench(FreeCADGui.Workbench):
    from . import utils
    MenuText = 'Assembly 3'
    Icon = os.path.join(utils.iconPath, 'AssemblyWorkbench.svg')

    from .gui import SelectionObserver
    _observer = SelectionObserver()

    from .mover import AsmDocumentObserver
    _DocObserver = AsmDocumentObserver()

    def __init__(self):
        pass

    def check_slvs(self):
        from . import install_prompt
        install_prompt.check_slvs()
        try:
            from . import sys_slvs
        except ImportError as e:
            pass

    def Activated(self):
        from .gui import AsmCmdManager
        AsmCmdManager.WorkbenchActivated = True
        for cmd in AsmCmdManager.getInfo().Types:
            cmd.workbenchActivated()

        if not 'freecad.asm3.sys_slvs' in sys.modules:
            from PySide2.QtCore import QTimer
            QTimer.singleShot(100, self.check_slvs)

    def Deactivated(self):
        from .gui import AsmCmdManager
        AsmCmdManager.WorkbenchActivated = False
        for cmd in AsmCmdManager.getInfo().Types:
            cmd.workbenchDeactivated()

    def Initialize(self):
        from .gui import AsmCmdManager,AsmCmdGotoRelation,\
                         AsmCmdGotoLinked, AsmCmdGotoLinkedFinal
        AsmCmdManager.init()
        for name,cmds in AsmCmdManager.Toolbars.items():
            self.appendToolbar(name,[cmd.getName() for cmd in cmds])
        self.appendToolbar(translate('asm3','Assembly3 Navigation'), [
            AsmCmdGotoRelation.getName(), AsmCmdGotoLinked.getName(),
            AsmCmdGotoLinkedFinal.getName()])
        for name,cmds in AsmCmdManager.Menus.items():
            self.appendMenu(name,[cmd.getName() for cmd in cmds])

        self._observer.setCommands(AsmCmdManager.getInfo().Types)
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

    def ContextMenu(self, recipient):
        if recipient == 'Tree':
            from .gui import AsmCmdToggleConstraint
            if AsmCmdToggleConstraint.IsActive():
                self.appendContextMenu([],AsmCmdToggleConstraint.getName())

        logger.catch('',self._contextMenu)

FreeCADGui.addWorkbench(Assembly3Workbench)
