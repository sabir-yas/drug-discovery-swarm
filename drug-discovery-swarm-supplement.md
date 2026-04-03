# Supplement: Cluster Activity Map + Enhanced Demo Features

Add these to the main implementation plan.

---

## Cluster Activity Map Component

This is the "judges lean forward" feature. A real-time visualization showing
which HPC nodes are doing what, right now.

### Backend Addition: Node Telemetry

Add to `coordinator.py` — collect per-node activity from Ray:

```python
import ray

def get_cluster_activity(self) -> list:
    """Get real-time activity for each Ray worker node."""
    nodes = ray.nodes()
    activities = []
    for node in nodes:
        node_id = node["NodeID"][:8]
        # Get tasks running on this node
        resources = node.get("Resources", {})
        resources_used = node.get("ResourcesUsed", {})
        cpu_total = resources.get("CPU", 0)
        cpu_used = resources_used.get("CPU", 0)

        activities.append({
            "node_id": node_id,
            "hostname": node.get("NodeManagerHostname", "unknown"),
            "cpu_total": cpu_total,
            "cpu_used": cpu_used,
            "utilization": cpu_used / max(cpu_total, 1),
            "status": "active" if node["Alive"] else "dead",
            "current_task": None,  # Filled by agent reporting
        })
    return activities
```

Each agent should report what it's currently doing. Add to every agent class:

```python
# In each agent's task methods, update a shared Redis key:
import redis
import json

r = redis.Redis()

def _report_activity(self, node_id: str, activity: str, detail: str):
    """Report current activity to coordinator via Redis."""
    r.setex(
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
```

Example usage in ExplorerAgent:

```python
def generate_evolved(self, population, count, mutation_rate, crossover_rate):
    self._report_activity(
        ray.get_runtime_context().get_node_id()[:8],
        "generating",
        f"Evolving {count} molecules from Gen {population[0].get('generation', '?')}"
    )
    # ... existing code ...
```

### Add to WebSocket broadcast payload

In the generation result dict, add:

```python
"cluster_activity": self.get_cluster_activity(),
"agent_reports": self._get_all_agent_reports(),  # Read from Redis
```

```python
def _get_all_agent_reports(self) -> list:
    """Collect all active agent reports from Redis."""
    import redis
    r = redis.Redis()
    reports = []
    for key in r.scan_iter("agent_activity:*"):
        data = r.get(key)
        if data:
            reports.append(json.loads(data))
    return reports
```

### Frontend: ClusterActivityMap.tsx

```typescript
/**
 * Cluster Activity Map — shows HPC nodes working in real-time.
 *
 * Visual: Grid of node cards, each showing:
 * - Node ID + hostname
 * - CPU utilization bar
 * - Current task with agent icon
 * - Pulsing glow when active
 *
 * Design: Dark cards on a dark background, green pulse = active,
 * similar to a server monitoring dashboard.
 */

import React from "react";
import { motion, AnimatePresence } from "framer-motion";

interface NodeActivity {
  node_id: string;
  hostname: string;
  cpu_total: number;
  cpu_used: number;
  utilization: number;
  status: "active" | "dead";
  agents: AgentReport[];
}

interface AgentReport {
  agent_id: string;
  agent_type: string; // "ExplorerAgent" | "ChemistAgent" | "SafetyAgent" | "SelectorAgent"
  activity: string;
  detail: string;
}

const AGENT_ICONS: Record<string, string> = {
  ExplorerAgent: "🧬",
  ChemistAgent: "🔬",
  SafetyAgent: "⚠️",
  SelectorAgent: "🏆",
};

const AGENT_COLORS: Record<string, string> = {
  ExplorerAgent: "#a78bfa",  // purple
  ChemistAgent: "#34d399",   // green
  SafetyAgent: "#fbbf24",    // amber
  SelectorAgent: "#60a5fa",  // blue
};

interface Props {
  nodes: NodeActivity[];
}

export function ClusterActivityMap({ nodes }: Props) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 p-3">
      {nodes.map((node) => (
        <motion.div
          key={node.node_id}
          className="relative rounded-lg border p-3"
          style={{
            background: "rgba(255,255,255,0.02)",
            borderColor: node.status === "active"
              ? "rgba(52, 211, 153, 0.3)"
              : "rgba(255,255,255,0.05)",
          }}
          animate={{
            boxShadow: node.utilization > 0.5
              ? [
                  "0 0 0px rgba(52, 211, 153, 0)",
                  "0 0 12px rgba(52, 211, 153, 0.3)",
                  "0 0 0px rgba(52, 211, 153, 0)",
                ]
              : "none",
          }}
          transition={{ repeat: Infinity, duration: 2 }}
        >
          {/* Header */}
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-mono text-white/80">
              {node.hostname}
            </span>
            <span className="text-[10px] text-white/40">{node.node_id}</span>
          </div>

          {/* CPU Bar */}
          <div className="h-1.5 bg-white/5 rounded-full mb-2 overflow-hidden">
            <motion.div
              className="h-full rounded-full"
              style={{
                background: node.utilization > 0.8
                  ? "#ef4444"
                  : node.utilization > 0.5
                  ? "#fbbf24"
                  : "#34d399",
              }}
              animate={{ width: `${node.utilization * 100}%` }}
              transition={{ duration: 0.5 }}
            />
          </div>
          <div className="text-[10px] text-white/30 mb-2">
            CPU {Math.round(node.utilization * 100)}%
            ({node.cpu_used}/{node.cpu_total} cores)
          </div>

          {/* Agent Tasks */}
          <AnimatePresence mode="popLayout">
            {node.agents.map((agent) => (
              <motion.div
                key={agent.agent_id}
                initial={{ opacity: 0, y: -5 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="flex items-start gap-1.5 mb-1"
              >
                <span className="text-xs">{AGENT_ICONS[agent.agent_type] || "🤖"}</span>
                <div className="min-w-0">
                  <span
                    className="text-[10px] font-medium block"
                    style={{ color: AGENT_COLORS[agent.agent_type] || "#fff" }}
                  >
                    {agent.activity}
                  </span>
                  <span className="text-[9px] text-white/30 block truncate">
                    {agent.detail}
                  </span>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        </motion.div>
      ))}
    </div>
  );
}
```

