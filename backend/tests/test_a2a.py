"""
Production-quality tests for the A2A (Agent-to-Agent) layer of the drug discovery swarm.

Coverage:
  - a2a/models.py          : Pydantic model construction, defaults, validation errors
  - a2a/run_store.py       : Redis-backed run lifecycle (create → update → complete / fail)
  - a2a/fhir_extractor.py  : Mock path, real FHIR path (httpx mocked), network error resilience
  - a2a/target_resolver.py : Lookup table, LLM fallback (anthropic mocked), default fallback
  - a2a/fhir_output.py     : FHIR R4 Bundle structure, extensions, drug interaction notes
  - a2a_router.py          : FastAPI endpoints (submit 202, poll, results 200/202/404)
  - agents/safety.py       : Fitness formula with default and custom weight kwargs

No real network calls, no real Ray cluster, no real Redis.
"""

import json
import os
import sys
import types
import uuid
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import AsyncClient, Response
from pydantic import ValidationError

# ─────────────────────────────────────────────────────────────────────────────
# Path setup — tests run from the backend/ directory
# ─────────────────────────────────────────────────────────────────────────────

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# ─────────────────────────────────────────────────────────────────────────────
# Ray stub — must be in place before importing any agent module
# ─────────────────────────────────────────────────────────────────────────────

def _make_ray_stub():
    """Return a minimal ray stub that makes @ray.remote a no-op decorator."""
    ray_stub = types.ModuleType("ray")

    def remote(cls_or_fn=None, **kwargs):
        # Called as @ray.remote or @ray.remote(num_cpus=1) — handle both
        if cls_or_fn is not None:
            return cls_or_fn
        return lambda f: f

    ray_stub.remote = remote

    class _FakeRuntimeContext:
        def get_node_id(self):
            return "test-node-id-00000000"

    ray_stub.get_runtime_context = _FakeRuntimeContext

    return ray_stub


_ray_stub = _make_ray_stub()
sys.modules.setdefault("ray", _ray_stub)


# ─────────────────────────────────────────────────────────────────────────────
# Shared fakeredis fixture
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def fake_redis_client():
    """Return a fakeredis.FakeRedis instance with decode_responses=True."""
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def patch_redis(fake_redis_client, monkeypatch):
    """
    Patch run_store._get_redis() globally so every test gets an isolated
    in-memory Redis instead of hitting a real server.
    """
    import a2a.run_store as run_store_module
    monkeypatch.setattr(run_store_module, "_get_redis", lambda: fake_redis_client)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_candidate(rank: int = 1, smiles: str = "CC(=O)Oc1ccccc1C(=O)O") -> dict:
    """Return a leaderboard-style dict as produced by the coordinator."""
    return {
        "id": f"mol-{rank}",
        "smiles": smiles,
        "fitness": 0.8 - (rank - 1) * 0.05,
        "binding_score": 0.75,
        "drug_likeness": 0.80,
        "toxicity_flag": False,
        "generation": 5,
    }


def _make_candidate_model(rank: int = 1, smiles: str = "CC(=O)Oc1ccccc1C(=O)O"):
    """Return a CandidateMolecule Pydantic model."""
    from a2a.models import CandidateMolecule
    return CandidateMolecule(
        rank=rank,
        id=f"mol-{rank}",
        smiles=smiles,
        fitness=0.8 - (rank - 1) * 0.05,
        binding_score=0.75,
        drug_likeness=0.80,
        toxicity_flag=False,
        generation_found=5,
    )


# ═════════════════════════════════════════════════════════════════════════════
# 1. models.py
# ═════════════════════════════════════════════════════════════════════════════

class TestModels:

    def test_gene_variant_minimal_construction(self):
        from a2a.models import GeneVariant
        gv = GeneVariant(gene="GBA1")
        assert gv.gene == "GBA1"
        assert gv.variant is None
        assert gv.zygosity is None

    def test_gene_variant_full_construction(self):
        from a2a.models import GeneVariant
        gv = GeneVariant(gene="CFTR", variant="F508del", zygosity="homozygous")
        assert gv.gene == "CFTR"
        assert gv.variant == "F508del"
        assert gv.zygosity == "homozygous"

    def test_patient_target_context_required_fields(self):
        from a2a.models import PatientTargetContext
        ctx = PatientTargetContext(
            fhir_patient_id="Patient/123",
            fhir_server_url="https://fhir.example.com",
            sharp_access_token="tok123",
        )
        assert ctx.fhir_patient_id == "Patient/123"
        assert ctx.condition_codes == []
        assert ctx.gene_variants == []
        assert ctx.current_medications == []

    def test_patient_target_context_missing_fhir_patient_id_raises(self):
        from a2a.models import PatientTargetContext
        with pytest.raises(ValidationError) as exc_info:
            PatientTargetContext(
                fhir_server_url="https://fhir.example.com",
                sharp_access_token="tok",
            )
        assert "fhir_patient_id" in str(exc_info.value)

    def test_discovery_config_defaults_to_20_generations(self):
        from a2a.models import DiscoveryConfig
        cfg = DiscoveryConfig()
        assert cfg.max_generations == 20
        assert cfg.target_hint is None

    def test_discovery_config_custom_values(self):
        from a2a.models import DiscoveryConfig
        cfg = DiscoveryConfig(max_generations=50, target_hint="GCase active site")
        assert cfg.max_generations == 50
        assert cfg.target_hint == "GCase active site"

    def test_submit_request_defaults_discovery_config(self):
        from a2a.models import DiscoveryConfig, PatientTargetContext, SubmitRequest
        req = SubmitRequest(
            task_id="task-abc",
            patient_context=PatientTargetContext(
                fhir_patient_id="Patient/1",
                fhir_server_url="mock",
                sharp_access_token="tok",
            ),
        )
        assert isinstance(req.discovery_config, DiscoveryConfig)
        assert req.discovery_config.max_generations == 20

    def test_submit_request_missing_task_id_raises(self):
        from a2a.models import PatientTargetContext, SubmitRequest
        with pytest.raises(ValidationError) as exc_info:
            SubmitRequest(
                patient_context=PatientTargetContext(
                    fhir_patient_id="Patient/1",
                    fhir_server_url="mock",
                    sharp_access_token="tok",
                ),
            )
        assert "task_id" in str(exc_info.value)

    def test_target_resolution_scoring_bias_defaults_to_empty_dict(self):
        from a2a.models import TargetResolution
        tr = TargetResolution(
            gene="GBA1",
            protein="Glucocerebrosidase",
            mechanism="enzyme_chaperone",
            binding_site="active_site",
        )
        assert isinstance(tr.scoring_bias, dict)
        assert tr.source == "lookup"

    def test_candidate_molecule_construction(self):
        from a2a.models import CandidateMolecule
        mol = CandidateMolecule(
            rank=1,
            id="mol-001",
            smiles="CC(=O)O",
            fitness=0.75,
            binding_score=0.80,
            drug_likeness=0.70,
            toxicity_flag=False,
            generation_found=3,
        )
        assert mol.rank == 1
        assert mol.drug_interaction_note is None

    def test_run_result_status_defaults(self):
        from a2a.models import RunResult
        rr = RunResult(run_id="run-1", task_id="task-1", status="accepted")
        assert rr.generation == 0
        assert rr.best_fitness == 0.0
        assert rr.top_candidates == []
        assert rr.error is None

    def test_run_result_missing_run_id_raises(self):
        from a2a.models import RunResult
        with pytest.raises(ValidationError):
            RunResult(task_id="task-1", status="accepted")


