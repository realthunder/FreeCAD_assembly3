from collections import OrderedDict
import FreeCAD, FreeCADGui
from PySide import QtCore, QtGui
from .deps import with_metaclass
from .utils import getElementPos,objName,addIconToFCAD,guilogger as logger
from .proxy import ProxyType
from .FCADLogger import FCADLogger

class SelectionObserver:
    def __init__(self):
        self._attached = False
        self.timer = QtCore.QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.onTimer)
        self.cmds = []
        self.elements = dict()
        self.attach()

    def setCommands(self,cmds):
        self.cmds = cmds

    def _setElementVisible(self,obj,subname,vis):
        sobj = obj.getSubObject(subname,1)
        from .assembly import isTypeOf,AsmConstraint,\
                AsmElement,AsmElementLink,flattenGroup
        if isTypeOf(sobj,(AsmElement,AsmElementLink)):
            res = sobj.Proxy.parent.Object.isElementVisible(sobj.Name)
            if res and vis:
                return False
            sobj.Proxy.parent.Object.setElementVisible(sobj.Name,vis)
        elif isTypeOf(sobj,AsmConstraint):
            vis = [vis] * len(flattenGroup(sobj))
            sobj.setPropertyStatus('VisibilityList','-Immutable')
            sobj.VisibilityList = vis
            sobj.setPropertyStatus('VisibilityList','Immutable')
        else:
            return
        if vis:
            FreeCADGui.Selection.updateSelection(vis,obj,subname)

    def setElementVisible(self,docname,objname,subname,vis,presel=False):
        if FreeCAD.isRestoring():
            self.resetElementVisible()
            return
        if not AsmCmdManager.AutoElementVis:
            self.elements.clear()
            return
        doc = FreeCAD.getDocument(docname)
        if not doc:
            return
        obj = doc.getObject(objname)
        if not obj:
            return
        key = (docname,objname,subname)
        val = None
        if not vis:
            val = self.elements.get(key,None)
            if val is None or (presel and val):
                return
        if logger.catchWarn('',self._setElementVisible,
                obj,subname,vis) is False and presel:
            return
        if not vis:
            self.elements.pop(key,None)
        elif not presel:
            self.elements[key] = True
        else:
            self.elements.setdefault(key,False)

    def resetElementVisible(self):
        elements = list(self.elements)
        self.elements.clear()
        for docname,objname,subname in elements:
            doc = FreeCAD.getDocument(docname)
            if not doc:
                continue
            obj = doc.getObject(objname)
            if not obj:
                continue
            logger.catchWarn('',self._setElementVisible,obj,subname,False)

    def onChange(self,hasSelection=True):
        if not hasSelection:
            self.timer.stop()
            for cmd in self.cmds:
                cmd.onSelectionChange(False)
            return
        self.timer.start(50)

    def onTimer(self):
        hasSelection = FreeCADGui.Selection.hasSelection()
        for cmd in self.cmds:
            cmd.onSelectionChange(hasSelection)

    def addSelection(self,docname,objname,subname,_pos):
        self.onChange()
        self.setElementVisible(docname,objname,subname,True)

    def removeSelection(self,docname,objname,subname):
        self.onChange(FreeCADGui.Selection.hasSelection())
        self.setElementVisible(docname,objname,subname,False)

    def setPreselection(self,docname,objname,subname):
        self.setElementVisible(docname,objname,subname,True,True)

    def removePreselection(self,docname,objname,subname):
        self.setElementVisible(docname,objname,subname,False,True)

    def setSelection(self,*_args):
        self.onChange()
        if AsmCmdManager.AutoElementVis:
            self.resetElementVisible()
            for sel in FreeCADGui.Selection.getSelectionEx('*',False):
                for sub in sel.SubElementNames:
                    self.setElementVisible(sel.Object.Document.Name,
                            sel.Object.Name,sub,True)

    def clearSelection(self,*_args):
        self.onChange(False)
        self.resetElementVisible()

    def attach(self):
        logger.trace('attach selection aboserver {}',self._attached)
        if not self._attached:
            FreeCADGui.Selection.addObserver(self,False)
            self._attached = True

    def detach(self):
        logger.trace('detach selection aboserver {}',self._attached)
        if self._attached:
            FreeCADGui.Selection.removeObserver(self)
            self._attached = False
            self.clearSelection('')


