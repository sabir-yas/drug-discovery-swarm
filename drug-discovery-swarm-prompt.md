# AI Drug Discovery Swarm — Full Implementation Plan

## Project Overview

Build a distributed AI drug discovery system where a **swarm of specialized agents** explores chemical space to find molecules that bind to a target protein. The system runs on an HPC cluster (backend) with a real-time 3D web frontend.

**Target protein**: COVID-19 Main Protease (Mpro/3CLpro) — PDB ID `6LU7`
This is well-studied with known inhibitors we can validate against.

---

## Architecture

```
HPC Cluster (Python Backend)
├── Coordinator (FastAPI + Redis)
│   ├── 🧬 Explorer Agents — generate candidate molecules (SELFIES)
│   ├── 🔬 Chemist Agents — predict binding affinity (RDKit + Vina)
│   ├── ⚠️ Safety Agents — check toxicity (Lipinski + QSAR)
│   └── 🏆 Selector Agent — evolutionary selection + leaderboard
│
WebSocket Bridge (real-time streaming)
│
Frontend (React + TypeScript)
├── UMAP Chemical Space (Three.js point cloud — HERO VISUAL)
├── 3D Molecule Viewer (3Dmol.js)
├── Generation Timeline + Fitness Graph (Recharts)
├── Agent Activity Feed (real-time)
└── Top Candidates Leaderboard
```

---

## Part 1: Backend (Python)

### Directory Structure

```
backend/
├── main.py                  # FastAPI app + WebSocket endpoint
├── coordinator.py           # Orchestrates generations + agents
├── agents/
│   ├── explorer.py          # Molecule generation agent
│   ├── chemist.py           # Binding prediction agent
│   ├── safety.py            # Toxicity checking agent
│   └── selector.py          # Evolutionary selection agent
├── chemistry/
│   ├── molecule.py          # Molecule dataclass + utils
│   ├── scoring.py           # Scoring functions
│   ├── fingerprints.py      # Morgan fingerprints + UMAP
│   └── conformer.py         # 3D conformer generation
├── config.py                # All hyperparameters
├── requirements.txt
└── run_cluster.py           # Ray cluster launcher
```

### requirements.txt

```
fastapi==0.104.1
uvicorn==0.24.0
websockets==12.0
redis==5.0.1
ray==2.9.0
rdkit-pypi==2023.9.4
selfies==2.1.1
umap-learn==0.5.5
numpy==1.26.2
scipy==1.11.4
scikit-learn==1.3.2
aiofiles==23.2.1
pydantic==2.5.2
```

### config.py

```python
"""All tunable hyperparameters in one place."""

# Swarm config
NUM_EXPLORER_AGENTS = 10
NUM_CHEMIST_AGENTS = 8
NUM_SAFETY_AGENTS = 4
MOLECULES_PER_GENERATION = 200
MAX_GENERATIONS = 50

# Evolutionary config
ELITE_FRACTION = 0.1          # top 10% survive unchanged
MUTATION_RATE = 0.3
CROSSOVER_RATE = 0.5
TOURNAMENT_SIZE = 5

# Molecule constraints
MIN_HEAVY_ATOMS = 10
MAX_HEAVY_ATOMS = 50
MAX_MOLECULAR_WEIGHT = 500.0

# Scoring weights (for composite fitness)
BINDING_WEIGHT = 0.5
DRUG_LIKENESS_WEIGHT = 0.3
TOXICITY_PENALTY_WEIGHT = 0.2

# Server
WEBSOCKET_BROADCAST_INTERVAL = 0.5  # seconds
REDIS_URL = "redis://localhost:6379"
```

### main.py — FastAPI + WebSocket

```python
"""
FastAPI server with WebSocket for real-time streaming to frontend.
Run: uvicorn main:app --host 0.0.0.0 --port 8000
"""

import asyncio
import json
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from coordinator import SwarmCoordinator

app = FastAPI(title="Drug Discovery Swarm")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

coordinator = SwarmCoordinator()
connected_clients: List[WebSocket] = []


async def broadcast(data: dict):
    """Send data to all connected frontend clients."""
    message = json.dumps(data)
    disconnected = []
    for ws in connected_clients:
        try:
            await ws.send_text(message)
        except:
            disconnected.append(ws)
    for ws in disconnected:
        connected_clients.remove(ws)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            # Listen for commands from frontend (start, pause, config changes)
            data = await websocket.receive_text()
            command = json.loads(data)
            if command.get("action") == "start":
                asyncio.create_task(run_swarm())
            elif command.get("action") == "pause":
                coordinator.pause()
            elif command.get("action") == "resume":
                coordinator.resume()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


async def run_swarm():
    """Main swarm loop — runs generations and broadcasts results."""
    async for generation_result in coordinator.run():
        await broadcast(generation_result)


@app.get("/api/status")
async def get_status():
    return coordinator.get_status()


@app.get("/api/molecule/{mol_id}")
async def get_molecule_3d(mol_id: str):
    """Return 3D conformer data for a specific molecule."""
    return coordinator.get_molecule_3d(mol_id)


@app.get("/api/leaderboard")
async def get_leaderboard():
    return coordinator.get_leaderboard()
```

