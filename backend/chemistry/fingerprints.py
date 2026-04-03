"""
Compute Morgan fingerprints and UMAP 3D coordinates for visualization.
"""

import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem
from umap import UMAP


def compute_morgan_fingerprint(smiles: str, radius: int = 2, n_bits: int = 1024):
    """Compute Morgan fingerprint as numpy array."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return np.zeros(n_bits)
    fp = AllChem.GetMorganFingerprintAsBitVect(mol, radius, nBits=n_bits)
    return np.array(fp)


def compute_umap_coordinates(molecules: list, n_components: int = 3) -> list:
    """
    Compute 3D UMAP coordinates for all molecules.
    Updates molecules in-place with umap_x, umap_y, umap_z.
    """
    if len(molecules) < 5:
        # Not enough for UMAP, assign random positions
        for m in molecules:
            m["umap_x"] = float(np.random.randn())
            m["umap_y"] = float(np.random.randn())
            m["umap_z"] = float(np.random.randn())
        return molecules

    # Compute fingerprints
    fps = np.array([
        compute_morgan_fingerprint(m["smiles"]) for m in molecules
    ])

    # Run UMAP to 3D
    reducer = UMAP(
        n_components=n_components,
        n_neighbors=min(15, len(molecules) - 1),
        min_dist=0.1,
        metric="jaccard",
        random_state=42,
    )
    
    try:
        embedding = reducer.fit_transform(fps)
        for i, m in enumerate(molecules):
            m["umap_x"] = float(embedding[i, 0])
            m["umap_y"] = float(embedding[i, 1])
            m["umap_z"] = float(embedding[i, 2])
    except Exception as e:
        # Fallback if UMAP fails
        for m in molecules:
            m["umap_x"] = float(np.random.randn())
            m["umap_y"] = float(np.random.randn())
            m["umap_z"] = float(np.random.randn())
            
    return molecules