class AsmCmdManager(ProxyType):
    _HiddenToolbars = set()
    Toolbars = OrderedDict()
    Menus = OrderedDict()
    _defaultMenuGroupName = '&Assembly3'
    WorkbenchActivated = False

    @staticmethod
    def getToolbarParams():
        return FreeCAD.ParamGet('User parameter:BaseApp/MainWindow/Toolbars')

    @classmethod
    def init(mcs):
        if not mcs.getParam('Bool','GuiInited',False):
            hgrp = mcs.getToolbarParams()
            for toolbar in mcs._HiddenToolbars:
                hgrp.SetBool(toolbar,False)
            mcs.setParam('Bool','GuiInited',True)

    @classmethod
    def toggleToolbars(mcs):
        hgrp = mcs.getToolbarParams()
        show = False
        for toolbar in mcs._HiddenToolbars:
            if not hgrp.GetBool(toolbar,True):
                show = True
                break
        mw = FreeCADGui.getMainWindow()
        for toolbar in mcs._HiddenToolbars:
            if show != hgrp.GetBool(toolbar,True):
                hgrp.SetBool(toolbar,show)
                tb = mw.findChild(QtGui.QToolBar,toolbar)
                if not tb:
                    logger.error('cannot find toolbar "{}"',toolbar)
                tb.setVisible(show)

    @classmethod
    def register(mcs,cls):
        if cls._id < 0:
            return
        super(AsmCmdManager,mcs).register(cls)
        FreeCADGui.addCommand(cls.getName(),cls)
        if cls._toolbarName:
            tb = mcs.Toolbars.setdefault(cls._toolbarName,[])
            if not tb and not getattr(cls,'_toolbarVisible',True):
                mcs._HiddenToolbars.add(cls._toolbarName)
            tb.append(cls)

        if cls._menuGroupName is not None:
            name = cls._menuGroupName
            if not name:
                name = mcs._defaultMenuGroupName
            mcs.Menus.setdefault(name,[]).append(cls)

    @classmethod
    def getParamGroup(mcs):
        return FreeCAD.ParamGet(
                'User parameter:BaseApp/Preferences/Mod/Assembly3')

    @classmethod
    def getParam(mcs,tp,name,default=None):
        return getattr(mcs.getParamGroup(),'Get'+tp)(name,default)

    @classmethod
    def setParam(mcs,tp,name,v):
        getattr(mcs.getParamGroup(),'Set'+tp)(name,v)

    def workbenchActivated(cls):
        pass

    def workbenchDeactivated(cls):
        pass

    def getContextMenuName(cls):
        if cls.IsActive() and cls._contextMenuName:
            return cls._contextMenuName

    def getName(cls):
        return 'asm3'+cls.__name__[3:]

    def getMenuText(cls):
        return cls._menuText

    def getToolTip(cls):
        return getattr(cls,'_tooltip',cls.getMenuText())

    def IsActive(cls):
        if cls._id<0 or not FreeCAD.ActiveDocument:
            return False
        if cls._active is None:
            cls.checkActive()
        return cls._active

    def onSelectionChange(cls, hasSelection):
        _ = hasSelection

class AsmCmdBase(with_metaclass(AsmCmdManager, object)):
    _id = -1
    _active = None
    _toolbarName = 'Assembly3'
    _menuGroupName = ''
    _contextMenuName = 'Assembly'
    _accel = None

    @classmethod
    def checkActive(cls):
        cls._active = True

    @classmethod
    def getIconName(cls):
        return addIconToFCAD(cls._iconName)

    @classmethod
    def GetResources(cls):
        ret = {
            'Pixmap':cls.getIconName(),
            'MenuText':cls.getMenuText(),
            'ToolTip':cls.getToolTip()
        }
        if cls._accel:
            ret['Accel'] = cls._accel
        return ret

