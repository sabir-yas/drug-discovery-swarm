"""
🏆 Selector Agent — Evolutionary selection.
Maintains leaderboard and selects next generation via tournament selection.
"""

import random
import ray
import uuid
import json
import redis
from rdkit import Chem
from rdkit.Chem import AllChem, DataStructs

@ray.remote
class SelectorAgent:
    def __init__(self):
        self.agent_id = str(uuid.uuid4())[:8]
        import os
        self.r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))

    def _report_activity(self, node_id: str, activity: str, detail: str):
        self.r.setex(
            f"agent_activity:{self.agent_id}",
            5,
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
        self.r.xadd("agent_events", {
            "agent_type": self.__class__.__name__,
            "agent_id": self.agent_id,
            "event_type": event_type,
            "message": message,
            "timestamp": time.time(),
        }, maxlen=200)

    def select(
        self,
        population: list,
        elite_fraction: float,
        tournament_size: int,
    ) -> list:
        """Select the next generation using elitism + tournament selection."""
        node_id = ray.get_runtime_context().get_node_id()[:8]
        self._report_activity(node_id, "selecting", f"Selecting next gen from {len(population)} candidates")

        if not population:
            return []

        # Deduplicate by canonical SMILES — remove exact duplicates first
        seen_smiles = set()
        unique_pop = []
        for m in sorted(population, key=lambda m: m["fitness"], reverse=True):
            if m["smiles"] not in seen_smiles:
                seen_smiles.add(m["smiles"])
                unique_pop.append(m)
        sorted_pop = unique_pop

        pop_size = len(sorted_pop)
        num_elite = max(1, int(pop_size * elite_fraction))

        # Elites pass through unchanged
        next_gen = sorted_pop[:num_elite]

        # Precompute Morgan fingerprints for diversity scoring
        fps = {}
        for m in sorted_pop:
            try:
                mol = Chem.MolFromSmiles(m["smiles"])
                if mol:
                    fps[m["id"]] = AllChem.GetMorganFingerprintAsBitVect(mol, 2, nBits=1024)
            except Exception:
                pass

        selected_fps = [fps[m["id"]] for m in next_gen if m["id"] in fps]

        # Diversity-aware tournament selection for remaining slots
        remaining = pop_size - num_elite
        for _ in range(remaining):
            tournament = random.sample(sorted_pop, min(tournament_size, pop_size))
            best, best_score = None, -1.0
            for candidate in tournament:
                fp = fps.get(candidate["id"])
                if fp and selected_fps:
                    # Penalise molecules too similar to already-selected ones
                    max_sim = max(DataStructs.TanimotoSimilarity(fp, sfp) for sfp in selected_fps)
                    diversity_bonus = (1.0 - max_sim) * 0.15
                else:
                    diversity_bonus = 0.0
                score = candidate["fitness"] + diversity_bonus
                if score > best_score:
                    best_score = score
                    best = candidate
            if best:
                next_gen.append(best)
                if best["id"] in fps:
                    selected_fps.append(fps[best["id"]])

        # Emit events
        if next_gen:
            gen_idx = population[0].get('generation', '?') if population else '?'
            avg_fitness = sum(m["fitness"] for m in next_gen) / len(next_gen)
            self._emit_event("selection", f"Gen {gen_idx} complete — elite pool fitness: {avg_fitness:.3f} avg")
            
            top_candidate = next_gen[0]
            self._emit_event("leaderboard", f"New #1 candidate! Fitness {top_candidate['fitness']:.4f}")

        return next_gen
