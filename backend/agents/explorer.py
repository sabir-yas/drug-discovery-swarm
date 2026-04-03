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

# Common SELFIES tokens for building molecules
SELFIES_ALPHABET = sf.get_semantic_robust_alphabet()
COMMON_TOKENS = list(SELFIES_ALPHABET)[:50]  # Use subset for speed

@ray.remote
class ExplorerAgent:
    def __init__(self):
        self.agent_id = str(uuid.uuid4())[:8]
        self.r = redis.Redis()

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
    ) -> list:
        """Generate molecules by mutating/crossing over the current population."""
        node_id = ray.get_runtime_context().get_node_id()[:8]
        gen_label = population[0].get('generation', '?') if population else '?'
        self._report_activity(
            node_id,
            "generating",
            f"Evolving {count} molecules from Gen {gen_label}"
        )
        self._emit_event("generation", f"Generated {count} candidates from Gen {gen_label} elite pool")

        molecules = []
        attempts = 0
        max_attempts = count * 20

        while len(molecules) < count and attempts < max_attempts:
            attempts += 1
            r_val = random.random()

            if r_val < crossover_rate and len(population) >= 2:
                # Crossover: combine two parents
                p1, p2 = random.sample(population, 2)
                child_selfies = self._crossover(p1["selfies"], p2["selfies"])
            elif r_val < crossover_rate + mutation_rate and population:
                # Mutation: modify a parent
                parent = random.choice(population)
                child_selfies = self._mutate(parent["selfies"])
            else:
                # Fresh random
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