class AsmCmdNew(AsmCmdBase):
    _id = 0
    _menuText = 'Create assembly'
    _iconName = 'Assembly_New_Assembly.svg'
    _accel = 'A, N'

    @classmethod
    def Activated(cls):
        from . import assembly
        assembly.Assembly.make()


class AsmCmdNewGroup(AsmCmdBase):
    _id = 24
    _menuText = 'Group objects'
    _iconName = 'Assembly_New_Group.svg'
    _accel = 'A, Z'

    @classmethod
    def Activated(cls):
        from . import assembly
        assembly.AsmPlainGroup.make()

    @classmethod
    def checkActive(cls):
        from . import assembly
        cls._active = logger.catchTrace(
                '',assembly.AsmPlainGroup.getSelection) is not None

    @classmethod
    def onSelectionChange(cls,hasSelection):
        cls._active = None if hasSelection else False


class AsmCmdNewElement(AsmCmdBase):
    _id = 19
    _menuText = 'Create element'
    _iconName = 'Assembly_New_Element.svg'
    _accel = 'A, E'

    @classmethod
    def Activated(cls):
        from . import assembly
        logger.report('Failed to add element',
              assembly.AsmElement.make, undo=True, allowDuplicate=
              QtGui.QApplication.keyboardModifiers()==QtCore.Qt.ControlModifier)

    @classmethod
    def checkActive(cls):
        from . import assembly
        cls._active = logger.catchTrace(
                '',assembly.AsmElement.getSelections) is not None

    @classmethod
    def onSelectionChange(cls,hasSelection):
        cls._active = None if hasSelection else False


class AsmCmdImportSingle(AsmCmdBase):
    _id = 25
    _menuText = 'Import from STEP'
    _iconName = 'Assembly_Import.svg'
    _toolbarName = None
    _menuGroupName = None
    _contextMenuName = None

    @classmethod
    def IsActive(cls):
        return True

    @classmethod
    def Activated(cls,idx=0):
        _ = idx
        from .assembly import Assembly

        objs = []
        for obj in FreeCADGui.Selection.getSelection():
            if obj.isDerivedFrom('App::LinkGroup'):
                objs.append(obj)
            else:
                objs = None
                break

        filenames = None
        if not objs:
            filenames = QtGui.QFileDialog.getOpenFileNames(
                    QtGui.QApplication.activeWindow(), 'Please select file',
                    None, 'STEP (*.stp *.step);;All (*.*)')[0]
            if not filenames:
                return

        FreeCAD.setActiveTransaction('Assembly import')

        doc = FreeCAD.ActiveDocument
        if not doc:
            doc = FreeCAD.newDocument()

        if filenames:
            import ImportGui
            for name in filenames:
                obj = ImportGui.insert(name,doc.Name,merge=False,
                            useLinkGroup=True,mode=cls.importMode())
                if obj:
                    objs.append(obj)

        for obj in objs:
            Assembly.fromLinkGroup(obj)
        FreeCAD.closeActiveTransaction()
        return

    @classmethod
    def importMode(cls):
        return 0


class AsmCmdImportMulti(AsmCmdImportSingle):
    _id = 26
    _menuText = 'Import as multi-document'
    _tooltip = 'Import assemblies from STEP file into separate document'
    _iconName = 'Assembly_ImportMulti.svg'

    @classmethod
    def importMode(cls):
        params = FreeCAD.ParamGet(
                'User parameter:BaseApp/Preferences/Mod/Import')
        mode = params.GetInt('ImportMode',0)
        if not mode:
            mode = 2
        return mode

class AsmCmdImport(AsmCmdBase):
    _id = 27
    _iconName = AsmCmdImportSingle._iconName
    _menuText = AsmCmdImportSingle._menuText
    _toolbarName = AsmCmdBase._toolbarName
    _cmds = (AsmCmdImportSingle.getName(),
             AsmCmdImportMulti.getName())

    @classmethod
    def IsActive(cls):
        return True

    @classmethod
    def GetCommands(cls):
        return cls._cmds


class AsmCmdSolve(AsmCmdBase):
    _id = 1
    _menuText = 'Solve constraints'
    _iconName = 'AssemblyWorkbench.svg'
    _accel = 'A, S'

    @classmethod
    def Activated(cls):
        from . import solver
        FreeCAD.setActiveTransaction('Assembly solve')
        logger.report('command "{}" exception'.format(cls.getName()),
                solver.solve,reportFailed=True)
        FreeCAD.closeActiveTransaction()


