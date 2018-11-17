import FreeCAD

class FCADLogger(FreeCAD.Logger):

    def __init__(self,tag,**kargs):
        kargs.setdefault('title','Assembly3')
        super(FCADLogger,self).__init__(tag,**kargs)
