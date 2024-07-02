# from sys import argv  # for benchmarking only
import logging
# import warnings
from functools import partial

from MDAnalysis.analysis.distances import self_distance_array
from MDAnalysis.transformations.wrap import wrap
import MDAnalysis as mda
import numpy as np

from scipy.spatial import ConvexHull
# from tqdm import tqdm
from tqdm.contrib.concurrent import process_map

# Local imports
from ..utilities.decorators import logger  # , timer
from ..utilities.universal_functions import extract_hull  # , _is_inside
from ..volume.monte_carlo import monte_carlo_volume
from ..settings import DEBUG, CPU_COUNT, TQDM_BAR_FORMAT, UNITS
from .utils import find_distance

logging.basicConfig(format='%(message)s')
np.seterr(invalid='ignore', divide='ignore')

"""
    Grid method for analyzing complex shaped structures
"""


class Mesh:
    """
        Class creates to create a mesh of points representing different molecule
        types of the system in a grid

        Attributes:
            traj (str): Path to any trajectory format supported by MDAnalysis package
            top (str): Path to any topology format supported by MDAnalysis package. Defaults to None
            rescale (int): Rescales the system down n times. Defaults to 1
    """

    def __init__(self, traj, top=None, rescale=1):
        self.grid_matrix = None
        self.u: mda.Universe = mda.Universe(top, traj) if top else mda.Universe(traj)
        self.ag = None
        self.dim = None
        self.mesh = None
        self.rescale = rescale
        self.interface_rescale = 1  # this is for calculating a rescaled interface then upscaling it
        self.length = self.u.trajectory.n_frames
        self.unique_resnames = None
        self.main_structure_selection = ''
        self.volume_data = None

        self.interface_borders = None  # defined in calculate_interface method
        self.current_frame = 0

    def select_atoms(self, sel):
        """
        Method for selecting the atoms using MDAnalysis selections

        Args:
            sel (str): selection string

        """
        self.ag = self.u.select_atoms(sel)
        self.unique_resnames = np.unique(self.ag.resnames)
        print('Wrapping trajectory...')
        transform = wrap(self.ag)
        self.u.trajectory.add_transformations(transform)

    def select_structure(self, selection):
        """
        Use this method to select the structure for density calculations. Enter 1 or more resnames
        :param selection: selection(s) of the main structure
        :return: None
        """
        self.main_structure_selection = selection

    def _get_int_dim(self):
        """
        Utility function to get box dimensions

        Returns:
            Dimensions of the box as an int
        """
        return int(np.ceil(self.u.dimensions[0]))

    @logger(DEBUG)
    def calculate_volume(self):
        """
        Returns the volume of the selected structure

        Returns:
            float: Volume of the structure
        """
        logging.log('Calculating the volume of the selected structure')
        hull_volumes = np.zeros(len(self.u.trajectory))

        for ts in self.u.trajectory:
            hull_volumes[ts.frame] = self._create_hull().volume

        self.volume_data = hull_volumes

    @staticmethod
    def make_grid(pbc_dim: int, dim=1, d4=None) -> np.ndarray:
        """
        Returns a 4D matrix

        Args:
             pbc_dim (int): Dimensions of the box
             dim (int): Dimensions of the box
             d4 (int): Returns an 4-D matrix if d4 is given. 4th dimension contains d4 elements
        """

        x = y = z = pbc_dim // dim + 1
        grid_matrix = np.zeros((x, y, z)) if d4 is None else np.zeros((x, y, z, d4))

        return grid_matrix

    @staticmethod
    def check_cube(x: float, y: float, z: float) -> tuple:
        """
        Find to which cube does the atom belong to
        Args:
            x (float): x coordinate
            y (float): y coordinate
            z (float): z coordinate

        Returns:
            tuple: Coordinates of the node inside the grid where the point belongs
        """

        n_x = int(x)
        n_y = int(y)
        n_z = int(z)

        return n_x, n_y, n_z

    @staticmethod
    def make_coordinates(mesh):
        """
        Converts the mesh to coordinates
        Args:
            mesh (np.ndarray):  Mesh to convert into 3D coordinates

        Returns:
            np.ndarray: Ndarray of tuples representing coordinates of each of the points in the mesh
        """

        coords = []
        for i, mat in enumerate(mesh):
            for j, col in enumerate(mat):
                for k, elem in enumerate(col):
                    if elem > 0:
                        coords.append((i, j, k))

        return np.array(coords, dtype=int)

    def find_min_dist(self):
        """
        Estimate rescale factor.
        Get rid of this.
        Returns:

        """
        return int(np.ceil(self_distance_array(self.ag.positions).min()))

    def _calc_mesh(self, grid_dim, selection):
        """
        Calculates the mesh according the atom positions in the box

        Args:
            grid_dim (int): Box dimensions

        Returns:
            np.ndarray: The grid
        """
        atom_group = self.u.select_atoms(selection)
        grid_matrix = self.make_grid(grid_dim)

        for atom in atom_group:
            x, y, z = self.check_cube(*atom.position)
            grid_matrix[x, y, z] += 1

        return grid_matrix

    # @logger(DEBUG)
    def calculate_mesh(self, selection, main_structure=False):
        """
        Calculates the mesh using _calc_mesh method
        Args:
            selection (str): Selection for atom group to calculate mesh
            main_structure (bool): use as the main structure if true (e.g. densities are calculated relative to this)
        Returns:
            np.ndarray: Returns the grid matrix
        """
        # define the matrices

        grid_matrix = self._calc_mesh(self._get_int_dim(), selection)  # !TODO _get_int_dim փոխի

        if main_structure:  # if selection is None, then it's the main structure
            self.grid_matrix = grid_matrix

        return grid_matrix

    # @logger(DEBUG)

    def _calculate_density_grid(self, coords, bin_count):
        # Works on a cubic box. !TODO Generalize later
        self.u.trajectory[self.current_frame]  # Set the frame to the current frame. Must be a better way...

        coords = np.array(coords)
        density_grid = np.zeros((bin_count, bin_count, bin_count))

        edges, step = np.linspace(0, self._get_int_dim(), bin_count + 1, retstep=True)
        grid_cell_volume = step ** 3

        # y_edges = np.linspace(0, self._get_int_dim(), bin_count + 1)
        # z_edges = np.linspace(0, self._get_int_dim(), bin_count + 1)

        for x, y, z in coords:
            x_idx = np.digitize(x, edges) - 1
            y_idx = np.digitize(y, edges) - 1
            z_idx = np.digitize(z, edges) - 1

            density_grid[x_idx, y_idx, z_idx] += 1

        density_grid /= grid_cell_volume

        return density_grid

    def _grid_centers(self, hull, bin_count):
        edges, step = np.linspace(0, self._get_int_dim(), bin_count + 1, retstep=True)
        x_centers = (edges[:-1] + edges[1:]) / 2
        y_centers = (edges[:-1] + edges[1:]) / 2
        z_centers = (edges[:-1] + edges[1:]) / 2
        x_grid, y_grid, z_grid = np.meshgrid(x_centers, y_centers, z_centers, indexing='ij')

        return np.vstack([x_grid.ravel(), y_grid.ravel(), z_grid.ravel()]).T

    def _normalize_density(self, coords, bin_count):
        density_grid = self._calculate_density_grid(coords, bin_count)
        density_grid = density_grid.flatten()

        return density_grid

    def _extract_from_mesh(self, mol_type):
        if mol_type not in self.unique_resnames:
            raise ValueError(
                f'Molecule type "{mol_type}" is not present in the system. Available types: {self.unique_resnames}'
            )

        mol_index = np.where(self.unique_resnames == mol_type)

        return self.grid_matrix[:, :, :, mol_index]

    def _create_hull(self):

        mesh = self.calculate_mesh(selection=self.main_structure_selection, main_structure=True)

        mesh_coords = self.make_coordinates(mesh[:, :, :])
        mesh_coordinates = np.array(mesh_coords)

        try:
            return ConvexHull(mesh_coordinates)  # , qhull_options='Q0')
        except IndexError as _:
            logging.warning(
                f'Cannot construct the hull at frame {self.current_frame}: one of your selections might be empty')
            return

    def _calc_dens_mp(self, frame_num, selection, norm_bin_count):
        """
        Calculates the density of selection from interface. Multiprocessing version

        Args:
            frame_num (int): Number of the frame
            selection (str): Selection of the atom group density of which is to be calculated
            ratio (float): Ratio moltype/water !TODO for testing. Remove later
        Returns:
            tuple: Density array and corresponding distances
        """
        self.current_frame = frame_num
        self.u.trajectory[self.current_frame]

        selection_coords = self.u.select_atoms(selection).positions  # self.make_coordinates(selection_mesh)

        hull = self._create_hull()

        grid_centers = self._grid_centers(hull, bin_count=norm_bin_count)

        distances = np.array(
            find_distance(hull, grid_centers)
        )  # Calculate distances from the interface to each grid cell
        densities = self._normalize_density(
            selection_coords,
            bin_count=norm_bin_count
        )  # Calculate the density of each cell

        indices = np.argsort(distances)
        distances = distances[indices]
        densities = densities[indices]

        return distances, densities

    # @timer
    def calculate_density(self, selection=None, start=0, skip=1, end=None,
                          norm_bin_count=20, cpu_count=CPU_COUNT):
        """
        Calculates density of selection from the interface
        :param end: Final frame
        :param norm_bin_count: Bin count for normalization
        :param cpu_count: Number of cores to use
        :param selection: MDAnalysis selection of ag
        :param interface_selection: Selection of what is considered as interface
        :param start: Starting frame
        :param skip: Skip every n-th frame
        :return:
        """
        n_frames = self.u.trajectory.n_frames if end is None else end

        dens_per_frame = partial(self._calc_dens_mp,
                                 selection=selection,
                                 norm_bin_count=norm_bin_count)  # _calc_dens_mp function with filled selection using partial
        frame_range = range(start, n_frames, skip)

        # with Pool(cpu_count) as worker_pool:
        #     res = worker_pool.map(dens_per_frame, frame_range)
        print(f'Running density calculation for the following atom group: {selection}')
        res = process_map(dens_per_frame, frame_range,
                          max_workers=cpu_count,
                          bar_format=TQDM_BAR_FORMAT
                          )

        res = np.array(res)

        distances, densities = self._process_result(res)

        # Simply taking the mean might not be the best option
        # distances = distances.mean(axis=0)
        # densities = densities.mean(axis=0)

        return distances, densities

    @staticmethod
    def _process_result(res):
        """ Helper method to correctly calculate the average of the result """
        distances = res[:, 0]
        densities = res[:, 1]
        dim_1, dim_2 = distances.shape
        offset = 50  # an offset to shift the distances to correct positions

        offset_distances = np.zeros((dim_1, dim_2 + offset))
        offset_densities = np.zeros((dim_1, dim_2 + offset))
        for i, arr in enumerate(distances):
            minim = abs(int(arr[0]))

            offset_distances[i, offset - minim:dim_2 + (offset - minim)] = arr
            offset_densities[i, offset - minim:dim_2 + (offset - minim)] = densities[i]

        # Trim zeros
        global_min = abs(int(distances.min()))

        final_distances = offset_distances[:, offset - global_min:dim_2 + (offset - global_min)]
        final_densities = offset_densities[:, offset - global_min:dim_2 + (offset - global_min)]

        final_distances = final_distances.mean(axis=0, where=final_distances != 0)
        final_densities = final_densities.mean(axis=0, where=final_distances != 0)

        return final_distances, final_densities


if __name__ == '__main__':
    pass
