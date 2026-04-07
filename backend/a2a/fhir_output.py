"""
Builds a FHIR R4 MedicationRequest bundle from the top drug candidate molecules.
Output is a draft proposal — not for direct clinical use without wet-lab validation.
"""

import uuid
from a2a.models import CandidateMolecule


def build_medication_request_bundle(
    patient_fhir_id: str,
    run_id: str,
    target_protein: str,
    disease_context: str,
    top_candidates: list[CandidateMolecule],
    current_medications: list[str] = [],
) -> dict:
    """
    Returns a FHIR R4 Bundle (collection) of MedicationRequest draft resources,
    one per top candidate molecule.
    """
    entries = []
    for candidate in top_candidates[:3]:  # Top 3 in bundle
        interaction_note = _check_interaction(candidate.smiles, current_medications)
        request_id = str(uuid.uuid4())
        entries.append({
            "fullUrl": f"urn:uuid:{request_id}",
            "resource": {
                "resourceType": "MedicationRequest",
                "id": request_id,
                "status": "draft",
                "intent": "proposal",
                "subject": {"reference": patient_fhir_id},
                "medication": {
                    "concept": {
                        "text": f"AI candidate molecule (SMILES: {candidate.smiles})"
                    }
                },
                "note": [
                    {
                        "text": (
                            f"Rank #{candidate.rank} AI-generated drug candidate from swarm optimization. "
                            f"Fitness: {candidate.fitness:.3f}. "
                            f"Binding score: {candidate.binding_score:.3f}. "
                            f"Drug-likeness: {candidate.drug_likeness:.3f}. "
                            f"Found in generation {candidate.generation_found}. "
                            f"Toxicity flag: {candidate.toxicity_flag}. "
                            "REQUIRES wet-lab validation before any clinical use."
                        )
                    },
                    *(
                        [{"text": f"Drug interaction note: {interaction_note}"}]
                        if interaction_note else []
                    ),
                ],
                "extension": [
                    {
                        "url": "http://drug-discovery-swarm.ai/fhir/StructureDefinition/discovery-run-id",
                        "valueString": run_id,
                    },
                    {
                        "url": "http://drug-discovery-swarm.ai/fhir/StructureDefinition/target-protein",
                        "valueString": target_protein,
                    },
                    {
                        "url": "http://drug-discovery-swarm.ai/fhir/StructureDefinition/disease-context",
                        "valueString": disease_context or "",
                    },
                    {
                        "url": "http://drug-discovery-swarm.ai/fhir/StructureDefinition/candidate-smiles",
                        "valueString": candidate.smiles,
                    },
                    {
                        "url": "http://drug-discovery-swarm.ai/fhir/StructureDefinition/fitness-score",
                        "valueDecimal": round(candidate.fitness, 4),
                    },
                ],
            },
        })

    return {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "type": "collection",
        "entry": entries,
        "meta": {
            "tag": [
                {
                    "system": "http://drug-discovery-swarm.ai/tags",
                    "code": "ai-generated",
                    "display": "AI-generated drug candidates — not clinically validated",
                }
            ]
        },
    }


def _check_interaction(smiles: str, current_medications: list[str]) -> str:
    """
    Lightweight interaction note. For hackathon scope: flags known substrate classes
    shared with common rare disease drugs (miglustat, ivacaftor, etc.).
    A production system would use a real DDI database.
    """
    notes = []
    smiles_lower = smiles.lower()

    # miglustat (N-butyldeoxynojirimycin) shares iminosugar scaffold
    if "miglustat" in current_medications:
        notes.append("Patient is on miglustat — monitor for additive GI effects if iminosugar scaffold present")

    # ivacaftor / lumacaftor are CYP3A4 substrates — flag if SMILES contains piperidine
    if any(m in current_medications for m in ["ivacaftor", "lumacaftor", "tezacaftor"]):
        if "N1CCCCC1" in smiles or "n1ccccc1" in smiles_lower:
            notes.append("Candidate may share CYP3A4 metabolism with CFTR modulators — pharmacokinetic review recommended")

    return "; ".join(notes) if notes else ""
