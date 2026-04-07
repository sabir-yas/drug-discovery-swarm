"""
Async FHIR R4 client that extracts patient context for drug target resolution.

Set FHIR_MOCK=true in the environment to return a hardcoded Gaucher Disease
patient (GBA1 N370S/L444P, ORPHA:93100) — used for demo/hackathon runs.
"""

import os
import httpx
from a2a.models import PatientTargetContext, GeneVariant

_MOCK_PATIENT = PatientTargetContext(
    fhir_patient_id="Patient/gaucher-demo-001",
    fhir_server_url="mock",
    sharp_access_token="mock",
    condition_codes=["ORPHA:93100", "ICD-10:E75.22"],
    condition_name="Gaucher Disease Type 1",
    gene_variants=[
        GeneVariant(gene="GBA1", variant="N370S", zygosity="heterozygous"),
        GeneVariant(gene="GBA1", variant="L444P", zygosity="heterozygous"),
    ],
    current_medications=["miglustat", "taliglucerase alfa"],
    allergy_codes=[],
)


async def extract_patient_context(
    fhir_patient_id: str,
    fhir_server_url: str,
    access_token: str,
) -> PatientTargetContext:
    """
    Fetch FHIR R4 resources for the patient and return a PatientTargetContext.
    Falls back to mock data if FHIR_MOCK=true or no real server is available.
    """
    if os.environ.get("FHIR_MOCK", "false").lower() == "true" or fhir_server_url == "mock":
        return _MOCK_PATIENT

    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/fhir+json"}
    patient_id = fhir_patient_id.replace("Patient/", "")

    condition_codes: list[str] = []
    condition_name: str = ""
    gene_variants: list[GeneVariant] = []
    current_medications: list[str] = []
    allergy_codes: list[str] = []

    async with httpx.AsyncClient(base_url=fhir_server_url, headers=headers, timeout=10.0) as client:

        # Conditions (ICD-10 / ORPHA / SNOMED)
        try:
            resp = await client.get(
                f"/Condition?patient={patient_id}&category=problem-list-item&clinical-status=active"
            )
            if resp.status_code == 200:
                bundle = resp.json()
                for entry in bundle.get("entry", []):
                    resource = entry.get("resource", {})
                    cc = resource.get("code", {})
                    # Prefer ORPHA then ICD-10 then SNOMED display text
                    for coding in cc.get("coding", []):
                        system = coding.get("system", "")
                        code = coding.get("code", "")
                        if code:
                            if "orpha" in system.lower():
                                condition_codes.append(f"ORPHA:{code}")
                            elif "icd" in system.lower():
                                condition_codes.append(f"ICD-10:{code}")
                            elif "snomed" in system.lower():
                                condition_codes.append(f"SNOMED:{code}")
                    if not condition_name and cc.get("text"):
                        condition_name = cc["text"]
        except Exception:
            pass

        # MolecularSequence — gene variants (HGVS)
        try:
            resp = await client.get(f"/MolecularSequence?patient={patient_id}&type=DNA")
            if resp.status_code == 200:
                bundle = resp.json()
                for entry in bundle.get("entry", []):
                    resource = entry.get("resource", {})
                    for variant in resource.get("variant", []):
                        gene_name = ""
                        # Try to extract gene from referenceSeqId or observedSeq
                        ref_seq = resource.get("referenceSeq", {})
                        ref_id = ref_seq.get("referenceSeqId", {})
                        for coding in ref_id.get("coding", []):
                            if coding.get("display"):
                                # e.g. "NM_001005741.3 (GBA1)"
                                display = coding["display"]
                                if "(" in display and ")" in display:
                                    gene_name = display.split("(")[-1].rstrip(")")
                        hgvs = variant.get("observedAllele", "")
                        if gene_name:
                            gene_variants.append(GeneVariant(gene=gene_name, variant=hgvs or None))
        except Exception:
            pass

        # Active MedicationRequests
        try:
            resp = await client.get(f"/MedicationRequest?patient={patient_id}&status=active")
            if resp.status_code == 200:
                bundle = resp.json()
                for entry in bundle.get("entry", []):
                    resource = entry.get("resource", {})
                    med = resource.get("medicationCodeableConcept", {})
                    text = med.get("text", "")
                    if text:
                        current_medications.append(text)
                    else:
                        for coding in med.get("coding", []):
                            if coding.get("display"):
                                current_medications.append(coding["display"])
                                break
        except Exception:
            pass

        # AllergyIntolerance
        try:
            resp = await client.get(f"/AllergyIntolerance?patient={patient_id}")
            if resp.status_code == 200:
                bundle = resp.json()
                for entry in bundle.get("entry", []):
                    resource = entry.get("resource", {})
                    substance = resource.get("code", {})
                    for coding in substance.get("coding", []):
                        if coding.get("code"):
                            allergy_codes.append(coding["code"])
        except Exception:
            pass

    return PatientTargetContext(
        fhir_patient_id=fhir_patient_id,
        fhir_server_url=fhir_server_url,
        sharp_access_token=access_token,
        condition_codes=condition_codes,
        condition_name=condition_name,
        gene_variants=gene_variants,
        current_medications=current_medications,
        allergy_codes=allergy_codes,
    )
