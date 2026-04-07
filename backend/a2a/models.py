"""
Pydantic models for the A2A (Agent-to-Agent) layer.
These define the data contracts for FHIR input, run state, and result output.
"""

from typing import Optional
from pydantic import BaseModel


class GeneVariant(BaseModel):
    gene: str
    variant: Optional[str] = None
    zygosity: Optional[str] = None


class PatientTargetContext(BaseModel):
    fhir_patient_id: str
    fhir_server_url: str
    sharp_access_token: str
    condition_codes: list[str] = []
    condition_name: Optional[str] = None
    gene_variants: list[GeneVariant] = []
    current_medications: list[str] = []
    allergy_codes: list[str] = []


class DiscoveryConfig(BaseModel):
    max_generations: int = 20
    target_hint: Optional[str] = None


class SubmitRequest(BaseModel):
    task_id: str
    patient_context: PatientTargetContext
    discovery_config: DiscoveryConfig = DiscoveryConfig()


class TargetResolution(BaseModel):
    gene: str
    protein: str
    mechanism: str
    binding_site: str
    scoring_bias: dict = {}
    source: str = "lookup"  # "lookup" or "llm"


class CandidateMolecule(BaseModel):
    rank: int
    id: str
    smiles: str
    fitness: float
    binding_score: float
    drug_likeness: float
    toxicity_flag: bool
    generation_found: int
    drug_interaction_note: Optional[str] = None


class RunResult(BaseModel):
    run_id: str
    task_id: str
    status: str  # "accepted" | "running" | "complete" | "failed"
    generation: int = 0
    best_fitness: float = 0.0
    patient_fhir_id: str = ""
    target_resolved: Optional[str] = None
    disease_context: Optional[str] = None
    top_candidates: list[CandidateMolecule] = []
    fhir_medication_request_bundle: Optional[dict] = None
    error: Optional[str] = None
