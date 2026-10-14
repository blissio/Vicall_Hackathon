"""Generate the local/team API contract without third-party dependencies."""
import json
from pathlib import Path

query = {"type": "object", "properties": {
    "question": {"type": "string", "maxLength": 2000},
    "intent": {"type": "string", "enum": ["prospects", "providers", "partners"], "default": "prospects"},
    "segment": {"type": "string", "enum": ["", "professional", "accounting", "legal", "insurance", "real_estate", "consulting", "education", "healthcare", "food", "technology", "other"]},
    "organization_type": {"type": "string", "enum": ["", "business", "school", "school_district", "nonprofit", "public_body"]},
    "category": {"type": "string"}, "neighborhood": {"type": "string"},
    "desired_services": {"type": "string", "maxLength": 1000}, "partner_services": {"type": "string", "maxLength": 1000},
    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
    **{key: {"type": "boolean", "default": False} for key in ("require_contact", "require_decision_maker", "require_website_issue")}}}
schemas = {"Search": query, "Ask": {**query, "properties": {**query["properties"], **{key: {"type": "boolean", "default": False} for key in ('use_ai', 'use_ai_plan')}}},
    "Person": {"type": "object", "required": ["business_id", "name", "role", "source_url", "observed_at", "excerpt"], "properties": {key: {"type": "string"} for key in ("business_id", "name", "role", "source_url", "observed_at", "excerpt", "email", "phone")}},
    "Organization": {"type": "object", "required": ["id", "organization_type", "source_url", "observed_at", "excerpt"], "properties": {key: {"type": "string"} for key in ("id", "organization_type", "services", "service_area", "parent_id", "source_url", "observed_at", "excerpt")}},
    "Workflow": {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}, "notes": {"type": "string", "maxLength": 12000}, "shortlisted": {"type": "boolean"}, "stage": {"type": "string", "enum": ["New", "Researching", "Qualified", "Not a fit"]}, "expected_updated_at": {"type": ["string", "null"]}}},
    "SavedSearch": {"type": "object", "required": ["name", "query"], "properties": {"name": {"type": "string", "maxLength": 100}, "query": {"$ref": "#/components/schemas/Search"}}},
    "Export": {"type": "object", "required": ["ids"], "properties": {"ids": {"type": "array", "items": {"type": "string"}}}},
    "AuditRequest": {"type": "object", "required": ["id", "url"], "properties": {"id": {"type": "string"}, "url": {"type": "string", "format": "uri"}, "strategy": {"type": "string", "enum": ["mobile", "desktop"], "default": "mobile"}}},
    "MatchingSettings": {"type": "object", "required": ["weights"], "properties": {"weights": {"type": "object", "additionalProperties": False, "required": list(__import__('matching').DEFAULT_WEIGHTS), "properties": {key: {"type": "integer", "minimum": 0, "maximum": 100} for key in __import__('matching').DEFAULT_WEIGHTS}}}},
    "Object": {"type": "object"}}
for name in ('Person', 'Organization'):
    schemas[name]['properties']['expected_revision'] = {'type': ['string', 'null'], 'description': 'Last-read revision; stale saves are rejected'}
schemas['Person']['properties']['id'] = {'type': 'string', 'description': 'Existing contact ID when editing'}
spec = {"openapi": "3.1.0", "info": {"title": "Pittsburgh IQ research API", "version": "2.0.0", "description": "Local evidence research and optional model interpretation. Local API: X-Vicall-Token from the app or VICALL_API_TOKEN bearer credential. Team API: Basic account authentication or VICALL_TEAM_API_TOKEN bearer credential; role checks apply."},
    "servers": [{"url": "http://127.0.0.1:8765"}], "security": [{"BearerToken": []}, {"LocalToken": []}, {"BasicAccount": []}],
    "components": {"securitySchemes": {"BearerToken": {"type": "http", "scheme": "bearer"}, "LocalToken": {"type": "apiKey", "in": "header", "name": "X-Vicall-Token"}, "BasicAccount": {"type": "http", "scheme": "basic"}}, "schemas": schemas}, "paths": {}}
