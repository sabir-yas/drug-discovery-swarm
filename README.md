# AI Drug Discovery Swarm

A distributed multi-agent system that autonomously evolves novel drug candidate molecules using evolutionary AI. A swarm of specialized agents explores chemical space, scores binding affinity, filters for drug safety, and selects the fittest candidates — all visualized in real time via a mission-control dashboard.

Also ships a fully compliant **A2A (Agent-to-Agent) endpoint** — submit a FHIR R4 patient record and the swarm resolves the drug target from gene variants, runs the evolutionary pipeline, and returns ranked candidates as a FHIR MedicationRequest bundle.

**Default target:** COVID-19 Main Protease (Mpro / PDB: 6LU7)  
**A2A targets:** GBA1, CFTR, HEXA/HEXB, PCSK9, and 6 more rare-disease genes — or any gene via Claude Haiku LLM fallback.

![Dashboard](https://img.shields.io/badge/status-working-4edea3?style=flat-square) ![Python](https://img.shields.io/badge/python-3.10-adc6ff?style=flat-square) ![React](https://img.shields.io/badge/react-19-61dafb?style=flat-square) ![A2A](https://img.shields.io/badge/A2A-COIN_compliant-a1ffc2?style=flat-square)

---

## How It Works

```
Explorer Agents → Chemist Agents → Safety Agents → Selector Agent → next generation
     ↓                  ↓                ↓               ↓
 SELFIES mol       RDKit heuristic   PAINS + reactive  Elitism +
 generation        or Vina docking   SMARTS + SA score  diversity
 + crossover       + SA scoring      toxicity filter    tournament
```

Each generation:
1. **Explorer** agents generate candidates via SELFIES encoding + genetic operators (mutation, crossover, elite-seeded crossover)
2. **Chemist** agents score binding affinity (fast RDKit heuristic or real AutoDock Vina) and compute SA score (synthetic accessibility)
3. **Safety** agents filter PAINS, reactive warheads, and toxic functional groups; compute composite fitness weighted by target-specific scoring bias
4. **Selector** agent picks the fittest candidates via elitism + diversity-aware tournament selection with SA penalty
5. Results broadcast in real time over WebSocket to the React dashboard

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                  React Dashboard (Vite)                       │
│   UMAP 3D · Floating 3D Conformer · Fitness Timeline         │
│   Top Candidates (SA score · ΔG · DL) · Cluster · Logs       │
│   Resizable sidebar + bottom panel via drag handles           │
└───────────────────────┬──────────────────────────────────────┘
                        │ WebSocket ws://localhost:8000/ws
┌───────────────────────▼──────────────────────────────────────┐
│                FastAPI + Uvicorn (Python)                     │
│                     coordinator.py                            │
│         Ray Actors ←→ Redis Streams / Keys                    │
│    [Explorer×3] [Chemist×3] [Safety×2] [Selector]            │
│                                                               │
│   POST /a2a/submit   → FHIR patient in, run_id out           │
│   GET  /a2a/run/{id} → live status (generation, fitness)     │
│   GET  /a2a/results/{id} → FHIR MedicationRequest bundle     │
│   GET  /.well-known/agent.json → A2A agent card              │
└──────────────────────────────────────────────────────────────┘
```

---

## A2A Agent — Drug Target Matching for Rare Disease FHIR Patients

The swarm exposes a COIN-compliant A2A endpoint. An external orchestrator submits a FHIR patient context; the swarm resolves the drug target from gene variants, runs molecule evolution, and returns a FHIR R4 MedicationRequest draft bundle.

### Submit a run (FHIR mock mode)
```bash
RUN_ID=$(curl -s -X POST http://localhost:8000/a2a/submit \
  -H "Content-Type: application/json" \
  -d '{
    "fhir_patient_id": "patient-gaucher-001",
    "fhir_server_url": "mock",
    "sharp_access_token": "test",
    "gene_variants": [{"gene": "GBA1", "variant": "N370S"}],
    "condition_name": "Gaucher disease type 1"
  }' | python3 -c "import sys,json; print(json.load(sys.stdin)['run_id'])")

echo "Run: $RUN_ID"
```

### Poll status
```bash
watch -n 3 "curl -s http://localhost:8000/a2a/run/$RUN_ID | python3 -m json.tool"
```

### Retrieve results (FHIR bundle)
```bash
curl -s http://localhost:8000/a2a/results/$RUN_ID | python3 -m json.tool
```

### Agent card
```bash
curl http://localhost:8000/.well-known/agent.json
```

### Supported gene targets

| Gene | Disease | Mechanism |
|---|---|---|
| GBA1 | Gaucher disease | Enzyme chaperone enhancement |
| CFTR | Cystic fibrosis | Corrector/potentiator |
| HEXA / HEXB | Tay-Sachs / Sandhoff | Enzyme replacement |
| PCSK9 | Familial hypercholesterolaemia | Inhibitor |
| BRCA1/2 | Hereditary breast cancer | PARP inhibitor sensitisation |
| FBN1 | Marfan syndrome | TGF-β modulation |
| LRRK2 | Parkinson's disease | Kinase inhibition |

Any gene not in the above table falls back to Claude Haiku for LLM-based target resolution (requires `ANTHROPIC_API_KEY`).

---

## Local Setup (Windows + WSL2)

### Prerequisites
- Windows 10/11 with WSL2 enabled
- Node.js 18+ (Windows)
- Miniforge/conda (WSL2)

### 1. Enable WSL2
```powershell
# PowerShell as Administrator
wsl --install
# Restart when prompted
```

### 2. Install conda in WSL2
```bash
curl -L -o Miniforge3.sh "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh"
bash Miniforge3.sh -b -p ~/miniforge3
~/miniforge3/bin/conda init bash && source ~/.bashrc
```

### 3. Create the Python environment
```bash
cd /mnt/c/path/to/drug-discovery-swarm/backend

conda create -n drugswarm python=3.10 -y
conda activate drugswarm
conda install -c conda-forge rdkit -y
pip install -r requirements.txt
```

### 4. Patch Ray for setuptools compatibility
```bash
# Ray 2.9.0 has a broken import with setuptools >= 67
sed -i 's/from pkg_resources import packaging/import packaging/' \
  ~/miniforge3/envs/drugswarm/lib/python3.10/site-packages/ray/_private/pydantic_compat.py
```

### 5. Install frontend dependencies
```powershell
# Windows terminal
cd frontend
npm install
```

---

## Running Locally

**Terminal 1 — WSL2 (backend)**
```bash
sudo service redis-server start
cd /mnt/c/path/to/drug-discovery-swarm/backend
conda activate drugswarm
uvicorn main:app --host 0.0.0.0 --port 8000
```

**Terminal 2 — Windows (frontend)**
```powershell
cd frontend
npm run dev
```

Open **http://localhost:5173**, click **Launch Swarm**.

---

## Real Docking with AutoDock Vina (optional)

### 1. Install docking dependencies
```bash
conda activate drugswarm
conda install -c conda-forge openbabel vina -y
pip install meeko
```

### 2. Prepare the receptor (one-time)
```bash
cd backend
python prepare_receptor.py
```

Downloads `6LU7.pdb` from RCSB, strips solvent/ligands, converts to PDBQT. Saved to `backend/data/6LU7_prepared.pdbqt`.

### 3. Enable docking in config
```python
# backend/config.py
USE_REAL_DOCKING = True
DOCKING_EXHAUSTIVENESS = 4   # 4 = fast/demo, 8 = production accuracy
```

Restart the backend. Chemist agents call Vina per molecule; ΔG values appear in the leaderboard. Docking failures fall back to heuristic scoring automatically.

---

## Fitness Function

Composite fitness balances three signals, with target-specific weight overrides for A2A runs:

```
fitness = bind_weight × binding_score
        + dl_weight   × drug_likeness   ← 60% Lipinski/Veber + 40% SA score
        - sa_penalty                     ← max(0, (SA - 7.0) × 0.05)
        - tox_penalty_weight × toxicity_penalty
        + diversity_bonus                ← 0.05 if Tanimoto < 0.4 vs selected pool
```

**SA score** (synthetic accessibility, 1–10) is computed via RDKit's SA scorer and penalizes chemically exotic structures. The leaderboard displays SA color-coded: green (≤3, easy), amber (4–6, moderate), red (>6, hard to synthesize).

**Molecule filters** applied at generation time:
- Max 2 phosphorus atoms per molecule
- No triple bonds to phosphorus (`C#P`)
- No `[N][N][O][P][Cl]` diazo-phosphorochloride warheads
- No `[C]#[S]` thioalkyne groups
- Neutral formal charge, drug-like atom set only (C N O F P S Cl Br I)

---

## Configuration

Edit `backend/config.py`:

| Parameter | Default | HPC |
|---|---|---|
| `NUM_EXPLORER_AGENTS` | 3 | 10 |
| `NUM_CHEMIST_AGENTS` | 3 | 8 |
| `NUM_SAFETY_AGENTS` | 2 | 4 |
| `MOLECULES_PER_GENERATION` | 50 | 200 |
| `MAX_GENERATIONS` | 100 | 50 |
| `USE_REAL_DOCKING` | `True` | `True` |
| `DOCKING_EXHAUSTIVENESS` | 8 | 8 |

`REDIS_URL` defaults to `redis://localhost:6379`, overridable via environment variable.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `WS` | `/ws` | Real-time swarm stream (start / pause / resume) |
| `GET` | `/api/status` | Current swarm status |
| `GET` | `/api/leaderboard` | Top molecules ranked by fitness |
| `GET` | `/api/leaderboard/export` | Save leaderboard to `leaderboard.json` |
| `GET` | `/api/molecule/{id}` | 3D conformer SDF for a molecule |
| `POST` | `/a2a/submit` | Submit FHIR patient context, get `run_id` |
| `GET` | `/a2a/run/{run_id}` | Poll run status (generation, best fitness, target) |
| `GET` | `/a2a/results/{run_id}` | Full results + FHIR MedicationRequest bundle |
| `GET` | `/.well-known/agent.json` | A2A agent card (COIN spec) |

---

## Project Structure

```
drug-discovery-swarm/
├── backend/
│   ├── agents/
│   │   ├── explorer.py          # SELFIES generation + genetic operators + elite seeding
│   │   ├── chemist.py           # Heuristic or Vina scoring + SA score
│   │   ├── safety.py            # PAINS + reactive SMARTS + fitness composite
│   │   └── selector.py          # Elitism + diversity tournament + SA penalty
│   ├── chemistry/
│   │   ├── fingerprints.py      # Morgan fingerprints + UMAP 3D
│   │   ├── conformer.py         # 3D conformer (ETKDGv3 + charge neutralization)
│   │   └── docking.py           # AutoDock Vina wrapper (meeko v0.5)
│   ├── a2a/
│   │   ├── models.py            # Pydantic A2A data contracts
│   │   ├── fhir_extractor.py    # Async FHIR R4 client (real + mock)
│   │   ├── target_resolver.py   # Gene → drug target + scoring bias
│   │   ├── fhir_output.py       # FHIR MedicationRequest bundle builder
│   │   ├── run_store.py         # Redis-backed run state (24h TTL)
│   │   └── agent_card.json      # A2A agent card (COIN spec)
│   ├── data/
│   │   └── 6LU7_prepared.pdbqt  # Prepared Mpro receptor (gitignored)
│   ├── tests/
│   │   └── test_a2a.py          # 92 A2A integration tests
│   ├── main.py                  # FastAPI + WebSocket server
│   ├── coordinator.py           # Swarm orchestrator (Ray + Redis)
│   ├── a2a_router.py            # A2A FastAPI router
│   ├── config.py                # All hyperparameters
│   ├── prepare_receptor.py      # One-time Mpro receptor preparation
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── App.tsx                       # Layout + WebSocket client + resize handles
    │   └── components/
    │       ├── UMAPVisualizer.tsx         # 3D chemical space (Three.js)
    │       ├── MoleculeViewer3D.tsx       # 3D conformer viewer (3Dmol.js)
    │       ├── FitnessTimeline.tsx        # Generation fitness chart (Recharts)
    │       ├── ClusterActivityMap.tsx     # Node telemetry (glass morphism overlay)
    │       └── AgentChatLog.tsx           # Live agent event feed
    ├── index.html                        # Space Grotesk + JetBrains Mono fonts
    ├── .env                              # Local backend (port 8000)
    └── .env.hpc                          # HPC backend (port 8080 tunnel)
```

---

## Running on HPC (CU Boulder Alpine)

### Submit the job
```bash
cd /path/to/drug-discovery-swarm/backend
mkdir -p logs
sbatch submit.sh
```

Watch the log for the SSH tunnel command:
```bash
tail -f logs/drug_discovery.*.out
# Look for: "=== CONNECT FROM WINDOWS ==="
```

Then on Windows:
```powershell
ssh -N -L 8080:localhost:8000 ysabir@xsede.org@login.rc.colorado.edu
cd frontend
npm run dev -- --mode hpc
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Molecule generation | SELFIES |
| Cheminformatics | RDKit (SA scorer, MMFF conformers, UMAP) |
| Molecular docking | AutoDock Vina + meeko v0.5 + Open Babel |
| LLM target resolution | Claude Haiku (Anthropic SDK) |
| Distributed agents | Ray |
| Real-time messaging | Redis Streams |
| FHIR client | httpx (async) |
| API + WebSocket | FastAPI + Uvicorn |
| 3D visualization | Three.js / React Three Fiber |
| Molecular viewer | 3Dmol.js |
| Charts | Recharts |
| Styling | Tailwind CSS + Space Grotesk + JetBrains Mono |
| HPC scheduler | SLURM (CU Boulder Alpine) |

---

## Known Limitations

- **SELFIES dockability** — SELFIES can combine clean tokens into structures that fail Vina's PDBQT preparation. Molecules that fail docking fall back to heuristic scoring. ~60–80% of generated molecules dock successfully after the phosphorus and charge filters.
- **Population convergence** — the swarm can converge to a dominant scaffold by generation ~20–30. The diversity-aware tournament selector (Tanimoto < 0.4 threshold) and elite-seeded crossover mitigate but don't eliminate this.
- **No persistent storage** — molecules are in-memory only. Use `/api/leaderboard/export` before stopping, or use the A2A endpoint which persists results in Redis for 24h.

  Contributors: Yasser Sabir, Khurshed Badalov and Jovan Rayhaga
