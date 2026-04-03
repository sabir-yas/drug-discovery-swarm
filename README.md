# AI Drug Discovery Swarm

A distributed multi-agent system that autonomously evolves novel drug candidate molecules using evolutionary AI. A swarm of specialized agents explores chemical space, scores binding affinity, filters for drug safety, and selects the fittest candidates — all visualized in real time via a mission-control dashboard.

**Target:** COVID-19 Main Protease (Mpro / PDB: 6LU7)

![Dashboard](https://img.shields.io/badge/status-working-4edea3?style=flat-square) ![Python](https://img.shields.io/badge/python-3.10-adc6ff?style=flat-square) ![React](https://img.shields.io/badge/react-19-61dafb?style=flat-square)

---

## How It Works

```
Explorer Agents → Chemist Agents → Safety Agents → Selector Agent → next generation
     ↓                  ↓                ↓               ↓
 SELFIES mol       RDKit descriptor   PAINS + Lipinski  Tournament
 generation        binding proxy      toxicity filter   selection
```

Each generation:
1. **Explorer** agents generate candidate molecules via SELFIES encoding + genetic operators (mutation, crossover)
2. **Chemist** agents score binding affinity using RDKit molecular descriptors (logP, TPSA, H-bonds, rings)
3. **Safety** agents filter out toxic/PAINS molecules and compute composite fitness
4. **Selector** agent picks the fittest candidates for the next generation via elitism + tournament selection
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
│  [Explorer×10] [Chemist×8] [Safety×4] [Sel] │
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

| Parameter | Local (recommended) | HPC |
|---|---|---|
| `NUM_EXPLORER_AGENTS` | 2 | 10 |
| `NUM_CHEMIST_AGENTS` | 2 | 8 |
| `NUM_SAFETY_AGENTS` | 1 | 4 |
| `MOLECULES_PER_GENERATION` | 20 | 200 |
| `MAX_GENERATIONS` | 10 | 50 |

---

## Validating Results

Run the validation script while the backend is running:
```bash
cd backend
conda activate drugswarm
python validate_results.py
```

This checks your top candidates against:
- **Lipinski's Rule of Five** — standard FDA oral drug-likeness filter
- **PAINS screening** — removes false-positive assay interference compounds
- **Tanimoto similarity** vs. Nirmatrelvir (Paxlovid) and Ensitrelvir — confirms candidates are novel

For full ADMET profiling, paste the output SMILES into **https://www.swissadme.ch**

---

## Project Structure

```
drug-discovery-swarm/
├── backend/
│   ├── agents/
│   │   ├── explorer.py      # SELFIES molecule generation + genetic operators
│   │   ├── chemist.py       # RDKit binding affinity scoring
│   │   ├── safety.py        # PAINS + Lipinski toxicity filtering
│   │   └── selector.py      # Tournament + elitism selection
│   ├── chemistry/
│   │   ├── fingerprints.py  # UMAP coordinate computation
│   │   └── conformer.py     # 3D conformer generation (RDKit MMFF)
│   ├── main.py              # FastAPI + WebSocket server
│   ├── coordinator.py       # Swarm orchestrator (Ray + Redis)
│   ├── config.py            # All hyperparameters
│   ├── validate_results.py  # Result validation script
│   ├── submit.sh            # SLURM HPC job script
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

- **Binding score is a proxy** — uses RDKit descriptors, not real molecular docking. AutoDock Vina integration is stubbed (receptor file `6LU7_prepared.pdbqt` not included).
- **Population convergence** — the swarm can converge to a single molecule by generation ~30. Reduce `MAX_GENERATIONS` or increase `MUTATION_RATE` in `config.py` to maintain diversity.
- **No persistent storage** — molecules are in-memory only. Restart clears all results.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Molecule generation | SELFIES |
| Cheminformatics | RDKit |
| Distributed agents | Ray |
| Real-time messaging | Redis Streams |
| API + WebSocket | FastAPI + Uvicorn |
| 3D visualization | Three.js / React Three Fiber |
| Molecular viewer | 3Dmol.js |
| Charts | Recharts |
| Animations | Framer Motion |
| Styling | Tailwind CSS |
| HPC scheduler | SLURM (CU Boulder Alpine) |