### coordinator.py — Swarm Orchestrator

```python
"""
Orchestrates the swarm of agents across generations.
Implements the evolutionary loop:
  Generate → Score → Filter → Select → Mutate → Repeat
"""

import asyncio
import uuid
import time
from typing import AsyncGenerator
import ray
from config import *
from agents.explorer import ExplorerAgent
from agents.chemist import ChemistAgent
from agents.safety import SafetyAgent
from agents.selector import SelectorAgent
from chemistry.fingerprints import compute_umap_coordinates


class SwarmCoordinator:
    def __init__(self):
        ray.init(ignore_reinit_error=True)
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

            # === PHASE 1: Explorer Agents generate molecules ===
            if gen == 0:
                # Random initial population
                mol_futures = [
                    explorer.generate_random.remote(
                        MOLECULES_PER_GENERATION // NUM_EXPLORER_AGENTS
                    )
                    for explorer in self.explorers
                ]
            else:
                # Evolve from previous generation
                mol_futures = [
                    explorer.generate_evolved.remote(
                        population,
                        MOLECULES_PER_GENERATION // NUM_EXPLORER_AGENTS,
                        MUTATION_RATE,
                        CROSSOVER_RATE,
                    )
                    for explorer in self.explorers
                ]

            # Gather generated molecules (parallel across agents)
            mol_batches = await asyncio.gather(
                *[asyncio.wrap_future(f.future()) for f in mol_futures]
            )
            candidates = [m for batch in mol_batches for m in batch]

            # === PHASE 2: Chemist Agents score binding ===
            chunk_size = len(candidates) // NUM_CHEMIST_AGENTS + 1
            chunks = [
                candidates[i : i + chunk_size]
                for i in range(0, len(candidates), chunk_size)
            ]
            score_futures = [
                chemist.predict_binding.remote(chunk)
                for chemist, chunk in zip(self.chemists, chunks)
            ]
            scored_batches = await asyncio.gather(
                *[asyncio.wrap_future(f.future()) for f in score_futures]
            )
            scored = [m for batch in scored_batches for m in batch]

            # === PHASE 3: Safety Agents filter ===
            safety_futures = [
                agent.check_toxicity.remote(scored[i::NUM_SAFETY_AGENTS])
                for i, agent in enumerate(self.safety_agents)
            ]
            safe_batches = await asyncio.gather(
                *[asyncio.wrap_future(f.future()) for f in safety_futures]
            )
            safe_molecules = [m for batch in safe_batches for m in batch]

            # === PHASE 4: Selector Agent ranks + selects ===
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
            self.all_molecules.extend(population)
            self.leaderboard = sorted(
                self.all_molecules, key=lambda m: m["fitness"], reverse=True
            )[:20]

            elapsed = time.time() - start_time

            # Yield generation result for WebSocket broadcast
            yield {
                "type": "generation_complete",
                "generation": gen,
                "num_explored": len(candidates),
                "num_safe": len(safe_molecules),
                "num_selected": len(population),
                "best_fitness": population[0]["fitness"] if population else 0,
                "avg_fitness": (
                    sum(m["fitness"] for m in population) / len(population)
                    if population
                    else 0
                ),
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
                "agent_activity": {
                    "explorers_active": NUM_EXPLORER_AGENTS,
                    "chemists_active": NUM_CHEMIST_AGENTS,
                    "safety_active": NUM_SAFETY_AGENTS,
                },
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
```

### agents/explorer.py

