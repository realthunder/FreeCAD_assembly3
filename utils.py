'''
Collection of helper function to extract geometry properties from OCC elements

Most of the functions are borrowed directly from assembly2lib.py or lib3D.py in
assembly2
'''

from collections import namedtuple
import FreeCAD, FreeCADGui, Part, Draft
import numpy as np
from .FCADLogger import FCADLogger
rootlogger = FCADLogger('asm3')
logger = FCADLogger('asm3.main',parent=rootlogger)
guilogger = FCADLogger('asm3.gui',parent=rootlogger)
cstrlogger = FCADLogger('asm3.cstr',parent=rootlogger)
syslogger = FCADLogger('asm3.sys',parent=rootlogger)
proxylogger = FCADLogger('asm3.proxy',parent=rootlogger)

import sys, os
modulePath = os.path.dirname(os.path.realpath(__file__))

from PySide.QtCore import Qt
from PySide.QtGui import QIcon, QPainter, QPixmap
iconPath = os.path.join(modulePath,'Gui','Resources','icons')
pixmapDisabled = QPixmap(os.path.join(iconPath,'Assembly_Disabled.svg'))
iconSize = (16,16)

def getIcon(obj,disabled=False,path=None):
    if not path:
        path = iconPath
    if not getattr(obj,'_icon',None):
        obj._icon = QIcon(os.path.join(path,obj._iconName))
    if not disabled:
        return obj._icon
    if not getattr(obj,'_iconDisabled',None):
        pixmap = obj._icon.pixmap(*iconSize,mode=QIcon.Disabled)
        icon = QIcon(pixmapDisabled)
        icon.paint(QPainter(pixmap),
                0,0,iconSize[0],iconSize[1],Qt.AlignCenter)
        obj._iconDisabled = QIcon(pixmap)
    return obj._iconDisabled

def addIconToFCAD(iconFile,path=None):
    iconName = ':asm3/icons/' + iconFile
    if not path:
        path = iconPath
    try:
        path = os.path.join(path,iconFile)
        FreeCADGui.addIcon(iconName,path)
    except AssertionError:
        pass
    return iconName

def objName(obj):
    if obj.Label == obj.Name:
        return '"'+obj.Name+'"'
    return '"{}({})"'.format(obj.Name,obj.Label)

def isLine(param):
    if hasattr(Part,"LineSegment"):
        return isinstance(param,(Part.Line,Part.LineSegment))
    else:
        return isinstance(param,Part.Line)

def deduceSelectedElement(obj,subname):
    shape = obj.getSubObject(subname)
    if not shape:
        return
    count = len(shape.Faces)
    if count==1:
        return 'Face1'
    elif not count:
        count = len(shape.Edges)
        if count==1:
            return 'Edge1'
        elif not count:
            count = len(shape.Vertexes)
            if count==1:
                return 'Vertex1'

def getElementShape(obj,tp):
    if not isinstance(obj,(tuple,list)):
        shape = obj
    else:
        sobj,mat,shape = obj[0].getSubObject(obj[1],2,transform=False)
        if not sobj:
            return
        if not shape:
            if sobj.TypeId == 'App::Line':
                if tp not in (Part.Shape,Part.Edge):
                    return
                shape = Part.makeLine(
                        FreeCAD.Vector(-1,0,0),FreeCAD.Vector(-1,0,0))
                shape.transformShape(mat,False,True)
                return shape
            elif sobj.TypeId == 'App::Plane':
                if tp not in (Part.Shape, Part.Face):
                    return
                shape = Part.makePlane(2,2,FreeCAD.Vector(-1,-1,0))
                shape.transformShape(mat,False,True)
                return shape
            else:
                return

    if not isinstance(shape,Part.Shape) or shape.isNull():
        return

    if isinstance(shape,tp):
        return shape
    elif isinstance(shape,(Part.Vertex,Part.Edge,Part.Face)):
        return
    elif tp is Part.Vertex:
        if len(Part.Edges):
            return
        v = shape.Vertexes
        if len(v)==1:
            return v[0]
    elif tp is Part.Edge:
        if len(Part.Faces):
            return
        e = shape.Edges
        if len(e)==1:
            return e[0]
    elif tp is Part.Face:
        f = shape.Faces
        if len(f)==1:
            return f[0]

