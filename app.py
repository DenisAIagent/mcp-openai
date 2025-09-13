import os
import json
import asyncio
import aiohttp
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse
from mcp.server import Server
from mcp import types

# --- Config ---
N8N_URL = os.environ.get("N8N_URL", "").rstrip("/")
N8N_API_KEY = os.environ.get("N8N_API_KEY", "")
MCP_BEARER = os.environ.get("MCP_BEARER", "change-me")

HEADERS = {
    "X-N8N-API-KEY": N8N_API_KEY,
    "Content-Type": "application/json",
}

# --- Init FastAPI et MCP ---
app = FastAPI(title="n8n-mcp")
server = Server("n8n-mcp")

# --- Middleware pour protéger /sse ---
@app.middleware("http")
async def bearer_auth(request: Request, call_next):
    if request.url.path == "/sse":
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or auth.split(" ", 1)[1] != MCP_BEARER:
            return PlainTextResponse("Unauthorized", status_code=401)
    return await call_next(request)

# --- Fonctions utilitaires API n8n ---
async def _n8n_get(path: str):
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        async with s.get(f"{N8N_URL}{path}") as r:
            txt = await r.text()
            if r.status >= 400:
                raise HTTPException(r.status, txt)
            return json.loads(txt)

async def _n8n_post(path: str, data: dict):
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        async with s.post(f"{N8N_URL}{path}", data=json.dumps(data)) as r:
            txt = await r.text()
            if r.status >= 400:
                raise HTTPException(r.status, txt)
            return json.loads(txt)

async def _n8n_patch(path: str, data: dict):
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        async with s.patch(f"{N8N_URL}{path}", data=json.dumps(data)) as r:
            txt = await r.text()
            if r.status >= 400:
                raise HTTPException(r.status, txt)
            return json.loads(txt)

async def _n8n_delete(path: str):
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        async with s.delete(f"{N8N_URL}{path}") as r:
            txt = await r.text()
            if r.status >= 400:
                raise HTTPException(r.status, txt)
            return {"ok": True, "status": r.status, "body": txt}

# --- Implémentations Tools ---
async def list_workflows():
    data = await _n8n_get("/rest/workflows")
    return [types.TextContent(text=json.dumps(data))]

async def create_workflow(workflow: dict):
    data = await _n8n_post("/rest/workflows", workflow)
    return [types.TextContent(text=json.dumps(data))]

async def set_active(workflow_id: str, active: bool = True):
    data = await _n8n_patch(f"/rest/workflows/{workflow_id}", {"active": active})
    return [types.TextContent(text=json.dumps(data))]

async def delete_workflow(workflow_id: str):
    data = await _n8n_delete(f"/rest/workflows/{workflow_id}")
    return [types.TextContent(text=json.dumps(data))]

async def run_webhook(path: str, payload: dict | None = None):
    payload = payload or {}
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{N8N_URL}{path}", json=payload) as r:
            try:
                body = await r.json()
            except Exception:
                body = await r.text()
            return [types.TextContent(text=json.dumps({"status": r.status, "body": body}))]

# --- Enregistrement des Tools ---
server.register_tool(
    "list_workflows",
    list_workflows,
    description="Liste tous les workflows n8n."
)

server.register_tool(
    "create_workflow",
    create_workflow,
    description="Crée un workflow n8n à partir d'un JSON export/import.",
    input_schema={"type": "object", "properties": {"workflow": {"type": "object"}}, "required": ["workflow"]}
)

server.register_tool(
    "set_active",
    set_active,
    description="Active/Désactive un workflow par ID.",
    input_schema={"type": "object", "properties": {
        "workflow_id": {"type": "string"},
        "active": {"type": "boolean"}
    }, "required": ["workflow_id"]}
)

server.register_tool(
    "delete_workflow",
    delete_workflow,
    description="Supprime un workflow par ID.",
    input_schema={"type": "object", "properties": {"workflow_id": {"type": "string"}}, "required": ["workflow_id"]}
)

server.register_tool(
    "run_webhook",
    run_webhook,
    description="Déclenche un workflow par son webhook (ex: /webhook/abc123).",
    input_schema={"type": "object", "properties": {
        "path": {"type": "string"},
        "payload": {"type": "object"}
    }, "required": ["path"]}
)

# --- Endpoint SSE pour ChatGPT ---
@app.get("/sse")
async def sse_endpoint(request: Request):
    async def event_publisher():
        queue = asyncio.Queue()

        async def send(msg):
            await queue.put(f"data: {json.dumps(msg)}\n\n")

        server.on_message(send)

        while True:
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=15)
                yield msg
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"

    return StreamingResponse(event_publisher(), media_type="text/event-stream")