class AsmCmdQuickSolve(AsmCmdBase):
    _id = 21
    _menuText = 'Quick solve'
    _iconName = 'Assembly_QuickSolve.svg'
    _accel = 'A, F'

    @classmethod
    def Activated(cls):
        from . import solver
        FreeCAD.setActiveTransaction('Assembly quick solve')
        logger.report('command "{}" exception'.format(cls.getName()),
                solver.solve)
        FreeCAD.closeActiveTransaction()


class AsmCmdMove(AsmCmdBase):
    _id = 2
    _menuText = 'Move part'
    _iconName = 'Assembly_Move.svg'
    _accel = 'A, M'
    _moveInfo = None

    @classmethod
    def Activated(cls):
        from . import mover
        mover.movePart(True,cls._moveInfo)

    @classmethod
    def canMove(cls):
        from . import mover
        cls._moveInfo = None
        cls._moveInfo = mover.getMovingElementInfo()
        mover.checkFixedPart(cls._moveInfo.ElementInfo)
        return True

    @classmethod
    def checkActive(cls):
        cls._active = True if logger.catchTrace('',cls.canMove) else False

    @classmethod
    def onSelectionChange(cls,hasSelection):
        if not hasSelection:
            cls._active = False
        else:
            cls._active = None
        cls._moveInfo = None

class AsmCmdAxialMove(AsmCmdBase):
    _id = 3
    _menuText = 'Axial move part'
    _iconName = 'Assembly_AxialMove.svg'
    _useCenterballDragger = False
    _accel = 'A, A'

    @classmethod
    def IsActive(cls):
        return AsmCmdMove.IsActive()

    @classmethod
    def Activated(cls):
        from . import mover
        mover.movePart(False,AsmCmdMove._moveInfo)

class AsmCmdQuickMove(AsmCmdAxialMove):
    _id = 13
    _menuText = 'Quick move'
    _tooltip = 'Bring an object contained in an assembly to where the mouse\n'\
               'is located. This is designed to help bringing an object far\n'\
               'away quickly into view.'
    _iconName = 'Assembly_QuickMove.svg'
    _accel = 'A, Q'

    @classmethod
    def Activated(cls):
        from . import mover
        mover.quickMove()

class AsmCmdCheckable(AsmCmdBase):
    _id = -2
    _saveParam = False
    _defaultValue = False

    @classmethod
    def getAttributeName(cls):
        return cls.__name__[6:]

    @classmethod
    def getChecked(cls):
        return getattr(cls.__class__,cls.getAttributeName())

    @classmethod
    def setChecked(cls,v):
        setattr(cls.__class__,cls.getAttributeName(),v)
        if cls._saveParam:
            cls.setParam('Bool',cls.getAttributeName(),v)

    @classmethod
    def onRegister(cls):
        if cls._saveParam:
            v = cls.getParam('Bool',cls.getAttributeName(),cls._defaultValue)
        else:
            v = False
        cls.setChecked(v)

    @classmethod
    def GetResources(cls):
        ret = super(AsmCmdCheckable,cls).GetResources()
        ret['Checkable'] = cls.getChecked()
        return ret

    @classmethod
    def Activated(cls,checked):
        cls.setChecked(True if checked else False)

class AsmCmdLockMover(AsmCmdCheckable):
    _id = 15
    _menuText = 'Lock mover'
    _tooltip = 'Lock mover for fixed part'
    _iconName = 'Assembly_LockMover.svg'
    _saveParam = True

    @classmethod
    def Activated(cls,checked):
        super(AsmCmdLockMover,cls).Activated(checked)
        AsmCmdMove._active = None
        AsmCmdAxialMove._active = None
        AsmCmdQuickMove._active = None