def isDraftWire(obj):
    proxy = getattr(obj,'Proxy',None)
    if isinstance(proxy,Draft._Wire) and not obj.Subdivisions:
        return obj

def isDraftCircle(obj):
    proxy = getattr(obj,'Proxy',None)
    if isinstance(proxy,Draft._Circle):
        return obj

def isDraftObject(obj):
    o = isDraftWire(obj)
    if o:
        return o
    return isDraftCircle(obj)

def isElement(obj):
    if not isinstance(obj,(tuple,list)):
        shape = obj
    else:
        sobj,_,shape = obj[0].getSubObject(obj[1],2)
        if not sobj:
            return
        if not shape:
            return sobj.TypeId in ('App::Line','App::Plane')
    if isinstance(obj,(Part.Vertex,Part.Face,Part.Edge)):
        return True
    if isinstance(shape,Part.Shape) and not shape.isNull():
        return len(shape.Vertexes)==1 or \
               len(shape.Edges)==1 or \
               len(shape.Faces)==1

def isPlanar(obj):
    if isCircularEdge(obj):
        return True
    shape = getElementShape(obj,Part.Face)
    if not shape:
        return False
    elif str(shape.Surface) == '<Plane object>':
        return True
    elif hasattr(shape.Surface,'Radius'):
        return False
    elif str(shape.Surface).startswith('<SurfaceOfRevolution'):
        return False
    else:
        _plane_norm,_plane_pos,error = fit_plane_to_surface1(shape.Surface)
        error_normalized = error / shape.BoundBox.DiagonalLength
        return error_normalized < 10**-6

def isCylindricalPlane(obj):
    face = getElementShape(obj,Part.Face)
    if not face:
        return False
    elif hasattr(face.Surface,'Radius'):
        return True
    elif str(face.Surface).startswith('<SurfaceOfRevolution'):
        return True
    elif str(face.Surface) == '<Plane object>':
        return False
    else:
        _axis,_center,error=fit_rotation_axis_to_surface1(face.Surface)
        error_normalized = error / face.BoundBox.DiagonalLength
        return error_normalized < 10**-6

def isAxisOfPlane(obj):
    face = getElementShape(obj,Part.Face)
    if not face:
        return False
    if str(face.Surface) == '<Plane object>':
        return True
    else:
        _axis,_center,error=fit_rotation_axis_to_surface1(face.Surface)
        error_normalized = error / face.BoundBox.DiagonalLength
        return error_normalized < 10**-6

def isCircularEdge(obj):
    edge = getElementShape(obj,Part.Edge)
    if not edge:
        return False
    elif not hasattr(edge, 'Curve'): #issue 39
        return False
    if hasattr( edge.Curve, 'Radius' ):
        return True
    elif isLine(edge.Curve):
        return False
    else:
        BSpline = edge.Curve.toBSpline()
        try:
            arcs = BSpline.toBiArcs(10**-6)
        except Exception:  #FreeCAD exception thrown ()
            return False
        if all( hasattr(a,'Center') for a in arcs ):
            centers = np.array([a.Center for a in arcs])
            sigma = np.std( centers, axis=0 )
            return max(sigma) < 10**-6
        return False

def isLinearEdge(obj):
    edge = getElementShape(obj,Part.Edge)
    if not edge:
        return False
    elif not hasattr(edge, 'Curve'): #issue 39
        return False
    if isLine(edge.Curve):
        return True
    elif hasattr( edge.Curve, 'Radius' ):
        return False
    else:
        BSpline = edge.Curve.toBSpline()
        try:
            arcs = BSpline.toBiArcs(10**-6)
        except Exception:  #FreeCAD exception thrown ()
            return False
        if all(isLine(a) for a in arcs):
            lines = arcs
            D = np.array([L.tangent(0)[0] for L in lines]) #D(irections)
            return np.std( D, axis=0 ).max() < 10**-9
        return False

