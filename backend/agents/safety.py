"""
⚠️ Safety Agent — Checks toxicity and drug safety.
Uses structural alerts (PAINS filters) and property-based rules.
"""

import ray
import uuid
import json
import redis
from rdkit import Chem
from rdkit.Chem import Descriptors
from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams

@ray.remote
class SafetyAgent:
    def __init__(self):
        self.agent_id = str(uuid.uuid4())[:8]
        import os
        self.r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
        params = FilterCatalogParams()
        params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS)
        self.pains_catalog = FilterCatalog(params)

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

    def check_toxicity(
        self,
        molecules: list,
        binding_weight: float = None,
        drug_likeness_weight: float = None,
        toxicity_penalty_weight: float = None,
    ) -> list:
        node_id = ray.get_runtime_context().get_node_id()[:8]
        self._report_activity(node_id, "checking", f"Screening {len(molecules)} molecules for toxicity")

        results = []
        alerts_found = 0
        for mol_data in molecules:
            try:
                mol = Chem.MolFromSmiles(mol_data["smiles"])
                if mol is None:
                    continue

                has_pains = self.pains_catalog.HasMatch(mol)

                toxic_smarts = [
                    "[N+](=O)[O-]",     # nitro group
                    "[SH]",              # thiol
                    "C(=O)Cl",           # acyl chloride
                    "[N;H0](=O)",        # nitroso
                    "C1(=O)OC(=O)C1",   # anhydride
                    "[N][N][O][P][Cl]",  # diazo-phosphorochloride (reactive warhead)
                    "[C]#[S]",           # thioalkyne (chemically exotic)
                ]
                has_toxic_group = any(
                    mol.HasSubstructMatch(Chem.MolFromSmarts(s))
                    for s in toxic_smarts
                    if Chem.MolFromSmarts(s) is not None
                )

                mol_data["toxicity_flag"] = has_pains or has_toxic_group
                mol_data["pains_alert"] = has_pains
                mol_data["toxic_group_alert"] = has_toxic_group
                
                if mol_data["toxicity_flag"]:
                    alerts_found += 1

                from config import BINDING_WEIGHT, DRUG_LIKENESS_WEIGHT, TOXICITY_PENALTY_WEIGHT
                bw = binding_weight if binding_weight is not None else BINDING_WEIGHT
                dlw = drug_likeness_weight if drug_likeness_weight is not None else DRUG_LIKENESS_WEIGHT
                tpw = toxicity_penalty_weight if toxicity_penalty_weight is not None else TOXICITY_PENALTY_WEIGHT
                toxicity_penalty = 0.5 if mol_data["toxicity_flag"] else 0.0
                mol_data["fitness"] = round(
                    bw * mol_data["binding_score"]
                    + dlw * mol_data["drug_likeness"]
                    - tpw * toxicity_penalty,
                    4,
                )

                results.append(mol_data)
            except Exception:
                continue

        safe_count = len(results) - alerts_found
        pass_rate = round(safe_count / len(results) * 100, 1) if results else 0
        if alerts_found > 0:
            self._emit_event("alert", f"Flagged {alerts_found}/{len(results)} — {pass_rate}% safe pass rate")
        else:
            self._emit_event("cleared", f"Batch cleared — {pass_rate}% safe pass rate ({safe_count}/{len(results)})")

        return results
