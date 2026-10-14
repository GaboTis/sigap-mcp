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
MAX_CONSULTAS_BATCH = 6  # máximo de consultas por llamada batch

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


def _sin_order_by_final(sql: str) -> str:
    """Quita el ORDER BY final (a nivel 0 de paréntesis) de la consulta.

    Al envolver la consulta en un SELECT TOP externo, un ORDER BY interno
    sin TOP es inválido en SQL Server ('ORDER BY no es válido en vistas…').
    """
    nivel = 0
    ultima_pos = -1
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == '(':
            nivel += 1
        elif ch == ')':
            nivel -= 1
        elif nivel == 0 and sql[i:i + 8].upper() == 'ORDER BY':
            ultima_pos = i
        i += 1
    if ultima_pos >= 0:
        return sql[:ultima_pos].rstrip()
    return sql


def ejecutar_sql(sql: str) -> dict:
    """Ejecuta una consulta SELECT (validada) contra SIGAP, con límites."""
    try:
        sql_limpia = _validar(sql)
    except ValueError as e:
        return {'ok': False, 'error': f'Consulta rechazada: {e}'}
    # TOP externo: garantiza el tope de filas aunque la consulta no tenga TOP.
    # Sin ORDER BY interno (inválido dentro de la tabla derivada).
    envuelta = f'SELECT TOP ({MAX_FILAS}) * FROM (\n{_sin_order_by_final(sql_limpia)}\n) AS _consulta'

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


def ejecutar_consultas(consultas) -> dict:
    """Ejecuta VARIAS consultas SELECT en una sola llamada (batch).

    Cada consulta se valida con las mismas guardas y se ejecuta en la MISMA
    conexión (una sola ida a la base). Límite: MAX_CONSULTAS_BATCH consultas,
    200 filas por consulta, timeout total 60s.
    """
    if not isinstance(consultas, (list, tuple)):
        return {'ok': False, 'error': 'Se esperaba una lista de consultas.'}
    consultas = [str(c or '') for c in consultas]
    if not consultas:
        return {'ok': False, 'error': 'La lista de consultas está vacía.'}
    if len(consultas) > MAX_CONSULTAS_BATCH:
        return {'ok': False,
                'error': f'Máximo {MAX_CONSULTAS_BATCH} consultas por llamada '
                         f'(recibidas {len(consultas)}). Dividí el análisis en bloques.'}

    # Validar TODAS antes de ejecutar (si una es inválida, se informa cuál)
    validadas = []
    for i, sql in enumerate(consultas):
        try:
            validadas.append(_validar(sql))
        except ValueError as e:
            return {'ok': False, 'error': f'Consulta {i + 1} rechazada: {e}'}

    conn = get_conn()
    resultados = []
    try:
        conn.timeout = 60
        cur = conn.cursor()
        cur.execute('SET LOCK_TIMEOUT 10000')
        for i, sql in enumerate(validadas):
            envuelta = f'SELECT TOP ({MAX_FILAS}) * FROM (\n{_sin_order_by_final(sql)}\n) AS _consulta'
            t0 = time.time()
            try:
                cur.execute(envuelta)
                columnas = [d[0] for d in cur.description] if cur.description else []
                filas = [[_celda(c) for c in r] for r in cur.fetchall()]
                resultados.append({
                    'indice': i + 1,
                    'ok': True,
                    'columnas': columnas,
                    'filas': filas,
                    'cantidad': len(filas),
                    'truncado': len(filas) >= MAX_FILAS,
                    'ms': round((time.time() - t0) * 1000),
                })
            except Exception as e:
                resultados.append({'indice': i + 1, 'ok': False,
                                   'error': f'{type(e).__name__}: {str(e)[:300]}'})
        return {'ok': True, 'total_consultas': len(validadas), 'resultados': resultados}
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
