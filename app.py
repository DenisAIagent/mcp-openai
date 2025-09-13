import os
import json
import asyncio
import aiohttp
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, PlainTextResponse
from typing import Dict, Any, Optional

# --- Config ---
N8N_URL = os.environ.get("N8N_URL", "").rstrip("/")
N8N_API_KEY = os.environ.get("N8N_API_KEY", "")
MCP_BEARER = os.environ.get("MCP_BEARER", "change-me")

HEADERS = {
    "X-N8N-API-KEY": N8N_API_KEY,
    "Content-Type": "application/json",
}

# --- Init FastAPI ---
app = FastAPI(title="n8n-mcp-proxy")

# --- Middleware pour sécuriser /sse ---
@app.middleware("http")
async def bearer_auth(request: Request, call_next):
    if request.url.path == "/sse":
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or auth.split(" ", 1)[1] != MCP_BEARER:
            return PlainTextResponse("Unauthorized", status_code=401)
    return await call_next(request)

# --- Fonctions utilitaires API n8n ---
async def _n8n_get(path: str) -> Dict[str, Any]:
    """Execute GET request to n8n API"""
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(f"{N8N_URL}{path}") as response:
            text = await response.text()
            if response.status >= 400:
                raise HTTPException(response.status, text)
            return json.loads(text) if text else {}

async def _n8n_post(path: str, data: dict) -> Dict[str, Any]:
    """Execute POST request to n8n API"""
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.post(f"{N8N_URL}{path}", data=json.dumps(data)) as response:
            text = await response.text()
            if response.status >= 400:
                raise HTTPException(response.status, text)
            return json.loads(text) if text else {}

async def _n8n_patch(path: str, data: dict) -> Dict[str, Any]:
    """Execute PATCH request to n8n API"""
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.patch(f"{N8N_URL}{path}", data=json.dumps(data)) as response:
            text = await response.text()
            if response.status >= 400:
                raise HTTPException(response.status, text)
            return json.loads(text) if text else {}

async def _n8n_delete(path: str) -> Dict[str, Any]:
    """Execute DELETE request to n8n API"""
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.delete(f"{N8N_URL}{path}") as response:
            text = await response.text()
            if response.status >= 400:
                raise HTTPException(response.status, text)
            return {"ok": True, "status": response.status, "body": text}

# --- Tools Implementation ---
class MCPTools:
    """Classe pour gérer les outils MCP"""
    
    @staticmethod
    async def list_workflows() -> Dict[str, Any]:
        """Liste tous les workflows n8n"""
        try:
            data = await _n8n_get("/rest/workflows")
            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    @staticmethod
    async def create_workflow(workflow: dict) -> Dict[str, Any]:
        """Crée un nouveau workflow n8n"""
        try:
            if not workflow:
                return {"success": False, "error": "workflow parameter is required"}
            data = await _n8n_post("/rest/workflows", workflow)
            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    @staticmethod
    async def set_active(workflow_id: str, active: bool = True) -> Dict[str, Any]:
        """Active ou désactive un workflow"""
        try:
            if not workflow_id:
                return {"success": False, "error": "workflow_id is required"}
            data = await _n8n_patch(f"/rest/workflows/{workflow_id}", {"active": active})
            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    @staticmethod
    async def delete_workflow(workflow_id: str) -> Dict[str, Any]:
        """Supprime un workflow"""
        try:
            if not workflow_id:
                return {"success": False, "error": "workflow_id is required"}
            data = await _n8n_delete(f"/rest/workflows/{workflow_id}")
            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    @staticmethod
    async def run_webhook(path: str, payload: Optional[dict] = None) -> Dict[str, Any]:
        """Déclenche un workflow via webhook"""
        try:
            if not path or not path.startswith("/"):
                return {"success": False, "error": "path must start with /"}
            
            if payload is None:
                payload = {}
            
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{N8N_URL}{path}", json=payload) as response:
                    try:
                        body = await response.json()
                    except:
                        body = await response.text()
                    return {"success": True, "status": response.status, "body": body}
        except Exception as e:
            return {"success": False, "error": str(e)}

# --- MCP Message Handler ---
mcp_tools = MCPTools()

