'''
Collection of helper function to extract geometry properties from OCC elements

Most of the functions are borrowed directly from assembly2lib.py or lib3D.py in
assembly2
'''

import FreeCAD, FreeCADGui, Part
import numpy

import asm3.FCADLogger
logger = asm3.FCADLogger.FCADLogger('assembly3')

def objName(obj):
    if obj.Label == obj.Name:
        return obj.Name
    return '{}({})'.format(obj.Name,obj.Label)

def isLine(param):
    if hasattr(Part,"LineSegment"):
        return isinstance(param,(Part.Line,Part.LineSegment))
    else:
        return isinstance(param,Part.Line)

def getElement(obj,tp):
    if isinstance(obj,tuple):
       obj = obj[0].getSubObject(obj[1])
    if not isinstance(obj,Part.Shape):
        return
    if obj.isNull() or not tp:
        return
    if tp == 'Vertex':
        vertexes = obj.Vertexes
        if len(vertexes)==1 and not obj.Edges:
            return vertexes[0]
    elif tp == 'Edge':
        edges = obj.Edges
        if len(edges)==1 and not obj.Faces:
            return edges[0]
    elif tp == 'Face':
        faces = obj.Faces
        if len(faces)==1:
            return faces[0]

def isPlane(obj):
    face = getElement(obj,'Face')
    if not face:
        return False
    elif str(face.Surface) == '<Plane object>':
        return True
    elif hasattr(face.Surface,'Radius'):
        return False
    elif str(face.Surface).startswith('<SurfaceOfRevolution'):
        return False
    else:
        _plane_norm,_plane_pos,error = fit_plane_to_surface1(face.Surface)
        error_normalized = error / face.BoundBox.DiagonalLength
        return error_normalized < 10**-6

def isCylindricalPlane(obj):
    face = getElement(obj,'Face')
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
    face = getElement(obj,'Face')
    if not face:
        return False
    if str(face.Surface) == '<Plane object>':
        return True
    else:
        _axis,_center,error=fit_rotation_axis_to_surface1(face.Surface)
        error_normalized = error / face.BoundBox.DiagonalLength
        return error_normalized < 10**-6

def isCircularEdge(obj):
    edge = getElement(obj,'Edge')
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
            centers = numpy.array([a.Center for a in arcs])
            sigma = numpy.std( centers, axis=0 )
            return max(sigma) < 10**-6
        return False

def isLinearEdge(obj):
    edge = getElement(obj,'Edge')
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
            D = numpy.array([L.tangent(0)[0] for L in lines]) #D(irections)
            return numpy.std( D, axis=0 ).max() < 10**-9
        return False

def isVertex(obj):
    return getElement(obj,'Vertex') is not None

def hasCenter(obj):
    return isVertex(obj) or isCircularEdge(obj) or \
            isAxisOfPlane(obj) or isSphericalSurface(obj)

def isSphericalSurface(obj):
    face = getElement(obj,'Face')
    if not face:
        return False
    return str( face.Surface ).startswith('Sphere ')

def getElementPos(obj):
    pos = None
    vertex = getElement(obj,'Vertex')
    if vertex:
        return vertex.Point
    face = getElement(obj,'Face')
    if face:
        surface = face.Surface
        if str(surface) == '<Plane object>':
            #  pos = face.BoundBox.Center
            pos = surface.Position
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
        edge = getElement(obj,'Edge')
        if edge:
            if isLine(edge.Curve):
                pos = edge.Vertexes[-1].Point
            elif hasattr( edge.Curve, 'Center'): #circular curve
                pos = edge.Curve.Center
            else:
                BSpline = edge.Curve.toBSpline()
                arcs = BSpline.toBiArcs(10**-6)
                if all( hasattr(a,'Center') for a in arcs ):
                    centers = numpy.array([a.Center for a in arcs])
                    sigma = numpy.std( centers, axis=0 )
                    if max(sigma) < 10**-6: #then circular curce
                        pos = centers[0]
                elif all(isLine(a) for a in arcs):
                    lines = arcs
                    D = numpy.array(
                            [L.tangent(0)[0] for L in lines]) #D(irections)
                    if numpy.std( D, axis=0 ).max() < 10**-9: #then linear curve
                        return lines[0].value(0)
    return pos


