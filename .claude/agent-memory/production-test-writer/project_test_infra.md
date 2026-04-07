---
name: A2A Test Infrastructure
description: Testing setup for the A2A layer — frameworks, environment quirks, skip patterns, and run commands
type: project
---

Test file lives at `backend/tests/test_a2a.py` (92 tests total).
Config file: `backend/pytest.ini` (asyncio_mode=auto, testpaths=tests).

**Why:** New A2A layer (FHIR extractor, run store, target resolver, FHIR output, router) added April 2026; no prior test infrastructure existed.

**How to apply:** When adding new A2A tests, follow the existing class structure (TestModels, TestRunStore, etc.) and keep all mocks in the test file itself — no conftest.py needed.

## Environment split

- **78 tests run everywhere** (no special env needed): models, run_store, fhir_extractor, target_resolver, fhir_output, a2a_router.
- **14 SafetyAgent tests require rdkit** — decorated with `@_SKIP_NO_RDKIT` and skip automatically in plain Python. Must be run inside the `drugswarm` conda environment (WSL terminal: `conda activate drugswarm`).

## Run commands

```bash
# From backend/ — works in system Python (78 tests)
python -m pytest tests/test_a2a.py -v

# From WSL with drugswarm env — runs all 92 tests
conda activate drugswarm && python -m pytest tests/test_a2a.py -v
```

## Key mocking patterns

- **Redis**: `fakeredis.FakeRedis(decode_responses=True)` injected via `monkeypatch.setattr(run_store_module, "_get_redis", ...)` in an autouse fixture.
- **httpx.AsyncClient**: `patch("httpx.AsyncClient", return_value=mock_client)` where mock_client has `__aenter__`/`__aexit__` as `AsyncMock`.
- **Anthropic SDK**: `patch.dict(sys.modules, {"anthropic": mock_anthropic_module})` + `importlib.reload(target_resolver)` to force re-import with the stub.
- **Ray**: Module-level stub (`sys.modules.setdefault("ray", _ray_stub)`) makes `@ray.remote` a no-op decorator before any agent import.
- **coordinator/main.py**: Never imported — router tests use a minimal `FastAPI()` app that mounts only `a2a_router`.
- **_run_pipeline**: Patched with `AsyncMock(return_value=None)` in router submit tests to prevent background task execution.

## Required packages (beyond requirements.txt)

```
pip install fakeredis pytest-asyncio
```