```python
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


# Common SELFIES tokens for building molecules
SELFIES_ALPHABET = sf.get_semantic_robust_alphabet()
COMMON_TOKENS = list(SELFIES_ALPHABET)[:50]  # Use subset for speed


@ray.remote
class ExplorerAgent:
    def __init__(self):
        self.agent_id = str(uuid.uuid4())[:8]

    def generate_random(self, count: int) -> list:
        """Generate random valid molecules."""
        molecules = []
        attempts = 0
        max_attempts = count * 20

        while len(molecules) < count and attempts < max_attempts:
            attempts += 1
            # Random SELFIES string
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
        molecules = []
        attempts = 0
        max_attempts = count * 20

        while len(molecules) < count and attempts < max_attempts:
            attempts += 1
            r = random.random()

            if r < crossover_rate and len(population) >= 2:
                # Crossover: combine two parents
                p1, p2 = random.sample(population, 2)
                child_selfies = self._crossover(p1["selfies"], p2["selfies"])
            elif r < crossover_rate + mutation_rate:
                # Mutation: modify a parent
                parent = random.choice(population)
                child_selfies = self._mutate(parent["selfies"])
            else:
                # Fresh random (maintains diversity)
                length = random.randint(5, 25)
                tokens = [random.choice(COMMON_TOKENS) for _ in range(length)]
                child_selfies = "".join(tokens)

            mol_data = self._validate_and_build(child_selfies)
            if mol_data:
                molecules.append(mol_data)

        return molecules

    def _mutate(self, selfies_str: str) -> str:
        """Point mutation on SELFIES tokens."""
        tokens = list(sf.split_selfies(selfies_str))
        if not tokens:
            return selfies_str

        # Random mutation type
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
        """Single-point crossover between two SELFIES strings."""
        tokens1 = list(sf.split_selfies(s1))
        tokens2 = list(sf.split_selfies(s2))

        if not tokens1 or not tokens2:
            return s1

        cut1 = random.randint(1, max(1, len(tokens1) - 1))
        cut2 = random.randint(1, max(1, len(tokens2) - 1))

        child_tokens = tokens1[:cut1] + tokens2[cut2:]
        return "".join(child_tokens)

    def _validate_and_build(self, selfies_str: str) -> dict | None:
        """Convert SELFIES to SMILES, validate, return molecule data or None."""
        try:
            smiles = sf.decoder(selfies_str)
            if not smiles:
                return None

            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                return None

            # Check constraints
            heavy = mol.GetNumHeavyAtoms()
            if heavy < MIN_HEAVY_ATOMS or heavy > MAX_HEAVY_ATOMS:
                return None

            mw = Descriptors.MolWt(mol)
            if mw > MAX_MOLECULAR_WEIGHT:
                return None

            # Canonicalize
            canonical_smiles = Chem.MolToSmiles(mol)

            return {
                "id": str(uuid.uuid4())[:12],
                "smiles": canonical_smiles,
                "selfies": selfies_str,
                "molecular_weight": mw,
                "heavy_atoms": heavy,
                "fitness": 0.0,  # Will be scored by Chemist
                "binding_score": 0.0,
                "drug_likeness": 0.0,
                "toxicity_flag": False,
                "generation": -1,  # Set by coordinator
                "agent_id": self.agent_id,
            }
        except Exception:
            return None
```

### agents/chemist.py

```python
"""
🔬 Chemist Agent — Predicts binding affinity.
Uses RDKit descriptors as a fast proxy scorer.
For hackathon: a composite score based on molecular properties
known to correlate with binding to protease targets.
Upgrade path: swap in AutoDock Vina or a pretrained GNN.
"""

import ray
import uuid
import numpy as np
from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolDescriptors, Crippen


@ray.remote
class ChemistAgent:
    def __init__(self):
        self.agent_id = str(uuid.uuid4())[:8]

    def predict_binding(self, molecules: list) -> list:
        """Score binding affinity for a batch of molecules."""
        for mol_data in molecules:
            try:
                mol = Chem.MolFromSmiles(mol_data["smiles"])
                if mol is None:
                    mol_data["binding_score"] = 0.0
                    continue

                # === Fast binding proxy score ===
                # Based on properties that correlate with protease inhibitor activity

                # LogP — ideal range 1-3 for oral drugs
                logp = Crippen.MolLogP(mol)
                logp_score = 1.0 - min(abs(logp - 2.0) / 3.0, 1.0)

                # HBD/HBA — hydrogen bond donors/acceptors
                hbd = rdMolDescriptors.CalcNumHBD(mol)
                hba = rdMolDescriptors.CalcNumHBA(mol)
                hbond_score = min(hbd + hba, 10) / 10.0

                # Rotatable bonds — flexibility
                rot = rdMolDescriptors.CalcNumRotatableBonds(mol)
                flex_score = 1.0 - min(rot / 10.0, 1.0)

                # TPSA — topological polar surface area
                tpsa = Descriptors.TPSA(mol)
                tpsa_score = 1.0 - min(abs(tpsa - 80) / 60, 1.0)

                # Ring count — protease inhibitors often have 2-4 rings
                rings = rdMolDescriptors.CalcNumRings(mol)
                ring_score = 1.0 - min(abs(rings - 3) / 3.0, 1.0)

                # Aromatic rings — contribute to binding pocket interactions
                arom = rdMolDescriptors.CalcNumAromaticRings(mol)
                arom_score = min(arom, 3) / 3.0

                # Composite binding score (0-1 range)
                binding = (
                    0.25 * logp_score
                    + 0.20 * hbond_score
                    + 0.15 * flex_score
                    + 0.15 * tpsa_score
                    + 0.15 * ring_score
                    + 0.10 * arom_score
                )

                # Drug-likeness (Lipinski + Veber)
                lipinski_violations = sum([
                    Descriptors.MolWt(mol) > 500,
                    logp > 5,
                    hbd > 5,
                    hba > 10,
                ])
                veber_ok = tpsa <= 140 and rot <= 10
                drug_likeness = (
                    (4 - lipinski_violations) / 4.0 * 0.7
                    + (1.0 if veber_ok else 0.0) * 0.3
                )

                mol_data["binding_score"] = round(binding, 4)
                mol_data["drug_likeness"] = round(drug_likeness, 4)

            except Exception:
                mol_data["binding_score"] = 0.0
                mol_data["drug_likeness"] = 0.0

        return molecules
```