### Updated Dashboard Layout

The cluster map should go below the header, above the main visualization:

```
┌─────────────────────────────────────────────────────────┐
│ Header: Stats + Controls + "Launch Swarm" button         │
├─────────────────────────────────────────────────────────┤
│ Cluster Activity Map (4-10 node cards in a row)          │
│ [Node1: 🧬generating] [Node2: 🔬scoring] [Node3: ⚠️check] │
├──────────────────────────┬──────────────────────────────┤
│                          │ Molecule 3D Viewer            │
│  Chemical Space          ├──────────────────────────────┤
│  (UMAP Point Cloud)      │ Fitness Graph                │
│  HERO VISUAL             ├──────────────────────────────┤
│                          │ Leaderboard                  │
└──────────────────────────┴──────────────────────────────┘
```

Updated App.tsx grid:

```typescript
<div className="h-screen w-screen bg-[#0a0a0f] text-white flex flex-col">
  {/* Header */}
  <header className="h-14 border-b border-white/10 ...">
    {/* ... same as before ... */}
  </header>

  {/* Cluster Activity Map — NEW */}
  <div className="h-28 border-b border-white/10 overflow-hidden">
    <ClusterActivityMap nodes={state.clusterNodes} />
  </div>

  {/* Main Visualization Grid */}
  <div className="flex-1 grid grid-cols-3 grid-rows-3 gap-px bg-white/5">
    {/* ... same as before ... */}
  </div>
</div>
```

---

## Agent Chat Log Component

Simulated "conversation" between agents. This is pure storytelling gold.

### Backend: Add event stream

In each agent, emit events to a Redis stream:

```python
def _emit_event(self, event_type: str, message: str):
    """Emit a log event for the frontend agent chat."""
    r.xadd("agent_events", {
        "agent_type": self.__class__.__name__,
        "agent_id": self.agent_id,
        "event_type": event_type,
        "message": message,
        "timestamp": time.time(),
    }, maxlen=200)  # Keep last 200 events
```

Example events from each agent type:

```python
# ExplorerAgent
self._emit_event("generation", f"Generated 25 candidates from Gen {gen} elite pool")
self._emit_event("mutation", f"Crossover produced high-potential scaffold: {smiles[:30]}...")

# ChemistAgent
self._emit_event("scoring", f"Batch scored — top hit: {best_score:.3f} binding affinity")
self._emit_event("discovery", f"New record! Molecule {mol_id} scores {score:.3f}")

# SafetyAgent
self._emit_event("alert", f"Flagged 3 PAINS alerts in batch of 50")
self._emit_event("cleared", f"Batch of 47 molecules passed safety screening")

# SelectorAgent
self._emit_event("selection", f"Gen {gen} complete — elite pool fitness: {avg:.3f} avg")
self._emit_event("leaderboard", f"New #1 candidate! Fitness {fitness:.4f}")
```

### Frontend: AgentChatLog.tsx

