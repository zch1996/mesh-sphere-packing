
import numpy as np
from numpy import linalg as npl
from meshpy import triangle

from mesh_sphere_packing.area_constraints import AreaConstraints

ONE_THIRD = 0.3333333333333333
WITH_PBC = True

# TODO : change nomenclature. Segment is used in geometry to refer to an
#      : edge connecting two points. Here segment is used to refer to part
#      : of a sphere surface. This is confusing...


def build_boundary_PSLGs(segments, Lx, Ly, Lz):
    # TODO : Break up this function a bit.

    def compile_points_edges(segments):

        def build_edge_list(tris, points):
            v_adj = np.zeros(2*[points.shape[0]], dtype=np.int32)
            v_adj[tris[:,0], tris[:,1]] = v_adj[tris[:,1], tris[:,0]] = 1
            v_adj[tris[:,1], tris[:,2]] = v_adj[tris[:,2], tris[:,1]] = 1
            v_adj[tris[:,2], tris[:,0]] = v_adj[tris[:,0], tris[:,2]] = 1
            return np.array(np.where(np.triu(v_adj) == 1), dtype=np.int32).T

        vcount = 0
        all_points = []
        all_edges = []
        for points, tris in segments:
            edges = build_edge_list(tris, points)
            edges += vcount
            vcount += len(points)
            all_points.append(points)
            all_edges.append(edges)
        return np.vstack(all_points), np.vstack(all_edges)

    def refined_perimeter(perim, axis):

        def filter_colocated_points(perim, axis):
            delta = np.diff(perim[:,axis])
            keep_idx = np.hstack(([0], np.where(~np.isclose(delta,0.))[0] + 1))
            return perim[keep_idx]

        perim = filter_colocated_points(perim, axis)
        refined_points = [perim[0]]
        for e in [[i, i+1] for i in range(perim.shape[0]-1)]:
            e_len = perim[e[1], axis] - perim[e[0], axis]
            ne = int(np.ceil(e_len / ds))
            if ne > 1:
                dse = e_len / ne
                add_points = np.zeros((ne,3))
                add_points[:,axis] = dse * np.arange(1,ne+1)
                refined_points.append(perim[e[0]] + add_points)
        return np.vstack(refined_points)

    def add_holes(segments):
        # TODO : this is a placeholder function. Ultimately holes need to
        #      : be created at the point when a sphere is split into pieces.
        holes = [[] for _ in range(3)]
        for i in range(3):
            j, k = (i+1)%3, (i+2)%3
            for points, tris in segments:
                points_ax = points[np.isclose(points[:,i], 0.)]
                if points_ax.shape[0]:
                    holes[i].append([
                        0.5 * (points_ax[:,j].max() + points_ax[:,j].min()),
                        0.5 * (points_ax[:,k].max() + points_ax[:,k].min())
                    ])
            holes[i] = np.vstack(holes[i]) if len(holes[i])\
                else np.empty((0,2), dtype=np.float64)
        return holes

    def reindex_edges(points, points_ax, edges_ax):
        points_segment = points[points_ax]
        reindex = {old: new for new, old in enumerate(np.where(points_ax)[0])}
        for i, (v0, v1) in enumerate(edges_ax):
            edges_ax[i] = np.array([reindex[v0], reindex[v1]])
        return points_segment, edges_ax

    def build_perim_edge_list(points_ax, perim_refined):
        # Need to adjust edge indices for perimeter segments
        v_count = len(points_ax)
        perim_edges = 4 * [None]
        for j in range(4):
            v_count_perim = len(perim_refined[j])
            perim_vidx = np.empty(v_count_perim, dtype=np.int32)
            mask = np.full(v_count_perim, True)
            v_count_new = 0
            for i, p in enumerate(perim_refined[j]):
                vidx = np.where(np.isclose(npl.norm(points_ax - p, axis=1), 0.))[0]
                if len(vidx):
                    mask[i] = False
                    perim_vidx[i] = vidx[0]
                else:
                    perim_vidx[i] = v_count + v_count_new
                    v_count_new += 1
            perim_edges[j] = np.array([
                [perim_vidx[k], perim_vidx[k+1]] for k in range(v_count_perim-1)
            ])
            perim_refined[j] = perim_refined[j][mask]
            v_count += v_count_new
        return perim_edges

    L = np.array([Lx, Ly, Lz])

    points, edges = compile_points_edges(segments)

    # TODO : get target point separation from segment properties.
    #      : For now, get this from mean edge length.
    ds = np.mean(npl.norm(points[edges[:,0]] - points[edges[:,1]], axis=1))

    # Get edges and points on each boundary
    edges_ax = [
        edges[np.all(np.isclose(points[edges,i], 0.), axis=1)]
        for i in range(3)
    ]
    points_ax = [np.isclose(points[:,i], 0.) for i in range(3)]

    # Fix boundary points to exactly zero
    for i in range(3):
        points[(points_ax[i], i)] = 0.

    # reindex edge vertices
    points_segments, edges_ax = [list(x) for x in zip(*[
        reindex_edges(points, points_ax[i], edges_ax[i]) for i in range(3)
    ])]
    perim = perim_refined = 3 * [4 * [None]]
    perim_segs = np.array([[0, 1], [1, 2], [2, 3], [3, 0]])

    perim_edges = []

    for i in range(3):
        # Rotate coordinate system by cyclic permutation of axes
        points_segments[i][:,(0,1,2)] = points_segments[i][:,(i,(i+1)%3,(i+2)%3)]

        corners = np.array([
            [0., 0., 0.], [0., L[1], 0.], [0., L[1], L[2]], [0., 0., L[2]]
        ])

        points_on_perim = 4 * [None]
        points_on_perim[0] = np.isclose(points_segments[i][:, 2], 0.)
        points_on_perim[1] = np.isclose(points_segments[i][:, 1], L[1])
        points_on_perim[2] = np.isclose(points_segments[i][:, 2], L[2])
        points_on_perim[3] = np.isclose(points_segments[i][:, 1], 0.)

        for j in range(2 + 2 * int(not WITH_PBC)):
            axis = 1 + j % 2
            perim[i][j] = np.vstack(
                (corners[perim_segs[j]], points_segments[i][points_on_perim[j]])
            )
            if WITH_PBC:
                translate = np.array([0., 0., -L[2]]) if axis == 1\
                    else np.array([0., L[1], 0.])
                translated_points = points_segments[i][points_on_perim[j + 2]]\
                    + translate
                perim[i][j] = np.vstack((perim[i][j], translated_points))
            perim[i][j] = perim[i][j][perim[i][j][:, axis].argsort()]
            perim_refined[i][j] = refined_perimeter(perim[i][j], axis)
            if WITH_PBC:
                perim[i][j+2] = perim[i][j] - translate
                perim_refined[i][j+2] = perim_refined[i][j] - translate

        # Add the corner points so that duplicate coners can be filtered out
        # in build_perim_edge_list
        points_segments[i] = np.append(points_segments[i], corners, axis=0)

        perim_edges.append(
            build_perim_edge_list(points_segments[i], perim_refined[i])
        )

        # Put coordinates back in proper order for this axis
        points_segments[i][:,(i,(i+1)%3,(i+2)%3)] = points_segments[i][:,(0,1,2)]

        L = L[np.newaxis, (1, 2, 0)][0]

    # TODO : refactor so boundary PSLG is built during above loop avoiding subsequent loops

    # add holes
    pslg_holes = add_holes(segments)

    # Group together segment and perimeter points and edges for each axis
    boundary_pslgs = []
    for i in range(3):
        pslg_points = np.vstack((
            points_segments[i][:,((i+1)%3,(i+2)%3)],
            np.vstack(perim_refined[i])[:,(1,2)]
        ))
        pslg_edges = np.vstack((edges_ax[i], np.vstack(perim_edges[i])))
        boundary_pslgs.append((pslg_points, pslg_edges, pslg_holes[i]))
    return boundary_pslgs


