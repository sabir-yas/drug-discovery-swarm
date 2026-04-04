# AI Drug Discovery Swarm

A distributed multi-agent system that autonomously evolves novel drug candidate molecules using evolutionary AI. A swarm of specialized agents explores chemical space, scores binding affinity, filters for drug safety, and selects the fittest candidates — all visualized in real time via a mission-control dashboard.

**Target:** COVID-19 Main Protease (Mpro / PDB: 6LU7)

![Dashboard](https://img.shields.io/badge/status-working-4edea3?style=flat-square) ![Python](https://img.shields.io/badge/python-3.10-adc6ff?style=flat-square) ![React](https://img.shields.io/badge/react-19-61dafb?style=flat-square)

---

## How It Works

```
Explorer Agents → Chemist Agents → Safety Agents → Selector Agent → next generation
     ↓                  ↓                ↓               ↓
 SELFIES mol       RDKit heuristic   PAINS + Lipinski  Tournament
 generation        or Vina docking   toxicity filter   selection
```

Each generation:
1. **Explorer** agents generate candidate molecules via SELFIES encoding + genetic operators (mutation, crossover)
2. **Chemist** agents score binding affinity — fast RDKit heuristic by default, or real AutoDock Vina docking when enabled
3. **Safety** agents filter out toxic/PAINS molecules and compute composite fitness
4. **Selector** agent picks the fittest candidates via elitism + tournament selection
5. Results broadcast in real time over WebSocket to the React dashboard

---

## Architecture

```
┌─────────────────────────────────────────────┐
│              React Dashboard (Vite)          │
│   UMAP 3D · 3D Conformer · Fitness Chart     │
│   Leaderboard · Cluster Activity · Logs      │
└───────────────────┬─────────────────────────┘
                    │ WebSocket ws://localhost:8000/ws
┌───────────────────▼─────────────────────────┐
│         FastAPI + Uvicorn (Python)           │
│              coordinator.py                  │
│    Ray Actors ←→ Redis Streams/Keys          │
│  [Explorer×3] [Chemist×3] [Safety×2] [Sel]  │
└─────────────────────────────────────────────┘
```

---

## Local Setup (Windows + WSL2)

### Prerequisites
- Windows 10/11 with WSL2 enabled
- Node.js 18+ (Windows)
- Miniforge/conda (WSL2)

### 1. Enable WSL2 (if not already)
```powershell
# In PowerShell as Administrator
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
pip install fastapi==0.104.1 uvicorn==0.24.0 websockets==12.0 redis==5.0.1 \
    ray==2.9.0 selfies==2.1.1 umap-learn==0.5.5 numpy==1.26.2 scipy==1.11.4 \
    scikit-learn==1.3.2 aiofiles==23.2.1 pydantic==2.5.2 setuptools packaging
```

### 4. Patch Ray for setuptools compatibility
```bash
# Ray 2.9.0 has a broken import with setuptools >= 67
sed -i 's/from pkg_resources import packaging/import packaging/' \
  ~/miniforge3/envs/drugswarm/lib/python3.10/site-packages/ray/_private/pydantic_compat.py
```

### 5. Install frontend dependencies
```powershell
# In Windows terminal
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

You should see:
```
INFO:     Started a local Ray instance.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

**Terminal 2 — Windows (frontend)**
```powershell
cd frontend
npm run dev
```

Open **http://localhost:5173** in your browser, then click **Launch Swarm**.

---

## Real Docking with AutoDock Vina (optional)

By default the swarm uses a fast RDKit heuristic to score molecules. For real binding affinities against the Mpro crystal structure, you can enable AutoDock Vina.

### 1. Install docking dependencies
```bash
conda activate drugswarm
conda install -c conda-forge openbabel meeko vina -y
```

### 2. Prepare the receptor (one-time)
```bash
cd backend
python prepare_receptor.py
```

This downloads `6LU7.pdb` from RCSB, strips water/ligands, converts to PDBQT with Open Babel, and verifies the pipeline with a test molecule. The prepared receptor is saved to `backend/data/6LU7_prepared.pdbqt`.

### 3. Enable docking in config
```python
# backend/config.py
USE_REAL_DOCKING = True
DOCKING_EXHAUSTIVENESS = 4   # 4 = fast/demo, 8 = production accuracy
```

Restart the backend. The Chemist agents will now call Vina for each molecule, falling back to heuristic scoring if docking fails for an individual candidate.

### 4. Offline validation of top candidates
After a swarm session, export the leaderboard and run full Vina validation:
```bash
# Export leaderboard (or use GET /api/leaderboard/export)
curl http://localhost:8000/api/leaderboard/export

# Dock top 10 swarm candidates vs. reference drugs (Nirmatrelvir, Ensitrelvir, GC376)
python validate_with_vina.py --top-n 10 --exhaustiveness 8
```

Results are saved to `backend/vina_validation.json`.

---

## Running on HPC (CU Boulder Alpine)

### One-time setup on login node
```bash
# Allow compute nodes to SSH back to login node (needed for reverse tunnel)
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

### Submit the job
```bash
cd /path/to/drug-discovery-swarm/backend
mkdir -p logs
sbatch submit.sh
```

### Connect from Windows (once job starts)
Watch the job log for the connection command:
```bash
tail -f logs/drug_discovery.*.out
# Look for: "=== CONNECT FROM WINDOWS ==="
```

Then run on Windows:
```powershell
ssh -N -L 8080:localhost:8000 ysabir@xsede.org@login.rc.colorado.edu
```

Start the frontend in HPC mode:
```powershell
cd frontend
npm run dev -- --mode hpc
```

Open **http://localhost:5173**

---

## Configuration

Edit `backend/config.py` to tune the swarm:

| Parameter | Default | HPC |
|---|---|---|
| `NUM_EXPLORER_AGENTS` | 3 | 10 |
| `NUM_CHEMIST_AGENTS` | 3 | 8 |
| `NUM_SAFETY_AGENTS` | 2 | 4 |
| `MOLECULES_PER_GENERATION` | 50 | 200 |
| `MAX_GENERATIONS` | 100 | 50 |
| `USE_REAL_DOCKING` | `False` | `True` |
| `DOCKING_EXHAUSTIVENESS` | 4 | 8 |

The Redis URL defaults to `redis://localhost:6379` and can be overridden with the `REDIS_URL` environment variable.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `WS` | `/ws` | Real-time swarm data stream (start / pause / resume) |
| `GET` | `/api/status` | Current swarm status |
| `GET` | `/api/leaderboard` | Top molecules ranked by fitness |
| `GET` | `/api/leaderboard/export` | Save leaderboard to `leaderboard.json` |
| `GET` | `/api/molecule/{id}` | 3D conformer data for a molecule |

---

## Project Structure

```
drug-discovery-swarm/
├── backend/
│   ├── agents/
│   │   ├── explorer.py          # SELFIES molecule generation + genetic operators
│   │   ├── chemist.py           # RDKit heuristic or Vina docking scoring
│   │   ├── safety.py            # PAINS + Lipinski toxicity filtering
│   │   └── selector.py          # Tournament + elitism selection
│   ├── chemistry/
│   │   ├── fingerprints.py      # Morgan fingerprint + UMAP 3D coordinates
│   │   ├── conformer.py         # 3D conformer generation (RDKit MMFF)
│   │   └── docking.py           # AutoDock Vina wrapper (requires prepare_receptor.py)
│   ├── data/                    # Created by prepare_receptor.py
│   │   └── 6LU7_prepared.pdbqt  # Prepared Mpro receptor (gitignored)
│   ├── main.py                  # FastAPI + WebSocket server
│   ├── coordinator.py           # Swarm orchestrator (Ray + Redis)
│   ├── config.py                # All hyperparameters
│   ├── prepare_receptor.py      # One-time Mpro receptor preparation
│   ├── validate_with_vina.py    # Offline Vina validation vs. reference drugs
│   ├── submit.sh                # SLURM HPC job script
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── App.tsx                      # Main layout + WebSocket client
    │   └── components/
    │       ├── UMAPVisualizer.tsx        # 3D chemical space (Three.js)
    │       ├── MoleculeViewer3D.tsx      # 3D conformer (3Dmol.js)
    │       ├── FitnessTimeline.tsx       # Generation fitness chart (Recharts)
    │       ├── ClusterActivityMap.tsx    # Node telemetry strip
    │       └── AgentChatLog.tsx          # Live agent event feed
    ├── .env                             # Local backend URL (port 8000)
    └── .env.hpc                         # HPC backend URL (port 8080, tunnel)
```

---

## Known Limitations

- **Heuristic mode only approximates docking** — the default RDKit descriptor scorer is a proxy, not real binding affinity. Enable `USE_REAL_DOCKING` for Vina-based scores.
- **Population convergence** — the swarm can converge to a single scaffold by generation ~30. Reduce `MAX_GENERATIONS` or increase `MUTATION_RATE` in `config.py` to maintain diversity.
- **No persistent storage** — molecules are in-memory only. Restart clears all results (use `/api/leaderboard/export` to save before stopping).

---

## Tech Stack

| Layer | Technology |
|---|---|
| Molecule generation | SELFIES |
| Cheminformatics | RDKit |
| Molecular docking | AutoDock Vina + meeko + Open Babel |
| Distributed agents | Ray |
| Real-time messaging | Redis Streams |
| API + WebSocket | FastAPI + Uvicorn |
| 3D visualization | Three.js / React Three Fiber |
| Molecular viewer | 3Dmol.js |
| Charts | Recharts |
| Animations | Framer Motion |
| Styling | Tailwind CSS |
| HPC scheduler | SLURM (CU Boulder Alpine) |