def isVertex(obj):
    return getElementShape(obj,Part.Vertex) is not None

def hasCenter(obj):
    return isVertex(obj) or isCircularEdge(obj) or \
            isAxisOfPlane(obj) or isSphericalSurface(obj)

def isSphericalSurface(obj):
    face = getElementShape(obj,Part.Face)
    if not face:
        return False
    return str( face.Surface ).startswith('Sphere ')

def getElementPos(obj):
    pos = None
    vertex = getElementShape(obj,Part.Vertex)
    if vertex:
        return vertex.Point
    face = getElementShape(obj,Part.Face)
    if face:
        surface = face.Surface
        if str(surface) == '<Plane object>':
            pos = face.BoundBox.Center
            #  pos = surface.Position
        elif all( hasattr(surface,a) for a in ['Axis','Center','Radius'] ):
            pos = surface.Center
        elif str(surface).startswith('<SurfaceOfRevolution'):
            pos = face.Edges1.Curve.Center
        else: #numerically approximating surface
            _plane_norm, plane_pos, error = \
                    fit_plane_to_surface1(face.Surface)
            error_normalized = error / face.BoundBox.DiagonalLength
            if error_normalized < 10**-6: #then good plane fit
                pos = plane_pos
            _axis, center, error = \
                    fit_rotation_axis_to_surface1(face.Surface)
            error_normalized = error / face.BoundBox.DiagonalLength
            if error_normalized < 10**-6: #then good rotation_axis fix
                pos = center
    else:
        edge = getElementShape(obj,Part.Edge)
        if edge:
            if isLine(edge.Curve):
                #  pos = edge.Vertexes[-1].Point
                pos = (edge.Vertexes[0].Point+edge.Vertexes[1].Point)*0.5
            elif hasattr( edge.Curve, 'Center'): #circular curve
                pos = edge.Curve.Center
            else:
                BSpline = edge.Curve.toBSpline()
                arcs = BSpline.toBiArcs(10**-6)
                if all( hasattr(a,'Center') for a in arcs ):
                    centers = np.array([a.Center for a in arcs])
                    sigma = np.std( centers, axis=0 )
                    if max(sigma) < 10**-6: #then circular curce
                        pos = centers[0]
                elif all(isLine(a) for a in arcs):
                    lines = arcs
                    D = np.array(
                            [L.tangent(0)[0] for L in lines]) #D(irections)
                    if np.std( D, axis=0 ).max() < 10**-9: #then linear curve
                        #  return lines[0].value(0)
                        return edge.BoundBox.Center
    return pos


def getElementRotation(obj,reverse=False):
    axis = None
    face = getElementShape(obj,Part.Face)
    if face:
        if face.Orientation == 'Reversed':
            reverse = not reverse
        surface = face.Surface
        if hasattr(surface,'Axis'):
            axis = surface.Axis
        elif str(surface).startswith('<SurfaceOfRevolution'):
            axis = face.Edges[0].Curve.Axis
        else: #numerically approximating surface
            plane_norm, _plane_pos, error = \
                    fit_plane_to_surface1(face.Surface)
            error_normalized = error / face.BoundBox.DiagonalLength
            if error_normalized < 10**-6: #then good plane fit
                axis = plane_norm
            axis_fitted, _center, error = \
                    fit_rotation_axis_to_surface1(face.Surface)
            error_normalized = error / face.BoundBox.DiagonalLength
            if error_normalized < 10**-6: #then good rotation_axis fix
                axis = axis_fitted
    else:
        edge = getElementShape(obj,Part.Edge)
        if edge:
            if isLine(edge.Curve):
                axis = edge.Curve.tangent(0)[0]
            elif hasattr( edge.Curve, 'Axis'): #circular curve
                axis =  edge.Curve.Axis
            else:
                BSpline = edge.Curve.toBSpline()
                arcs = BSpline.toBiArcs(10**-6)
                if all( hasattr(a,'Center') for a in arcs ):
                    centers = np.array([a.Center for a in arcs])
                    sigma = np.std( centers, axis=0 )
                    if max(sigma) < 10**-6: #then circular curce
                        axis = arcs[0].Axis
                if all(isLine(a) for a in arcs):
                    lines = arcs
                    D = np.array(
                            [L.tangent(0)[0] for L in lines]) #D(irections)
                    if np.std( D, axis=0 ).max() < 10**-9: #then linear curve
                        return D[0]
    if not axis:
        return FreeCAD.Rotation()
    return FreeCAD.Rotation(FreeCAD.Vector(0,0,-1 if reverse else 1),axis)

