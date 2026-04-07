"""
Generate 3D conformers for molecules.
"""
from rdkit import Chem
from rdkit.Chem import AllChem


def generate_3d_conformer(smiles: str) -> dict | None:
    """
    Generate a 3D conformer and return its properties.
    For visualization, we need atoms and an SDF string for 3Dmol.js.

    Tries multiple embedding strategies to handle unusual SELFIES-generated
    molecules with charged atoms that standard ETKDG can fail on.
    Falls back to a neutral sanitized version if needed.
    """
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None

    mol = Chem.AddHs(mol)

    # Strategy 1: standard ETKDGv3
    params = AllChem.ETKDGv3()
    params.randomSeed = 42
    result = AllChem.EmbedMolecule(mol, params)

    # Strategy 2: random coords as starting point (helps with strained/unusual structures)
    if result == -1:
        params2 = AllChem.ETKDGv3()
        params2.randomSeed = 42
        params2.useRandomCoords = True
        result = AllChem.EmbedMolecule(mol, params2)

    # Strategy 3: neutralize formal charges and retry (for heavily charged SELFIES molecules)
    if result == -1:
        try:
            neutral_smiles = _neutralize_smiles(smiles)
            if neutral_smiles and neutral_smiles != smiles:
                mol2 = Chem.MolFromSmiles(neutral_smiles)
                if mol2 is not None:
                    mol2 = Chem.AddHs(mol2)
                    params3 = AllChem.ETKDGv3()
                    params3.randomSeed = 42
                    params3.useRandomCoords = True
                    result = AllChem.EmbedMolecule(mol2, params3)
                    if result != -1:
                        mol = mol2
        except Exception:
            pass

    if result == -1:
        return None

    try:
        # MMFF optimization; fall back to UFF if MMFF fails (unusual atom types)
        ff_result = AllChem.MMFFOptimizeMolecule(mol, maxIters=500)
        if ff_result == -1:
            AllChem.UFFOptimizeMolecule(mol, maxIters=500)
    except Exception:
        pass

    try:
        sdf_block = Chem.MolToMolBlock(mol)
        return {"smiles": smiles, "sdf": sdf_block}
    except Exception:
        return None


def _neutralize_smiles(smiles: str) -> str | None:
    """
    Strip formal charges from a molecule to improve 3D embedding success.
    Returns canonical SMILES of the neutralized molecule, or None on failure.
    """
    try:
        from rdkit.Chem import rdmolops
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        rw = Chem.RWMol(mol)
        for atom in rw.GetAtoms():
            atom.SetFormalCharge(0)
        Chem.SanitizeMol(rw)
        return Chem.MolToSmiles(rw)
    except Exception:
        return None
