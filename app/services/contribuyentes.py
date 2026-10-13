"""Servicio de contribuyentes y deuda (padrón DWH oficial).

La deuda del padrón sale de la tabla DWH más reciente (DWH_Deudas_Items_YYYYMM).
Los snapshots acumulan una fila POR DÍA por nomencla → la deuda real es la fila
más reciente por nomencla (ROW_NUMBER por FechaActualizacion). Coincide con el
padrón SIGAP (validado en QA).
"""
from app.db import get_conn


def _ultima_tabla_dwh(cur):
    cur.execute(
        "SELECT MAX(table_name) FROM INFORMATION_SCHEMA.TABLES "
        "WHERE table_name LIKE 'DWH_Deudas_Items_%' AND table_name NOT LIKE '%web%'")
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def deuda_contribuyente(codigo):
    """Deuda del padrón oficial de un contribuyente (por nomenclatura, ej. IM344002000008)."""
    codigo = str(codigo or '').strip()
    if not codigo:
        return None

    conn = get_conn()
    cur = conn.cursor()
    tabla = _ultima_tabla_dwh(cur)
    if not tabla:
        conn.close()
        return None

    cur.execute(f"""
        SELECT Nomencla, NombreRazonSocial, Domicilio, tipocontribuyente, Nombre_Barrio,
               TotalBoleta, TotalPlanPago, TotalCertEjec, TotalValores, TotalGral,
               FechaActualizacion
        FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY Nomencla ORDER BY FechaActualizacion DESC) rn
            FROM [{tabla}] WITH (NOLOCK)
        ) x
        WHERE rn = 1 AND Nomencla = ?""", (codigo,))
    r = cur.fetchone()
    conn.close()
    if not r:
        return None

    return {
        'nomenclatura': str(r[0]),
        'nombre': str(r[1] or ''),
        'domicilio': str(r[2] or ''),
        'tipo': str(r[3] or ''),
        'barrio': str(r[4] or ''),
        'deuda': {
            'boletas': float(r[5] or 0),
            'planes_pago': float(r[6] or 0),
            'certificados': float(r[7] or 0),
            'valores': float(r[8] or 0),
            'total': float(r[9] or 0),
        },
        'actualizado': str(r[10] or ''),
        'fuente': tabla,
    }


def buscar_contribuyentes(q, limit=10):
    """Busca en el padrón DWH por nomenclatura o nombre."""
    q = str(q or '').strip()
    if not q:
        return {'total': 0, 'resultados': []}
    limit = max(1, min(int(limit or 10), 50))
    like = f'%{q}%'

    conn = get_conn()
    cur = conn.cursor()
    tabla = _ultima_tabla_dwh(cur)
    if not tabla:
        conn.close()
        return {'total': 0, 'resultados': []}

    cur.execute(f"""
        SELECT TOP {limit} Nomencla, NombreRazonSocial, Domicilio, tipocontribuyente,
               Nombre_Barrio, TotalGral, COUNT(*) OVER() as total
        FROM [{tabla}] WITH (NOLOCK)
        WHERE FechaActualizacion = (SELECT MAX(FechaActualizacion) FROM [{tabla}] WITH (NOLOCK))
          AND (Nomencla LIKE ? OR NombreRazonSocial LIKE ?)
        ORDER BY TotalGral DESC""", (like, like))
    raw = cur.fetchall()
    conn.close()

    total = int(raw[0][6]) if raw else 0
    resultados = [{
        'nomenclatura': str(r[0]), 'nombre': str(r[1] or ''), 'domicilio': str(r[2] or ''),
        'tipo': str(r[3] or ''), 'barrio': str(r[4] or ''), 'deuda_total': float(r[5] or 0),
    } for r in raw]
    return {'total': total, 'resultados': resultados}