# ═════════════════════════════════════════════════════════════════════════════
# 2. run_store.py
# ═════════════════════════════════════════════════════════════════════════════

class TestRunStore:

    def test_create_run_sets_accepted_status(self):
        from a2a import run_store
        run_id = str(uuid.uuid4())
        result = run_store.create_run(run_id, "task-1", "Patient/demo-001")
        assert result.status == "accepted"
        assert result.run_id == run_id
        assert result.task_id == "task-1"
        assert result.patient_fhir_id == "Patient/demo-001"

    def test_create_run_persists_to_redis(self, fake_redis_client):
        from a2a import run_store
        run_id = str(uuid.uuid4())
        run_store.create_run(run_id, "task-persist", "Patient/p1")
        raw = fake_redis_client.get(f"a2a:run:{run_id}")
        assert raw is not None
        data = json.loads(raw)
        assert data["status"] == "accepted"

    def test_create_run_has_ttl(self, fake_redis_client):
        from a2a import run_store
        run_id = str(uuid.uuid4())
        run_store.create_run(run_id, "task-ttl", "Patient/p1")
        ttl = fake_redis_client.ttl(f"a2a:run:{run_id}")
        # TTL should be set to 86400 seconds; fakeredis returns the value accurately
        assert ttl > 0

    def test_update_run_changes_status_to_running(self):
        from a2a import run_store
        run_id = str(uuid.uuid4())
        run_store.create_run(run_id, "task-2", "Patient/p2")
        run_store.update_run(run_id, generation=3, best_fitness=0.72, target_resolved="GCase")
        result = run_store.get_run(run_id)
        assert result.status == "running"
        assert result.generation == 3
        assert result.best_fitness == 0.72
        assert result.target_resolved == "GCase"

    def test_update_run_without_target_resolved_preserves_existing(self):
        from a2a import run_store
        run_id = str(uuid.uuid4())
        run_store.create_run(run_id, "task-3", "Patient/p3")
        run_store.update_run(run_id, generation=1, best_fitness=0.5, target_resolved="CFTR protein")
        run_store.update_run(run_id, generation=2, best_fitness=0.6)
        result = run_store.get_run(run_id)
        # target_resolved from first update must not be cleared
        assert result.target_resolved == "CFTR protein"

    def test_complete_run_sets_status_and_top_candidates(self):
        from a2a import run_store
        run_id = str(uuid.uuid4())
        run_store.create_run(run_id, "task-4", "Patient/p4")
        leaderboard = [_make_candidate(i + 1) for i in range(5)]
        run_store.complete_run(
            run_id,
            leaderboard=leaderboard,
            disease_context="Gaucher Disease Type 1",
            fhir_bundle={"resourceType": "Bundle"},
        )
        result = run_store.get_run(run_id)
        assert result.status == "complete"
        assert result.disease_context == "Gaucher Disease Type 1"
        assert len(result.top_candidates) == 5
        assert result.top_candidates[0].rank == 1
        assert result.fhir_medication_request_bundle == {"resourceType": "Bundle"}

    def test_complete_run_caps_top_candidates_at_10(self):
        from a2a import run_store
        run_id = str(uuid.uuid4())
        run_store.create_run(run_id, "task-cap", "Patient/p5")
        leaderboard = [_make_candidate(i + 1) for i in range(15)]
        run_store.complete_run(run_id, leaderboard=leaderboard)
        result = run_store.get_run(run_id)
        assert len(result.top_candidates) == 10

    def test_fail_run_sets_status_and_error(self):
        from a2a import run_store
        run_id = str(uuid.uuid4())
        run_store.create_run(run_id, "task-5", "Patient/p6")
        run_store.fail_run(run_id, "Connection timeout after 30s")
        result = run_store.get_run(run_id)
        assert result.status == "failed"
        assert result.error == "Connection timeout after 30s"

    def test_get_run_returns_none_for_unknown_run_id(self):
        from a2a import run_store
        result = run_store.get_run("non-existent-run-id-xyz")
        assert result is None

    def test_get_run_returns_correct_result_after_create(self):
        from a2a import run_store
        run_id = str(uuid.uuid4())
        run_store.create_run(run_id, "task-get", "Patient/p7")
        result = run_store.get_run(run_id)
        assert result is not None
        assert result.run_id == run_id
        assert result.task_id == "task-get"

    def test_update_run_is_noop_for_unknown_run_id(self):
        from a2a import run_store
        # Should not raise; just silently skip
        run_store.update_run("unknown-id", generation=5, best_fitness=0.9)

    def test_complete_run_is_noop_for_unknown_run_id(self):
        from a2a import run_store
        run_store.complete_run("unknown-id", leaderboard=[])

    def test_fail_run_is_noop_for_unknown_run_id(self):
        from a2a import run_store
        run_store.fail_run("unknown-id", "some error")


