"""
Generate 3D conformers for molecules.
"""
from rdkit import Chem
from rdkit.Chem import AllChem

def generate_3d_conformer(smiles: str) -> dict | None:
    """
    Generate a 3D conformer and return its properties.
    For visualization, we typically need atoms and PDB/SDF string.
    """
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
        
    mol = Chem.AddHs(mol)
    try:
        AllChem.EmbedMolecule(mol, randomSeed=42)
        AllChem.MMFFOptimizeMolecule(mol)
        
        # Save as SDF block string for 3Dmol.js viewer
        sdf_block = Chem.MolToMolBlock(mol)
        return {
            "smiles": smiles,
            "sdf": sdf_block
        }
    except Exception:
        return None