### agents/safety.py

```python
"""
⚠️ Safety Agent — Checks toxicity and drug safety.
Uses structural alerts (PAINS filters) and property-based rules.
"""

import ray
import uuid
from rdkit import Chem
from rdkit.Chem import Descriptors
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams


@ray.remote
class SafetyAgent:
    def __init__(self):
        self.agent_id = str(uuid.uuid4())[:8]
        # Initialize PAINS filter
        params = FilterCatalogParams()
        params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS)
        self.pains_catalog = FilterCatalog(params)

    def check_toxicity(self, molecules: list) -> list:
        """Flag molecules with toxicity concerns. Returns all molecules with flags."""
        results = []
        for mol_data in molecules:
            try:
                mol = Chem.MolFromSmiles(mol_data["smiles"])
                if mol is None:
                    continue

                # PAINS filter (pan-assay interference compounds)
                has_pains = self.pains_catalog.HasMatch(mol)

                # Basic toxicophore check
                toxic_smarts = [
                    "[N+](=O)[O-]",     # nitro group
                    "[SH]",              # thiol
                    "C(=O)Cl",           # acyl chloride
                    "[N;H0](=O)",        # nitroso
                    "C1(=O)OC(=O)C1",   # anhydride
                ]
                has_toxic_group = any(
                    mol.HasSubstructMatch(Chem.MolFromSmarts(s))
                    for s in toxic_smarts
                    if Chem.MolFromSmarts(s) is not None
                )

                mol_data["toxicity_flag"] = has_pains or has_toxic_group
                mol_data["pains_alert"] = has_pains
                mol_data["toxic_group_alert"] = has_toxic_group

                # Compute composite fitness
                from config import (
                    BINDING_WEIGHT, DRUG_LIKENESS_WEIGHT, TOXICITY_PENALTY_WEIGHT
                )
                toxicity_penalty = 0.5 if mol_data["toxicity_flag"] else 0.0
                mol_data["fitness"] = round(
                    BINDING_WEIGHT * mol_data["binding_score"]
                    + DRUG_LIKENESS_WEIGHT * mol_data["drug_likeness"]
                    - TOXICITY_PENALTY_WEIGHT * toxicity_penalty,
                    4,
                )

                results.append(mol_data)
            except Exception:
                continue

        return results
```

### agents/selector.py

```python
"""
🏆 Selector Agent — Evolutionary selection.
Maintains leaderboard and selects next generation via tournament selection.
"""

import random
import ray
import uuid


@ray.remote
class SelectorAgent:
    def __init__(self):
        self.agent_id = str(uuid.uuid4())[:8]

    def select(
        self,
        population: list,
        elite_fraction: float,
        tournament_size: int,
    ) -> list:
        """Select the next generation using elitism + tournament selection."""
        if not population:
            return []

        # Sort by fitness
        sorted_pop = sorted(population, key=lambda m: m["fitness"], reverse=True)

        pop_size = len(sorted_pop)
        num_elite = max(1, int(pop_size * elite_fraction))

        # Elites pass through unchanged
        next_gen = sorted_pop[:num_elite]

        # Tournament selection for remaining slots
        remaining = pop_size - num_elite
        for _ in range(remaining):
            tournament = random.sample(sorted_pop, min(tournament_size, pop_size))
            winner = max(tournament, key=lambda m: m["fitness"])
            next_gen.append(winner)

        return next_gen
```

### chemistry/fingerprints.py

```python
"""
Compute Morgan fingerprints and UMAP 3D coordinates for visualization.
"""

import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem
from umap import UMAP


def compute_morgan_fingerprint(smiles: str, radius: int = 2, n_bits: int = 1024):
    """Compute Morgan fingerprint as numpy array."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return np.zeros(n_bits)
    fp = AllChem.GetMorganFingerprintAsBitVect(mol, radius, nBits=n_bits)
    return np.array(fp)


def compute_umap_coordinates(molecules: list, n_components: int = 3) -> list:
    """
    Compute 3D UMAP coordinates for all molecules.
    Updates molecules in-place with umap_x, umap_y, umap_z.
    """
    if len(molecules) < 5:
        # Not enough for UMAP, assign random positions
        for m in molecules:
            m["umap_x"] = float(np.random.randn())
            m["umap_y"] = float(np.random.randn())
            m["umap_z"] = float(np.random.randn())
        return molecules

    # Compute fingerprints
    fps = np.array([
        compute_morgan_fingerprint(m["smiles"]) for m in molecules
    ])

    # Run UMAP to 3D
    reducer = UMAP(
        n_components=n_components,
        n_neighbors=min(15, len(molecules) - 1),
        min_dist=0.1,
        metric="jaccard",
        random_state=42,
    )
    coords = reducer.fit_transform(fps)

    # Normalize to [-1, 1] range for Three.js
    for dim in range(n_components):
        col = coords[:, dim]
        min_val, max_val = col.min(), col.max()
        if max_val - min_val > 0:
            coords[:, dim] = 2 * (col - min_val) / (max_val - min_val) - 1

    # Assign coordinates
    for i, m in enumerate(molecules):
        m["umap_x"] = float(coords[i, 0])
        m["umap_y"] = float(coords[i, 1])
        m["umap_z"] = float(coords[i, 2])

    return molecules
```