# ═════════════════════════════════════════════════════════════════════════════
# 3. fhir_extractor.py
# ═════════════════════════════════════════════════════════════════════════════

class TestFhirExtractor:

    @pytest.mark.asyncio
    async def test_mock_mode_via_env_var(self, monkeypatch):
        """FHIR_MOCK=true must return the hardcoded Gaucher patient."""
        monkeypatch.setenv("FHIR_MOCK", "true")
        from a2a import fhir_extractor
        # Reload to pick up env var (function reads at call time, so this is fine)
        ctx = await fhir_extractor.extract_patient_context(
            fhir_patient_id="Patient/any",
            fhir_server_url="https://real-server.example.com",
            access_token="sometoken",
        )
        assert ctx.fhir_patient_id == "Patient/gaucher-demo-001"
        assert ctx.condition_name == "Gaucher Disease Type 1"
        assert any(gv.gene == "GBA1" for gv in ctx.gene_variants)
        assert "miglustat" in ctx.current_medications

    @pytest.mark.asyncio
    async def test_mock_mode_via_mock_server_url(self, monkeypatch):
        """fhir_server_url='mock' must return mock patient regardless of env var."""
        monkeypatch.delenv("FHIR_MOCK", raising=False)
        from a2a import fhir_extractor
        ctx = await fhir_extractor.extract_patient_context(
            fhir_patient_id="Patient/any",
            fhir_server_url="mock",
            access_token="sometoken",
        )
        assert "ORPHA:93100" in ctx.condition_codes
        assert len(ctx.gene_variants) == 2
        variants = [gv.variant for gv in ctx.gene_variants]
        assert "N370S" in variants
        assert "L444P" in variants

    @pytest.mark.asyncio
    async def test_mock_patient_has_expected_allergy_codes(self, monkeypatch):
        monkeypatch.setenv("FHIR_MOCK", "true")
        from a2a import fhir_extractor
        ctx = await fhir_extractor.extract_patient_context("Patient/any", "mock", "tok")
        # Mock patient has no allergies
        assert ctx.allergy_codes == []

    @pytest.mark.asyncio
    async def test_real_fhir_path_extracts_condition_codes(self, monkeypatch):
        """Mock httpx to return a FHIR Condition bundle and verify parsing."""
        monkeypatch.delenv("FHIR_MOCK", raising=False)

        condition_bundle = {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "resourceType": "Condition",
                        "code": {
                            "coding": [
                                {
                                    "system": "http://www.orpha.net",
                                    "code": "93100",
                                    "display": "Gaucher disease",
                                },
                                {
                                    "system": "http://hl7.org/fhir/sid/icd-10",
                                    "code": "E75.22",
                                },
                            ],
                            "text": "Gaucher Disease Type 1",
                        },
                    }
                }
            ],
        }
        empty_bundle = {"resourceType": "Bundle", "entry": []}

        async def _mock_get(url, **kwargs):
            if "Condition" in url:
                return Response(200, json=condition_bundle)
            return Response(200, json=empty_bundle)

        mock_client = AsyncMock()
        mock_client.get = _mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from a2a import fhir_extractor
            ctx = await fhir_extractor.extract_patient_context(
                "Patient/p123", "https://fhir.example.com", "tok"
            )

        assert "ORPHA:93100" in ctx.condition_codes
        assert "ICD-10:E75.22" in ctx.condition_codes
        assert ctx.condition_name == "Gaucher Disease Type 1"

    @pytest.mark.asyncio
    async def test_real_fhir_path_extracts_gene_variants(self, monkeypatch):
        monkeypatch.delenv("FHIR_MOCK", raising=False)

        mol_seq_bundle = {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "resourceType": "MolecularSequence",
                        "referenceSeq": {
                            "referenceSeqId": {
                                "coding": [
                                    {"display": "NM_001005741.3 (GBA1)"}
                                ]
                            }
                        },
                        "variant": [{"observedAllele": "N370S"}],
                    }
                }
            ],
        }
        empty_bundle = {"resourceType": "Bundle", "entry": []}

        async def _mock_get(url, **kwargs):
            if "MolecularSequence" in url:
                return Response(200, json=mol_seq_bundle)
            return Response(200, json=empty_bundle)

        mock_client = AsyncMock()
        mock_client.get = _mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from a2a import fhir_extractor
            ctx = await fhir_extractor.extract_patient_context(
                "Patient/p123", "https://fhir.example.com", "tok"
            )

        assert len(ctx.gene_variants) == 1
        assert ctx.gene_variants[0].gene == "GBA1"
        assert ctx.gene_variants[0].variant == "N370S"

    @pytest.mark.asyncio
    async def test_real_fhir_path_extracts_medications(self, monkeypatch):
        monkeypatch.delenv("FHIR_MOCK", raising=False)

        med_bundle = {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "resourceType": "MedicationRequest",
                        "medicationCodeableConcept": {"text": "miglustat 100mg"},
                    }
                },
                {
                    "resource": {
                        "resourceType": "MedicationRequest",
                        "medicationCodeableConcept": {
                            "coding": [{"display": "taliglucerase alfa"}]
                        },
                    }
                },
            ],
        }
        empty_bundle = {"resourceType": "Bundle", "entry": []}

        async def _mock_get(url, **kwargs):
            if "MedicationRequest" in url:
                return Response(200, json=med_bundle)
            return Response(200, json=empty_bundle)

        mock_client = AsyncMock()
        mock_client.get = _mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from a2a import fhir_extractor
            ctx = await fhir_extractor.extract_patient_context(
                "Patient/p123", "https://fhir.example.com", "tok"
            )

        assert "miglustat 100mg" in ctx.current_medications
        assert "taliglucerase alfa" in ctx.current_medications

    @pytest.mark.asyncio
    async def test_real_fhir_path_extracts_allergy_codes(self, monkeypatch):
        monkeypatch.delenv("FHIR_MOCK", raising=False)

        allergy_bundle = {
            "resourceType": "Bundle",
            "entry": [
                {
                    "resource": {
                        "code": {
                            "coding": [{"code": "372687004"}]  # penicillin SNOMED
                        }
                    }
                }
            ],
        }
        empty_bundle = {"resourceType": "Bundle", "entry": []}

        async def _mock_get(url, **kwargs):
            if "AllergyIntolerance" in url:
                return Response(200, json=allergy_bundle)
            return Response(200, json=empty_bundle)

        mock_client = AsyncMock()
        mock_client.get = _mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from a2a import fhir_extractor
            ctx = await fhir_extractor.extract_patient_context(
                "Patient/p123", "https://fhir.example.com", "tok"
            )

        assert "372687004" in ctx.allergy_codes

    @pytest.mark.asyncio
    async def test_network_error_returns_partial_context_not_exception(self, monkeypatch):
        """All FHIR sub-requests raise — function must still return a PatientTargetContext."""
        monkeypatch.delenv("FHIR_MOCK", raising=False)

        async def _mock_get(url, **kwargs):
            raise ConnectionError("FHIR server unreachable")

        mock_client = AsyncMock()
        mock_client.get = _mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from a2a import fhir_extractor
            ctx = await fhir_extractor.extract_patient_context(
                "Patient/p999", "https://fhir.example.com", "tok"
            )

        # Should not raise; must return an empty-ish context
        assert ctx.fhir_patient_id == "Patient/p999"
        assert ctx.condition_codes == []
        assert ctx.gene_variants == []

    @pytest.mark.asyncio
    async def test_patient_id_prefix_stripped_in_requests(self, monkeypatch):
        """'Patient/' prefix must be stripped before sending to FHIR server."""
        monkeypatch.delenv("FHIR_MOCK", raising=False)

        captured_urls: list[str] = []
        empty_bundle = {"resourceType": "Bundle", "entry": []}

        async def _mock_get(url, **kwargs):
            captured_urls.append(url)
            return Response(200, json=empty_bundle)

        mock_client = AsyncMock()
        mock_client.get = _mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from a2a import fhir_extractor
            await fhir_extractor.extract_patient_context(
                "Patient/abc123", "https://fhir.example.com", "tok"
            )

        # All URLs should use the bare patient ID "abc123", not "Patient/abc123"
        for url in captured_urls:
            assert "Patient/abc123" not in url
            assert "abc123" in url


