"""
🔬 Chemist Agent — Predicts binding affinity.
Uses RDKit descriptors as a fast proxy scorer.
"""

import ray
import uuid
import numpy as np
from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolDescriptors, Crippen
import redis
import json

@ray.remote
class ChemistAgent:
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

    def predict_binding(self, molecules: list) -> list:
        node_id = ray.get_runtime_context().get_node_id()[:8]
        self._report_activity(node_id, "scoring", f"Scoring batch of {len(molecules)}")
        
        best_score = 0.0
        for mol_data in molecules:
            try:
                mol = Chem.MolFromSmiles(mol_data["smiles"])
                if mol is None:
                    mol_data["binding_score"] = 0.0
                    continue

                logp = Crippen.MolLogP(mol)
                logp_score = 1.0 - min(abs(logp - 2.0) / 3.0, 1.0)

                hbd = rdMolDescriptors.CalcNumHBD(mol)
                hba = rdMolDescriptors.CalcNumHBA(mol)
                hbond_score = min(hbd + hba, 10) / 10.0

                rot = rdMolDescriptors.CalcNumRotatableBonds(mol)
                flex_score = 1.0 - min(rot / 10.0, 1.0)

                tpsa = Descriptors.TPSA(mol)
                tpsa_score = 1.0 - min(abs(tpsa - 80) / 60, 1.0)

                rings = rdMolDescriptors.CalcNumRings(mol)
                ring_score = 1.0 - min(abs(rings - 3) / 3.0, 1.0)

                arom = rdMolDescriptors.CalcNumAromaticRings(mol)
                arom_score = min(arom, 3) / 3.0

                binding = (
                    0.25 * logp_score
                    + 0.20 * hbond_score
                    + 0.15 * flex_score
                    + 0.15 * tpsa_score
                    + 0.15 * ring_score
                    + 0.10 * arom_score
                )

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

                score = round(binding, 4)
                mol_data["binding_score"] = score
                mol_data["drug_likeness"] = round(drug_likeness, 4)
                
                if score > best_score:
                    best_score = score
                    if score > 0.8:  # threshold to emit discovery event
                        self._emit_event("discovery", f"New record! Molecule {mol_data['id']} scores {score:.3f}")

            except Exception:
                mol_data["binding_score"] = 0.0
                mol_data["drug_likeness"] = 0.0

        if molecules:
            self._emit_event("scoring", f"Batch scored — top hit: {best_score:.3f} binding affinity")
            
        return molecules