def getNormal(obj):
    if isinstance(obj,FreeCAD.Rotation):
        rot = obj
    elif isinstance(obj,FreeCAD.Placement):
        rot = obj.Rotation
    else:
        rot = getElementRotation(obj)
    q = rot.Q
    return q[3],q[0],q[1],q[2]

def getElementCircular(obj):
    'return radius if it is closed, or a list of two endpoints'
    edge = getElementShape(obj,Part.Edge)
    if not edge:
        return
    elif not hasattr(edge, 'Curve'): #issue 39
        return
    c = edge.Curve
    if hasattr( c, 'Radius' ):
        if edge.Closed:
            return c.Radius
    elif isLine(edge.Curve):
        return
    else:
        BSpline = edge.Curve.toBSpline()
        try:
            arc = BSpline.toBiArcs(10**-6)[0]
        except Exception:  #FreeCAD exception thrown ()
            return
        if edge.Closed:
            return arc[0].Radius
    return [v.Point for v in edge.Vertexes]

def fit_plane_to_surface1( surface, n_u=3, n_v=3 ):
    'borrowed from assembly2 lib3D.py'
    uv = sum( [ [ (u,v) for u in np.linspace(0,1,n_u)]
        for v in np.linspace(0,1,n_v) ], [] )
    # positions at u,v points
    P = [ surface.value(u,v) for u,v in uv ]
    N = [ np.cross( *surface.tangent(u,v) ) for u,v in uv ]
    # plane's normal, averaging done to reduce error
    plane_norm = sum(N) / len(N)
    plane_pos = P[0]
    error = sum([ abs( np.dot(p - plane_pos, plane_norm) ) for p in P ])
    return plane_norm, plane_pos, error

