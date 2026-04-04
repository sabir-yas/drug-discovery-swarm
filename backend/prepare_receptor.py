"""
One-time receptor preparation script for SARS-CoV-2 Mpro (PDB: 6LU7).

Run this ONCE before starting the swarm:
    cd backend
    python prepare_receptor.py

What it does:
  1. Downloads 6LU7.pdb from RCSB Protein Data Bank
  2. Strips water molecules and non-protein HETATM records
  3. Converts to PDBQT format (AutoDock Vina input) via openbabel
  4. Saves to backend/data/6LU7_prepared.pdbqt

Requirements:
    conda install -c conda-forge openbabel meeko -y
"""

import os
import sys
import urllib.request
import subprocess

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
RAW_PDB = os.path.join(DATA_DIR, "6LU7.pdb")
CLEAN_PDB = os.path.join(DATA_DIR, "6LU7_protein.pdb")
RECEPTOR_PDBQT = os.path.join(DATA_DIR, "6LU7_prepared.pdbqt")

RCSB_URL = "https://files.rcsb.org/download/6LU7.pdb"


def download_6lu7():
    print("Downloading 6LU7 from RCSB Protein Data Bank...")
    os.makedirs(DATA_DIR, exist_ok=True)
    urllib.request.urlretrieve(RCSB_URL, RAW_PDB)
    size_kb = os.path.getsize(RAW_PDB) // 1024
    print(f"  Downloaded: {RAW_PDB} ({size_kb} KB)")


def clean_pdb():
    """
    Strip water (HOH) and HETATM records — keep only protein ATOM records.
    6LU7 contains the N3 inhibitor as HETATM; we remove it so only apo
    protein remains for docking.
    """
    print("Cleaning PDB: removing water and ligands...")
    with open(RAW_PDB) as f:
        lines = f.readlines()

    protein_lines = [
        line for line in lines
        if line.startswith("ATOM") or line.startswith("TER") or line.startswith("END")
    ]

    with open(CLEAN_PDB, "w") as f:
        f.writelines(protein_lines)

    atom_count = sum(1 for l in protein_lines if l.startswith("ATOM"))
    print(f"  Kept {atom_count} protein atoms → {CLEAN_PDB}")


def convert_to_pdbqt():
    """
    Convert cleaned PDB to PDBQT using Open Babel.
    -xr flag tells obabel to treat as receptor (no rotatable bonds).
    """
    print("Converting to PDBQT with Open Babel...")
    result = subprocess.run(
        ["obabel", CLEAN_PDB, "-O", RECEPTOR_PDBQT, "-xr", "--partialcharge", "gasteiger"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not os.path.exists(RECEPTOR_PDBQT):
        print(f"  obabel failed: {result.stderr}")
        print("\nTrying without charge assignment...")
        result2 = subprocess.run(
            ["obabel", CLEAN_PDB, "-O", RECEPTOR_PDBQT, "-xr"],
            capture_output=True,
            text=True,
        )
        if result2.returncode != 0:
            print(f"  obabel failed again: {result2.stderr}")
            print("\nIs Open Babel installed? Try:")
            print("  conda install -c conda-forge openbabel -y")
            sys.exit(1)

    size_kb = os.path.getsize(RECEPTOR_PDBQT) // 1024
    print(f"  Receptor ready: {RECEPTOR_PDBQT} ({size_kb} KB)")


def verify_docking():
    """Quick sanity check — dock a known Mpro inhibitor (nirmatrelvir-like scaffold)."""
    print("\nVerifying docking pipeline with test molecule...")
    test_smiles = "CC(C)(C)C(=O)N[C@@H](CC1CCNC1=O)C(=O)N[C@@H](C#N)C2CC2"
    try:
        from chemistry.docking import dock_smiles
        result = dock_smiles(test_smiles, exhaustiveness=4)
        if result is not None:
            score, affinity = result
            print(f"  Test molecule docking score: {score:.3f} ({affinity:.1f} kcal/mol)")
            if affinity < -5.0:
                print("  Docking pipeline working correctly.")
            else:
                print("  Warning: affinity seems weak — check receptor prep.")
        else:
            print("  Docking returned None — check meeko installation.")
    except Exception as e:
        print(f"  Verification error: {e}")


if __name__ == "__main__":
    print("=" * 55)
    print("  Mpro Receptor Preparation (6LU7)")
    print("=" * 55)

    if os.path.exists(RECEPTOR_PDBQT):
        print(f"Receptor already prepared: {RECEPTOR_PDBQT}")
        print("Delete it and re-run to force re-preparation.")
        verify_docking()
        sys.exit(0)

    download_6lu7()
    clean_pdb()
    convert_to_pdbqt()
    verify_docking()

    print("\nDone! You can now set USE_REAL_DOCKING = True in config.py")
    print("and restart the swarm.\n")
