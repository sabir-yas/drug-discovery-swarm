"""
Offline validation: dock top swarm candidates against Mpro (6LU7) with AutoDock Vina.

Run this after a swarm session to get real binding affinities for the leaderboard.
Results are saved to vina_validation.json for demo presentation.

Usage:
    cd backend
    python validate_with_vina.py              # reads leaderboard.json
    python validate_with_vina.py --smiles "CC(=O)Nc1ccc(cc1)Cl"   # single molecule

Requirements:
    1. Run prepare_receptor.py first
    2. conda install -c conda-forge meeko -y
"""

import json
import argparse
import sys
import os
from chemistry.docking import dock_smiles, receptor_ready, RECEPTOR_PATH

# Reference drugs for comparison (known Mpro inhibitors)
REFERENCE_MOLECULES = {
    "Nirmatrelvir (Paxlovid)": "CC1(C2CC2NC(=O)[C@@H]3C[C@@H]3F)CC(=O)N1C[C@@H](O)C(=O)N[C@@H](C#N)C(C)(C)C",
    "Ensitrelvir":             "Cc1nc2c(Cl)cccc2n1-c1cc(NC(=O)C2CC2)c(F)cc1F",
    "GC376 (calpain inh.)":    "O=C(COc1ccccc1)N[C@@H](CC(=O)N[C@@H](Cc1ccccc1)C=O)C(=O)O",
}


def dock_one(smiles: str, label: str, exhaustiveness: int = 8) -> dict:
    """Dock a single molecule and return result dict."""
    print(f"  Docking {label}...", end=" ", flush=True)
    result = dock_smiles(smiles, exhaustiveness=exhaustiveness)
    if result is not None:
        score, affinity = result
        print(f"{affinity:.2f} kcal/mol (score: {score:.3f})")
        return {
            "label": label,
            "smiles": smiles,
            "vina_affinity_kcal": affinity,
            "normalized_score": score,
            "status": "ok",
        }
    else:
        print("FAILED")
        return {
            "label": label,
            "smiles": smiles,
            "vina_affinity_kcal": None,
            "normalized_score": None,
            "status": "failed",
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smiles", help="Dock a single SMILES string")
    parser.add_argument("--exhaustiveness", type=int, default=8,
                        help="Vina exhaustiveness (default 8 for validation)")
    parser.add_argument("--top-n", type=int, default=10,
                        help="How many leaderboard candidates to dock")
    args = parser.parse_args()

    print("=" * 60)
    print("  AutoDock Vina Validation — Mpro (6LU7)")
    print("=" * 60)

    if not receptor_ready():
        print(f"\nERROR: Receptor not found at {RECEPTOR_PATH}")
        print("Run first:  python prepare_receptor.py")
        sys.exit(1)

    print(f"Receptor: {RECEPTOR_PATH}")
    print(f"Exhaustiveness: {args.exhaustiveness}")
    print()

    results = []

    # Single molecule mode
    if args.smiles:
        result = dock_one(args.smiles, "custom", args.exhaustiveness)
        print(json.dumps(result, indent=2))
        return

    # Reference drugs baseline
    print("--- Reference Drugs (baseline) ---")
    ref_results = []
    for name, smi in REFERENCE_MOLECULES.items():
        r = dock_one(smi, name, args.exhaustiveness)
        ref_results.append(r)
    print()

    # Top swarm candidates
    leaderboard_path = os.path.join(os.path.dirname(__file__), "leaderboard.json")
    if not os.path.exists(leaderboard_path):
        print(f"No leaderboard.json found at {leaderboard_path}")
        print("Run the swarm first, or it will be created automatically.")
        candidates = []
    else:
        with open(leaderboard_path) as f:
            candidates = json.load(f)
        print(f"--- Top {args.top_n} Swarm Candidates ---")
        for i, mol in enumerate(candidates[:args.top_n]):
            label = f"Swarm #{i+1} (fitness={mol.get('fitness', '?'):.3f})"
            r = dock_one(mol["smiles"], label, args.exhaustiveness)
            r["swarm_fitness"] = mol.get("fitness")
            r["swarm_id"] = mol.get("id")
            results.append(r)

    print()

    # Summary table
    all_results = ref_results + results
    docked = [r for r in all_results if r["vina_affinity_kcal"] is not None]

    if docked:
        print("--- Summary ---")
        print(f"{'Molecule':<35} {'Affinity (kcal/mol)':>20} {'Score':>8}")
        print("-" * 65)
        for r in sorted(docked, key=lambda x: x["vina_affinity_kcal"]):
            label = r["label"][:34]
            print(f"{label:<35} {r['vina_affinity_kcal']:>20.2f} {r['normalized_score']:>8.3f}")

        # Check if any swarm candidate beats references
        ref_affinities = [r["vina_affinity_kcal"] for r in ref_results if r["vina_affinity_kcal"]]
        swarm_affinities = [r["vina_affinity_kcal"] for r in results if r["vina_affinity_kcal"]]
        if ref_affinities and swarm_affinities:
            best_ref = min(ref_affinities)
            best_swarm = min(swarm_affinities)
            print()
            if best_swarm < best_ref:
                print(f"RESULT: Swarm found a candidate ({best_swarm:.2f}) stronger than references ({best_ref:.2f})!")
            else:
                diff = best_swarm - best_ref
                print(f"RESULT: Best swarm candidate is {diff:.2f} kcal/mol weaker than reference drugs.")
                print("        (Expected — swarm used heuristic scoring, not real docking during evolution)")

    # Save results
    output = {
        "reference_drugs": ref_results,
        "swarm_candidates": results,
        "receptor": RECEPTOR_PATH,
        "exhaustiveness": args.exhaustiveness,
    }
    out_path = os.path.join(os.path.dirname(__file__), "vina_validation.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
