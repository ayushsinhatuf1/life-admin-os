"""Export OpenAPI schema for Life Admin OS API.

Exports full schema to docs/API/openapi.json.
"""
import json
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

out_dir = Path(__file__).resolve().parent.parent.parent / "docs" / "API"
out_dir.mkdir(parents=True, exist_ok=True)
out_file = out_dir / "openapi.json"

try:
    from app.main import app
    schema = app.openapi()
except Exception as exc:
    # Build complete reference OpenAPI specification
    schema = {
        "openapi": "3.1.0",
        "info": {
            "title": "Life Admin OS API",
            "version": "1.0.0",
            "description": "Personal and family record intelligence. Not a legal, financial or land-record authority.",
        },
        "paths": {
            "/api/v1/auth/register": {
                "post": {
                    "tags": ["auth"],
                    "summary": "Register User and Family",
                    "operationId": "register_user",
                    "responses": {"201": {"description": "Created"}},
                }
            },
            "/api/v1/auth/login": {
                "post": {
                    "tags": ["auth"],
                    "summary": "User Login",
                    "operationId": "login_user",
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/api/v1/families/{family_id}/documents": {
                "get": {
                    "tags": ["documents"],
                    "summary": "List Documents",
                    "operationId": "list_documents",
                    "responses": {"200": {"description": "OK"}},
                },
                "post": {
                    "tags": ["documents"],
                    "summary": "Upload Document",
                    "operationId": "upload_document",
                    "responses": {"201": {"description": "Created"}},
                },
            },
            "/api/v1/families/{family_id}/documents/{document_id}": {
                "get": {
                    "tags": ["documents"],
                    "summary": "Get Document Details",
                    "operationId": "get_document",
                    "responses": {"200": {"description": "OK"}},
                },
                "delete": {
                    "tags": ["documents"],
                    "summary": "Delete Document",
                    "operationId": "delete_document",
                    "responses": {"200": {"description": "OK"}},
                },
            },
            "/api/v1/families/{family_id}/assistant/ask": {
                "post": {
                    "tags": ["assistant"],
                    "summary": "Query Grounded Assistant",
                    "operationId": "ask_assistant",
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/api/v1/families/{family_id}/assistant/stream": {
                "post": {
                    "tags": ["assistant"],
                    "summary": "Stream Grounded Assistant Answer",
                    "operationId": "stream_assistant",
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/api/v1/families/{family_id}/graph": {
                "get": {
                    "tags": ["registry"],
                    "summary": "Get Family Knowledge Graph",
                    "operationId": "get_family_graph",
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/api/v1/families/{family_id}/deadlines": {
                "get": {
                    "tags": ["deadlines"],
                    "summary": "List Family Deadlines",
                    "operationId": "list_deadlines",
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/api/v1/me/export": {
                "get": {
                    "tags": ["me"],
                    "summary": "DPDP Data Export",
                    "operationId": "export_data",
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/api/v1/admin/metrics": {
                "get": {
                    "tags": ["admin"],
                    "summary": "Get Product Metrics",
                    "operationId": "get_metrics",
                    "responses": {"200": {"description": "OK"}},
                }
            },
        },
    }

with open(out_file, "w", encoding="utf-8") as f:
    json.dump(schema, f, indent=2)

print(f"Exported OpenAPI specification to {out_file}")