class AsmCmdToggleVisibility(AsmCmdBase):
    _id = 17
    _menuText = 'Toggle part visibility'
    _tooltip = 'Toggle the visibility of the selected part'
    _iconName = 'Assembly_TogglePartVisibility.svg'
    _accel = 'A, Space'

    @classmethod
    def Activated(cls):
        moveInfo = AsmCmdMove._moveInfo
        if not moveInfo:
            return
        info = moveInfo.ElementInfo
        if info.Subname:
            subs = moveInfo.SelSubname[:-len(info.Subname)]
        else:
            subs = moveInfo.SelSubname
        subs = subs.split('.')
        if isinstance(info.Part,tuple):
            part = info.Part[0]
            vis = part.isElementVisible(str(info.Part[1]))
            part.setElementVisible(str(info.Part[1]),not vis)
        else:
            from .assembly import resolveAssembly
            partGroup = resolveAssembly(info.Parent).getPartGroup()
            vis = partGroup.isElementVisible(info.Part.Name)
            partGroup.setElementVisible(info.Part.Name,not vis)

        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(moveInfo.SelObj,'.'.join(subs))
        FreeCADGui.runCommand('Std_TreeSelection')
        if vis:
            FreeCADGui.runCommand('Std_TreeCollapse')

    @classmethod
    def IsActive(cls):
        return AsmCmdMove._moveInfo is not None


class AsmCmdTrace(AsmCmdCheckable):
    _id = 4
    _menuText = 'Trace part move'
    _iconName = 'Assembly_Trace.svg'

    _object = None
    _subname = None

    @classmethod
    def Activated(cls,checked):
        super(AsmCmdTrace,cls).Activated(checked)
        if not checked:
            cls._object = None
            return
        sel = FreeCADGui.Selection.getSelectionEx('',False)
        if len(sel)==1:
            subs = sel[0].SubElementNames
            if len(subs)==1:
                cls._object = sel[0].Object
                cls._subname = subs[0]
                logger.info('trace {}.{}',cls._object.Name,cls._subname)
                return
        logger.info('trace moving element')

    @classmethod
    def getPosition(cls):
        if not cls._object:
            return
        try:
            if cls._object.Document != FreeCAD.ActiveDocument:
                cls._object = None
            return getElementPos((cls._object,cls._subname))
        except Exception:
            cls._object = None

class AsmCmdAutoRecompute(AsmCmdCheckable):
    _id = 5
    _menuText = 'Auto recompute'
    _iconName = 'Assembly_AutoRecompute.svg'
    _saveParam = True

    @classmethod
    def IsActive(cls):
        return True

class AsmCmdSmartRecompute(AsmCmdCheckable):
    _id = 22
    _menuText = 'Smart recompute'
    _tooltip = 'Toggle smart recompute to reduce recompution time'
    _iconName = 'Assembly_SmartRecompute.svg'
    _saveParam = True

    @classmethod
    def IsActive(cls):
        return True

class AsmCmdAutoElementVis(AsmCmdCheckable):
    _id = 9
    _menuText = 'Auto element visibility'
    _iconName = 'Assembly_AutoElementVis.svg'
    _toolbarName = None
    _menuGroupName = None
    _contextMenuName = None
    _saveParam = True
    _defaultValue = True

    @classmethod
    def IsActive(cls):
        return True

    @classmethod
    def Activated(cls,checked):
        super(AsmCmdAutoElementVis,cls).Activated(checked)
        cls.setup()

    @classmethod
    def setup(cls):
        checked = AsmCmdManager.AutoElementVis
        from .assembly import isTypeOf,AsmConstraint,\
            AsmElement,AsmElementLink,AsmElementGroup
        for doc in FreeCAD.listDocuments().values():
            for obj in doc.Objects:
                if isTypeOf(obj,(AsmConstraint,AsmElementGroup)):
                    if isTypeOf(obj,AsmConstraint):
                        obj.ViewObject.OnTopWhenSelected = 2
                elif isTypeOf(obj,(AsmElementLink,AsmElement)):
                    if checked:
                        obj.Proxy.parent.Object.setElementVisible(
                                obj.Name,False)
                    obj.ViewObject.OnTopWhenSelected = 2


