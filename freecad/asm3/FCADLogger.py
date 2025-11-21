# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileNotice: Part of the Assembly3 addon.

import FreeCAD

class FCADLogger(FreeCAD.Logger):

    def __init__(self,tag,**kargs):
        kargs.setdefault('title','Assembly3')
        super(FCADLogger,self).__init__(tag,**kargs)
