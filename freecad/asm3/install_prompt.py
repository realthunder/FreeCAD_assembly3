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
print_warn = FreeCAD.Console.PrintWarning

def report_view_param(val=None):
    param = FreeCAD.ParamGet('User parameter:BaseApp/Preferences/OutputWindow')
    key = 'checkShowReportViewOnNormalMessage'
    if val is None:
        return param.GetBool(key, False)
    else:
        param.SetBool(key, val)

def pip_install(package):
    if not report_view_param():
        report_view_param(True)
        QTimer.singleShot(2000, lambda:report_view_param(False))

    postfix = '.exe' if platform.system() == 'Windows' else ''
    bin_path = os.path.dirname(sys.executable)
    exe_path = os.path.join(bin_path, 'FreeCADCmd' + postfix)
    if os.path.exists(exe_path):
        stdin = '''
import sys
from pip._internal.cli.main import main
if __name__ == '__main__':
    sys.argv = ['pip', 'install', '%s', '--user']
    sys.exit(main())
''' % package
        args = [exe_path]
    else:
        stdin = None
        exe_path = os.path.join(bin_path, 'python' + postfix)
        if not os.path.exists(exe_path):
            bin_path = FreeCAD.ConfigGet('BinPath')
            exe_path = os.path.join(bin_path, 'python' + postfix)
            if not os.path.exists(exe_path):
                exe_path = 'python3' + postfix
        args = [exe_path, '-m', 'pip', 'install', package, '--user']
        print_msg(' '.join(args) + '\n')

    try:
        if stdin:
            proc = subp.Popen(args, stdin=subp.PIPE, stdout=subp.PIPE, stderr=subp.PIPE)
            out, err = proc.communicate(input=stdin.encode('utf8'))
        else:
            proc = subp.Popen(args, stdout=subp.PIPE, stderr=subp.PIPE)
            out, err = proc.communicate()
        print_msg(out.decode('utf8') + '\n')
        if err:
            print_func = print_err
            for msg in err.decode("utf8").split('\r\n'):
                m = msg.lower()
                if 'warning' in m:
                    print_func = print_warn
                elif any(key in m for key in ('exception', 'error')):
                    print_func = print_err
                print_func(msg + '\n')
    except Exception as e:
        msg = str(e)
        if not msg:
            msg = 'Failed'
        print_err(msg + '\n')

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