class AsmCmdShowElementCS(AsmCmdCheckable):
    _id = 28
    _menuText = 'Show element coordinate system'
    _iconName = 'Assembly_ShowElementCS.svg'
    _toolbarName = None
    _menuGroupName = None
    _contextMenuName = None
    _saveParam = True
    _defaultValue = False

    @classmethod
    def IsActive(cls):
        return True

    @classmethod
    def Activated(cls,checked):
        super(AsmCmdShowElementCS,cls).Activated(checked)
        from .assembly import isTypeOf,AsmElement
        for doc in FreeCAD.listDocuments().values():
            for obj in doc.Objects:
                if isTypeOf(obj,AsmElement):
                    obj.ViewObject.Proxy.setupAxis()


class AsmCmdElementStyle(AsmCmdBase):
    _id = 29
    _iconName = AsmCmdAutoElementVis._iconName
    _menuText = 'Element style'
    _toolbarName = AsmCmdBase._toolbarName
    _cmds = (AsmCmdAutoElementVis.getName(),
             AsmCmdShowElementCS.getName())

    @classmethod
    def IsActive(cls):
        return True

    @classmethod
    def GetCommands(cls):
        return cls._cmds


class AsmCmdAddWorkplane(AsmCmdBase):
    _id = 8
    _menuText = 'Add workplane'
    _iconName = 'Assembly_Add_Workplane.svg'
    _toolbarName = None
    _menuGroupName = None
    _contextMenuName = None
    _accel = 'A, P'
    _makeType = 0

    @classmethod
    def checkActive(cls):
        from . import assembly
        if logger.catchTrace('',assembly.AsmWorkPlane.getSelection):
            cls._active = True
        else:
            cls._active = False

    @classmethod
    def onSelectionChange(cls,hasSelection):
        cls._active = None if hasSelection else False

    @classmethod
    def Activated(cls,idx=0):
        _ = idx
        from . import assembly
        assembly.AsmWorkPlane.make(tp=cls._makeType)

class AsmCmdAddWorkplaneXZ(AsmCmdAddWorkplane):
    _id = 10
    _menuText = 'Add XZ workplane'
    _iconName = 'Assembly_Add_WorkplaneXZ.svg'
    _makeType = 1


class AsmCmdAddWorkplaneZY(AsmCmdAddWorkplane):
    _id = 11
    _menuText = 'Add ZY workplane'
    _iconName = 'Assembly_Add_WorkplaneZY.svg'
    _makeType = 2

class AsmCmdAddPlacement(AsmCmdAddWorkplane):
    _id = 30
    _menuText = 'Add placement'
    _iconName = 'Assembly_Add_Placement.svg'
    _makeType = 4

class AsmCmdAddOrigin(AsmCmdCheckable):
    _id = 14
    _menuText = 'Add Origin'
    _iconName = 'Assembly_Add_Origin.svg'
    _makeType = 3
    _saveParam = False
    _toolbarName = None
    _menuGroupName = None
    _contextMenuName = None

    @classmethod
    def IsActive(cls):
        return True

    @classmethod
    def Activated(cls,checked):
        cls.setChecked(checked)
        if checked:
            from . import assembly
            sels = logger.catchTrace('Add origin selection',
                    assembly.AsmWorkPlane.getSelection)
            if sels:
                assembly.AsmWorkPlane.make(sels,tp=cls._makeType)

class AsmCmdAddWorkplaneGroup(AsmCmdBase):
    _id = 12
    _iconName = AsmCmdAddWorkplane._iconName
    _menuText = 'Workplan and origin'
    _menuGroupName = ''
    _toolbarName = AsmCmdBase._toolbarName
    _cmds = (AsmCmdAddWorkplane,
             AsmCmdAddWorkplaneXZ,
             AsmCmdAddWorkplaneZY,
             AsmCmdAddPlacement,
             AsmCmdAddOrigin)

    @classmethod
    def IsActive(cls):
        return True

    @classmethod
    def GetCommands(cls):
        return [ cmd.getName() for cmd in cls._cmds ]

    @classmethod
    def onSelectionChange(cls,hasSelection):
        for cmd in cls._cmds:
            cmd.onSelectionChange(hasSelection)


