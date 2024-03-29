import numpy as np
cimport numpy as np
from pygel3d import hmesh
from scipy.spatial import ConvexHull

np.import_array()

def find_distance(np.ndarray points, np.ndarray mesh_coords, np.ndarray mesh):
    cdef list node_count
    cdef list temp
    cdef dict dists_dict
    cdef double min_dist
    cdef int num
    cdef np.ndarray coord
    cdef bint inside
    cdef double dist
    cdef double origin_dist
    dists_dict = {}
    node_count = []

    cdef int i
    cdef np.ndarray point

    for i, point in enumerate(points):
        min_dist = 1000  # some starting distance. FIXME take from the existing ones
        coord = point[0:3]
        num = point[3]  # num is the number of particles at node coord
        inside = _is_inside(coord, mesh)  # flag to determine if the point is inside the mesh

        for mesh_point in mesh_coords:
            dist = norm(mesh_point, coord)

            if dist < min_dist:
                min_dist = dist
        origin_dist = norm(coord - (0, 0, 0))

        if inside:
            min_dist *= -1  # distance from interface is negative if inside

        temp = [min_dist]
        node_count += temp

        if not dists_dict.get(min_dist):  # Check if the distance is in the dictionary
            dists_dict[min_dist] = []  # create it if not

        dists_dict[min_dist] += (temp * num)
        # dists += (temp * num)

    return node_count, dists_dict

def norm(np.ndarray point, np.ndarray plane) -> float:
    cdef np.ndarray p0
    cdef np.ndarray p1
    cdef np.ndarray p2
    cdef np.ndarray normal
    cdef np.ndarray n
    p0, p1, p2 = plane
    normal = np.cross(p1 - p0, p2 - p0)
    n = normal / np.abs(normal)
    dist = np.abs(np.dot(point - p0, n))
    return dist

def find_distance_2(hull, np.ndarray points):
    cdef list res
    cdef np.ndarray p
    cdef float d

    # Construct PyGEL Manifold from the convex hull
    m = hmesh.Manifold()
    for s in hull.simplices:
        m.add_face(hull.points[s])

    dist = hmesh.MeshDistance(m)
    res = []
    for p in points:
        # Get the distance to the point
        # But don't trust its sign, because of possible
        # wrong orientation of mesh face
        d = dist.signed_distance(p)

        # Correct the sign with ray inside test
        if dist.ray_inside_test(p):
            if d > 0:
                d *= -1
        else:
            if d < 0:
                d *= -1

        res.append((d, p))

    return res
# def find_distance_2(np.ndarray points, np.ndarray mesh_coords):
#     cdef list dists_and_coord
#     cdef double min_dist
#     # cdef int num
#     cdef np.ndarray coord
#     cdef bint inside
#     cdef int sign
#     cdef double dist
#     dists_and_coord = []  # Will contain distance of the point from the interface and from the origin
#     hull = ConvexHull(mesh_coords, qhull_options='Q0')
#
#     cdef int i
#     cdef np.ndarray point
#     cdef np.ndarray simplex
#     cdef int vertex
#
#     for i, point in enumerate(points):
#         min_dist = 1000
#         coord = point[0:3]
#         # num = point[3]  # num is the number of particles at node coord
#         inside = _is_inside(coord, hull)  # flag to determine if the point is inside the mesh
#
#         for simplex in hull.simplices:
#             # Calculate distance between centroid of simplices and coordinates
#             dist = norm(coord, mesh_coords[simplex].mean(axis=0))
#
#             if dist < min_dist:
#                 min_dist = dist
#
#         for vertex in hull.vertices:
#             # Calculate distances between vertices and coordinates
#             dist = norm(coord, mesh_coords[vertex])
#
#             if dist < min_dist:
#                 min_dist = dist
#
#         sign = -1 if inside else 1
#
#         dists_and_coord.append((sign * min_dist, coord))
#
#     return dists_and_coord

def _is_inside_old(np.ndarray point, np.ndarray mesh):
    """ Doesn't work correctly """
    cdef int x, y, z
    cdef np.ndarray yz_proj
    cdef np.ndarray xz_proj
    cdef np.ndarray xy_proj
    x, y, z = point
    yz_proj = mesh.sum(axis=0)
    xz_proj = mesh.sum(axis=1)
    xy_proj = mesh.sum(axis=2)

    if yz_proj[y, z] > 0 and xz_proj[x, z] > 0 and xy_proj[x, y] > 0:
        return True

    return False


def _is_inside(np.ndarray point, hull) -> np.bool_:
    return point_in_hull(point, hull)