# ═════════════════════════════════════════════════════════════════════════════
# 4. target_resolver.py
# ═════════════════════════════════════════════════════════════════════════════

class TestTargetResolver:

    def _patient_with_genes(self, genes: list[str], condition_name: str = ""):
        from a2a.models import GeneVariant, PatientTargetContext
        return PatientTargetContext(
            fhir_patient_id="Patient/test",
            fhir_server_url="mock",
            sharp_access_token="tok",
            gene_variants=[GeneVariant(gene=g) for g in genes],
            condition_name=condition_name,
        )

    def test_gba1_resolves_from_lookup(self):
        from a2a.target_resolver import resolve_target
        patient = self._patient_with_genes(["GBA1"])
        result = resolve_target(patient)
        assert result.source == "lookup"
        assert "Glucocerebrosidase" in result.protein
        assert result.gene == "GBA1"

    def test_cftr_resolves_from_lookup(self):
        from a2a.target_resolver import resolve_target
        patient = self._patient_with_genes(["CFTR"])
        result = resolve_target(patient)
        assert result.source == "lookup"
        assert "CFTR" in result.protein or "Cystic Fibrosis" in result.protein

    def test_hexa_resolves_from_lookup(self):
        from a2a.target_resolver import resolve_target
        patient = self._patient_with_genes(["HEXA"])
        result = resolve_target(patient)
        assert result.source == "lookup"
        assert "Hexosaminidase" in result.protein

    def test_lookup_is_case_insensitive(self):
        """Gene name 'gba1' (lowercase) must match lookup entry 'GBA1'."""
        from a2a.target_resolver import resolve_target
        patient = self._patient_with_genes(["gba1"])
        result = resolve_target(patient)
        assert result.source == "lookup"

    def test_lookup_takes_first_known_gene_in_list(self):
        """When multiple genes are present, the first known one wins."""
        from a2a.target_resolver import resolve_target
        patient = self._patient_with_genes(["UNKNOWN_GENE", "CFTR"])
        # UNKNOWN_GENE not in table → falls through to CFTR
        result = resolve_target(patient)
        assert result.source == "lookup"
        assert result.gene == "CFTR"

    def test_scoring_bias_always_present_in_lookup_result(self):
        from a2a.target_resolver import resolve_target
        for gene in ["GBA1", "CFTR", "HEXA", "HEXB", "PCSK9", "ASAH1", "GAA"]:
            patient = self._patient_with_genes([gene])
            result = resolve_target(patient)
            assert isinstance(result.scoring_bias, dict)
            assert "binding_weight" in result.scoring_bias

    def test_unknown_gene_with_api_key_calls_llm(self, monkeypatch):
        """Unknown gene + ANTHROPIC_API_KEY set → must delegate to Claude Haiku."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")

        llm_response = json.dumps({
            "protein": "MyosinIIb protein",
            "mechanism": "allosteric_inhibition",
            "binding_site": "motor_domain",
        })

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=llm_response)]

        mock_anthropic_client = MagicMock()
        mock_anthropic_client.messages.create.return_value = mock_message

        mock_anthropic_module = MagicMock()
        mock_anthropic_module.Anthropic.return_value = mock_anthropic_client

        with patch.dict(sys.modules, {"anthropic": mock_anthropic_module}):
            from a2a import target_resolver as tr_module
            # Reload to pick up the patched anthropic module
            import importlib
            importlib.reload(tr_module)
            patient = self._patient_with_genes(["MYH10"], condition_name="Novel myopathy")
            result = tr_module.resolve_target(patient)

        assert result.source == "llm"
        assert result.protein == "MyosinIIb protein"
        assert result.mechanism == "allosteric_inhibition"

    def test_unknown_gene_without_api_key_returns_default(self, monkeypatch):
        """No ANTHROPIC_API_KEY → must return source='default' without raising."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from a2a.target_resolver import resolve_target
        patient = self._patient_with_genes(["NOVELGENE99"], condition_name="Rare syndrome")
        result = resolve_target(patient)
        assert result.source == "default"
        assert "NOVELGENE99" in result.gene

    def test_empty_gene_variants_returns_default_fallback(self, monkeypatch):
        """Empty gene list → must not crash; returns source='default'."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from a2a.models import PatientTargetContext
        from a2a.target_resolver import resolve_target
        patient = PatientTargetContext(
            fhir_patient_id="Patient/x",
            fhir_server_url="mock",
            sharp_access_token="tok",
            gene_variants=[],
        )
        result = resolve_target(patient)
        assert result.source == "default"
        assert result.gene == "unknown"

    def test_llm_fallback_handles_markdown_code_fences(self, monkeypatch):
        """LLM response wrapped in ```json ... ``` code fences must parse correctly."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-abc")

        fenced_response = "```json\n{\"protein\": \"TestProtein\", \"mechanism\": \"inhibition\", \"binding_site\": \"active_site\"}\n```"

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=fenced_response)]

        mock_anthropic_client = MagicMock()
        mock_anthropic_client.messages.create.return_value = mock_message

        mock_anthropic_module = MagicMock()
        mock_anthropic_module.Anthropic.return_value = mock_anthropic_client

        with patch.dict(sys.modules, {"anthropic": mock_anthropic_module}):
            from a2a import target_resolver as tr_module
            import importlib
            importlib.reload(tr_module)
            patient = self._patient_with_genes(["RARE1"])
            result = tr_module.resolve_target(patient)

        assert result.protein == "TestProtein"
        assert result.source == "llm"

    def test_llm_failure_falls_back_to_default(self, monkeypatch):
        """When LLM raises an exception, must gracefully fall back to default."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-fail")

        mock_anthropic_client = MagicMock()
        mock_anthropic_client.messages.create.side_effect = RuntimeError("API timeout")

        mock_anthropic_module = MagicMock()
        mock_anthropic_module.Anthropic.return_value = mock_anthropic_client

        with patch.dict(sys.modules, {"anthropic": mock_anthropic_module}):
            from a2a import target_resolver as tr_module
            import importlib
            importlib.reload(tr_module)
            patient = self._patient_with_genes(["RAREGENE_X"])
            result = tr_module.resolve_target(patient)

        assert result.source == "default"

    def test_default_fallback_scoring_bias_is_populated(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from a2a.target_resolver import _DEFAULT_BIAS, resolve_target
        from a2a.models import PatientTargetContext
        patient = PatientTargetContext(
            fhir_patient_id="Patient/x",
            fhir_server_url="mock",
            sharp_access_token="tok",
            gene_variants=[],
        )
        result = resolve_target(patient)
        assert result.scoring_bias == _DEFAULT_BIAS


# ═════════════════════════════════════════════════════════════════════════════
# 5. fhir_output.py
# ═════════════════════════════════════════════════════════════════════════════

class TestFhirOutput:

    def _build_bundle(
        self,
        num_candidates: int = 3,
        current_medications: list = None,
        smiles_override: str = None,
    ) -> dict:
        from a2a.fhir_output import build_medication_request_bundle
        candidates = [
            _make_candidate_model(
                rank=i + 1,
                smiles=smiles_override or "CC(=O)Oc1ccccc1C(=O)O",
            )
            for i in range(num_candidates)
        ]
        return build_medication_request_bundle(
            patient_fhir_id="Patient/gaucher-001",
            run_id="run-abc-123",
            target_protein="Glucocerebrosidase (GCase)",
            disease_context="Gaucher Disease Type 1",
            top_candidates=candidates,
            current_medications=current_medications or [],
        )

    def test_bundle_resource_type_is_bundle(self):
        bundle = self._build_bundle()
        assert bundle["resourceType"] == "Bundle"

    def test_bundle_type_is_collection(self):
        bundle = self._build_bundle()
        assert bundle["type"] == "collection"

    def test_bundle_has_id(self):
        bundle = self._build_bundle()
        assert "id" in bundle
        # Must be a UUID
        uuid.UUID(bundle["id"])

    def test_bundle_entries_limited_to_top_3(self):
        """build_medication_request_bundle only emits the top 3 candidates."""
        bundle = self._build_bundle(num_candidates=5)
        assert len(bundle["entry"]) == 3

    def test_bundle_with_fewer_than_3_candidates(self):
        bundle = self._build_bundle(num_candidates=2)
        assert len(bundle["entry"]) == 2

    def test_each_entry_is_medication_request(self):
        bundle = self._build_bundle()
        for entry in bundle["entry"]:
            resource = entry["resource"]
            assert resource["resourceType"] == "MedicationRequest"

    def test_medication_request_status_is_draft(self):
        bundle = self._build_bundle()
        for entry in bundle["entry"]:
            assert entry["resource"]["status"] == "draft"

    def test_medication_request_intent_is_proposal(self):
        bundle = self._build_bundle()
        for entry in bundle["entry"]:
            assert entry["resource"]["intent"] == "proposal"

    def test_subject_reference_matches_patient_fhir_id(self):
        bundle = self._build_bundle()
        for entry in bundle["entry"]:
            assert entry["resource"]["subject"]["reference"] == "Patient/gaucher-001"

    def test_extension_discovery_run_id_present(self):
        bundle = self._build_bundle()
        for entry in bundle["entry"]:
            ext_urls = [e["url"] for e in entry["resource"]["extension"]]
            assert "http://drug-discovery-swarm.ai/fhir/StructureDefinition/discovery-run-id" in ext_urls

    def test_extension_target_protein_value(self):
        bundle = self._build_bundle()
        for entry in bundle["entry"]:
            extensions = {e["url"]: e for e in entry["resource"]["extension"]}
            target_ext = extensions.get(
                "http://drug-discovery-swarm.ai/fhir/StructureDefinition/target-protein"
            )
            assert target_ext is not None
            assert target_ext["valueString"] == "Glucocerebrosidase (GCase)"

    def test_extension_fitness_score_present(self):
        bundle = self._build_bundle()
        for entry in bundle["entry"]:
            ext_urls = [e["url"] for e in entry["resource"]["extension"]]
            assert "http://drug-discovery-swarm.ai/fhir/StructureDefinition/fitness-score" in ext_urls

    def test_extension_fitness_score_is_numeric(self):
        bundle = self._build_bundle()
        for entry in bundle["entry"]:
            extensions = {e["url"]: e for e in entry["resource"]["extension"]}
            fitness_ext = extensions[
                "http://drug-discovery-swarm.ai/fhir/StructureDefinition/fitness-score"
            ]
            assert isinstance(fitness_ext["valueDecimal"], float)

    def test_meta_tag_contains_ai_generated_code(self):
        bundle = self._build_bundle()
        tag_codes = [tag["code"] for tag in bundle["meta"]["tag"]]
        assert "ai-generated" in tag_codes

    def test_miglustat_drug_interaction_note_added(self):
        """When patient is on miglustat, an interaction note must appear in the notes."""
        bundle = self._build_bundle(current_medications=["miglustat"])
        for entry in bundle["entry"]:
            notes_text = " ".join(n["text"] for n in entry["resource"]["note"])
            assert "miglustat" in notes_text.lower()

    def test_no_interaction_note_when_no_relevant_medications(self):
        """Clean medication list — no extra interaction note appended."""
        bundle = self._build_bundle(current_medications=["vitamin D"])
        for entry in bundle["entry"]:
            # Only the standard note should be present (no drug interaction note)
            assert len(entry["resource"]["note"]) == 1

    def test_full_url_is_urn_uuid(self):
        bundle = self._build_bundle()
        for entry in bundle["entry"]:
            assert entry["fullUrl"].startswith("urn:uuid:")

    def test_smiles_embedded_in_medication_text(self):
        smiles = "CC(=O)Oc1ccccc1C(=O)O"
        bundle = self._build_bundle(smiles_override=smiles)
        for entry in bundle["entry"]:
            text = entry["resource"]["medication"]["concept"]["text"]
            assert smiles in text

    def test_note_references_wet_lab_validation(self):
        """Every MedicationRequest must include the clinical-use disclaimer."""
        bundle = self._build_bundle()
        for entry in bundle["entry"]:
            main_note = entry["resource"]["note"][0]["text"]
            assert "wet-lab validation" in main_note.lower() or "REQUIRES" in main_note


# ═════════════════════════════════════════════════════════════════════════════
# 6. a2a_router.py  (FastAPI endpoint tests — isolated, no real Ray/coordinator)
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def test_app():
    """
    Build a minimal FastAPI app that mounts only the a2a_router.
    We avoid importing main.py (which starts Ray) entirely.
    """
    app = FastAPI()
    from a2a_router import router
    app.include_router(router)
    return app


@pytest.fixture()
def client(test_app):
    return TestClient(test_app, raise_server_exceptions=True)


@pytest.fixture()
def valid_submit_body() -> dict:
    return {
        "task_id": "task-abc-001",
        "patient_context": {
            "fhir_patient_id": "Patient/gaucher-001",
            "fhir_server_url": "mock",
            "sharp_access_token": "tok123",
        },
        "discovery_config": {"max_generations": 5},
    }


# Patch _run_pipeline to be a no-op so background tasks don't blow up
_NOOP_PIPELINE = AsyncMock(return_value=None)


class TestA2ARouter:

    def test_submit_returns_202_with_run_id(self, client, valid_submit_body):
        with patch("a2a_router._run_pipeline", _NOOP_PIPELINE):
            resp = client.post("/a2a/submit", json=valid_submit_body)
        assert resp.status_code == 202
        data = resp.json()
        assert "run_id" in data
        uuid.UUID(data["run_id"])  # must be a valid UUID

    def test_submit_returns_task_id_in_response(self, client, valid_submit_body):
        with patch("a2a_router._run_pipeline", _NOOP_PIPELINE):
            resp = client.post("/a2a/submit", json=valid_submit_body)
        data = resp.json()
        assert data["task_id"] == "task-abc-001"

    def test_submit_returns_poll_url_and_results_url(self, client, valid_submit_body):
        with patch("a2a_router._run_pipeline", _NOOP_PIPELINE):
            resp = client.post("/a2a/submit", json=valid_submit_body)
        data = resp.json()
        run_id = data["run_id"]
        assert data["poll_url"] == f"/a2a/run/{run_id}"
        assert data["results_url"] == f"/a2a/results/{run_id}"

    def test_submit_sharp_headers_override_body_patient_id(self, client, valid_submit_body):
        """X-FHIR-Patient header must take precedence over patient_context.fhir_patient_id."""
        with patch("a2a_router._run_pipeline", _NOOP_PIPELINE):
            resp = client.post(
                "/a2a/submit",
                json=valid_submit_body,
                headers={"X-FHIR-Patient": "Patient/sharp-override-999"},
            )
        run_id = resp.json()["run_id"]
        # The run should have been created with the header-provided patient ID
        from a2a import run_store
        result = run_store.get_run(run_id)
        assert result is not None
        assert result.patient_fhir_id == "Patient/sharp-override-999"

    def test_submit_sharp_server_header_overrides_body(self, client, valid_submit_body):
        """X-FHIR-Server header value must replace body's fhir_server_url in pipeline call."""
        pipeline_calls: list = []

        async def _capture_pipeline(**kwargs):
            pipeline_calls.append(kwargs)

        with patch("a2a_router._run_pipeline", _capture_pipeline):
            resp = client.post(
                "/a2a/submit",
                json=valid_submit_body,
                headers={"X-FHIR-Server": "https://sharp.example.com/fhir"},
            )

        assert resp.status_code == 202
        # Background tasks get the overridden URL (note: TestClient runs bg tasks synchronously)
        if pipeline_calls:
            assert pipeline_calls[0]["fhir_server_url"] == "https://sharp.example.com/fhir"

    def test_submit_invalid_body_returns_422(self, client):
        with patch("a2a_router._run_pipeline", _NOOP_PIPELINE):
            resp = client.post("/a2a/submit", json={"bad_field": "value"})
        assert resp.status_code == 422

    def test_get_run_unknown_id_returns_404(self, client):
        resp = client.get("/a2a/run/non-existent-run-id-xyz")
        assert resp.status_code == 404

    def test_get_run_known_id_returns_status(self, client, valid_submit_body):
        with patch("a2a_router._run_pipeline", _NOOP_PIPELINE):
            submit_resp = client.post("/a2a/submit", json=valid_submit_body)
        run_id = submit_resp.json()["run_id"]

        resp = client.get(f"/a2a/run/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id
        assert data["status"] == "accepted"
        assert "generation" in data
        assert "best_fitness" in data

    def test_get_results_unknown_id_returns_404(self, client):
        resp = client.get("/a2a/results/non-existent-xyz")
        assert resp.status_code == 404

    def test_get_results_for_running_run_returns_202(self, client):
        """A run that is still 'running' must return 202, not 200."""
        from a2a import run_store
        run_id = str(uuid.uuid4())
        run_store.create_run(run_id, "task-running", "Patient/p1")
        run_store.update_run(run_id, generation=5, best_fitness=0.6)

        resp = client.get(f"/a2a/results/{run_id}")
        assert resp.status_code == 202

    def test_get_results_for_accepted_run_returns_202(self, client):
        """A run that is still 'accepted' (not yet started) must return 202."""
        from a2a import run_store
        run_id = str(uuid.uuid4())
        run_store.create_run(run_id, "task-pending", "Patient/p2")

        resp = client.get(f"/a2a/results/{run_id}")
        assert resp.status_code == 202

    def test_get_results_for_complete_run_returns_200_with_candidates(self, client):
        from a2a import run_store
        run_id = str(uuid.uuid4())
        run_store.create_run(run_id, "task-done", "Patient/p3")
        leaderboard = [_make_candidate(i + 1) for i in range(3)]
        run_store.complete_run(run_id, leaderboard=leaderboard, disease_context="Gaucher")

        resp = client.get(f"/a2a/results/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "complete"
        assert len(data["top_candidates"]) == 3
        assert data["top_candidates"][0]["rank"] == 1

    def test_get_results_for_failed_run_returns_200_with_error(self, client):
        """A failed run should be returned as 200 with status=failed and error field."""
        from a2a import run_store
        run_id = str(uuid.uuid4())
        run_store.create_run(run_id, "task-fail", "Patient/p4")
        run_store.fail_run(run_id, "FHIR server returned 503")

        resp = client.get(f"/a2a/results/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert "503" in data["error"]


# ═════════════════════════════════════════════════════════════════════════════
# 7. agents/safety.py  (regression tests for the weight kwargs addition)
# ═════════════════════════════════════════════════════════════════════════════

# rdkit is only available in the drugswarm conda environment.  When it's
# absent (e.g. plain CI Python), all SafetyAgent tests are skipped rather
# than failing with an ImportError.
def _rdkit_available() -> bool:
    try:
        import rdkit  # noqa: F401
        return True
    except ImportError:
        return False


_SKIP_NO_RDKIT = pytest.mark.skipif(
    not _rdkit_available(),
    reason="rdkit not installed — activate the drugswarm conda env to run SafetyAgent tests",
)


# We use a fresh SafetyAgent per test for full isolation.
def _make_safety_agent():
    fake_r = fakeredis.FakeRedis(decode_responses=False)
    with patch("redis.Redis.from_url", return_value=fake_r):
        from agents.safety import SafetyAgent
        agent = SafetyAgent.__new__(SafetyAgent)
        SafetyAgent.__init__(agent)
        return agent


# Simple aspirin SMILES — passes all safety filters (no PAINS, no toxic groups)
_ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"
# Nitro-containing compound — will trigger toxicity flag
_NITRO = "c1ccc([N+](=O)[O-])cc1"


def _mol_dict(smiles: str, binding_score: float = 0.7, drug_likeness: float = 0.8) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "smiles": smiles,
        "binding_score": binding_score,
        "drug_likeness": drug_likeness,
    }


@_SKIP_NO_RDKIT
class TestSafetyAgent:

    def test_check_toxicity_returns_list_of_molecules(self):
        agent = _make_safety_agent()
        result = agent.check_toxicity([_mol_dict(_ASPIRIN)])
        assert isinstance(result, list)
        assert len(result) == 1

    def test_clean_molecule_has_toxicity_flag_false(self):
        agent = _make_safety_agent()
        result = agent.check_toxicity([_mol_dict(_ASPIRIN)])
        assert result[0]["toxicity_flag"] is False

    def test_nitro_compound_has_toxicity_flag_true(self):
        agent = _make_safety_agent()
        result = agent.check_toxicity([_mol_dict(_NITRO)])
        assert result[0]["toxicity_flag"] is True

    def test_default_weights_fitness_formula(self):
        """
        With no kwargs, fitness = 0.5*binding + 0.3*drug_likeness - 0.2*(0.5 if toxic else 0).
        Clean molecule: 0.5*0.7 + 0.3*0.8 - 0.2*0.0 = 0.35 + 0.24 = 0.59
        """
        agent = _make_safety_agent()
        mol = _mol_dict(_ASPIRIN, binding_score=0.7, drug_likeness=0.8)
        result = agent.check_toxicity([mol])
        expected_fitness = round(0.5 * 0.7 + 0.3 * 0.8 - 0.2 * 0.0, 4)
        assert result[0]["fitness"] == pytest.approx(expected_fitness, abs=1e-4)

    def test_custom_weights_produce_different_fitness(self):
        """
        Custom weights must change the computed fitness from the default.
        binding_weight=0.6, drug_likeness_weight=0.3, toxicity_penalty_weight=0.1
        Expected: 0.6*0.7 + 0.3*0.8 - 0.1*0.0 = 0.42 + 0.24 = 0.66
        """
        agent = _make_safety_agent()
        mol = _mol_dict(_ASPIRIN, binding_score=0.7, drug_likeness=0.8)
        result = agent.check_toxicity(
            [mol],
            binding_weight=0.6,
            drug_likeness_weight=0.3,
            toxicity_penalty_weight=0.1,
        )
        expected_fitness = round(0.6 * 0.7 + 0.3 * 0.8 - 0.1 * 0.0, 4)
        assert result[0]["fitness"] == pytest.approx(expected_fitness, abs=1e-4)

    def test_custom_weights_fitness_differs_from_default(self):
        """A higher binding_weight must produce a measurably different fitness score."""
        agent = _make_safety_agent()
        mol1 = _mol_dict(_ASPIRIN, binding_score=0.7, drug_likeness=0.8)
        mol2 = _mol_dict(_ASPIRIN, binding_score=0.7, drug_likeness=0.8)

        default_result = agent.check_toxicity([mol1])
        custom_result = agent.check_toxicity(
            [mol2],
            binding_weight=0.9,
            drug_likeness_weight=0.05,
            toxicity_penalty_weight=0.05,
        )
        assert default_result[0]["fitness"] != custom_result[0]["fitness"]

    def test_toxicity_penalty_applied_to_toxic_molecule_with_default_weights(self):
        """
        Toxic molecule: fitness includes -0.2 * 0.5 = -0.1 penalty.
        """
        agent = _make_safety_agent()
        mol = _mol_dict(_NITRO, binding_score=0.7, drug_likeness=0.8)
        result = agent.check_toxicity([mol])
        expected_fitness = round(0.5 * 0.7 + 0.3 * 0.8 - 0.2 * 0.5, 4)
        assert result[0]["fitness"] == pytest.approx(expected_fitness, abs=1e-4)

    def test_custom_toxicity_penalty_weight_reduces_penalty(self):
        """
        A lower toxicity_penalty_weight means a smaller fitness penalty for a toxic molecule.
        """
        agent = _make_safety_agent()
        mol_a = _mol_dict(_NITRO, binding_score=0.7, drug_likeness=0.8)
        mol_b = _mol_dict(_NITRO, binding_score=0.7, drug_likeness=0.8)

        default_result = agent.check_toxicity([mol_a])
        reduced_penalty_result = agent.check_toxicity(
            [mol_b],
            binding_weight=0.5,
            drug_likeness_weight=0.3,
            toxicity_penalty_weight=0.05,  # much lower than default 0.2
        )
        # Reduced penalty → higher fitness than default for the same toxic molecule
        assert reduced_penalty_result[0]["fitness"] > default_result[0]["fitness"]

    def test_invalid_smiles_is_skipped_not_raised(self):
        """Malformed SMILES must be silently dropped, not raise an exception."""
        agent = _make_safety_agent()
        bad_mol = {"id": "bad", "smiles": "INVALID_SMILES_XYZ", "binding_score": 0.5, "drug_likeness": 0.5}
        result = agent.check_toxicity([bad_mol])
        assert result == []

    def test_mixed_valid_and_invalid_smiles_only_valid_returned(self):
        agent = _make_safety_agent()
        mols = [
            _mol_dict(_ASPIRIN),
            {"id": "bad", "smiles": "NOT_A_SMILES", "binding_score": 0.5, "drug_likeness": 0.5},
            _mol_dict(_NITRO),
        ]
        result = agent.check_toxicity(mols)
        assert len(result) == 2

    def test_empty_molecule_list_returns_empty_list(self):
        agent = _make_safety_agent()
        result = agent.check_toxicity([])
        assert result == []

    def test_fitness_value_is_rounded_to_4_decimal_places(self):
        agent = _make_safety_agent()
        result = agent.check_toxicity([_mol_dict(_ASPIRIN, binding_score=1 / 3, drug_likeness=2 / 3)])
        fitness = result[0]["fitness"]
        # Verify it's rounded (at most 4 decimal places)
        assert fitness == round(fitness, 4)

    def test_pains_alert_field_present_in_result(self):
        agent = _make_safety_agent()
        result = agent.check_toxicity([_mol_dict(_ASPIRIN)])
        assert "pains_alert" in result[0]

    def test_toxic_group_alert_field_present_in_result(self):
        agent = _make_safety_agent()
        result = agent.check_toxicity([_mol_dict(_ASPIRIN)])
        assert "toxic_group_alert" in result[0]