### chemistry/conformer.py

```python
"""
Generate 3D conformers for molecule visualization.
Returns atomic coordinates in a format 3Dmol.js can render.
"""

from rdkit import Chem
from rdkit.Chem import AllChem


def generate_3d_conformer(smiles: str) -> dict | None:
    """Generate 3D coordinates and return as SDF block for 3Dmol.js."""
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None

        mol = Chem.AddHs(mol)
        result = AllChem.EmbedMolecule(mol, randomSeed=42)
        if result == -1:
            return None

        AllChem.MMFFOptimizeMolecule(mol, maxIters=200)
        sdf_block = Chem.MolToMolBlock(mol)

        return {
            "smiles": smiles,
            "sdf": sdf_block,
            "num_atoms": mol.GetNumAtoms(),
        }
    except Exception:
        return None
```

---

## Part 2: Frontend (React + TypeScript)

### Directory Structure

```
frontend/
├── package.json
├── tsconfig.json
├── vite.config.ts
├── index.html
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── hooks/
│   │   └── useSwarmWebSocket.ts     # WebSocket connection + state
│   ├── components/
│   │   ├── Dashboard.tsx             # Main layout
│   │   ├── ChemicalSpaceViewer.tsx   # THREE.js UMAP point cloud (HERO)
│   │   ├── MoleculeViewer3D.tsx      # 3Dmol.js individual molecule
│   │   ├── FitnessGraph.tsx          # Recharts generation fitness
│   │   ├── Leaderboard.tsx           # Top candidates table
│   │   ├── AgentActivityFeed.tsx     # Live agent status
│   │   ├── GenerationTimeline.tsx    # Generation progress bar
│   │   └── ControlPanel.tsx          # Start/pause/config
│   ├── types/
│   │   └── swarm.ts                  # TypeScript interfaces
│   └── utils/
│       └── colors.ts                 # Fitness-to-color mapping
```

### package.json dependencies

```json
{
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "three": "^0.160.0",
    "@react-three/fiber": "^8.15.0",
    "@react-three/drei": "^9.92.0",
    "3dmol": "^2.1.0",
    "recharts": "^2.10.0",
    "framer-motion": "^10.16.0",
    "lucide-react": "^0.292.0",
    "tailwindcss": "^3.4.0"
  },
  "devDependencies": {
    "@types/react": "^18.2.0",
    "@types/three": "^0.160.0",
    "typescript": "^5.3.0",
    "vite": "^5.0.0",
    "@vitejs/plugin-react": "^4.2.0"
  }
}
```

### types/swarm.ts

```typescript
export interface Molecule {
  id: string;
  smiles: string;
  fitness: number;
  binding_score: number;
  drug_likeness: number;
  toxicity_flag: boolean;
  umap_x: number;
  umap_y: number;
  umap_z: number;
  generation: number;
}

export interface GenerationResult {
  type: "generation_complete";
  generation: number;
  num_explored: number;
  num_safe: number;
  num_selected: number;
  best_fitness: number;
  avg_fitness: number;
  elapsed_seconds: number;
  molecules: Molecule[];
  leaderboard: Molecule[];
  total_explored: number;
  agent_activity: {
    explorers_active: number;
    chemists_active: number;
    safety_active: number;
  };
}

export interface SwarmState {
  generations: GenerationResult[];
  allMolecules: Molecule[];
  leaderboard: Molecule[];
  currentGeneration: number;
  totalExplored: number;
  isRunning: boolean;
  selectedMolecule: Molecule | null;
  fitnessHistory: { generation: number; best: number; avg: number }[];
}
```

### hooks/useSwarmWebSocket.ts

