"""
🧬 Explorer Agent — Generates candidate molecules.
Generation 1: random valid molecules via SELFIES
Generation N: mutate + crossover from top performers
"""

import random
import uuid
import ray
import selfies as sf
from rdkit import Chem
from rdkit.Chem import Descriptors
from config import MIN_HEAVY_ATOMS, MAX_HEAVY_ATOMS, MAX_MOLECULAR_WEIGHT
import redis
import json

# Restrict to drug-like atoms only: C, N, O, F, P, S, Cl, Br, I (+ H implicit)
ALLOWED_ATOMIC_NUMS = {1, 6, 7, 8, 9, 15, 16, 17, 35, 53}

def _build_drug_tokens() -> list:
    """
    Filter SELFIES alphabet to tokens that only introduce drug-like, neutral atoms.
    Excludes any token that produces formal charges, radicals, or non-drug atoms.
    This ensures generated molecules are dockable by Vina/meeko.
    """
    tokens = []
    for tok in sf.get_semantic_robust_alphabet():
        # Keep structural tokens (Branch, Ring, epsilon) — they have no SMILES
        if not any(c.isalpha() or c in '[]' for c in tok.replace('[', '').replace(']', '')):
            tokens.append(tok)
            continue
        try:
            smi = sf.decoder(tok)
            if not smi:
                tokens.append(tok)  # structural token — keep
                continue
            mol = Chem.MolFromSmiles(smi)
            if mol is None:
                continue
            # Reject non-drug atoms
            atoms = {a.GetAtomicNum() for a in mol.GetAtoms()}
            if not atoms.issubset(ALLOWED_ATOMIC_NUMS):
                continue
            # Reject any formal charge
            if any(a.GetFormalCharge() != 0 for a in mol.GetAtoms()):
                continue
            # Reject radicals
            if any(a.GetNumRadicalElectrons() != 0 for a in mol.GetAtoms()):
                continue
            tokens.append(tok)
        except Exception:
            continue  # skip unknown tokens rather than keeping them
    return tokens or list(sf.get_semantic_robust_alphabet())[:50]

COMMON_TOKENS = _build_drug_tokens()

