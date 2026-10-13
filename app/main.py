"""sigap-mcp — entrada única: FastAPI REST + MCP (HTTP) en el mismo proceso.

Uso:
    uvicorn app.main:app --host 127.0.0.1 --port 8100

Endpoints:
    /api/*            → REST con token (web, dashboards, bots)
    /mcp              → MCP streamable HTTP con token
    /api/health       → estado (sin auth)

El MCP local (stdio) corre aparte: python app/mcp_server.py
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from starlette.requests import Request

from app.mcp_server import mcp
from app.routes import router

load_dotenv()
API_TOKEN = os.getenv('API_TOKEN', '')

# El servidor MCP HTTP necesita su propio lifespan (task group interno).
_mcp_http = mcp.streamable_http_app(streamable_http_path='/mcp')

app = FastAPI(
    title='SIGAP Data API',
    description='Capa de datos municipales de Rawson (SIGAP) — solo lectura. '
                'Consumida por la app web, dashboards ejecutivos y agentes IA (MCP).',
    version='1.0.0',
    lifespan=_mcp_http.router.lifespan_context,
)

app.include_router(router)


@app.get('/dashboard')
def dashboard():
    """Panel Ejecutivo standalone — cliente web de esta API."""
    ruta = Path(__file__).parent / 'static' / 'dashboard.html'
    return FileResponse(ruta)


@app.get('/')
def raiz():
    return {
        'servicio': 'sigap-mcp',
        'version': '1.0.0',
        'acceso': 'solo lectura',
        'dashboard': '/dashboard (panel ejecutivo web)',
        'rest': '/api/*  (header Authorization: Bearer <API_TOKEN>)',
        'mcp_http': '/mcp (Bearer token)',
        'mcp_local': 'python app/mcp_server.py (stdio, sin token)',
        'salud': '/api/health',
    }


# ── MCP sobre HTTP con token ─────────────────────────────────
if API_TOKEN:
    @app.middleware('http')
    async def proteger_mcp(request: Request, call_next):
        if request.url.path.startswith('/mcp'):
            auth = request.headers.get('authorization', '')
            if auth != f'Bearer {API_TOKEN}':
                return JSONResponse(status_code=401,
                                    content={'detail': 'Token requerido para MCP HTTP'})
        return await call_next(request)

# Montaje en raíz (patrón oficial del SDK): las rutas /api/* y / registradas
# antes tienen prioridad; el resto cae en el servidor MCP (paths /mcp*).
app.mount('/', _mcp_http)
