"""
FastAPI router exposing A2A (Agent-to-Agent) endpoints for the drug discovery swarm.

Endpoints:
  POST /a2a/submit          — accepts SHARP-enriched FHIR patient context, starts a run
  GET  /a2a/run/{run_id}    — poll run status
  GET  /a2a/results/{run_id} — retrieve completed results + FHIR bundle
"""

import asyncio
import uuid
import json
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from a2a.models import SubmitRequest, RunResult
from a2a import run_store
from a2a.fhir_extractor import extract_patient_context
from a2a.target_resolver import resolve_target

router = APIRouter()


# ──────────────────────────────────────────────
# POST /a2a/submit
# ──────────────────────────────────────────────
@router.post("/a2a/submit", status_code=202)
async def submit(request: Request, body: SubmitRequest, background_tasks: BackgroundTasks):
    """
    Accept a FHIR patient context via SHARP extension headers + request body.
    Starts an async discovery run and returns a run_id for polling.
    """
    # Read SHARP extension headers (propagated by Prompt Opinion platform)
    sharp_patient = request.headers.get("X-FHIR-Patient", "")
    sharp_server = request.headers.get("X-FHIR-Server", "")
    sharp_token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()

    # Prefer header values over body values (SHARP spec precedence)
    patient_ctx = body.patient_context
    if sharp_patient:
        patient_ctx.fhir_patient_id = sharp_patient
    if sharp_server:
        patient_ctx.fhir_server_url = sharp_server
    if sharp_token:
        patient_ctx.sharp_access_token = sharp_token

    run_id = str(uuid.uuid4())

    # Persist initial accepted state immediately
    run_store.create_run(run_id, body.task_id, patient_ctx.fhir_patient_id)

    # Fire and forget — background task runs the full pipeline
    background_tasks.add_task(
        _run_pipeline,
        run_id=run_id,
        patient_fhir_id=patient_ctx.fhir_patient_id,
        fhir_server_url=patient_ctx.fhir_server_url,
        access_token=patient_ctx.sharp_access_token,
        discovery_config=body.discovery_config.model_dump(),
    )

    return {
        "run_id": run_id,
        "task_id": body.task_id,
        "status": "accepted",
        "poll_url": f"/a2a/run/{run_id}",
        "results_url": f"/a2a/results/{run_id}",
    }


# ──────────────────────────────────────────────
# GET /a2a/run/{run_id}
# ──────────────────────────────────────────────
@router.get("/a2a/run/{run_id}")
async def get_run_status(run_id: str):
    result = run_store.get_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return {
        "run_id": result.run_id,
        "status": result.status,
        "generation": result.generation,
        "best_fitness": result.best_fitness,
        "target_resolved": result.target_resolved,
        "patient_fhir_id": result.patient_fhir_id,
    }


# ──────────────────────────────────────────────
# GET /a2a/results/{run_id}
# ──────────────────────────────────────────────
@router.get("/a2a/results/{run_id}")
async def get_results(run_id: str):
    result = run_store.get_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if result.status not in ("complete", "failed"):
        raise HTTPException(
            status_code=202,
            detail=f"Run {run_id} is still {result.status}. Poll /a2a/run/{run_id} until status=complete.",
        )
    return result.model_dump()


# ──────────────────────────────────────────────
# Background pipeline
# ──────────────────────────────────────────────
async def _run_pipeline(
    run_id: str,
    patient_fhir_id: str,
    fhir_server_url: str,
    access_token: str,
    discovery_config: dict,
):
    """
    Full A2A discovery pipeline:
    1. Extract FHIR patient context
    2. Resolve drug target (lookup → Claude Haiku fallback)
    3. Run evolutionary swarm with per-target scoring weights
    """
    try:
        # Step 1: FHIR extraction
        patient = await extract_patient_context(patient_fhir_id, fhir_server_url, access_token)

        # Step 2: Target resolution
        target = resolve_target(patient)
        run_store.update_run(run_id, 0, 0.0, target.protein)

        # Build target_context dict passed to coordinator
        target_context = {
            "patient_fhir_id": patient_fhir_id,
            "target_resolved": target.protein,
            "disease_context": patient.condition_name or ", ".join(patient.condition_codes),
            "scoring_bias": target.scoring_bias,
            "current_medications": patient.current_medications,
        }

        # Step 3: Run swarm (uses the app-level singleton coordinator)
        from main import coordinator
        max_gen = discovery_config.get("max_generations", 20)

        async for _ in coordinator.run(
            run_id=run_id,
            target_context=target_context,
            max_generations=max_gen,
        ):
            # Results streamed to run_store inside coordinator.run()
            pass

    except Exception as exc:
        run_store.fail_run(run_id, str(exc))
        raise
