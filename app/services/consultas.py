"""Consultas SQL generadas por el agente — SOLO LECTURA, con guardas fuertes.

El agente (LLM) genera la consulta; este servicio la valida, la ejecuta contra
SQL Server con límites duros (filas, timeout, lock timeout) y devuelve filas
compactas. Todo queda auditado por el middleware de acceso.
"""
import logging
import re
import time

from app.db import get_conn

logger = logging.getLogger('sigap.consultas')

MAX_FILAS = 200          # máximo de filas devueltas al agente
TIMEOUT_S = 20           # timeout de ejecución (segundos)
CELDA_MAX = 500          # truncado de celdas de texto largas

# Instrucciones prohibidas aunque estén dentro de un SELECT (defensa en profundidad)
_PROHIBIDOS = re.compile(
    r'\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|EXEC(UTE)?|'
    r'OPENROWSET|OPENQUERY|OPENXML|INTO|WAITFOR|BACKUP|RESTORE|GRANT|REVOKE|'
    r'DENY|DBCC|BULK|SAVE|xp_|sp_)\b',
    re.IGNORECASE,
)


def _validar(sql: str) -> str:
    """Valida que sea UNA sola sentencia SELECT inocua. Lanza ValueError."""
    s = sql or ''
    s = re.sub(r'--[^\n]*', ' ', s)               # comentarios de línea
    s = re.sub(r'/\*.*?\*/', ' ', s, flags=re.S)  # comentarios de bloque
    s = s.strip().rstrip(';').strip()
    if not s:
        raise ValueError('La consulta está vacía.')
    if len(s) > 4000:
        raise ValueError('La consulta es demasiado larga (máx. 4.000 caracteres).')
    if _PROHIBIDOS.search(s):
        raise ValueError('La consulta contiene instrucciones no permitidas (solo SELECT).')
    if not re.match(r'^(SELECT|WITH)\b', s, re.IGNORECASE):
        raise ValueError('Solo se permiten consultas SELECT.')
    partes = s.split(';', 1)
    if len(partes) > 1 and partes[1].strip():
        raise ValueError('Solo se permite una sentencia por consulta.')
    return s


def _celda(v):
    """Convierte un valor pyodbc a algo JSON-serializable y compacto."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(v, 4) if isinstance(v, float) else v
    if isinstance(v, bytes):
        v = v.decode('utf-8', 'replace')
    if hasattr(v, 'isoformat'):  # date/datetime
        return v.isoformat()[:19]
    s = str(v)
    return s if len(s) <= CELDA_MAX else s[:CELDA_MAX] + f'…({len(s)} chars)'


def ejecutar_sql(sql: str) -> dict:
    """Ejecuta una consulta SELECT (validada) contra SIGAP, con límites."""
    try:
        sql_limpia = _validar(sql)
    except ValueError as e:
        return {'ok': False, 'error': f'Consulta rechazada: {e}'}
    # TOP externo: garantiza el tope de filas aunque la consulta no tenga TOP.
    envuelta = f'SELECT TOP ({MAX_FILAS}) * FROM (\n{sql_limpia}\n) AS _consulta'

    conn = get_conn()
    try:
        conn.timeout = TIMEOUT_S
        cur = conn.cursor()
        cur.execute('SET LOCK_TIMEOUT 10000')  # no bloquear el OLTP municipal
        t0 = time.time()
        cur.execute(envuelta)
        columnas = [d[0] for d in cur.description] if cur.description else []
        filas = [[_celda(c) for c in r] for r in cur.fetchall()]
        ms = round((time.time() - t0) * 1000)
        return {
            'ok': True,
            'columnas': columnas,
            'filas': filas,
            'cantidad': len(filas),
            'truncado': len(filas) >= MAX_FILAS,
            'ms': ms,
        }
    except Exception as e:
        # El error de SQL se devuelve al agente para que corrija la consulta.
        logger.warning(f'consulta rechazada: {str(e)[:200]}')
        return {'ok': False, 'error': f'{type(e).__name__}: {str(e)[:400]}'}
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ── Catálogo (tablas y columnas) para que el LLM genere SQL ────

_catalogo_cache = {'ts': 0.0, 'tablas': None, 'columnas': {}}
_CATALOGO_TTL = 3600


def listar_tablas(filtro: str = '') -> dict:
    """Lista tablas de SIGAP con cantidad de filas (las más grandes primero)."""
    global _catalogo_cache
    filtro = (filtro or '').strip()
    if _catalogo_cache['tablas'] and (time.time() - _catalogo_cache['ts']) < _CATALOGO_TTL:
        tablas = _catalogo_cache['tablas']
    else:
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT t.name, SUM(p.rows) AS filas
                FROM sys.tables t WITH (NOLOCK)
                JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0, 1)
                GROUP BY t.name
                ORDER BY SUM(p.rows) DESC
            """)
            tablas = [(r[0], int(r[1] or 0)) for r in cur.fetchall()]
            _catalogo_cache = {'ts': time.time(), 'tablas': tablas,
                               'columnas': _catalogo_cache['columnas']}
        finally:
            conn.close()
    if filtro:
        tablas = [t for t in tablas if filtro.lower() in t[0].lower()]
    return {'total': len(tablas),
            'tablas': [{'nombre': n, 'filas': f} for n, f in tablas[:50]]}


def columnas_tabla(tabla: str) -> dict:
    """Columnas de una tabla (nombre y tipo) para armar la consulta."""
    global _catalogo_cache
    tabla = (tabla or '').strip()
    if not re.match(r'^[A-Za-z0-9_]+$', tabla):
        return {'error': 'Nombre de tabla inválido.'}
    if tabla in _catalogo_cache['columnas'] and \
            (time.time() - _catalogo_cache['ts']) < _CATALOGO_TTL:
        return {'tabla': tabla, 'columnas': _catalogo_cache['columnas'][tabla]}

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = ?
            ORDER BY ORDINAL_POSITION
        """, (tabla,))
        columnas = [{'nombre': r[0], 'tipo': r[1], 'largo': int(r[2] or 0)}
                    for r in cur.fetchall()]
        if not columnas:
            return {'tabla': tabla, 'columnas': [],
                    'error': f'La tabla "{tabla}" no existe en SIGAP.'}
        _catalogo_cache['columnas'][tabla] = columnas
        return {'tabla': tabla, 'columnas': columnas}
    finally:
        conn.close()
