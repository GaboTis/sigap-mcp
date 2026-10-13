"""Autenticación y autorización por cliente.

Modelo de seguridad:
- Cada cliente (dashboard, app web, bot WhatsApp, etc.) tiene SU PROPIO token,
  listado en tokens.json (gitignored). Revocar un cliente = borrar su entrada.
- Cada token tiene scopes: permisos mínimos por cliente (least privilege).
  Scope '*' = acceso total (solo para administración interna).
- Rate limiting por cliente y por IP (ventana deslizante en memoria).
- Auditoría: cada petición autenticada queda registrada en logs/access.log.
"""
import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from dotenv import load_dotenv
from fastapi import HTTPException, Request, status

load_dotenv()
logger = logging.getLogger('sigap.acceso')

_TOKENS_FILE = Path(__file__).resolve().parent.parent / 'tokens.json'
_LOG_FILE = Path(__file__).resolve().parent.parent / 'logs' / 'access.log'

# ── Configuración ─────────────────────────────────────────────
RATE_MAX_POR_MINUTO = int(os.getenv('RATE_LIMIT_POR_MINUTO', '120'))       # por cliente
RATE_MAX_IP_POR_MINUTO = int(os.getenv('RATE_LIMIT_IP_POR_MINUTO', '30'))  # sin token / por IP
BLOQUEO_SEGUNDOS = int(os.getenv('RATE_LIMIT_BLOQUEO_SEG', '300'))

_audit_lock = threading.Lock()


def cargar_clientes() -> dict:
    """token → {'nombre', 'scopes'} desde tokens.json (única fuente)."""
    clientes = {}
    if _TOKENS_FILE.exists():
        try:
            data = json.loads(_TOKENS_FILE.read_text(encoding='utf-8'))
            for nombre, cfg in data.get('clientes', {}).items():
                token = (cfg.get('token') or '').strip()
                if token:
                    clientes[token] = {'nombre': nombre, 'scopes': cfg.get('scopes', [])}
        except Exception as e:
            logger.error(f'No se pudo leer tokens.json: {e}')
    if not clientes:
        logger.warning('auth: no hay tokens definidos en tokens.json — la API quedará cerrada.')
    return clientes


CLIENTES = cargar_clientes()

# ── Rate limiting (ventana deslizante en memoria) ─────────────
_ventanas = defaultdict(deque)
_bloqueos = {}
# RLock (reentrante): _registrar → _bloquear anidan el mismo lock.
_rl_lock = threading.RLock()


def _clave_limite(cliente, ip):
    return f'{cliente}|{ip}' if cliente else f'ip|{ip}'


def _esta_bloqueado(clave):
    with _rl_lock:
        hasta = _bloqueos.get(clave)
        if hasta and time.time() < hasta:
            return True
        if hasta:
            _bloqueos.pop(clave, None)
    return False


def _bloquear(clave):
    with _rl_lock:
        _bloqueos[clave] = time.time() + BLOQUEO_SEGUNDOS


def _registrar(clave, maximo):
    ahora = time.time()
    with _rl_lock:
        cola = _ventanas[clave]
        while cola and ahora - cola[0] > 60:
            cola.popleft()
        if len(cola) >= maximo:
            _bloquear(clave)
            return False
        cola.append(ahora)
        return True


# ── Auditoría ─────────────────────────────────────────────────
def auditar(ip, cliente, metodo, ruta, codigo, ms):
    """Registra el acceso en logs/access.log (formato simple, parseable)."""
    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        linea = (f'{time.strftime("%Y-%m-%d %H:%M:%S")} | {ip} | {cliente or "-"} | '
                 f'{metodo} {ruta} | {codigo} | {ms:.0f}ms\n')
        with _audit_lock, open(_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(linea)
    except Exception:
        pass


# ── Resolución de token ──────────────────────────────────────
def resolver(request: Request) -> dict:
    """Devuelve el cliente {'nombre','scopes'} o None si no hay token válido."""
    auth = request.headers.get('authorization', '')
    if auth.startswith('Bearer '):
        token = auth[7:].strip()
        return CLIENTES.get(token)
    return None


def tiene_scope(cliente, scope):
    scopes = cliente.get('scopes', [])
    return '*' in scopes or scope in scopes


def verificar(request: Request) -> dict:
    """Autentica y aplica rate limit. Lanza 401/429."""
    ip = request.client.host if request.client else '?'
    cliente = resolver(request)
    clave = _clave_limite(cliente['nombre'] if cliente else None, ip)

    if _esta_bloqueado(clave):
        raise HTTPException(status_code=429,
                            detail='Demasiadas peticiones. Intente más tarde.')

    if not cliente:
        if not _registrar(clave, RATE_MAX_IP_POR_MINUTO):
            raise HTTPException(status_code=429, detail='Límite de peticiones excedido.')
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail='Token inválido o ausente.')

    if not _registrar(clave, RATE_MAX_POR_MINUTO):
        raise HTTPException(status_code=429, detail='Límite de peticiones excedido.')

    request.state.cliente = cliente
    return cliente


def requiere_scope(scope):
    """Dependency factory: exige token con el scope indicado."""

    def _dependencia(request: Request) -> dict:
        cliente = verificar(request)
        if not tiene_scope(cliente, scope):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail=f'El token no tiene permiso "{scope}".')
        return cliente

    return _dependencia
