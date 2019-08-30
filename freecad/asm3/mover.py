import math
from collections import namedtuple
import FreeCAD, FreeCADGui
from PySide import QtCore, QtGui
from . import utils, gui
from .assembly import isTypeOf, Assembly, ViewProviderAssembly, \
    resolveAssembly, getElementInfo, setPlacement
from .utils import moverlogger as logger, objName
from .constraint import Constraint

MovingPartInfo = namedtuple('MovingPartInfo',
        ('Hierarchy','HierarchyList','ElementInfo','SelObj','SelSubname'))

class AsmMovingPart(object):
    def __init__(self,hierarchy,info):
        self.objs = [h.Assembly for h in reversed(hierarchy)]
        self.assembly = resolveAssembly(info.Parent)
        self.viewObject = self.assembly.Object.ViewObject
        self.info = info
        self.undos = None

        fixed = Constraint.getFixedTransform(self.assembly.getConstraints())
        fixed = fixed.get(info.Part,None)
        self.fixedTransform = fixed
        if fixed and fixed.Shape:
            shape = fixed.Shape
        else:
            shape = info.Shape

        rot = utils.getElementRotation(shape)
        if not rot:
            # in case the shape has no normal, like a vertex, just use an empty
            # rotation, which means having the same rotation as the owner part.
            rot = FreeCAD.Rotation()

        hasBound = True
        if not utils.isVertex(shape):
            self.bbox = shape.BoundBox
        else:
            bbox = info.Object.ViewObject.getBoundingBox()
            if bbox.isValid():
                self.bbox = bbox
            else:
                logger.warn('empty bounding box of part {}',info.PartName)
                self.bbox = FreeCAD.BoundBox(0,0,0,5,5,5)
                hasBound = False

        pos = utils.getElementPos(shape)
        if not pos:
            if hasBound:
                pos = self.bbox.Center
            else:
                pos = shape.Placement.Base
        pla = FreeCAD.Placement(pos,rot)

        self.offset = pla.copy()
        self.offsetInv = pla.inverse()
        self.draggerPlacement = info.Placement.multiply(pla)
        self.trace = None
        self.tracePoint = None

    @classmethod
    def onRollback(cls):
        doc = FreeCADGui.editDocument()
        if not doc:
            return
        vobj = doc.getInEdit()
        if vobj and isTypeOf(vobj,ViewProviderAssembly):
            movingPart = getattr(vobj.Proxy,'_movingPart',None)
            if movingPart:
                vobj.Object.recompute(True)
                movingPart.tracePoint = movingPart.TracePosition

    def begin(self):
        self.tracePoint = self.TracePosition

    def update(self):
        info = getElementInfo(self.info.Parent,self.info.SubnameRef)
        self.info = info
        if utils.isDraftObject(info.Part):
            pos = utils.getElementPos(info.Shape)
            rot = utils.getElementRotation(info.Shape)
            pla = info.Placement.multiply(FreeCAD.Placement(pos,rot))
        else:
            pla = info.Placement.multiply(self.offset)
        logger.trace('part move update {}: {}',objName(info.Parent),pla)
        self.draggerPlacement = pla
        return pla

    @property
    def Movement(self):
        pla = self.viewObject.DraggingPlacement.multiply(
                self.draggerPlacement.inverse())
        return utils.roundPlacement(pla)

    @property
    def TracePosition(self):
        pos = gui.AsmCmdTrace.getPosition()
        if pos:
            return pos
        mat = FreeCADGui.editDocument().EditingTransform
        return mat.multiply(self.draggerPlacement.Base)

    def move(self):
        info = self.info
        part = info.Part
        obj = self.assembly.Object
        pla = self.viewObject.DraggingPlacement
        updatePla = True

        rollback = []
        if not info.Subname.startswith('Face') and utils.isDraftWire(part):
            updatePla = False
            if info.Subname.startswith('Vertex'):
                idx = utils.draftWireVertex2PointIndex(part,info.Subname)
                if idx is None:
                    logger.error('Invalid draft wire vertex {} {}',
                        info.Subname, info.PartName)
                    return
                change = [idx]
            else:
                change = utils.edge2VertexIndex(part,info.Subname,True)
                if change[0] is None or change[1] is None:
                    logger.error('Invalid draft wire edge {} {}',
                        info.Subname, info.PartName)
                    return

            movement = self.Movement
            points = part.Points
            for idx in change:
                pt = points[idx]
                rollback.append((info.PartName, part, (idx,pt)))
                points[idx] = movement.multVec(pt)
            part.Points = points

        elif info.Subname.startswith('Vertex') and \
             utils.isDraftCircle(part):
            updatePla = False
            a1 = part.FirstAngle
            a2 = part.LastAngle
            r = part.Radius
            rollback.append((info.PartName, part, (r,a1,a2)))
            pt = info.Placement.inverse().multVec(pla.Base)
            part.Radius = pt.Length
            if a1 != a2:
                pt.z = 0
                a = math.degrees(FreeCAD.Vector(1,0,0).getAngle(pt))
                if info.Subname.endswith('1'):
                    part.FirstAngle = a
                else:
                    part.LastAngle = a

        elif self.fixedTransform:
            fixed = self.fixedTransform
            movement = self.Movement
            if fixed.Shape:
                # fixed position, so reset translation
                movement.Base = FreeCAD.Vector()
                if not utils.isVertex(fixed.Shape):
                    yaw,_,_ = movement.Rotation.toEuler()
                    # when dragging with a fixed axis, we align the dragger Z
                    # axis with that fixed axis. So we shall only keep the yaw
                    # among the euler angles
                    movement.Rotation = FreeCAD.Rotation(yaw,0,0)
                pla = self.draggerPlacement.multiply(movement)

        if updatePla:
            # obtain and update the part placement
            pla = pla.multiply(self.offsetInv)
            setPlacement(info.Part,pla)
            rollback.append((info.PartName,info.Part,info.Placement.copy()))

        if not gui.AsmCmdManager.AutoRecompute or \
           QtGui.QApplication.keyboardModifiers()==QtCore.Qt.ControlModifier:
            # AsmCmdManager.AutoRecompute means auto re-solve the system. The
            # recompute() call below is only for updating linked element and
            # stuff
            obj.recompute(True)
            return

        # calls solver.solve(obj) and redirect all the exceptions message
        # to logger only.
        from . import solver
        if not logger.catch('solver exception when moving part',
               solver.solve, self.objs, dragPart=info.Part, rollback=rollback):
            obj.recompute(True)

        if gui.AsmCmdManager.Trace:
            pos = self.TracePosition
            if not self.tracePoint.isEqual(pos,1e-5):
                try:
                    # check if the object is deleted
                    self.trace.Name
                except Exception:
                    self.trace = None
                if not self.trace:
                    self.trace = FreeCAD.ActiveDocument.addObject(
                        'Part::Polygon','AsmTrace')
                    self.trace.Nodes = [self.tracePoint]
                self.tracePoint = pos
                self.trace.Nodes = {-1:pos}
                self.trace.recompute()

        # self.draggerPlacement, which holds the intended dragger placement, is
        # updated by the above solver call through the following chain, 
        #   solver.solve() -> (triggers dependent objects recompute when done)
        #   Assembly.execute() ->
        #   ViewProviderAssembly.onExecute() -> 
        #   AsmMovingPart.update()
        return self.draggerPlacement

