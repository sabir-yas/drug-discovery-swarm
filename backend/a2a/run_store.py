"""
Redis-backed run state store for A2A discovery runs.
Keys: a2a:run:{run_id}  (JSON blob, 24h TTL)
"""

import json
import time
import redis
import os
from a2a.models import RunResult, CandidateMolecule

_TTL_SECONDS = 86400  # 24 hours


def _get_redis() -> redis.Redis:
    url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    return redis.Redis.from_url(url, decode_responses=True)


def create_run(run_id: str, task_id: str, patient_fhir_id: str) -> RunResult:
    result = RunResult(
        run_id=run_id,
        task_id=task_id,
        status="accepted",
        patient_fhir_id=patient_fhir_id,
    )
    r = _get_redis()
    r.setex(f"a2a:run:{run_id}", _TTL_SECONDS, result.model_dump_json())
    return result


def update_run(run_id: str, generation: int, best_fitness: float, target_resolved: str = None):
    r = _get_redis()
    raw = r.get(f"a2a:run:{run_id}")
    if not raw:
        return
    result = RunResult.model_validate_json(raw)
    result.status = "running"
    result.generation = generation
    result.best_fitness = best_fitness
    if target_resolved:
        result.target_resolved = target_resolved
    r.setex(f"a2a:run:{run_id}", _TTL_SECONDS, result.model_dump_json())


def complete_run(run_id: str, leaderboard: list, disease_context: str = None, fhir_bundle: dict = None):
    r = _get_redis()
    raw = r.get(f"a2a:run:{run_id}")
    if not raw:
        return
    result = RunResult.model_validate_json(raw)
    result.status = "complete"
    result.disease_context = disease_context

    # Build ranked candidate list from leaderboard (top 10)
    candidates = []
    for i, mol in enumerate(leaderboard[:10]):
        candidates.append(CandidateMolecule(
            rank=i + 1,
            id=mol.get("id", ""),
            smiles=mol.get("smiles", ""),
            fitness=mol.get("fitness", 0.0),
            binding_score=mol.get("binding_score", 0.0),
            drug_likeness=mol.get("drug_likeness", 0.0),
            toxicity_flag=mol.get("toxicity_flag", False),
            generation_found=mol.get("generation", 0),
        ))
    result.top_candidates = candidates
    result.fhir_medication_request_bundle = fhir_bundle
    r.setex(f"a2a:run:{run_id}", _TTL_SECONDS, result.model_dump_json())


def fail_run(run_id: str, error: str):
    r = _get_redis()
    raw = r.get(f"a2a:run:{run_id}")
    if not raw:
        return
    result = RunResult.model_validate_json(raw)
    result.status = "failed"
    result.error = error
    r.setex(f"a2a:run:{run_id}", _TTL_SECONDS, result.model_dump_json())


def get_run(run_id: str) -> RunResult | None:
    r = _get_redis()
    raw = r.get(f"a2a:run:{run_id}")
    if not raw:
        return None
    return RunResult.model_validate_json(raw)
