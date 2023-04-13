# grid_project

Clone the project, go into its directory and install it using pip

```
pip install .
```

To use, import class Mesh from grid_project and create an instance by passing paths to trajectory and topology to it. The files can be in any format that MDAnalysis recognizes (https://docs.mdanalysis.org/stable/documentation_pages/coordinates/init.html#supported-coordinate-formats).

```python
from grid_project import Mesh

traj = <PATH_TO_TRAJECTORY>
top = <PATH_TO_TOPOLOGY>

mesh = Mesh(
    traj=traj,
    top=top,
    )
```

You need to define the interface by selecting atoms that the interface encloses. First select which atoms are being used in general, and after provide the residue names for the atoms inside of your structure. If multiple components are forming the structure, pass a list of their resnames.

```python

mesh.select_atoms('not type H')  # excluding hydrogen atoms from the trajectory
mesh.select_structure(['<RESNAME_OF_THE_INTERFACE_COMPONENT>'])
```

Finally, you can compute the density of some species using the calculate_density method. Your interface may differ from the structure (your structure can be a micelle, but the interface is the border between the hydrophobic and hydrophylic moieties of the components), so pass the interface to the calculate_density method.


```python

dens, dist = mesh.calculate_density(selection='resname TIP3', interface_selection='<INTERFACE_SELECTION>')  # Calculate water density

```

You can plot the results with matplotlib

```python
plt.plot(dist, dens, label='Water')
plt.show()
```

Volume of the structure can be calculated using calculate_volume method

```python
vol = mesh.calculate_volume()
```