def checkFixedPart(info):
    if not gui.AsmCmdManager.LockMover:
        return
    assembly = resolveAssembly(info.Parent)
    cstrs = assembly.getConstraints()
    partGroup = assembly.getPartGroup()
    if info.Part in Constraint.getFixedParts(None,cstrs,partGroup,False):
        raise RuntimeError('cannot move fixed part')

def findAssembly(obj,subname):
    return Assembly.find(obj,subname,
            recursive=True,relativeToChild=True,keepEmptyChild=True)

def getMovingElementInfo():
    '''Extract information from current selection for part moving

    It returns a tuple containing the selected assembly hierarchy, and
    AsmElementInfo of the selected child part object. 
    
    If there is only one selection, then the moving part will be one belong to
    the highest level assembly in selected hierarchy.

    If there are two selections, then one selection must be a parent assembly
    containing the other child object. The moving object will then be the
    immediate child part object of the owner assembly. The actual selected sub
    element, i.e. vertex, edge, face will determine the dragger placement
    '''

    sels = FreeCADGui.Selection.getSelectionEx('',False)
    if not sels:
        raise RuntimeError('no selection')

    if not sels[0].SubElementNames:
        raise RuntimeError('no sub-object in selection')

    if len(sels)>1 or len(sels[0].SubElementNames)>2:
        raise RuntimeError('too many selection')

    selObj = sels[0].Object
    selSub = sels[0].SubElementNames[0]
    ret = findAssembly(selObj,selSub)
    if not ret:
        raise RuntimeError('invalid selection {}, subname {}'.format(
            objName(selObj),selSub))

    if len(sels[0].SubElementNames)==1:
        r = ret[0]
        # Warning! Must not calling like below, because r.Assembly maybe a link,
        # and we need that information
        #
        # info = getElementInfo(r.Object,r.Subname, ...)
        info = getElementInfo(r.Assembly,
                r.Object.Name+'.'+r.Subname, checkPlacement=True)
        return MovingPartInfo(SelObj=selObj,
                              SelSubname=selSub,
                              HierarchyList=ret,
                              Hierarchy=r,
                              ElementInfo=info)

    ret2 = findAssembly(selObj,sels[0].SubElementNames[1])
    if not ret2:
        raise RuntimeError('invalid selection {}, subname {}'.format(
            objName(selObj,sels[0].SubElementNames[1])))

    if len(ret) == len(ret2):
        if len(ret2[-1].Subname) < len(ret[-1].Subname):
            ret,ret2 = ret2,ret
        else:
            selSub = sels[0].SubElementNames[1]
    elif len(ret) > len(ret2):
        ret,ret2 = ret2,ret
    else:
        selSub = sels[0].SubElementNames[1]

    assembly = ret[-1].Assembly
    for r in ret2:
        if assembly == r.Assembly:
            # Warning! Must not calling like below, because r.Assembly maybe a
            # link, and we need that information
            #
            # info = getElementInfo(r.Object,r.Subname, ...)
            info = getElementInfo(r.Assembly,
                    r.Object.Name+'.'+r.Subname,checkPlacement=True)
            return MovingPartInfo(SelObj=selObj,
                            SelSubname=selSub,
                            HierarchyList=ret2,
                            Hierarchy=r,
                            ElementInfo=info)
    raise RuntimeError('not child parent selection')