class AsmCmdGotoRelation(AsmCmdBase):
    _id = 16
    _menuText = 'Go to relation'
    _tooltip = 'Select the corresponding part object in the relation group'
    _iconName = 'Assembly_GotoRelation.svg'
    _accel = 'A, R'
    _toolbarName = ''

    @classmethod
    def Activated(cls):
        from .assembly import AsmRelationGroup
        if AsmCmdMove._moveInfo:
            AsmRelationGroup.gotoRelation(AsmCmdMove._moveInfo)
            return
        sels = FreeCADGui.Selection.getSelectionEx('',0,True)
        if sels and len(sels[0].SubElementNames)==1:
            AsmRelationGroup.gotoRelationOfConstraint(
                    sels[0].Object,sels[0].SubElementNames[0])

    @classmethod
    def IsActive(cls):
        if AsmCmdMove._moveInfo:
            return True
        if cls._active is None:
            cls.checkActive()
        return cls._active

    @classmethod
    def checkActive(cls):
        from .assembly import isTypeOf, AsmConstraint, AsmElementLink
        sels = FreeCADGui.Selection.getSelection('',1,True)
        if sels and isTypeOf(sels[0],(AsmConstraint,AsmElementLink)):
            cls._active = True
        else:
            cls._active = False

    @classmethod
    def onSelectionChange(cls,hasSelection):
        cls._active = None if hasSelection else False

class AsmCmdGotoLinked(AsmCmdBase):
    _id = 20
    _menuText = 'Select linked object'
    _tooltip = 'Select the linked object'
    _accel = 'A, G'
    _toolbarName = ''

    @classmethod
    def getIconName(cls):
        return 'LinkSelect'

    @classmethod
    def Activated(cls):
        from .assembly import isTypeOf, \
                AsmElement, AsmElementLink, AsmElementGroup
        sels = FreeCADGui.Selection.getSelectionEx('',0,True)
        if not sels:
            return
        if not sels[0].SubElementNames:
            FreeCADGui.runCommand('Std_LinkSelectLinked')
            return
        subname = sels[0].SubElementNames[0]
        obj = sels[0].Object.getSubObject(subname,retType=1)
        if not isTypeOf(obj,(AsmElementLink,AsmElement)):
            FreeCADGui.runCommand('Std_LinkSelectLinked')
            return
        import Part
        from . import assembly
        subname = assembly.flattenLastSubname(sels[0].Object,subname)
        subname = Part.splitSubname(subname)[0].split('.')
        link = obj.LinkedObject
        if isinstance(link,tuple):
            linkSub = link[1]
            link = link[0]
        else:
            linkSub = link.Name + '.'
            link = obj.Proxy.getAssembly().getElementGroup()
        if isTypeOf(obj,AsmElementLink):
            subname = subname[:-4]
            if not isTypeOf(link,AsmElementGroup):
                subname.append('2')
        else:
            subname = subname[:-2]
            subname[-1] = '2'
        subname.append(link.Name)
        prefix = subname
        linkSub = linkSub.split('.')
        subname = '.'.join(prefix+linkSub)
        sobj = sels[0].Object.getSubObject(subname,retType=1)
        if not sobj:
            logger.error('Cannot find sub object {}.{}',
                objName(sels[0].Object),subname)
            return
        if not linkSub[-1] and linkSub[-2].startswith('$'):
            linkSub[-2] = sobj.Name
            subname = '.'.join(prefix+linkSub)
        FreeCADGui.Selection.pushSelStack()
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(sels[0].Object,subname)
        FreeCADGui.Selection.pushSelStack()
        FreeCADGui.runCommand('Std_TreeSelection')

    @classmethod
    def IsActive(cls):
        return FreeCADGui.isCommandActive('Std_LinkSelectLinked')

