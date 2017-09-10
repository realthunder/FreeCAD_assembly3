
import FreeCAD, FreeCADGui, Part
import asm3.assembly as assembly
import asm3.constraint as constraint
import asm3.utils as utils
import asm3.solver as solver
from asm3.assembly import Assembly,AsmConstraint

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