def movePart(useCenterballDragger=None,moveInfo=None):
    if not moveInfo:
        moveInfo = logger.catch(
                'exception when moving part', getMovingElementInfo)
        if not moveInfo:
            return False
    info = moveInfo.ElementInfo
    doc = FreeCADGui.editDocument()
    if doc:
        doc.resetEdit()
    vobj = resolveAssembly(info.Parent).Object.ViewObject
    vobj.Proxy._movingPart = AsmMovingPart(moveInfo.HierarchyList,info)
    if useCenterballDragger is not None:
        vobj.UseCenterballDragger = useCenterballDragger
    FreeCADGui.Selection.clearSelection()

    subname = moveInfo.SelSubname[:-len(info.SubnameRef)]
    topVObj = moveInfo.SelObj.ViewObject
    mode = 1 if info.Parent==vobj.Object else 0x8001
    return topVObj.Document.setEdit(topVObj,mode,subname)

class AsmQuickMover:
    def __init__(self, info):
        self.info = info.ElementInfo
        idx = len(self.info.Subname)
        if idx:
            sub = info.SelSubname[:-idx]
        else:
            sub = info.SelSubname
        _,mat = info.SelObj.getSubObject(sub,1,FreeCAD.Matrix())
        pos = utils.getElementPos(self.info.Shape)
        if not pos:
            pos = self.info.Shape.BoundBox.Center
        pos = mat.multiply(pos)
        self.matrix = mat*self.info.Placement.inverse().toMatrix()
        base = self.matrix.multiply(self.info.Placement.Base)
        self.offset = pos - base

        self.matrix.invert()
        self.view = info.SelObj.ViewObject.Document.ActiveView
        self.callbackMove = self.view.addEventCallback(
                "SoLocation2Event",self.moveMouse)
        self.callbackClick = self.view.addEventCallback(
                "SoMouseButtonEvent",self.clickMouse)
        self.callbackKey = self.view.addEventCallback(
                "SoKeyboardEvent",self.keyboardEvent)
        FreeCAD.setActiveTransaction('Assembly quick move',True)
        self.active = True

    def moveMouse(self, info):
        pla = self.info.Placement
        pos = self.view.getPoint(*info['Position'])
        pla.Base = self.matrix.multiply(pos-self.offset)
        setPlacement(self.info.Part,pla)

    def removeCallbacks(self, abort=False):
        if not self.active:
            return
        self.view.removeEventCallback("SoLocation2Event",self.callbackMove)
        self.view.removeEventCallback("SoMouseButtonEvent",self.callbackClick)
        self.view.removeEventCallback("SoKeyboardEvent",self.callbackKey)
        FreeCAD.closeActiveTransaction(abort)
        self.active = False
        self.info = None
        self.view = None

    def clickMouse(self, info):
        if info['State'] == 'DOWN':
            self.removeCallbacks(info['Button']!='BUTTON1')

    def keyboardEvent(self, info):
        if info['Key'] == 'ESCAPE':
            self.removeCallbacks(True)

class AsmDocumentObserver:
    _quickMover = None

    def __init__(self):
        FreeCAD.addDocumentObserver(self)

    @classmethod
    def closeMover(cls):
        if cls._quickMover:
            cls._quickMover.removeCallbacks(True)
            cls._quickMover = None

    @classmethod
    def quickMove(cls,info):
        cls.closeMover()
        cls._quickMover = AsmQuickMover(info)

    def slotCreatedDocument(self,_doc):
        self.closeMover()

    def slotDeletedDocument(self,_doc):
        self.closeMover()

    def slotUndo(self):
        self.closeMover()
        AsmMovingPart.onRollback()
        Assembly.cancelAutoSolve()
        gui.AsmCmdAutoElementVis.setup()

    def slotRedo(self):
        self.slotUndo()

    def slotBeforeCloseTransaction(self, abort):
        if not abort:
            Assembly.doAutoSolve()

    def slotCloseTransaction(self, abort):
        if abort:
            self.slotUndo()

    def slotChangedObject(self,obj,prop):
        Assembly.checkPartChange(obj,prop)

    def slotRecomputedDocument(self,_doc):
        Assembly.resumeSchedule()

    def slotBeforeRecomputeDocument(self,_doc):
        Assembly.pauseSchedule()


def quickMove():
    ret = logger.catch('exception when moving part', getMovingElementInfo)
    if not ret:
        return False
    doc = FreeCADGui.editDocument()
    if doc:
        doc.resetEdit()
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(ret.SelObj,ret.SelSubname)
    AsmDocumentObserver.quickMove(ret)