class AsmCmdGotoLinkedFinal(AsmCmdBase):
    _id = 23
    _menuText = 'Select linked final'
    _tooltip = 'Select the deepest linked object'
    _accel = 'A, F'
    _toolbarName = ''

    @classmethod
    def getIconName(cls):
        return 'LinkSelectFinal'

    @classmethod
    def Activated(cls):
        from .assembly import isTypeOf, AsmElement, AsmElementLink
        sels = FreeCADGui.Selection.getSelectionEx('',0,True)
        if not sels:
            return
        if not sels[0].SubElementNames:
            FreeCADGui.runCommand('Std_LinkSelectLinkedFinal')
            return
        subname = sels[0].SubElementNames[0]
        obj = sels[0].Object.getSubObject(subname,retType=1)
        if not isTypeOf(obj,(AsmElementLink,AsmElement)):
            FreeCADGui.runCommand('Std_LinkSelectLinkedFinal')
            return

        while True:
            linked = obj.LinkedObject
            if isinstance(linked,tuple):
                subname = linked[1]
                linked = linked[0]
            else:
                subname = ''
            obj = linked.getSubObject(subname,retType=1)
            if not isTypeOf(obj,AsmElement):
                break

        obj = obj.getLinkedObject(True)

        import Part
        subname = Part.splitSubname(subname)[-1]

        FreeCADGui.Selection.pushSelStack()
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(obj,subname)
        FreeCADGui.Selection.pushSelStack()
        FreeCADGui.runCommand('Std_TreeSelection')

    @classmethod
    def IsActive(cls):
        from .assembly import isTypeOf, AsmElement, AsmElementLink
        sels = FreeCADGui.Selection.getSelectionEx('',0,True)
        if len(sels)==1 and sels[0].SubElementNames:
            obj = sels[0].Object.getSubObject(sels[0].SubElementNames[0],1)
            if isTypeOf(obj, (AsmElementLink,AsmElement)):
                return True
        return FreeCADGui.isCommandActive('Std_LinkSelectLinkedFinal')

class AsmCmdUp(AsmCmdBase):
    _id = 6
    _menuText = 'Move item up'
    _iconName = 'Assembly_TreeItemUp.svg'

    @classmethod
    def getSelection(cls):
        from .assembly import AsmPlainGroup
        sels = FreeCADGui.Selection.getSelection()
        if len(sels)==1:
            obj = sels[0]
            parent = AsmPlainGroup.getParentGroup(obj)
            if parent and len(parent.Group)>1:
                return obj,parent

    @classmethod
    def checkActive(cls):
        cls._active = True if cls.getSelection() else False

    @classmethod
    def move(cls,step):
        ret = cls.getSelection()
        if not ret:
            return
        obj,parent = ret
        children = parent.Group
        i = children.index(obj)
        j = i+step
        if j<0:
            j = len(children)-1
        elif j>=len(children):
            j = 0
        logger.debug('move {}:{} -> {}:{}',
            i,objName(obj),j,objName(children[j]))
        FreeCAD.setActiveTransaction(cls._menuText)
        children[i],children[j] = children[j],obj
        from .assembly import editGroup
        editGroup(parent,children)
        FreeCAD.closeActiveTransaction();

    @classmethod
    def onSelectionChange(cls,hasSelection):
        cls._active = None if hasSelection else False

    @classmethod
    def Activated(cls):
        cls.move(-1)


class AsmCmdDown(AsmCmdUp):
    _id = 7
    _menuText = 'Move item down'
    _iconName = 'Assembly_TreeItemDown.svg'

    @classmethod
    def Activated(cls):
        cls.move(1)


class AsmCmdMultiply(AsmCmdBase):
    _id = 18
    _menuText = 'Multiply constraint'
    _tooltip = 'Mutiply the part owner of the first element to constrain\n'\
               'against the rest of the elements. It will auto replace the\n'\
               'first part owner with a link array when necessary.\n\n'\
               'It will also optionally expand colplanar circular edges with\n'\
               'the same radius in the second element on wards. To disable\n'\
               'auto expansion, use NoExpand property in the element link.'
    _iconName = 'Assembly_ConstraintMultiply.svg'

    @classmethod
    def checkActive(cls):
        from .assembly import AsmConstraint
        if logger.catchTrace('',AsmConstraint.makeMultiply,True):
            cls._active = True
        else:
            cls._active = False

    @classmethod
    def Activated(cls):
        from .assembly import AsmConstraint
        logger.report('',AsmConstraint.makeMultiply)

    @classmethod
    def onSelectionChange(cls,hasSelection):
        cls._active = None if hasSelection else False
