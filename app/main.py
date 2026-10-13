"""sigap-mcp — entrada única: FastAPI REST + MCP (HTTP) en el mismo proceso.

Uso:
    uvicorn app.main:app --host 0.0.0.0 --port 8100

Endpoints:
    /api/*            → REST con token + scopes (web, dashboards, bots)
    /mcp              → MCP streamable HTTP con token + scope 'mcp'
    /dashboard        → panel ejecutivo web (cliente de esta API)
    /api/health       → estado (sin auth)

Seguridad: tokens por cliente con scopes, rate limiting, auditoría de accesos,
security headers y CORS con lista blanca (ver app/auth.py y docs/SEGURIDAD.md).

El MCP local (stdio) corre aparte: python app/mcp_server.py
"""
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.cors import CORSMiddleware

from app import auth
from app.mcp_server import mcp
from app.routes import router

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('sigap')

# El servidor MCP HTTP necesita su propio lifespan (task group interno).
_mcp_http = mcp.streamable_http_app(streamable_http_path='/mcp')

app = FastAPI(
    title='SIGAP Data API',
    description='Capa de datos municipales de Rawson (SIGAP) — solo lectura. '
                'Acceso por token por cliente con scopes.',
    version='1.1.0',
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
        'version': '1.1.0',
        'acceso': 'solo lectura · token por cliente con scopes',
        'dashboard': '/dashboard',
        'rest': '/api/*  (header Authorization: Bearer <token de cliente>)',
        'mcp_http': '/mcp (Bearer token con scope mcp)',
        'mcp_local': 'python app/mcp_server.py (stdio, sin token)',
        'salud': '/api/health',
    }


# ── CORS con lista blanca de orígenes ─────────────────────────
_CORS = os.getenv('CORS_ORIGINS', '').strip()
if _CORS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in _CORS.split(',') if o.strip()],
        allow_credentials=False,
        allow_methods=['GET', 'POST', 'DELETE'],
        allow_headers=['Authorization', 'Content-Type', 'MCP-Protocol-Version', 'MCP-Session-Id'],
    )
# Sin CORS_ORIGINS → sin headers CORS → solo same-origin (más seguro).


# ── Security headers ──────────────────────────────────────────
@app.middleware('http')
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    if request.url.path.startswith('/api') or request.url.path.startswith('/mcp'):
        response.headers['Cache-Control'] = 'no-store'
    return response


# ── Auditoría + rate limit en el borde ────────────────────────
@app.middleware('http')
async def auditoria(request: Request, call_next):
    inicio = time.time()
    ip = request.client.host if request.client else '?'
    cliente = auth.resolver(request)
    nombre = cliente['nombre'] if cliente else None

    if request.url.path.startswith('/mcp'):
        # El MCP HTTP exige token con scope 'mcp'
        if not cliente or not auth.tiene_scope(cliente, 'mcp'):
            auth.auditar(ip, nombre, request.method, request.url.path, 401, 0)
            return JSONResponse(status_code=401,
                                content={'detail': 'Token con scope "mcp" requerido.'})
        clave = auth._clave_limite(nombre, ip)
        if auth._esta_bloqueado(clave) or not auth._registrar(clave, auth.RATE_MAX_POR_MINUTO):
            auth.auditar(ip, nombre, request.method, request.url.path, 429, 0)
            return JSONResponse(status_code=429,
                                content={'detail': 'Límite de peticiones excedido.'})

    try:
        response = await call_next(request)
    except HTTPException as e:
        auth.auditar(ip, nombre, request.method, request.url.path, e.status_code,
                     (time.time() - inicio) * 1000)
        raise
    ms = (time.time() - inicio) * 1000
    auth.auditar(ip, nombre, request.method, request.url.path, response.status_code, ms)
    return response


# Montaje en raíz (patrón oficial del SDK): las rutas /api/*, /dashboard y /
# registradas antes tienen prioridad; el resto cae en el servidor MCP (paths /mcp*).
app.mount('/', _mcp_http)
