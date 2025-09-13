# app.py
# MCP proxy vers n8n : expose des tools que ChatGPT peut appeler
# Dépendances : openai-agents-python, aiohttp
import os, json, asyncio, aiohttp
from agents.mcp.server import MCPServerStreamableHttp, Tool  # OpenAI Agents SDK (MCP)

N8N_URL = os.environ.get("N8N_URL", "").rstrip("/")
N8N_API_KEY = os.environ.get("N8N_API_KEY", "")
AUTH_TOKENS = [os.environ.get("MCP_BEARER", "change-me")]

HEADERS = {"X-N8N-API-KEY": N8N_API_KEY, "Content-Type": "application/json"}

async def _n8n_get(path: str):
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        async with s.get(f"{N8N_URL}{path}") as r:
            r.raise_for_status()
            return await r.json()

async def _n8n_post(path: str, data: dict):
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        async with s.post(f"{N8N_URL}{path}", data=json.dumps(data)) as r:
            r.raise_for_status()
            return await r.json()

async def _n8n_patch(path: str, data: dict):
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        async with s.patch(f"{N8N_URL}{path}", data=json.dumps(data)) as r:
            r.raise_for_status()
            return await r.json()

async def _n8n_delete(path: str):
    async with aiohttp.ClientSession(headers=HEADERS) as s:
        async with s.delete(f"{N8N_URL}{path}") as r:
            r.raise_for_status()
            return {"ok": True, "status": r.status}

# --------- TOOLS EXPOSÉS À CHATGPT ---------

# 1) Lister les workflows
async def list_workflows(_=None):
    return await _n8n_get("/rest/workflows")

# 2) Créer un workflow (JSON n8n complet attendu)
#    Exige un objet {"workflow": {...}} — exactement ce que tu importerais dans n8n
async def create_workflow(args):
    wf = args.get("workflow")
    if not wf:
        return {"error": "Paramètre 'workflow' manquant"}
    return await _n8n_post("/rest/workflows", wf)

# 3) Activer / désactiver un workflow
async def set_active(args):
    workflow_id = args.get("workflow_id")
    active = bool(args.get("active", True))
    if not workflow_id:
        return {"error": "Paramètre 'workflow_id' manquant"}
    return await _n8n_patch(f"/rest/workflows/{workflow_id}", {"active": active})

# 4) Supprimer un workflow
async def delete_workflow(args):
    workflow_id = args.get("workflow_id")
    if not workflow_id:
        return {"error": "Paramètre 'workflow_id' manquant"}
    return await _n8n_delete(f"/rest/workflows/{workflow_id}")

# 5) Déclencher un workflow via Webhook (ton workflow doit avoir un Webhook Trigger)
async def run_webhook(args):
    path = args.get("path")  # ex: "/webhook/abc123"
    payload = args.get("payload", {})
    if not path or not path.startswith("/"):
        return {"error": "Paramètre 'path' invalide (ex: /webhook/abc123)"}
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{N8N_URL}{path}", json=payload) as r:
            # pas d'API key pour le webhook public ; utilise un secret dans l'URL n8n
            try:
                data = await r.json()
            except Exception:
                data = await r.text()
            return {"status": r.status, "response": data}

server = MCPServerStreamableHttp(
    tools=[
        Tool(
            name="list_workflows",
            description="Liste tous les workflows n8n (GET /rest/workflows).",
            input_schema={"type": "object", "properties": {}},
        )(lambda args: list_workflows(args)),

        Tool(
            name="create_workflow",
            description="Crée un workflow n8n. Input: { workflow: <JSON n8n export/import> }",
            input_schema={"type": "object", "properties": {
                "workflow": {"type": "object"}
            }, "required": ["workflow"]},
        )(create_workflow),

        Tool(
            name="set_active",
            description="Active/Désactive un workflow. Input: { workflow_id: string|number, active: boolean }",
            input_schema={"type": "object", "properties": {
                "workflow_id": {"type": ["string","number"]},
                "active": {"type": "boolean", "default": True}
            }, "required": ["workflow_id"]},
        )(set_active),

        Tool(
            name="delete_workflow",
            description="Supprime un workflow. Input: { workflow_id }",
            input_schema={"type": "object", "properties": {
                "workflow_id": {"type": ["string","number"]}
            }, "required": ["workflow_id"]},
        )(delete_workflow),

        Tool(
            name="run_webhook",
            description="Déclenche un workflow par son webhook. Input: { path: '/webhook/...', payload?: object }",
            input_schema={"type": "object", "properties": {
                "path": {"type": "string"},
                "payload": {"type": "object"}
            }, "required": ["path"]},
        )(run_webhook),
    ],
    auth_tokens=AUTH_TOKENS,  # Bearer token pour ChatGPT
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    asyncio.run(server.run(host="0.0.0.0", port=port))  # exposé sur /sse