def getElementAxis(obj):
    axis = None
    face = getElement(obj,'Face')
    if face:
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
        edge = getElement(obj,'Edge')
        if edge:
            if isLine(edge.Curve):
                axis = edge.Curve.tangent(0)[0]
            elif hasattr( edge.Curve, 'Axis'): #circular curve
                axis =  edge.Curve.Axis
            else:
                BSpline = edge.Curve.toBSpline()
                arcs = BSpline.toBiArcs(10**-6)
                if all( hasattr(a,'Center') for a in arcs ):
                    centers = numpy.array([a.Center for a in arcs])
                    sigma = numpy.std( centers, axis=0 )
                    if max(sigma) < 10**-6: #then circular curce
                        axis = arcs[0].Axis
                if all(isLine(a) for a in arcs):
                    lines = arcs
                    D = numpy.array(
                            [L.tangent(0)[0] for L in lines]) #D(irections)
                    if numpy.std( D, axis=0 ).max() < 10**-9: #then linear curve
                        return D[0]
    return axis

def axisToNormal(v):
    return FreeCAD.Rotation(FreeCAD.Vector(0,0,1),v).Q

def getElementNormal(obj):
    return axisToNormal(getElementAxis(obj))

def getElementCircular(obj):
    'return radius if it is closed, or a list of two endpoints'
    edge = getElement(obj,'Edge')
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
    uv = sum( [ [ (u,v) for u in numpy.linspace(0,1,n_u)]
        for v in numpy.linspace(0,1,n_v) ], [] )
    # positions at u,v points
    P = [ surface.value(u,v) for u,v in uv ]
    N = [ numpy.cross( *surface.tangent(u,v) ) for u,v in uv ]
    # plane's normal, averaging done to reduce error
    plane_norm = sum(N) / len(N)
    plane_pos = P[0]
    error = sum([ abs( numpy.dot(p - plane_pos, plane_norm) ) for p in P ])
    return plane_norm, plane_pos, error

def fit_rotation_axis_to_surface1( surface, n_u=3, n_v=3 ):
    '''
    should work for cylinders and pssibly cones (depending on the u,v mapping)

    borrowed from assembly2 lib3D.py
    '''
    uv = sum( [ [ (u,v) for u in numpy.linspace(0,1,n_u)]
        for v in numpy.linspace(0,1,n_v) ], [] )
    # positions at u,v points
    P = [ numpy.array(surface.value(u,v)) for u,v in uv ]
    N = [ numpy.cross( *surface.tangent(u,v) ) for u,v in uv ]
    intersections = []
    for i in range(len(N)-1):
        for j in range(i+1,len(N)):
            # based on the distance_between_axes( p1, u1, p2, u2) function,
            if 1 - abs(numpy.dot( N[i], N[j])) < 10**-6:
                continue #ignore parrallel case
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
            A = numpy.array([ [ 2*t1_t1_coef , t1_t2_coef ],
                [ t1_t2_coef, 2*t2_t2_coef ] ])
            b = numpy.array([ t1_coef, t2_coef])
            try:
                t1, t2 = numpy.linalg.solve(A,-b)
            except numpy.linalg.LinAlgError:
                continue
            pos_t1 = P[i] + numpy.array(N[i])*t1
            pos_t2 = P[j] + N[j]*t2
            intersections.append( pos_t1 )
            intersections.append( pos_t2 )
    if len(intersections) < 2:
        error = numpy.inf
        return 0, 0, error
    else: 
        # fit vector to intersection points; 
        # http://mathforum.org/library/drmath/view/69103.html
        X = numpy.array(intersections)
        centroid = numpy.mean(X,axis=0)
        M = numpy.array([i - centroid for i in intersections ])
        A = numpy.dot(M.transpose(), M)
        # numpy docs: s : (..., K) The singular values for every matrix, 
        # sorted in descending order.
        _U,s,V = numpy.linalg.svd(A)
        axis_pos = centroid
        axis_dir = V[0]
        error = s[1] #dont know if this will work
        return axis_dir, axis_pos, error

_tol = 10e-7

def isSamePlacement(pla1,pla2):
    return pla1.Base.distanceToPoint(pla2.Base) < _tol and \
        numpy.norm(numpy.array(pla1.Rotation.Q) - \
                   numpy.array(pla2.Rotation.Q)) < _tol
