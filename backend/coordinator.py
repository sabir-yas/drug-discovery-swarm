"""
Orchestrates the swarm of agents across generations.
Implements the evolutionary loop:
  Generate → Score → Filter → Select → Mutate → Repeat
"""

import asyncio
import time
from typing import AsyncGenerator
import ray
import json
import redis
from config import *
from agents.explorer import ExplorerAgent
from agents.chemist import ChemistAgent
from agents.safety import SafetyAgent
from agents.selector import SelectorAgent
from chemistry.fingerprints import compute_umap_coordinates

class SwarmCoordinator:
    def __init__(self):
        import os
        # None = start a fresh local Ray instance (single-node dev mode)
        # Set RAY_ADDRESS env var on HPC to connect to an existing cluster
        ray_address = os.environ.get("RAY_ADDRESS") or None
        ray.init(address=ray_address, ignore_reinit_error=True)
        self.generation = 0
        self.all_molecules = []
        self.leaderboard = []
        self.is_running = False
        self.is_paused = False

        # Initialize agent pools as Ray actors
        self.explorers = [
            ExplorerAgent.remote() for _ in range(NUM_EXPLORER_AGENTS)
        ]
        self.chemists = [
            ChemistAgent.remote() for _ in range(NUM_CHEMIST_AGENTS)
        ]
        self.safety_agents = [
            SafetyAgent.remote() for _ in range(NUM_SAFETY_AGENTS)
        ]
        self.selector = SelectorAgent.remote()
        
        self.redis = redis.Redis()
        
        # Clear old events
        try:
            self.redis.delete("agent_events")
        except:
            pass

    def get_cluster_activity(self) -> list:
        """Get real-time activity for each Ray worker node."""
        try:
            nodes = ray.nodes()
        except:
            nodes = []
        activities = []
        
        # We also want to map agents to node to show in UI
        agent_reports = self._get_all_agent_reports()
        
        for node in nodes:
            node_id = node["NodeID"][:8]
            resources = node.get("Resources", {})
            resources_used = node.get("ResourcesUsed", {})
            cpu_total = resources.get("CPU", 1)  # Fallback to 1 to avoid div by zero
            cpu_used = resources_used.get("CPU", 0)

            node_agents = [a for a in agent_reports if a.get("node_id") == node_id]

            activities.append({
                "node_id": node_id,
                "hostname": node.get("NodeManagerHostname", "unknown"),
                "cpu_total": cpu_total,
                "cpu_used": cpu_used,
                "utilization": cpu_used / max(cpu_total, 1),
                "status": "active" if node.get("Alive") else "dead",
                "agents": node_agents,
            })
        return activities

    def _get_all_agent_reports(self) -> list:
        """Collect all active agent reports from Redis."""
        reports = []
        try:
            for key in self.redis.scan_iter("agent_activity:*"):
                data = self.redis.get(key)
                if data:
                    reports.append(json.loads(data))
        except:
            pass
        return reports

    def _get_agent_events(self) -> list:
        """Fetch latest agent chat events."""
        try:
            events = self.redis.xrevrange("agent_events", max="+", min="-", count=20)
            parsed_events = []
            for msg_id, data in events:
                parsed_events.append({
                    "agent_type": data.get(b"agent_type", b"").decode("utf-8"),
                    "agent_id": data.get(b"agent_id", b"").decode("utf-8"),
                    "event_type": data.get(b"event_type", b"").decode("utf-8"),
                    "message": data.get(b"message", b"").decode("utf-8"),
                    "timestamp": float(data.get(b"timestamp", 0))
                })
            return parsed_events[::-1]
        except:
            return []

    async def run(self) -> AsyncGenerator[dict, None]:
        """Run the evolutionary swarm loop, yielding results each generation."""
        self.is_running = True
        population = []

        for gen in range(MAX_GENERATIONS):
            if not self.is_running:
                break
            while self.is_paused:
                await asyncio.sleep(0.1)

            self.generation = gen
            start_time = time.time()

            # Assign generation tag so agents can reference it
            for m in population:
                m["generation"] = gen

            # === PHASE 1: Explorer Agents ===
            if gen == 0:
                mol_futures = [
                    explorer.generate_random.remote(MOLECULES_PER_GENERATION // NUM_EXPLORER_AGENTS)
                    for explorer in self.explorers
                ]
            else:
                mol_futures = [
                    explorer.generate_evolved.remote(
                        population,
                        MOLECULES_PER_GENERATION // NUM_EXPLORER_AGENTS,
                        MUTATION_RATE,
                        CROSSOVER_RATE,
                    )
                    for explorer in self.explorers
                ]

            mol_batches = await asyncio.gather(*[asyncio.wrap_future(f.future()) for f in mol_futures])
            candidates = [m for batch in mol_batches for m in batch if m]

            # Yield interim UI update for generation pipeline visualization
            yield {
                "type": "generation_update",
                "phase": "generating",
                "cluster_activity": self.get_cluster_activity(),
                "agent_events": self._get_agent_events()
            }

            # === PHASE 2: Chemist Agents ===
            chunk_size = max(1, len(candidates) // NUM_CHEMIST_AGENTS + 1)
            chunks = [candidates[i : i + chunk_size] for i in range(0, len(candidates), chunk_size)]
            
            # Match lengths
            chunks = chunks[:NUM_CHEMIST_AGENTS]
            while len(chunks) < NUM_CHEMIST_AGENTS:
                chunks.append([])

            score_futures = [
                chemist.predict_binding.remote(chunk)
                for chemist, chunk in zip(self.chemists, chunks)
            ]
            scored_batches = await asyncio.gather(*[asyncio.wrap_future(f.future()) for f in score_futures])
            scored = [m for batch in scored_batches for m in batch]

            yield {
                "type": "generation_update",
                "phase": "scoring",
                "cluster_activity": self.get_cluster_activity(),
                "agent_events": self._get_agent_events()
            }

            # === PHASE 3: Safety Agents ===
            safety_futures = [
                agent.check_toxicity.remote(scored[i::NUM_SAFETY_AGENTS])
                for i, agent in enumerate(self.safety_agents)
            ]
            safe_batches = await asyncio.gather(*[asyncio.wrap_future(f.future()) for f in safety_futures])
            safe_molecules = [m for batch in safe_batches for m in batch if not m["toxicity_flag"]]
            
            if not safe_molecules:
                # Give a lifeline if toxicity filters wiped everyone out
                safe_molecules = sorted(scored, key=lambda x: x["binding_score"], reverse=True)[:5]
                for m in safe_molecules:
                    m["fitness"] = m.get("fitness", 0)

            yield {
                "type": "generation_update",
                "phase": "filtering",
                "cluster_activity": self.get_cluster_activity(),
                "agent_events": self._get_agent_events()
            }

            # === PHASE 4: Selector Agent ===
            population = await asyncio.wrap_future(
                self.selector.select.remote(
                    safe_molecules, ELITE_FRACTION, TOURNAMENT_SIZE
                ).future()
            )

            # Compute UMAP coordinates for visualization
            umap_coords = compute_umap_coordinates(
                [m for m in self.all_molecules] + population
            )

            # Update global state
            for m in population:
                m["generation"] = gen

            self.all_molecules.extend(population)
            self.leaderboard = sorted(
                self.all_molecules, key=lambda m: m["fitness"], reverse=True
            )[:20]

            elapsed = time.time() - start_time

            # Yield full generation result
            yield {
                "type": "generation_complete",
                "generation": gen,
                "num_explored": len(candidates),
                "num_safe": len(safe_molecules),
                "num_selected": len(population),
                "best_fitness": population[0]["fitness"] if population else 0,
                "avg_fitness": (sum(m["fitness"] for m in population) / len(population) if population else 0),
                "elapsed_seconds": elapsed,
                "molecules": [
                    {
                        "id": m["id"],
                        "smiles": m["smiles"],
                        "fitness": m["fitness"],
                        "binding_score": m["binding_score"],
                        "drug_likeness": m["drug_likeness"],
                        "toxicity_flag": m["toxicity_flag"],
                        "umap_x": m.get("umap_x", 0),
                        "umap_y": m.get("umap_y", 0),
                        "umap_z": m.get("umap_z", 0),
                        "generation": gen,
                    }
                    for m in population
                ],
                "leaderboard": self.leaderboard[:10],
                "total_explored": len(self.all_molecules),
                "cluster_activity": self.get_cluster_activity(),
                "agent_events": self._get_agent_events(),
            }

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    def get_status(self):
        return {
            "generation": self.generation,
            "total_molecules": len(self.all_molecules),
            "is_running": self.is_running,
            "is_paused": self.is_paused,
        }

    def get_leaderboard(self):
        return self.leaderboard

    def get_molecule_3d(self, mol_id: str):
        for m in self.all_molecules:
            if m["id"] == mol_id:
                from chemistry.conformer import generate_3d_conformer
                return generate_3d_conformer(m["smiles"])
        return None