def buscar_por_dni(dni):
    """Busca contribuyentes por DNI (para verificación de identidad).

    Busca en contribu (DNIOCUIT o DNI) y une el padrón DWH para nombre,
    domicilio y deuda. Devuelve los datos completos al LLM — el agente es
    responsable de NO mostrarlos al usuario antes de la verificación.
    """
    dni = int(dni or 0)
    if dni <= 0:
        return {'total': 0, 'resultados': []}

    conn = get_conn()
    cur = conn.cursor()
    tabla = _ultima_tabla_dwh(cur)

    cur.execute("""
        SELECT c.NOMENCLA, c.TIPOCONTRIBUYENTE, c.RAZONSOCI,
               RTRIM(ISNULL(c.CALLEFISCAL,'')) + ' ' + ISNULL(CAST(c.NUMEROFISCAL AS varchar), '') as domicilio,
               ISNULL(c.BARRIO,'') as barrio,
               CASE WHEN c.FECHABAJA = CONVERT(datetime,'1900-01-01') THEN 1 ELSE 0 END as activo
        FROM contribu c WITH (NOLOCK)
        WHERE (c.DNIOCUIT = ? OR c.DNI = ?)
        ORDER BY activo DESC""", (dni, dni))
    filas = cur.fetchall()
    conn.close()
    if not filas:
        return {'total': 0, 'dni': dni, 'resultados': []}

    resultados = []
    for r in filas[:10]:
        nomencla = str(r[0]).strip()
        resultados.append({
            'nomenclatura': nomencla,
            'tipo': str(r[1] or '').strip(),
            'nombre': str(r[2] or '').strip(),
            'domicilio': str(r[3] or '').strip(),
            'barrio': str(r[4] or '').strip(),
            'activo': bool(r[5]),
        })

    # Enriquecer con la deuda del padrón (sin volver a abrir otra conexión pesada)
    if tabla and resultados:
        conn = get_conn()
        cur = conn.cursor()
        nomenclas = [x['nomenclatura'] for x in resultados]
        placeholders = ','.join('?' * len(nomenclas))
        cur.execute(f"""
            SELECT Nomencla, TotalGral FROM (
                SELECT Nomencla, TotalGral,
                       ROW_NUMBER() OVER (PARTITION BY Nomencla ORDER BY FechaActualizacion DESC) rn
                FROM [{tabla}] WITH (NOLOCK)
            ) x WHERE rn = 1 AND Nomencla IN ({placeholders})""", nomenclas)
        deudas = {str(r[0]): float(r[1] or 0) for r in cur.fetchall()}
        conn.close()
        for x in resultados:
            x['deuda_total'] = round(deudas.get(x['nomenclatura'], 0), 2)

    return {'total': len(resultados), 'dni': dni, 'resultados': resultados}


def _normalizar(texto):
    """Normaliza para comparar: mayúsculas, sin acentos, espacios colapsados."""
    import unicodedata
    t = unicodedata.normalize('NFKD', str(texto or '')).encode('ascii', 'ignore').decode()
    return ' '.join(t.upper().split())


def verificar_identidad(dni, nomenclatura, respuesta):
    """Verifica la identidad comparando la respuesta del usuario con el padrón.

    Reglas de coincidencia (sobre texto normalizado):
    - respuesta == calle completa (ej. "CANO 0")
    - respuesta == calle sin número (ej. "CANO" contra "CANO 0")
    - respuesta == nombre del titular
    - respuesta contenida en la calle registrada
    """
    datos = buscar_por_dni(dni)
    cuenta = next((x for x in datos.get('resultados', [])
                   if x['nomenclatura'] == str(nomenclatura).strip()), None)
    if not cuenta:
        return {'verificada': False, 'motivo': 'La cuenta no corresponde al DNI indicado.'}

    resp_n = _normalizar(respuesta)
    if not resp_n:
        return {'verificada': False, 'motivo': 'Respuesta vacía.'}

    calle_n = _normalizar(cuenta['domicilio'])
    nombre_n = _normalizar(cuenta['nombre'])
    calle_sin_numero = ' '.join(calle_n.split(' ')[:-1]) if ' ' in calle_n else calle_n

    coincide = (resp_n == calle_n or resp_n == calle_sin_numero or resp_n == nombre_n
                or resp_n in calle_n)
    return {
        'verificada': coincide,
        'cuenta': cuenta['nomenclatura'],
        'motivo': 'Identidad verificada.' if coincide else
                  'La respuesta no coincide con el dato registrado en el padrón.',
    }


def resumen_deuda():
    """Deuda municipal total del padrón (por componente y tipo de contribuyente)."""
    conn = get_conn()
    cur = conn.cursor()
    tabla = _ultima_tabla_dwh(cur)
    if not tabla:
        conn.close()
        return None

    cur.execute(f"""
        SELECT COUNT(*), SUM(TotalBoleta), SUM(TotalPlanPago), SUM(TotalCertEjec),
               SUM(TotalValores), SUM(TotalGral)
        FROM (
            SELECT TotalBoleta, TotalPlanPago, TotalCertEjec, TotalValores, TotalGral,
                   ROW_NUMBER() OVER (PARTITION BY Nomencla ORDER BY FechaActualizacion DESC) rn
            FROM [{tabla}] WITH (NOLOCK)
        ) x WHERE rn = 1""")
    n, boletas, planes, cert, valores, total = cur.fetchone()

    cur.execute(f"""
        SELECT tipocontribuyente, COUNT(*), SUM(TotalGral)
        FROM (
            SELECT tipocontribuyente, TotalGral,
                   ROW_NUMBER() OVER (PARTITION BY Nomencla ORDER BY FechaActualizacion DESC) rn
            FROM [{tabla}] WITH (NOLOCK)
        ) x WHERE rn = 1
        GROUP BY tipocontribuyente ORDER BY 3 DESC""")
    por_tipo = [{'tipo': str(r[0]), 'contribuyentes': int(r[1]), 'deuda': float(r[2] or 0)}
                for r in cur.fetchall()]
    conn.close()

    return {
        'contribuyentes_con_deuda': int(n or 0),
        'total': float(total or 0),
        'componentes': {'boletas': float(boletas or 0), 'planes_pago': float(planes or 0),
                        'certificados': float(cert or 0), 'valores': float(valores or 0)},
        'por_tipo': por_tipo,
        'fuente': tabla,
    }