```typescript
import { useState, useEffect, useCallback, useRef } from "react";
import type { SwarmState, GenerationResult, Molecule } from "../types/swarm";

const WS_URL = "ws://localhost:8000/ws";

export function useSwarmWebSocket() {
  const [state, setState] = useState<SwarmState>({
    generations: [],
    allMolecules: [],
    leaderboard: [],
    currentGeneration: 0,
    totalExplored: 0,
    isRunning: false,
    selectedMolecule: null,
    fitnessHistory: [],
  });

  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      const data: GenerationResult = JSON.parse(event.data);

      if (data.type === "generation_complete") {
        setState((prev) => ({
          ...prev,
          generations: [...prev.generations, data],
          allMolecules: [...prev.allMolecules, ...data.molecules],
          leaderboard: data.leaderboard,
          currentGeneration: data.generation,
          totalExplored: data.total_explored,
          isRunning: true,
          fitnessHistory: [
            ...prev.fitnessHistory,
            {
              generation: data.generation,
              best: data.best_fitness,
              avg: data.avg_fitness,
            },
          ],
        }));
      }
    };

    return () => ws.close();
  }, []);

  const sendCommand = useCallback((action: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action }));
    }
  }, []);

  const start = () => sendCommand("start");
  const pause = () => sendCommand("pause");
  const resume = () => sendCommand("resume");

  const selectMolecule = (mol: Molecule | null) => {
    setState((prev) => ({ ...prev, selectedMolecule: mol }));
  };

  return { state, start, pause, resume, selectMolecule };
}
```

### Key Component: ChemicalSpaceViewer.tsx (HERO VISUAL)

```typescript
/**
 * 3D UMAP Chemical Space Viewer — the centerpiece visualization.
 * Each point is a molecule, colored by fitness, sized by generation.
 * Points from recent generations glow brighter.
 * Click a point to inspect the molecule in the 3D viewer.
 *
 * Uses @react-three/fiber for Three.js rendering.
 */

import React, { useRef, useMemo } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import type { Molecule } from "../types/swarm";

interface Props {
  molecules: Molecule[];
  currentGeneration: number;
  onSelectMolecule: (mol: Molecule) => void;
}

// Color scale: red (low fitness) → yellow → green (high fitness)
function fitnessToColor(fitness: number): THREE.Color {
  const t = Math.max(0, Math.min(1, fitness));
  if (t < 0.5) {
    return new THREE.Color().setHSL(0, 0.9, 0.4 + t * 0.2); // red → orange
  }
  return new THREE.Color().setHSL(0.1 + (t - 0.5) * 0.3, 0.9, 0.5); // orange → green
}

function MoleculeCloud({ molecules, currentGeneration, onSelectMolecule }: Props) {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const dummy = useMemo(() => new THREE.Object3D(), []);

  const { positions, colors, scales } = useMemo(() => {
    const pos = new Float32Array(molecules.length * 3);
    const col = new Float32Array(molecules.length * 3);
    const scl = new Float32Array(molecules.length);

    molecules.forEach((mol, i) => {
      // Position from UMAP
      pos[i * 3] = mol.umap_x * 50;     // Scale up for visibility
      pos[i * 3 + 1] = mol.umap_y * 50;
      pos[i * 3 + 2] = mol.umap_z * 50;

      // Color from fitness
      const color = fitnessToColor(mol.fitness);
      col[i * 3] = color.r;
      col[i * 3 + 1] = color.g;
      col[i * 3 + 2] = color.b;

      // Size: recent generations are bigger
      const recency = 1 - (currentGeneration - mol.generation) / Math.max(currentGeneration, 1);
      scl[i] = 0.2 + recency * 0.8;
    });

    return { positions: pos, colors: col, scales: scl };
  }, [molecules, currentGeneration]);

  useFrame(() => {
    if (!meshRef.current) return;
    molecules.forEach((_, i) => {
      dummy.position.set(positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2]);
      dummy.scale.setScalar(scales[i]);
      dummy.updateMatrix();
      meshRef.current!.setMatrixAt(i, dummy.matrix);
    });
    meshRef.current.instanceMatrix.needsUpdate = true;
  });

  return (
    <instancedMesh
      ref={meshRef}
      args={[undefined, undefined, molecules.length]}
      onClick={(e) => {
        if (e.instanceId !== undefined) {
          onSelectMolecule(molecules[e.instanceId]);
        }
      }}
    >
      <sphereGeometry args={[0.5, 16, 16]} />
      <meshStandardMaterial vertexColors />
    </instancedMesh>
  );
}

export function ChemicalSpaceViewer(props: Props) {
  return (
    <div style={{ width: "100%", height: "100%", background: "#0a0a0f" }}>
      <Canvas camera={{ position: [80, 60, 80], fov: 60 }}>
        <ambientLight intensity={0.4} />
        <pointLight position={[100, 100, 100]} intensity={1} />
        <MoleculeCloud {...props} />
        <OrbitControls enableDamping dampingFactor={0.05} autoRotate autoRotateSpeed={0.5} />
        {/* Grid for spatial reference */}
        <gridHelper args={[100, 20, "#1a1a2e", "#1a1a2e"]} />
      </Canvas>
    </div>
  );
}
```

### Component: MoleculeViewer3D.tsx

