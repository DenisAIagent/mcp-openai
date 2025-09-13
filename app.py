import os
import json
import asyncio
import aiohttp
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, PlainTextResponse
from mcp.server.fastmcp import FastMCP
from mcp.types import Tool, TextContent
from pydantic import BaseModel
from typing import Optional

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
mcp_server = FastMCP("n8n-mcp")

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

# --- Modèles Pydantic pour les paramètres ---
class CreateWorkflowArgs(BaseModel):
    workflow: dict

class SetActiveArgs(BaseModel):
    workflow_id: str
    active: bool = True

class DeleteWorkflowArgs(BaseModel):
    workflow_id: str

class RunWebhookArgs(BaseModel):
    path: str
    payload: Optional[dict] = {}

# --- Déclaration des tools avec FastMCP ---
@mcp_server.tool()
async def list_workflows() -> str:
    """Liste tous les workflows n8n disponibles."""
    try:
        data = await _n8n_get("/rest/workflows")
        return json.dumps(data, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp_server.tool()
async def create_workflow(workflow: dict) -> str:
    """
    Crée un nouveau workflow n8n à partir d'un JSON export/import.
    
    Args:
        workflow: Le workflow au format JSON n8n
    """
    try:
        data = await _n8n_post("/rest/workflows", workflow)
        return json.dumps(data, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp_server.tool()
async def set_active(workflow_id: str, active: bool = True) -> str:
    """
    Active ou désactive un workflow n8n.
    
    Args:
        workflow_id: L'ID du workflow
        active: True pour activer, False pour désactiver
    """
    try:
        data = await _n8n_patch(f"/rest/workflows/{workflow_id}", {"active": active})
        return json.dumps(data, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp_server.tool()
async def delete_workflow(workflow_id: str) -> str:
    """
    Supprime définitivement un workflow n8n.
    
    Args:
        workflow_id: L'ID du workflow à supprimer
    """
    try:
        data = await _n8n_delete(f"/rest/workflows/{workflow_id}")
        return json.dumps(data, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

@mcp_server.tool()
async def run_webhook(path: str, payload: Optional[dict] = None) -> str:
    """
    Déclenche un workflow n8n via webhook.
    
    Args:
        path: Le chemin webhook (doit commencer par /)
        payload: Les données à envoyer (optionnel)
    """
    if not path or not path.startswith("/"):
        return json.dumps({"error": "Le path doit commencer par /"})
    
    if payload is None:
        payload = {}
    
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(f"{N8N_URL}{path}", json=payload) as r:
                try:
                    body = await r.json()
                except Exception:
                    body = await r.text()
                return json.dumps({"status": r.status, "body": body}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})

# --- Endpoint principal ---
@app.get("/")
async def root():
    return {
        "service": "n8n-mcp",
        "status": "running",
        "endpoints": {
            "/": "Info service",
            "/sse": "SSE endpoint pour MCP (Bearer auth requis)"
        }
    }

# --- Endpoint SSE pour MCP ---
@app.get("/sse")
async def sse_endpoint(request: Request):
    """Endpoint SSE pour la communication MCP."""
    async def event_generator():
        try:
            # Envoie l'événement d'initialisation
            init_event = {
                "type": "init",
                "capabilities": {
                    "tools": True
                }
            }
            yield f"data: {json.dumps(init_event)}\n\n"
            
            # Keep-alive loop
            while True:
                if await request.is_disconnected():
                    break
                await asyncio.sleep(30)
                yield ": keep-alive\n\n"
                
        except asyncio.CancelledError:
            pass
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

# --- Healthcheck ---
@app.get("/health")
async def health():
    """Endpoint de healthcheck."""
    try:
        # Test la connexion n8n
        await _n8n_get("/rest/workflows?limit=1")
        return {"status": "healthy", "n8n": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

# --- Lancement du serveur ---
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