def triangulate_PSLGs(pslgs, args):

    # TODO : set max_volume based on geometry
    points, edges, _ = pslgs[0]
    ds = np.mean(npl.norm(points[edges[:,0]] - points[edges[:,1]], axis=1))

    # TODO : rather than passing ds this should be available in some class.
    area_constraints = AreaConstraints(args, ds)

    triangulated_boundaries = []
    for i, (points, edges, holes) in enumerate(pslgs):

        target_area_grid = area_constraints.grid[i]
        inv_dx = area_constraints.inv_dx[i]
        inv_dy = area_constraints.inv_dy[i]

        def rfunc(vertices, area):
            (ox, oy), (dx, dy), (ax, ay) = vertices
            cx = ONE_THIRD * (ox + dx + ax)  # Triangle center x coord.
            cy = ONE_THIRD * (oy + dy + ay)  # Triangle center y coord.
            ix = int(cx * inv_dx)
            iy = int(cy * inv_dy)
            target_area = target_area_grid[ix][iy]
            return int(area > target_area)  # True -> 1 means refine


        # Set mesh info for triangulation
        mesh_data = triangle.MeshInfo()
        mesh_data.set_points(points)
        mesh_data.set_facets(edges.tolist())
        if len(holes):
            mesh_data.set_holes(holes)

        # Call triangle library to perform Delaunay triangulation
        max_volume = ds**2
        min_angle = 20.

        mesh = triangle.build(
            mesh_data,
            max_volume=max_volume,
            min_angle=min_angle,
            allow_boundary_steiner=False,
            refinement_func=rfunc
        )

        # Extract triangle vertices from triangulation adding back x coord
        points = np.column_stack((np.zeros(len(mesh.points)), np.array(mesh.points)))
        points = points[:,(-i%3,(1-i)%3,(2-i)%3)]
        tris = np.array(mesh.elements)
        holes = np.column_stack((np.zeros(len(mesh.holes)), np.array(mesh.holes)))
        holes = holes[:,(-i%3,(1-i)%3,(2-i)%3)]

        triangulated_boundaries.append((points, tris, holes))
    return triangulated_boundaries


def boundarypslg(segments, args):
    Lx, Ly, Lz = args.domain_dimensions
    boundary_pslgs = build_boundary_PSLGs(segments, Lx, Ly, Lz)
    return triangulate_PSLGs(boundary_pslgs, args)
