"""
Validates the swarm's top candidates against real pharmaceutical benchmarks.
Run while uvicorn is running: python validate_results.py
"""

import requests
from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolDescriptors, DataStructs
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams
from rdkit.Chem import AllChem

# Known COVID Mpro inhibitors for comparison
REFERENCE_DRUGS = {
    "Nirmatrelvir (Paxlovid)": "CC1(C2CC12NC(=O)C(F)(F)F)C(=O)NC(CC3CCNC3=O)C#N",
    "Ensitrelvir (Xocova)":    "Cc1nc(NC(=O)C2CC2)c(-c2ccc(Cl)cn2)c(-c2cnc(N)nc2F)n1",
}

def lipinski(mol):
    mw   = Descriptors.MolWt(mol)
    logp = Descriptors.MolLogP(mol)
    hbd  = rdMolDescriptors.CalcNumHBD(mol)
    hba  = rdMolDescriptors.CalcNumHBA(mol)
    violations = sum([mw > 500, logp > 5, hbd > 5, hba > 10])
    return dict(mw=mw, logp=logp, hbd=hbd, hba=hba,
                violations=violations, passes=violations <= 1)

def tanimoto(mol_a, mol_b):
    """Morgan fingerprint Tanimoto similarity (0=different, 1=identical)."""
    fp_a = AllChem.GetMorganFingerprintAsBitVect(mol_a, 2, nBits=2048)
    fp_b = AllChem.GetMorganFingerprintAsBitVect(mol_b, 2, nBits=2048)
    return DataStructs.TanimotoSimilarity(fp_a, fp_b)

def pains_check(mol):
    params = FilterCatalogParams()
    params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS)
    catalog = FilterCatalog(params)
    return not catalog.HasMatch(mol)  # True = clean

def validate():
    # Fetch leaderboard from running server
    try:
        r = requests.get("http://localhost:8000/api/leaderboard", timeout=5)
        candidates = r.json()[:10]
    except Exception as e:
        print(f"Could not reach server: {e}")
        print("Make sure uvicorn is running on port 8000.")
        return

    ref_mols = {}
    for name, smi in REFERENCE_DRUGS.items():
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            print(f"WARNING: Could not parse reference SMILES for {name}: {smi}")
        ref_mols[name] = mol

    print("\n" + "="*80)
    print("SWARM VALIDATION REPORT")
    print("="*80)

    # --- Reference drug properties ---
    print("\nREFERENCE DRUGS (ground truth)\n")
    print(f"{'Name':<28} {'MW':>6} {'LogP':>6} {'HBD':>4} {'HBA':>4} {'Violations':>10} {'PAINS':>6}")
    print("-"*70)
    for name, mol in ref_mols.items():
        if mol is None:
            print(f"{name:<28} [SMILES parse failed]")
            continue
        l = lipinski(mol)
        clean = pains_check(mol)
        print(f"{name:<28} {l['mw']:>6.1f} {l['logp']:>6.2f} {l['hbd']:>4} {l['hba']:>4} "
              f"{l['violations']:>10} {'PASS' if clean else 'FAIL':>6}")

    # --- Swarm top candidates ---
    print("\n\nSWARM TOP CANDIDATES\n")
    print(f"{'Rank':<5} {'Fitness':>8} {'MW':>6} {'LogP':>6} {'HBD':>4} {'HBA':>4} "
          f"{'Lipinski':>9} {'PAINS':>6} {'Sim/Nirm':>9} {'Sim/Ensi':>9}")
    print("-"*80)

    valid_count = 0
    novel_count = 0

    for i, mol_data in enumerate(candidates):
        mol = Chem.MolFromSmiles(mol_data["smiles"])
        if mol is None:
            print(f"#{i+1:>2}  [invalid SMILES]")
            continue

        l = lipinski(mol)
        clean = pains_check(mol)
        sims = {name: tanimoto(mol, ref_mol)
                for name, ref_mol in ref_mols.items()
                if ref_mol is not None}

        sim_values = list(sims.values())
        nirm_sim = sim_values[0] if len(sim_values) > 0 else None
        ensi_sim = sim_values[1] if len(sim_values) > 1 else None

        is_novel = all(s < 0.4 for s in sims.values()) if sims else True

        if l["passes"]:
            valid_count += 1
        if is_novel:
            novel_count += 1

        nirm_str = f"{nirm_sim:>9.3f}" if nirm_sim is not None else "     N/A"
        ensi_str = f"{ensi_sim:>9.3f}" if ensi_sim is not None else "     N/A"

        print(f"#{i+1:>2}  {mol_data['fitness']:>8.4f} {l['mw']:>6.1f} {l['logp']:>6.2f} "
              f"{l['hbd']:>4} {l['hba']:>4} "
              f"{'PASS' if l['passes'] else 'FAIL':>9} "
              f"{'PASS' if clean else 'FAIL':>6} "
              f"{nirm_str} {ensi_str}")

    n = len(candidates)
    print(f"\nSUMMARY")
    print(f"  Candidates evaluated : {n}")
    print(f"  Lipinski compliant   : {valid_count}/{n}  ({100*valid_count//n}%)")
    print(f"  PAINS-free           : {sum(pains_check(Chem.MolFromSmiles(m['smiles'])) for m in candidates if Chem.MolFromSmiles(m['smiles']))}/{n}")
    print(f"  Novel (Tanimoto<0.4) : {novel_count}/{n}  — structurally distinct from known drugs")
    print(f"\n  Tanimoto similarity: 0.0=completely different, 1.0=identical")
    print(f"  A good candidate is Lipinski-compliant, PAINS-free, and novel (<0.4 sim).")

    # --- SMILES export for external tools ---
    print(f"\n\nSMILES FOR EXTERNAL VALIDATION")
    print(f"  Paste these into https://www.swissadme.ch for full ADMET profiling\n")
    for i, m in enumerate(candidates[:5]):
        print(f"  #{i+1}: {m['smiles']}")

    print("\n" + "="*80)

if __name__ == "__main__":
    validate()