```typescript
import React, { useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";

interface AgentEvent {
  agent_type: string;
  agent_id: string;
  event_type: string;
  message: string;
  timestamp: number;
}

const AGENT_CONFIG: Record<string, { icon: string; color: string; label: string }> = {
  ExplorerAgent: { icon: "🧬", color: "#a78bfa", label: "Explorer" },
  ChemistAgent: { icon: "🔬", color: "#34d399", label: "Chemist" },
  SafetyAgent: { icon: "⚠️", color: "#fbbf24", label: "Safety" },
  SelectorAgent: { icon: "🏆", color: "#60a5fa", label: "Selector" },
};

export function AgentChatLog({ events }: { events: AgentEvent[] }) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events]);

  return (
    <div
      ref={scrollRef}
      className="h-full overflow-y-auto p-3 space-y-1.5"
      style={{ scrollBehavior: "smooth" }}
    >
      <AnimatePresence initial={false}>
        {events.slice(-30).map((evt, i) => {
          const config = AGENT_CONFIG[evt.agent_type] || {
            icon: "🤖", color: "#888", label: "Agent"
          };
          return (
            <motion.div
              key={`${evt.timestamp}-${i}`}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              className="flex items-start gap-2 text-xs"
            >
              <span>{config.icon}</span>
              <span
                className="font-medium shrink-0"
                style={{ color: config.color }}
              >
                {config.label}-{evt.agent_id.slice(0, 4)}
              </span>
              <span className="text-white/60">{evt.message}</span>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
```

---

## Demo Prep Checklist

Things to do BEFORE the presentation:

```bash
# 1. Submit SLURM job 30-45 min early
sbatch submit.sh

# 2. Verify Ray cluster is up
ray status  # Should show all nodes

# 3. Test WebSocket connection
# Open frontend, verify "Launch Swarm" button connects

# 4. Have demo_mode.py ready as fallback
# If SLURM queue is backed up, run locally:
python demo_mode.py

# 5. Pre-record a backup video
# Screen record a full run in case everything fails live

# 6. Pre-compute one Vina docking result
# Have one validated molecule to show as "scientific validation"
# Run this the night before:
python validate_with_vina.py --top-candidates 5
```

### validate_with_vina.py (run separately, not during demo)

```python
"""
Validate top candidates with real AutoDock Vina docking.
Run overnight or before the demo — NOT during live presentation.
"""

from vina import Vina
from rdkit import Chem
from rdkit.Chem import AllChem
import json

def dock_molecule(smiles: str, receptor_pdb: str = "6LU7_prepared.pdbqt"):
    """Run AutoDock Vina docking for a single molecule."""
    # Generate 3D conformer
    mol = Chem.MolFromSmiles(smiles)
    mol = Chem.AddHs(mol)
    AllChem.EmbedMolecule(mol, randomSeed=42)
    AllChem.MMFFOptimizeMolecule(mol)

    # Save as PDBQT (Vina input format)
    ligand_pdb = Chem.MolToPDBBlock(mol)
    # ... convert to PDBQT using meeko or openbabel ...

    v = Vina(sf_name="vina")
    v.set_receptor(receptor_pdb)
    v.set_ligand_from_string(ligand_pdbqt)

    # Active site box for Mpro (known coordinates)
    v.compute_vina_maps(
        center=[-10.9, 15.5, 68.8],
        box_size=[20, 20, 20],
    )

    v.dock(exhaustiveness=8, n_poses=5)
    energies = v.energies()

    return {
        "smiles": smiles,
        "best_affinity_kcal": energies[0][0],
        "poses": len(energies),
    }


if __name__ == "__main__":
    # Load top candidates from swarm run
    with open("leaderboard.json") as f:
        top_mols = json.load(f)

    results = []
    for mol in top_mols[:5]:
        print(f"Docking {mol['smiles']}...")
        result = dock_molecule(mol["smiles"])
        results.append(result)
        print(f"  Affinity: {result['best_affinity_kcal']:.2f} kcal/mol")

    with open("vina_validation.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nValidation complete! Show these results during demo.")
```

---

## Presentation Script (2-minute demo)

Use this narrative flow:

**0:00 — Hook**
"We built a swarm of AI scientists that runs on a supercomputer to discover
potential drug candidates."

**0:15 — Launch**
Click "Launch Swarm." Point to cluster activity map.
"Right now, [N] nodes are spinning up across the cluster. Each node runs
dozens of specialized agents."

**0:30 — Generation 1**
"Generation 1 — our Explorer agents generate random molecules. The Chemist
agents score their binding potential. Safety agents filter toxins."
Point to UMAP cloud filling in randomly.

**0:45 — Evolution**
"Now watch — each generation, the swarm evolves. Mutations. Crossover.
Survival of the fittest."
Point to UMAP cloud starting to cluster.

**1:00 — Convergence**
"By generation 10, the swarm has explored thousands of molecules and
converged on promising regions of chemical space."
Point to tight clusters in UMAP. Show fitness graph climbing.

**1:15 — Top Candidate**
Click the #1 molecule on the leaderboard.
"Our top candidate — [show 3D viewer]. This molecule was discovered by the
swarm, not designed by a human."

**1:30 — Validation**
"We validated our top 5 candidates with AutoDock Vina molecular docking.
[Show pre-computed results]. Binding affinity of [X] kcal/mol — competitive
with published inhibitors."

**1:45 — Scale**
"In total, the swarm explored [N,000] molecules across [M] generations
in [T] minutes. On a laptop, this would take hours."

**2:00 — Close**
"This is what happens when you give AI agents access to a supercomputer."