async def handle_mcp_message(message: dict) -> dict:
    """Traite les messages MCP entrants"""
    msg_type = message.get("type")
    
    if msg_type == "initialize":
        return {
            "type": "initialized",
            "capabilities": {
                "tools": [
                    {
                        "name": "list_workflows",
                        "description": "Liste tous les workflows n8n",
                        "inputSchema": {"type": "object", "properties": {}}
                    },
                    {
                        "name": "create_workflow",
                        "description": "Crée un nouveau workflow n8n",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "workflow": {"type": "object", "description": "Le workflow JSON n8n"}
                            },
                            "required": ["workflow"]
                        }
                    },
                    {
                        "name": "set_active",
                        "description": "Active ou désactive un workflow",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "workflow_id": {"type": "string", "description": "ID du workflow"},
                                "active": {"type": "boolean", "description": "État actif", "default": True}
                            },
                            "required": ["workflow_id"]
                        }
                    },
                    {
                        "name": "delete_workflow",
                        "description": "Supprime un workflow",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "workflow_id": {"type": "string", "description": "ID du workflow"}
                            },
                            "required": ["workflow_id"]
                        }
                    },
                    {
                        "name": "run_webhook",
                        "description": "Déclenche un workflow via webhook",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Chemin webhook (commence par /)"},
                                "payload": {"type": "object", "description": "Données à envoyer", "default": {}}
                            },
                            "required": ["path"]
                        }
                    }
                ]
            }
        }
    
    elif msg_type == "tool_call":
        tool_name = message.get("tool", {}).get("name")
        params = message.get("tool", {}).get("arguments", {})
        
        if tool_name == "list_workflows":
            result = await mcp_tools.list_workflows()
        elif tool_name == "create_workflow":
            result = await mcp_tools.create_workflow(params.get("workflow"))
        elif tool_name == "set_active":
            result = await mcp_tools.set_active(
                params.get("workflow_id"),
                params.get("active", True)
            )
        elif tool_name == "delete_workflow":
            result = await mcp_tools.delete_workflow(params.get("workflow_id"))
        elif tool_name == "run_webhook":
            result = await mcp_tools.run_webhook(
                params.get("path"),
                params.get("payload")
            )
        else:
            result = {"error": f"Unknown tool: {tool_name}"}
        
        return {
            "type": "tool_result",
            "tool_call_id": message.get("id"),
            "result": result
        }
    
    else:
        return {"type": "error", "error": f"Unknown message type: {msg_type}"}

# --- Endpoints FastAPI ---
@app.get("/")
async def root():
    """Endpoint d'information"""
    return {
        "service": "n8n-mcp-proxy",
        "status": "operational",
        "version": "2.0.0",
        "endpoints": {
            "/": "Service info",
            "/health": "Health check",
            "/sse": "SSE endpoint for MCP (requires Bearer auth)",
            "/mcp": "MCP JSON-RPC endpoint (requires Bearer auth)"
        },
        "n8n_connected": bool(N8N_URL and N8N_API_KEY)
    }

@app.get("/health")
async def health():
    """Health check endpoint"""
    try:
        # Test la connexion n8n
        await _n8n_get("/rest/workflows?limit=1")
        return {
            "status": "healthy",
            "n8n": "connected",
            "n8n_url": N8N_URL.replace("https://", "").replace("http://", "")
        }
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)}
        )

@app.post("/mcp")
async def mcp_endpoint(request: Request):
    """Endpoint JSON-RPC pour MCP"""
    # Vérification Bearer token
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or auth.split(" ", 1)[1] != MCP_BEARER:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    
    try:
        body = await request.json()
        response = await handle_mcp_message(body)
        return JSONResponse(content=response)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

@app.get("/sse")
async def sse_endpoint(request: Request):
    """SSE endpoint pour MCP streaming"""
    async def event_generator():
        try:
            # Envoi du message d'initialisation
            init_msg = {
                "type": "initialize",
                "version": "1.0.0",
                "capabilities": {
                    "tools": True
                }
            }
            yield f"data: {json.dumps(init_msg)}\n\n"
            
            # Keep-alive loop
            while True:
                if await request.is_disconnected():
                    break
                    
                # Envoie un ping toutes les 30 secondes
                await asyncio.sleep(30)
                yield f": keep-alive\n\n"
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            error_msg = {"type": "error", "error": str(e)}
            yield f"data: {json.dumps(error_msg)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*"
        }
    )

# --- Pour test local ---
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting n8n-mcp-proxy on port {port}")
    print(f"N8N URL: {N8N_URL}")
    print(f"Bearer Token configured: {bool(MCP_BEARER)}")
    uvicorn.run(app, host="0.0.0.0", port=port)
