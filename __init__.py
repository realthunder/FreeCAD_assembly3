import FreeCAD, FreeCADGui, Part
from asm3 import proxy,utils,assembly,solver,constraint,system,gui
from asm3.utils import logger
from asm3.assembly import Assembly,AsmConstraint
try:
    from asm3 import sys_slvs
except ImportError as e:
    logger.error('failed to import slvs: {}'.format(e))
try:
    from asm3 import sys_sympy
except ImportError as e:
    logger.error('failed to import sympy: {}'.format(e))

def test():
    doc = FreeCAD.newDocument()
    cylinder1 = doc.addObject('Part::Cylinder','cylinder1')
    cylinder1.Visibility = False
    asm1 = Assembly.make(doc)
    asm1.Proxy.getPartGroup().setLink({-1:cylinder1})
    cylinder2 = doc.addObject('Part::Cylinder','cylinder2')
    cylinder2.Visibility = False
    asm2 = Assembly.make(doc)
    asm2.Placement.Base.z = -20
    asm2.Proxy.getPartGroup().setLink({-1:cylinder2})
    doc.recompute()
    FreeCADGui.SendMsgToActiveView("ViewFit")
    asm = Assembly.make(doc)
    asm.Proxy.getPartGroup().setLink((asm1,asm2))
    asm1.Visibility = False
    asm2.Visibility = False