post_routes = {
    **{path: (summary, 'AuditRequest') for path, summary in {'link-audit': 'Sample up to ten same-origin links', 'performance-audit': 'Google Lighthouse lab report', 'field-audit': 'Google CrUX real-user metrics'}.items()},
    'matching-settings': ('Set shared ranking weights (team admin)', 'MatchingSettings'),
    "search": ("Search retained business evidence", "Search"), "ask": ("Research with optional grounded AI", "Ask"),
    "person": ("Save a sourced public person/role", "Person"), "organization": ("Review organization, services, and parent", "Organization"),
    "workflow": ("Update notes/stage/shortlist; use expected_updated_at for conflict detection", "Workflow"),
    "saved-search": ("Save reusable search criteria", "SavedSearch"), "export": ("Export business/contact evidence as CSV", "Export"),
    **{path: (summary, "Object") for path, summary in {
        "person-delete": "Remove reviewed contact by id", "saved-search-delete": "Delete saved search by id",
        "backup": "Create a SQLite backup (team admin)", "collect": "Collect OSM: mode collect, refresh, or clean (team admin)",
        "collect-cancel": "Stop active collection (team admin)", "collect-resume": "Resume unfinished collection using saved source responses (team admin)",
        "audit": "Audit 1–25 business ids with optional url and force", "audit-cancel": "Stop audit after current website",
        "audit-resume": "Resume unfinished audit targets", "research": "Research ids and/or public-directory sources",
        "research-cancel": "Stop research after current task", "research-resume": "Resume unfinished research tasks",
        "research-settings": "Configure automation (team admin)", "discovery-add": "Submit sourced business listing",
        "discovery-import": "Import CSV to discovery inbox", "discovery-review": "Review candidate: add, dismiss, or restore",
        "target-catalog": "Add official-source office/district starter catalog to inbox (team admin)",
        "rendered-audit": "Start optional browser-rendered audit for id and url"}.items()}}
for path, (summary, schema) in post_routes.items():
    success = "202" if path in {"collect", "collect-resume", "audit", "audit-resume", "research", "research-resume", "rendered-audit", "link-audit", "performance-audit", "field-audit"} else "200"
    content = {"text/csv": {"schema": {"type": "string"}}} if path == "export" else {"application/json": {"schema": {"type": "object"}}}
    spec["paths"]["/api/"+path] = {"post": {"operationId": path.replace('-', '_'), "summary": summary,
        "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/"+schema}}}},
        "responses": {success: {"description": "Success", "content": content}, "400": {"description": "Invalid input or stale research revision"}, "403": {"description": "Authentication, origin, token, or role denied"}, "404": {"description": "Record not found"}}}}
for path, summary in {"data": "Directory snapshot", "intelligence": "Saved searches, history, and configuration status", "business": "Business with reviewed contacts and evidence", "research": "Research settings, job, and inbox", "job": "Collection progress", "audit-job": "Audit progress", "audit-report": "Static audit report and history", "rendered-report": "Rendered audit and screenshots", "openapi.json": "OpenAPI contract"}.items():
    params = [{"name": "id", "in": "query", "required": True, "schema": {"type": "string"}}] if path in {"business", "audit-report", "rendered-report"} else []
    spec["paths"].setdefault("/api/"+path, {})["get"] = {"operationId": "get_"+path.replace('-','_').replace('.','_'), "summary": summary, "parameters": params, "responses": {"200": {"description": "Success", "content": {"application/json": {"schema": {"type": "object"}}}}, "403": {"description": "Authentication required"}, "404": {"description": "Record not found"}}}
spec["paths"]["/api/search"]["get"] = {"operationId": "search_get", "summary": "Search using query parameters", "parameters": [{"name": k, "in": "query", "schema": v} for k,v in query["properties"].items()], "responses": {"200": {"description": "Search results"}, "400": {"description": "Invalid parameters"}}}
for kind in ('link', 'performance', 'field'):
    spec['paths']['/api/'+kind+'-report'] = {'get': {'operationId': 'get_'+kind+'_report', 'summary': 'Read saved '+kind+' report', 'parameters': [{'name': 'id', 'in': 'query', 'required': True, 'schema': {'type': 'string'}}], 'responses': {'200': {'description': 'Saved report or not_run'}, '404': {'description': 'Business not found'}}}}
if __name__ == "__main__":
    Path("docs/openapi.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    print("Generated docs/openapi.json")
