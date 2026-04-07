"""
Real AutoDock Vina docking against SARS-CoV-2 Mpro (PDB: 6LU7).

Binding pocket defined by the co-crystallized N3 inhibitor.
Center: [-10.9, 15.5, 68.8], Box: 20x20x20 Angstroms.

Usage:
  score = dock_smiles("CC(=O)Nc1ccc(cc1)S(N)(=O)=O")
  # Returns normalized [0.0, 1.0] where 1.0 = -12 kcal/mol (very strong binding)
  # Returns None if receptor not prepared or docking fails
"""

import os
import tempfile
from rdkit import Chem
from rdkit.Chem import AllChem

# Receptor file lives in backend/data/
_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
RECEPTOR_PATH = os.path.join(_DATA_DIR, "6LU7_prepared.pdbqt")

# Mpro active site — catalytic dyad Cys145/His41
# Coordinates derived from N3 inhibitor centroid in 6LU7
MPRO_CENTER = [-10.9, 15.5, 68.8]
MPRO_BOX_SIZE = [20, 20, 20]


def _prepare_ligand_pdbqt(mol) -> str | None:
    """Convert an RDKit mol with 3D conformer to PDBQT using meeko.
    Supports both meeko >= 0.5 (new API) and older versions.
    """
    try:
        from meeko import MoleculePreparation
        preparator = MoleculePreparation()

        # meeko >= 0.5: prepare() returns a list of MoleculeSetup instances
        setups = preparator.prepare(mol)
        if setups:
            from meeko import PDBQTWriterLegacy
            pdbqt_string, is_ok, error_msg = PDBQTWriterLegacy.write_string(setups[0])
            if not is_ok:
                return None
            return pdbqt_string

        # meeko < 0.5 fallback
        pdbqt_string, is_ok, error_msg = preparator.write_pdbqt_string()
        if not is_ok:
            return None
        return pdbqt_string
    except Exception as e:
        return None


def _is_dockable(smiles: str) -> bool:
    """
    Quick pre-check: can meeko prepare this molecule for Vina?
    Filters out charged, radical, or otherwise problematic structures
    before spending time on conformer generation.
    """
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return False
        # Reject any formal charge
        if sum(a.GetFormalCharge() for a in mol.GetAtoms()) != 0:
            return False
        # Reject radicals
        if sum(a.GetNumRadicalElectrons() for a in mol.GetAtoms()) != 0:
            return False
        # Reject atoms meeko can't type: only C, N, O, F, S, Cl, Br, I, P allowed
        allowed = {6, 7, 8, 9, 15, 16, 17, 35, 53}
        if not {a.GetAtomicNum() for a in mol.GetAtoms()}.issubset(allowed):
            return False
        # Must have at least one carbon
        if not any(a.GetAtomicNum() == 6 for a in mol.GetAtoms()):
            return False
        return True
    except Exception:
        return False


def receptor_ready() -> bool:
    """Check if the prepared receptor PDBQT file exists."""
    return os.path.exists(RECEPTOR_PATH)


def dock_smiles(smiles: str, exhaustiveness: int = 4) -> float | None:
    """
    Dock a molecule against Mpro and return a normalized binding score.

    Args:
        smiles: SMILES string of the molecule
        exhaustiveness: Vina exhaustiveness (4 = fast/demo, 8 = production)

    Returns:
        float in [0.0, 1.0] where higher = stronger predicted binding
        None if receptor not found, conformer fails, or docking errors
    """
    if not receptor_ready():
        return None

    if not _is_dockable(smiles):
        return None

    try:
        from vina import Vina

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None

        mol = Chem.AddHs(mol)
        result = AllChem.EmbedMolecule(mol, randomSeed=42)
        if result == -1:
            # Try ETKDG fallback
            params = AllChem.ETKDGv3()
            params.randomSeed = 42
            result = AllChem.EmbedMolecule(mol, params)
            if result == -1:
                return None

        AllChem.MMFFOptimizeMolecule(mol)

        pdbqt = _prepare_ligand_pdbqt(mol)
        if pdbqt is None:
            return None

        v = Vina(sf_name="vina", verbosity=0)
        v.set_receptor(RECEPTOR_PATH)
        v.set_ligand_from_string(pdbqt)
        v.compute_vina_maps(center=MPRO_CENTER, box_size=MPRO_BOX_SIZE)
        v.dock(exhaustiveness=exhaustiveness, n_poses=1)

        best_affinity = v.energies()[0][0]  # kcal/mol, negative = better binding

        # Normalize to [0, 1]:
        # -12 kcal/mol → 1.0 (strong binder, comparable to known drugs)
        #   0 kcal/mol → 0.0 (no binding)
        # Clamp so positive affinities don't go negative
        normalized = min(1.0, max(0.0, -best_affinity / 12.0))
        return round(normalized, 4), round(best_affinity, 3)

    except Exception:
        return None