def fit_rotation_axis_to_surface1( surface, n_u=3, n_v=3 ):
    '''
    should work for cylinders and pssibly cones (depending on the u,v mapping)

    borrowed from assembly2 lib3D.py
    '''
    uv = sum( [ [ (u,v) for u in np.linspace(0,1,n_u)]
        for v in np.linspace(0,1,n_v) ], [] )
    # positions at u,v points
    P = [ np.array(surface.value(u,v)) for u,v in uv ]
    N = [ np.cross( *surface.tangent(u,v) ) for u,v in uv ]
    intersections = []
    for i in range(len(N)-1):
        for j in range(i+1,len(N)):
            # based on the distance_between_axes( p1, u1, p2, u2) function,
            if 1 - abs(np.dot( N[i], N[j])) < 10**-6:
                continue #ignore parallel case
            p1_x, p1_y, p1_z = P[i]
            u1_x, u1_y, u1_z = N[i]
            p2_x, p2_y, p2_z = P[j]
            u2_x, u2_y, u2_z = N[j]
            t1_t1_coef = u1_x**2 + u1_y**2 + u1_z**2 #should equal 1
            # collect( expand(d_sqrd), [t1*t2] )
            t1_t2_coef = -2*u1_x*u2_x - 2*u1_y*u2_y - 2*u1_z*u2_z
            t2_t2_coef = u2_x**2 + u2_y**2 + u2_z**2 #should equal 1 too
            t1_coef    = 2*p1_x*u1_x + 2*p1_y*u1_y + 2*p1_z*u1_z - \
                    2*p2_x*u1_x - 2*p2_y*u1_y - 2*p2_z*u1_z
            t2_coef    =-2*p1_x*u2_x - 2*p1_y*u2_y - 2*p1_z*u2_z + \
                    2*p2_x*u2_x + 2*p2_y*u2_y + 2*p2_z*u2_z
            A = np.array([ [ 2*t1_t1_coef , t1_t2_coef ],
                [ t1_t2_coef, 2*t2_t2_coef ] ])
            b = np.array([ t1_coef, t2_coef])
            try:
                t1, t2 = np.linalg.solve(A,-b)
            except np.linalg.LinAlgError:
                continue
            pos_t1 = P[i] + np.array(N[i])*t1
            pos_t2 = P[j] + N[j]*t2
            intersections.append( pos_t1 )
            intersections.append( pos_t2 )
    if len(intersections) < 2:
        error = np.inf
        return 0, 0, error
    else: 
        # fit vector to intersection points; 
        # http://mathforum.org/library/drmath/view/69103.html
        X = np.array(intersections)
        centroid = np.mean(X,axis=0)
        M = np.array([i - centroid for i in intersections ])
        A = np.dot(M.transpose(), M)
        # np docs: s : (..., K) The singular values for every matrix, 
        # sorted in descending order.
        _U,s,V = np.linalg.svd(A)
        axis_pos = centroid
        axis_dir = V[0]
        error = s[1] #don't know if this will work
        return axis_dir, axis_pos, error

_tol = 10e-7

def roundPlacement(pla):
    pos = [ 0.0 if abs(v)<_tol else v for v in pla.Base ]
    q = [ 0.0 if abs(v)<_tol else v for v in pla.Rotation.Q ]
    return FreeCAD.Placement(FreeCAD.Vector(*pos),FreeCAD.Rotation(*q))

def isSameValue(v1,v2):
    if isinstance(v1,(tuple,list)):
        assert(len(v1)==len(v2))
        vs = zip(v1,v2)
    else:
        vs = (v1,v2),
    return all([abs(v1-v2)<_tol for v1,v2 in vs])

def isSamePos(p1,p2):
    return p1.distanceToPoint(p2) < _tol

def isSamePlacement(pla1,pla2):
    return isSamePos(pla1.Base,pla2.Base) and \
        isSameValue(pla1.Rotation.Q,pla2.Rotation.Q)

def getElementIndex(name,check=None):
    'Return element index (starting with 1), 0 if invalid'
    for i,c in enumerate(reversed(name)):
        if not c.isdigit():
            if not i:
                break
            idx = int(name[-i:])
            if check and '{}{}'.format(check,idx)!=name:
                break
            return idx
    return 0

def draftWireVertex2PointIndex(obj,name):
    'Convert vertex index to draft wire point index, None if invalid'
    obj = isDraftWire(obj)
    if not obj:
        return
    idx = getElementIndex(name,'Vertex')
    # We don't support subdivision yet (checked in isDraftWire())
    if idx <= 0:
        return
    idx -= 1
    if idx < len(obj.Points):
        return idx

def edge2VertexIndex(obj,name,retInteger=False):
    'deduct the vertex index from the edge index'
    idx = getElementIndex(name,'Edge')
    if not idx:
        return None,None
    dwire = isDraftWire(obj)
    if dwire and dwire.Closed and idx==len(dwire.Points):
        idx2 = 1
    else:
        idx2 = idx+1
    if retInteger:
        return idx-1,idx2-1
    return 'Vertex{}'.format(idx),'Vertex{}'.format(idx2)