```typescript
/**
 * 3D Molecule Viewer using 3Dmol.js
 * Shows the selected molecule's 3D structure with ball-and-stick model.
 */

import React, { useEffect, useRef } from "react";
import type { Molecule } from "../types/swarm";

// 3Dmol.js is loaded via CDN in index.html
declare const $3Dmol: any;

interface Props {
  molecule: Molecule | null;
}

export function MoleculeViewer3D({ molecule }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<any>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    viewerRef.current = $3Dmol.createViewer(containerRef.current, {
      backgroundColor: "0x0a0a0f",
    });
  }, []);

  useEffect(() => {
    if (!molecule || !viewerRef.current) return;

    // Fetch 3D conformer from backend
    fetch(`http://localhost:8000/api/molecule/${molecule.id}`)
      .then((r) => r.json())
      .then((data) => {
        if (data?.sdf) {
          const viewer = viewerRef.current;
          viewer.removeAllModels();
          viewer.addModel(data.sdf, "sdf");
          viewer.setStyle({}, { stick: { radius: 0.15 }, sphere: { scale: 0.25 } });
          viewer.setStyle(
            { elem: "C" },
            { stick: { color: "0x00ff88" }, sphere: { color: "0x00ff88", scale: 0.25 } }
          );
          viewer.zoomTo();
          viewer.spin("y", 1);
          viewer.render();
        }
      });
  }, [molecule]);

  return (
    <div
      ref={containerRef}
      style={{ width: "100%", height: "100%", position: "relative" }}
    />
  );
}
```

### Component: FitnessGraph.tsx

```typescript
import React from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from "recharts";

interface Props {
  data: { generation: number; best: number; avg: number }[];
}

export function FitnessGraph({ data }: Props) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1a1a2e" />
        <XAxis dataKey="generation" stroke="#666" label={{ value: "Generation", position: "bottom" }} />
        <YAxis stroke="#666" domain={[0, 1]} />
        <Tooltip
          contentStyle={{ background: "#0a0a0f", border: "1px solid #333" }}
        />
        <Legend />
        <Line
          type="monotone" dataKey="best" stroke="#00ff88"
          name="Best Fitness" dot={false} strokeWidth={2}
        />
        <Line
          type="monotone" dataKey="avg" stroke="#4488ff"
          name="Avg Fitness" dot={false} strokeWidth={1.5}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
```

---

## Part 3: Dashboard Layout (App.tsx)

```typescript
/**
 * Main dashboard layout.
 *
 * ┌─────────────────────────────────────────────────┐
 * │ Header: Stats + Controls                         │
 * ├────────────────────────┬────────────────────────-┤
 * │                        │ Molecule 3D Viewer       │
 * │  Chemical Space        ├──────────────────────────┤
 * │  (UMAP Point Cloud)    │ Fitness Graph            │
 * │  HERO VISUAL           ├──────────────────────────┤
 * │                        │ Leaderboard              │
 * └────────────────────────┴──────────────────────────┘
 */

import React from "react";
import { useSwarmWebSocket } from "./hooks/useSwarmWebSocket";
import { ChemicalSpaceViewer } from "./components/ChemicalSpaceViewer";
import { MoleculeViewer3D } from "./components/MoleculeViewer3D";
import { FitnessGraph } from "./components/FitnessGraph";
// ... other component imports

