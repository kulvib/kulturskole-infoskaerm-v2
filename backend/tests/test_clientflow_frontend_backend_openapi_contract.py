from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from service1.main import app


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / "frontend" / "tests" / "contracts" / "clientflowFrontendBackendContract.json"


def _contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _resolve_ref(openapi: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not ref:
        return schema
    prefix = "#/components/schemas/"
    assert ref.startswith(prefix), f"Unsupported OpenAPI ref: {ref}"
    name = ref[len(prefix):]
    return openapi["components"]["schemas"][name]


def _schema_property_names(openapi: dict[str, Any], schema: dict[str, Any] | None) -> set[str]:
    if not schema:
        return set()
    schema = _resolve_ref(openapi, schema)
    names = set((schema.get("properties") or {}).keys())
    for key in ("allOf", "anyOf", "oneOf"):
        for child in schema.get(key) or []:
            names.update(_schema_property_names(openapi, child))
    return names


def _response_item_schema(openapi: dict[str, Any], schema: dict[str, Any] | None) -> dict[str, Any] | None:
    if not schema:
        return None
    schema = _resolve_ref(openapi, schema)
    if schema.get("type") == "array":
        return schema.get("items")
    for key in ("anyOf", "oneOf"):
        for child in schema.get(key) or []:
            resolved = _resolve_ref(openapi, child)
            if resolved.get("type") == "array":
                return resolved.get("items")
    return None


def _json_schema(content: dict[str, Any] | None) -> dict[str, Any] | None:
    if not content:
        return None
    media = content.get("application/json")
    if not isinstance(media, dict):
        return None
    schema = media.get("schema")
    return schema if isinstance(schema, dict) else None


def test_frontend_clientflow_contract_matches_actual_fastapi_routes_and_schemas():
    """Cross-check the reviewed frontend contract against FastAPI's actual app schema.

    This intentionally uses ``app.openapi()`` rather than reading router source text.
    Frontend execution of the same contract is covered in the Node/Vite test that
    consumes the same JSON contract file.
    """

    contract = _contract()
    assert contract["schema_version"] == 1
    openapi = app.openapi()
    paths = openapi["paths"]

    for operation in contract["operations"]:
        path = operation["path"]
        method = operation["method"].lower()
        assert path in paths, f"Frontend operation {operation['name']} has no backend route {path}"
        assert method in paths[path], f"Frontend operation {operation['name']} expects {method.upper()} {path}"
        backend_operation = paths[path][method]

        request_properties = set(operation.get("request_properties") or [])
        if request_properties:
            request_schema = _json_schema((backend_operation.get("requestBody") or {}).get("content"))
            actual = _schema_property_names(openapi, request_schema)
            assert request_properties <= actual, (
                f"{operation['name']} request drift: frontend requires {sorted(request_properties)}, "
                f"backend schema exposes {sorted(actual)}"
            )

        success_status = str(operation["success_status"])
        responses = backend_operation.get("responses") or {}
        assert success_status in responses, (
            f"{operation['name']} expects success HTTP {success_status}, backend declares {sorted(responses)}"
        )
        response_schema = _json_schema((responses[success_status] or {}).get("content"))

        response_properties = set(operation.get("response_properties") or [])
        if response_properties:
            actual = _schema_property_names(openapi, response_schema)
            assert response_properties <= actual, (
                f"{operation['name']} response drift: frontend requires {sorted(response_properties)}, "
                f"backend schema exposes {sorted(actual)}"
            )

        response_item_properties = set(operation.get("response_item_properties") or [])
        if response_item_properties:
            item_schema = _response_item_schema(openapi, response_schema)
            actual = _schema_property_names(openapi, item_schema)
            assert response_item_properties <= actual, (
                f"{operation['name']} list-item drift: frontend requires {sorted(response_item_properties)}, "
                f"backend schema exposes {sorted(actual)}"
            )
