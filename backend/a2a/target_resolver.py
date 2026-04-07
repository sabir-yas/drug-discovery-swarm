"""
Resolves a patient's gene variants and disease context to a drug target.

Fast path: lookup table of known rare disease gene → target mappings.
Fallback: Claude Haiku API for novel or unlisted gene variants.
"""

import json
import os
from a2a.models import PatientTargetContext, TargetResolution

# Known rare disease gene → drug target mappings
# scoring_bias overrides coordinator's default weights for per-target optimization
GENE_TO_TARGET: dict[str, dict] = {
    "GBA1": {
        "protein": "Glucocerebrosidase (GCase)",
        "mechanism": "enzyme_chaperone_enhancement",
        "binding_site": "active_site_tunnel",
        "scoring_bias": {"binding_weight": 0.45, "drug_likeness_weight": 0.40, "toxicity_penalty_weight": 0.15},
    },
    "CFTR": {
        "protein": "Cystic Fibrosis Transmembrane Conductance Regulator",
        "mechanism": "channel_potentiation",
        "binding_site": "nucleotide_binding_domain_2",
        "scoring_bias": {"binding_weight": 0.55, "drug_likeness_weight": 0.30, "toxicity_penalty_weight": 0.15},
    },
    "HEXA": {
        "protein": "Hexosaminidase A alpha subunit",
        "mechanism": "enzyme_chaperone",
        "binding_site": "catalytic_pocket",
        "scoring_bias": {"binding_weight": 0.50, "drug_likeness_weight": 0.35, "toxicity_penalty_weight": 0.15},
    },
    "HEXB": {
        "protein": "Hexosaminidase B beta subunit",
        "mechanism": "enzyme_chaperone",
        "binding_site": "catalytic_pocket",
        "scoring_bias": {"binding_weight": 0.50, "drug_likeness_weight": 0.35, "toxicity_penalty_weight": 0.15},
    },
    "PCSK9": {
        "protein": "Proprotein Convertase Subtilisin/Kexin 9",
        "mechanism": "inhibition",
        "binding_site": "catalytic_domain",
        "scoring_bias": {"binding_weight": 0.60, "drug_likeness_weight": 0.25, "toxicity_penalty_weight": 0.15},
    },
    "ASAH1": {
        "protein": "Acid ceramidase",
        "mechanism": "enzyme_replacement_chaperone",
        "binding_site": "active_site",
        "scoring_bias": {"binding_weight": 0.50, "drug_likeness_weight": 0.35, "toxicity_penalty_weight": 0.15},
    },
    "SMPD1": {
        "protein": "Sphingomyelin phosphodiesterase 1 (acid sphingomyelinase)",
        "mechanism": "enzyme_enhancement",
        "binding_site": "active_site",
        "scoring_bias": {"binding_weight": 0.50, "drug_likeness_weight": 0.35, "toxicity_penalty_weight": 0.15},
    },
    "GAA": {
        "protein": "Acid alpha-glucosidase",
        "mechanism": "enzyme_chaperone",
        "binding_site": "active_site",
        "scoring_bias": {"binding_weight": 0.50, "drug_likeness_weight": 0.35, "toxicity_penalty_weight": 0.15},
    },
    "IDUA": {
        "protein": "Alpha-L-iduronidase",
        "mechanism": "enzyme_chaperone",
        "binding_site": "active_site",
        "scoring_bias": {"binding_weight": 0.50, "drug_likeness_weight": 0.35, "toxicity_penalty_weight": 0.15},
    },
    "IDS": {
        "protein": "Iduronate-2-sulfatase",
        "mechanism": "enzyme_chaperone",
        "binding_site": "active_site",
        "scoring_bias": {"binding_weight": 0.50, "drug_likeness_weight": 0.35, "toxicity_penalty_weight": 0.15},
    },
}

_DEFAULT_BIAS = {"binding_weight": 0.50, "drug_likeness_weight": 0.30, "toxicity_penalty_weight": 0.20}


def _llm_resolve(gene: str, variant: str, condition_name: str) -> TargetResolution:
    """Call Claude Haiku to resolve an unknown gene variant to a drug target."""
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    prompt = (
        f"A patient has a rare genetic disease. Gene: {gene}, Variant: {variant or 'unknown'}, "
        f"Condition: {condition_name or 'unknown rare disease'}.\n"
        "What is the most drugable protein target and binding mechanism for a small molecule drug? "
        'Respond ONLY with valid JSON in this exact format: {"protein": "...", "mechanism": "...", "binding_site": "..."}'
    )
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw)
    return TargetResolution(
        gene=gene,
        protein=data.get("protein", gene),
        mechanism=data.get("mechanism", "unknown"),
        binding_site=data.get("binding_site", "active_site"),
        scoring_bias=_DEFAULT_BIAS,
        source="llm",
    )


def resolve_target(patient: PatientTargetContext) -> TargetResolution:
    """
    Return a TargetResolution for the patient's primary gene variant.
    Tries the lookup table first; falls back to Claude Haiku if not found.
    """
    # Try each gene variant in priority order
    for gv in patient.gene_variants:
        gene = gv.gene.upper()
        if gene in GENE_TO_TARGET:
            entry = GENE_TO_TARGET[gene]
            return TargetResolution(
                gene=gene,
                protein=entry["protein"],
                mechanism=entry["mechanism"],
                binding_site=entry["binding_site"],
                scoring_bias=entry["scoring_bias"],
                source="lookup",
            )

    # No known gene — try LLM fallback if API key is available
    if patient.gene_variants and os.environ.get("ANTHROPIC_API_KEY"):
        gv = patient.gene_variants[0]
        try:
            return _llm_resolve(gv.gene, gv.variant or "", patient.condition_name or "")
        except Exception:
            pass

    # Last resort: generic target with default weights
    gene_label = patient.gene_variants[0].gene if patient.gene_variants else "unknown"
    return TargetResolution(
        gene=gene_label,
        protein=f"{gene_label} protein target",
        mechanism="inhibition",
        binding_site="active_site",
        scoring_bias=_DEFAULT_BIAS,
        source="default",
    )