export default function App() {
  const { state, start, pause, resume, selectMolecule } = useSwarmWebSocket();

  return (
    <div className="h-screen w-screen bg-[#0a0a0f] text-white flex flex-col">
      {/* Header */}
      <header className="h-16 border-b border-white/10 flex items-center justify-between px-6">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-bold tracking-tight">
            <span className="text-emerald-400">AI</span> Drug Discovery Swarm
          </h1>
          <div className="flex gap-6 text-sm text-white/60">
            <span>Gen <strong className="text-white">{state.currentGeneration}</strong></span>
            <span>Explored <strong className="text-white">{state.totalExplored.toLocaleString()}</strong></span>
            <span>Best <strong className="text-emerald-400">{state.fitnessHistory.at(-1)?.best.toFixed(3) ?? "—"}</strong></span>
          </div>
        </div>
        <div className="flex gap-2">
          {!state.isRunning ? (
            <button onClick={start} className="px-4 py-1.5 bg-emerald-500 rounded text-sm font-medium">
              Launch Swarm
            </button>
          ) : (
            <button onClick={pause} className="px-4 py-1.5 bg-amber-500 rounded text-sm font-medium">
              Pause
            </button>
          )}
        </div>
      </header>

      {/* Main Grid */}
      <div className="flex-1 grid grid-cols-3 grid-rows-3 gap-px bg-white/5">
        {/* Chemical Space — spans 2 cols, 3 rows */}
        <div className="col-span-2 row-span-3">
          <ChemicalSpaceViewer
            molecules={state.allMolecules}
            currentGeneration={state.currentGeneration}
            onSelectMolecule={selectMolecule}
          />
        </div>

        {/* Molecule Viewer — 1 col, 1 row */}
        <div className="col-span-1 row-span-1 p-2">
          <MoleculeViewer3D molecule={state.selectedMolecule} />
        </div>

        {/* Fitness Graph — 1 col, 1 row */}
        <div className="col-span-1 row-span-1 p-2">
          <FitnessGraph data={state.fitnessHistory} />
        </div>

        {/* Leaderboard — 1 col, 1 row */}
        <div className="col-span-1 row-span-1 p-2 overflow-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-white/40 text-left">
                <th className="py-1">#</th>
                <th>SMILES</th>
                <th>Fitness</th>
                <th>Binding</th>
                <th>Safe</th>
              </tr>
            </thead>
            <tbody>
              {state.leaderboard.map((mol, i) => (
                <tr
                  key={mol.id}
                  className="hover:bg-white/5 cursor-pointer"
                  onClick={() => selectMolecule(mol)}
                >
                  <td className="py-1 text-white/40">{i + 1}</td>
                  <td className="font-mono text-emerald-300 truncate max-w-[120px]">
                    {mol.smiles}
                  </td>
                  <td className="text-white font-medium">{mol.fitness.toFixed(3)}</td>
                  <td>{mol.binding_score.toFixed(3)}</td>
                  <td>{mol.toxicity_flag ? "⚠️" : "✅"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
```

---

## Part 4: HPC Cluster Deployment

### run_cluster.py — Ray Cluster Launcher

```python
"""
Launch the swarm on an HPC cluster with Ray.

Usage:
  # On head node:
  ray start --head --port=6379
  python run_cluster.py

  # On worker nodes:
  ray start --address='<head-ip>:6379'
"""

import ray
import os

# Connect to existing Ray cluster or start local
ray.init(address=os.environ.get("RAY_ADDRESS", "auto"))

print(f"Connected to Ray cluster:")
print(f"  Nodes: {len(ray.nodes())}")
print(f"  CPUs: {ray.cluster_resources().get('CPU', 0)}")
print(f"  GPUs: {ray.cluster_resources().get('GPU', 0)}")

# Start the FastAPI server
import uvicorn
from main import app

uvicorn.run(app, host="0.0.0.0", port=8000)
```

### SLURM job script (submit.sh)

```bash
#!/bin/bash
#SBATCH --job-name=drug-swarm
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --time=02:00:00
#SBATCH --output=swarm_%j.log

module load python/3.11
module load cuda/12.2  # if using GPU scoring

# Start Ray head node
ray start --head --port=6379 --num-cpus=$SLURM_CPUS_PER_TASK &
sleep 5

# Start Ray workers on other nodes
srun --nodes=$((SLURM_NNODES-1)) --ntasks=$((SLURM_NNODES-1)) \
  ray start --address=$(hostname):6379 --num-cpus=$SLURM_CPUS_PER_TASK &
sleep 10

# Launch the application
python run_cluster.py
```

---

## Part 5: Demo Mode (For when HPC isn't available)

Create a `demo_mode.py` that simulates the swarm locally with pre-computed data, so you can always demo the frontend even without the cluster:

```python
"""
Demo mode: runs a small local swarm with reduced parameters.
Perfect for presentation fallback.
"""

from config import *
import config

# Override for demo
config.NUM_EXPLORER_AGENTS = 2
config.NUM_CHEMIST_AGENTS = 2
config.NUM_SAFETY_AGENTS = 1
config.MOLECULES_PER_GENERATION = 50
config.MAX_GENERATIONS = 20

from main import app
import uvicorn

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

---

## Quick Start Commands

```bash
# Backend setup
cd backend
pip install -r requirements.txt
ray start --head
uvicorn main:app --host 0.0.0.0 --port 8000

# Frontend setup
cd frontend
npm install
npm run dev

# Open http://localhost:5173
# Click "Launch Swarm" and watch the magic
```

---

## Upgrade Path (Nice-to-haves if time permits)

1. **AutoDock Vina integration**: Replace the proxy scorer in `chemist.py` with actual docking
   ```bash
   pip install vina
   ```
   You'll need the target protein PDB file (6LU7.pdb).

2. **Sound design**: Add subtle audio feedback — a soft tone when new top candidates are found, rising pitch as fitness improves.

3. **Agent chat log**: Show a simulated "conversation" between agents in the UI:
   ```
   🧬 Explorer-3a: Generated 25 candidates from Gen 4 elite
   🔬 Chemist-7f: Scored batch — top hit 0.847 binding
   ⚠️ Safety-2c: Flagged 3 PAINS alerts
   🏆 Selector: New #1 candidate! Fitness 0.891
   ```

4. **UMAP animation**: Instead of recomputing UMAP each generation, use `umap.transform()` on new points to maintain stable coordinates, so you see new molecules "appear" in chemical space.
