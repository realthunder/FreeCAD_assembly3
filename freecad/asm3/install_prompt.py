import FreeCAD, FreeCADGui
import sys
import os.path
import platform
import subprocess as subp
from PySide2.QtWidgets import QCheckBox, QMessageBox
from PySide2.QtCore import QTimer
from .utils import guilogger as logger

from FreeCAD import Qt
translate = Qt.translate
QT_TRANSLATE_NOOP = Qt.QT_TRANSLATE_NOOP

print_msg = FreeCAD.Console.PrintMessage
print_err = FreeCAD.Console.PrintError

def report_view_param(val=None):
    param = FreeCAD.ParamGet('User parameter:BaseApp/Preferences/OutputWindow')
    key = 'checkShowReportViewOnNormalMessage'
    if val is None:
        return param.GetBool(key, False)
    else:
        param.SetBool(key, val)

def pip_install(package, silent=False):
    if not report_view_param():
        report_view_param(True)
        QTimer.singleShot(2000, lambda:report_view_param(False))

    bin_path = FreeCAD.ConfigGet('BinPath')
    py_exe = os.path.join(bin_path, 'python.exe' if platform.system() == 'Windows' else 'python')
    if not os.path.exists(py_exe):
        # MacOS homebrew build somehow install python there
        py_exe = os.path.join(bin_path, '../lib/python')
        if not os.path.exists(py_exe):
            py_exe = 'python3'
    args = [py_exe, '-m', 'pip', 'install', package, '--user']
    if not silent:
        print_msg(' '.join(args))
        print_msg("\n")
    try:
        proc = subp.Popen(args, stdout=subp.PIPE, stderr=subp.PIPE)
        out, err = proc.communicate()
        print_msg(out.decode('utf8'))
        print_msg('\n')
        if err:
            raise RuntimeError(err.decode("utf8"))
    except Exception as e:
        msg = str(e)
        if not msg:
            msg = 'Failed'
        print_err(msg)
        print_err('\n')

_param = FreeCAD.ParamGet('User parameter:BaseApp/Preferences/Mod/Assembly3')

def check_slvs():
    if not _param.GetBool('CheckSLVS', True):
        return
    try:
        import py_slvs
        return
    except ImportError:
        pass

    def dont_ask(checked):
        param.SetBool('CheckSLVS', checked)

    checkbox = QCheckBox(translate('asm3', "Don't ask again"))
    dlg = QMessageBox(FreeCADGui.getMainWindow())
    dlg.setWindowTitle(translate('asm3', 'Install Assembly Solver'))
    dlg.setText(translate('asm3',
"""
The Assembly3 workbench uses <a href="https://solvespace.com/">SolveSpace</a>
as the assembly solver. It is not included in this package due to licensing restrictions.
<br><br>
Would you like to download and install the Python bindings of
SolveSpace (<a href="https://pypi.org/project/py-slvs/">py-slvs</a>)?
"""))

    dlg.setIcon(QMessageBox.Icon.Question)
    dlg.addButton(QMessageBox.Yes)
    dlg.addButton(QMessageBox.No)
    dlg.setDefaultButton(QMessageBox.Yes)
    dlg.setCheckBox(checkbox)
    checkbox.toggled.connect(dont_ask)
    if dlg.exec() != QMessageBox.Yes:
        return
    pip_install("py-slvs")
    try:
        import py_slvs
        QMessageBox.information(FreeCADGui.getMainWindow(),
                                translate('asm3', 'Succeed'),
                                translate('asm3', 'Done!'))
    except ImportError:
        QMessageBox.critical(FreeCADGui.getMainWindow(),
                                translate('asm3', 'Failed'),
                                translate('asm3', 'Failed to install py-slvs'))
