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

# --- Middleware pour sécuriser /sse ---
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
async def tool_list_workflows(_args=None):
    data = await _n8n_get("/rest/workflows")
    return [types.TextContent(text=json.dumps(data))]

async def tool_create_workflow(args):
    wf = args.get("workflow")
    if not wf:
        return [types.TextContent(text="Erreur: paramètre 'workflow' manquant")]
    data = await _n8n_post("/rest/workflows", wf)
    return [types.TextContent(text=json.dumps(data))]

async def tool_set_active(args):
    workflow_id = args.get("workflow_id")
    active = bool(args.get("active", True))
    if not workflow_id:
        return [types.TextContent(text="Erreur: 'workflow_id' manquant")]
    data = await _n8n_patch(f"/rest/workflows/{workflow_id}", {"active": active})
    return [types.TextContent(text=json.dumps(data))]

async def tool_delete_workflow(args):
    workflow_id = args.get("workflow_id")
    if not workflow_id:
        return [types.TextContent(text="Erreur: 'workflow_id' manquant")]
    data = await _n8n_delete(f"/rest/workflows/{workflow_id}")
    return [types.TextContent(text=json.dumps(data))]

async def tool_run_webhook(args):
    path = args.get("path")
    payload = args.get("payload", {})
    if not path or not path.startswith("/"):
        return [types.TextContent(text="Erreur: 'path' invalide")]
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{N8N_URL}{path}", json=payload) as r:
            try:
                body = await r.json()
            except Exception:
                body = await r.text()
            return [types.TextContent(text=json.dumps({"status": r.status, "body": body}))]

# --- Déclaration manuelle des tools ---
server.add_tool(
    name="list_workflows",
    description="Liste les workflows n8n.",
    handler=tool_list_workflows,
)

server.add_tool(
    name="create_workflow",
    description="Crée un workflow n8n à partir d'un JSON export/import.",
    handler=tool_create_workflow,
    input_schema={"type": "object", "properties": {"workflow": {"type": "object"}}, "required": ["workflow"]},
)

server.add_tool(
    name="set_active",
    description="Active/Désactive un workflow.",
    handler=tool_set_active,
    input_schema={"type": "object", "properties": {
        "workflow_id": {"type": "string"},
        "active": {"type": "boolean"}
    }, "required": ["workflow_id"]},
)

server.add_tool(
    name="delete_workflow",
    description="Supprime un workflow.",
    handler=tool_delete_workflow,
    input_schema={"type": "object", "properties": {"workflow_id": {"type": "string"}}, "required": ["workflow_id"]},
)

server.add_tool(
    name="run_webhook",
    description="Déclenche un workflow par webhook.",
    handler=tool_run_webhook,
    input_schema={"type": "object", "properties": {
        "path": {"type": "string"},
        "payload": {"type": "object"}
    }, "required": ["path"]},
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