def _is_inside_meh(np.ndarray point, np.ndarray mesh) -> np.bool_:
    cdef np.ndarray inside
    cdef list slice_index

    inside = np.array((False, False, False))
    slice_index = [[1, 2],
                   [0, 2],
                   [0, 1]]
    cdef int i
    for i in range(3):
        mesh_slice = mesh[mesh[:, i] == point[i]]
        if len(mesh_slice) >= 3:
            hull = ConvexHull(mesh_slice[:, slice_index[i]], qhull_options='QJ')
            inside[i] = point_in_hull(point[slice_index[i]], hull)

    return inside.all()

def _is_inside_not_working_again(np.ndarray point, np.ndarray mesh):
    cdef bint yz_inside, xz_inside, xy_inside
    cdef np.ndarray yz_proj
    cdef np.ndarray xz_proj
    cdef np.ndarray xy_proj

    yz_proj = make_coordinates(mesh.sum(axis=0))
    xz_proj = make_coordinates(mesh.sum(axis=1))
    xy_proj = make_coordinates(mesh.sum(axis=2))

    yz_hull = ConvexHull(yz_proj)
    xz_hull = ConvexHull(xz_proj)
    xy_hull = ConvexHull(xy_proj)

    yz_inside = point_in_hull(point[[1, 2]], yz_hull)
    xz_inside = point_in_hull(point[[0, 2]], xz_hull)
    xy_inside = point_in_hull(point[[0, 1]], xy_hull)

    return yz_inside and xz_inside and xy_inside

def point_in_hull(np.ndarray point, hull):
    cdef double tolerance
    tolerance = 1e-12

    return all(
        (np.dot(eq[:-1], point) + eq[-1] <= tolerance)
        for eq in hull.equations)

def make_coordinates(mesh, keep_numbers=False):
    """
    Converts the mesh to coordinates
    Args:
        mesh (np.ndarray):  Mesh to convert into 3D coordinates
        keep_numbers (bool): Resulting tuples will also contain the number of particles at that coordinate if True

    Returns:
        np.ndarray: Ndarray of tuples representing coordinates of each of the points in the mesh
    """
    cdef int dim
    cdef list coords

    dim = mesh.ndim
    coords = []

    if dim == 2:
        for i, col in enumerate(mesh):
            for j, elem in enumerate(col):
                if elem > 0:
                    coords.append((i, j)) if not keep_numbers else coords.append((i, j, mesh[i, j]))
    else:
        for i, mat in enumerate(mesh):
            for j, col in enumerate(mat):
                for k, elem in enumerate(col):
                    if elem > 0:
                        coords.append((i, j, k)) if not keep_numbers else coords.append((i, j, k, mesh[i, j, k]))

    return np.array(coords, dtype=int)

def _is_inside_not_right(np.ndarray point, np.ndarray mesh):
    cdef int x, y, z
    cdef int x_1, y_1, z_1  # to check if point is inside
    cdef bint x_inside, y_inside, z_inside
    cdef np.ndarray yz_proj
    cdef np.ndarray xz_proj
    cdef np.ndarray xy_proj
    x_inside, y_inside, z_inside = False, False, False
    x, y, z = point
    x_1, y_1, z_1 = point  # initialize to point's coordinates
    yz_proj = mesh.sum(axis=0)
    xz_proj = mesh.sum(axis=1)
    xy_proj = mesh.sum(axis=2)

    # cast a line from the point on yz plane in z direction
    while not y_inside and y_1 < yz_proj.shape[0]:
        if yz_proj[y_1, z] > 0:
            y_inside = True
            break
        y_1 += 1  # go 1 point right in horizontal direction in yz plane

    while not z_inside and z_1 < xz_proj.shape[0]:
        if xz_proj[x, z_1] > 0:
            z_inside = True
            break
        z_1 += 1  # go 1 point right in horizontal direction in xz plane

    while not x_inside and x_1 < xy_proj.shape[0]:
        if xy_proj[x_1, y] > 0:
            x_inside = True
            break
        x_1 += 1  # go 1 point right in horizontal direction in xy plane

    return x_inside and z_inside and y_inside

def norm(np.ndarray p_1, np.ndarray p_2):
    cdef int x_1
    cdef int y_1
    cdef int z_1
    cdef int x_2
    cdef int y_2
    cdef int z_2
    x_1 = p_1[0]
    y_1 = p_1[1]
    z_1 = p_1[2]
    x_2 = p_2[0]
    y_2 = p_2[1]
    z_2 = p_2[2]
    return np.sqrt((x_1 - x_2) * (x_1 - x_2) + (y_1 - y_2) * (y_1 - y_2) + (z_1 - z_2) * (z_1 - z_2))