@ray.remote
class ExplorerAgent:
    def __init__(self):
        self.agent_id = str(uuid.uuid4())[:8]
        import os
        self.r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))

    def _report_activity(self, node_id: str, activity: str, detail: str):
        """Report current activity to coordinator via Redis."""
        self.r.setex(
            f"agent_activity:{self.agent_id}",
            5,  # expires in 5 seconds (auto-cleanup)
            json.dumps({
                "agent_id": self.agent_id,
                "agent_type": self.__class__.__name__,
                "activity": activity,
                "detail": detail,
                "node_id": node_id,
            })
        )

    def _emit_event(self, event_type: str, message: str):
        import time
        """Emit a log event for the frontend agent chat."""
        self.r.xadd("agent_events", {
            "agent_type": self.__class__.__name__,
            "agent_id": self.agent_id,
            "event_type": event_type,
            "message": message,
            "timestamp": time.time(),
        }, maxlen=200)

    def generate_random(self, count: int) -> list:
        """Generate random valid molecules."""
        node_id = ray.get_runtime_context().get_node_id()[:8]
        self._report_activity(node_id, "generating", f"Generating {count} random molecules")
        self._emit_event("generation", f"Generated {count} random candidates for initial pool")

        molecules = []
        attempts = 0
        max_attempts = count * 20

        while len(molecules) < count and attempts < max_attempts:
            attempts += 1
            length = random.randint(5, 25)
            tokens = [random.choice(COMMON_TOKENS) for _ in range(length)]
            selfies_str = "".join(tokens)

            mol_data = self._validate_and_build(selfies_str)
            if mol_data:
                molecules.append(mol_data)

        return molecules

    def generate_evolved(
        self,
        population: list,
        count: int,
        mutation_rate: float,
        crossover_rate: float,
        elite_seed_ids: list = None,
    ) -> list:
        """Generate molecules by mutating/crossing over the current population.

        elite_seed_ids: list of molecule IDs to bias crossover toward — these
        are crossed with random partners at 2x the normal rate to preserve
        promising scaffolds (e.g. a breakthrough Gen6 lineage).
        """
        node_id = ray.get_runtime_context().get_node_id()[:8]
        gen_label = population[0].get('generation', '?') if population else '?'
        self._report_activity(
            node_id,
            "generating",
            f"Evolving {count} molecules from Gen {gen_label}"
        )
        self._emit_event("generation", f"Generated {count} candidates from Gen {gen_label} elite pool")

        # Build fast lookup for seeded elites
        seed_set = set(elite_seed_ids or [])
        seed_pool = [m for m in population if m.get("id", "") in seed_set] or []

        molecules = []
        attempts = 0
        max_attempts = count * 20

        while len(molecules) < count and attempts < max_attempts:
            attempts += 1
            r_val = random.random()

            # Boost crossover for seeded elites: 20% extra chance when seed pool exists
            use_seed_crossover = seed_pool and r_val < 0.20

            if use_seed_crossover:
                seed_parent = random.choice(seed_pool)
                other = random.choice(population)
                child_selfies = self._crossover(seed_parent["selfies"], other["selfies"])
                self._emit_event("scaffold", f"Seeded crossover — preserving elite lineage {seed_parent['id'][:8]}")
            elif r_val < crossover_rate and len(population) >= 2:
                p1, p2 = random.sample(population, 2)
                child_selfies = self._crossover(p1["selfies"], p2["selfies"])
            elif r_val < crossover_rate + mutation_rate and population:
                parent = random.choice(population)
                child_selfies = self._mutate(parent["selfies"])
            else:
                length = random.randint(5, 25)
                tokens = [random.choice(COMMON_TOKENS) for _ in range(length)]
                child_selfies = "".join(tokens)

            mol_data = self._validate_and_build(child_selfies)
            if mol_data:
                molecules.append(mol_data)

        return molecules

    def _mutate(self, selfies_str: str) -> str:
        tokens = list(sf.split_selfies(selfies_str))
        if not tokens:
            return selfies_str

        mutation = random.choice(["substitute", "insert", "delete"])

        if mutation == "substitute" and tokens:
            idx = random.randint(0, len(tokens) - 1)
            tokens[idx] = random.choice(COMMON_TOKENS)
        elif mutation == "insert":
            idx = random.randint(0, len(tokens))
            tokens.insert(idx, random.choice(COMMON_TOKENS))
        elif mutation == "delete" and len(tokens) > 3:
            idx = random.randint(0, len(tokens) - 1)
            tokens.pop(idx)

        return "".join(tokens)

    def _crossover(self, s1: str, s2: str) -> str:
        tokens1 = list(sf.split_selfies(s1))
        tokens2 = list(sf.split_selfies(s2))

        if not tokens1 or not tokens2:
            return s1

        cut1 = random.randint(1, max(1, len(tokens1) - 1))
        cut2 = random.randint(1, max(1, len(tokens2) - 1))

        child_tokens = tokens1[:cut1] + tokens2[cut2:]
        return "".join(child_tokens)

    def _validate_and_build(self, selfies_str: str) -> dict | None:
        try:
            smiles = sf.decoder(selfies_str)
            if not smiles:
                return None

            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                return None

            heavy = mol.GetNumHeavyAtoms()
            if heavy < MIN_HEAVY_ATOMS or heavy > MAX_HEAVY_ATOMS:
                return None

            mw = Descriptors.MolWt(mol)
            if mw > MAX_MOLECULAR_WEIGHT:
                return None

            # Reject exotic atoms (anything outside drug-like set)
            atom_nums = {a.GetAtomicNum() for a in mol.GetAtoms()}
            if not atom_nums.issubset(ALLOWED_ATOMIC_NUMS):
                return None

            # Reject formally charged molecules — they score well heuristically but aren't drug-like
            total_charge = sum(a.GetFormalCharge() for a in mol.GetAtoms())
            if total_charge != 0:
                return None

            # Must contain at least one carbon
            if not any(a.GetAtomicNum() == 6 for a in mol.GetAtoms()):
                return None

            # Cap phosphorus atoms — >2 P atoms is a red flag for synthetically unrealistic structures
            p_count = sum(1 for a in mol.GetAtoms() if a.GetAtomicNum() == 15)
            if p_count > 2:
                return None

            # Reject C#P triple bonds (chemically exotic, not drug-like)
            from rdkit.Chem import rdMolDescriptors
            for bond in mol.GetBonds():
                if bond.GetBondTypeAsDouble() == 3.0:
                    a1, a2 = bond.GetBeginAtom().GetAtomicNum(), bond.GetEndAtom().GetAtomicNum()
                    if 15 in (a1, a2):  # triple bond to phosphorus
                        return None

            canonical_smiles = Chem.MolToSmiles(mol)

            return {
                "id": str(uuid.uuid4())[:12],
                "smiles": canonical_smiles,
                "selfies": selfies_str,
                "molecular_weight": mw,
                "heavy_atoms": heavy,
                "fitness": 0.0,
                "binding_score": 0.0,
                "drug_likeness": 0.0,
                "toxicity_flag": False,
                "generation": -1,
                "agent_id": self.agent_id,
            }
        except Exception:
            return None
