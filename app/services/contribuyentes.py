"""Servicio de contribuyentes y deuda (padrón DWH oficial).

La deuda del padrón sale de la tabla DWH más reciente (DWH_Deudas_Items_YYYYMM).
Los snapshots acumulan una fila POR DÍA por nomencla → la deuda real es la fila
más reciente por nomencla (ROW_NUMBER por FechaActualizacion). Coincide con el
padrón SIGAP (validado en QA).
"""
from app import oraculo_deuda
from app.db import get_conn


def _ultima_tabla_dwh(cur):
    cur.execute(
        "SELECT MAX(table_name) FROM INFORMATION_SCHEMA.TABLES "
        "WHERE table_name LIKE 'DWH_Deudas_Items_%' AND table_name NOT LIKE '%web%'")
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def deuda_contribuyente(codigo):
    """Deuda de un contribuyente (por nomenclatura, ej. IM344002000008).

    La cuenta sale del ORÁCULO DE DEUDA (app/oraculo_deuda.py), la misma
    fuente única que usan la app web, el mapa, el panel y el bot:
    padrón DWH oficial (TotalGral + InteresCertEjec) para IM/CO/CM/PT y
    cálculo interno para CG/DC/JF/PN/MA.
    """
    codigo = str(codigo or '').strip()
    if not codigo:
        return None

    conn = get_conn()
    cur = conn.cursor()

    # Identidad: padrón DWH si existe, si no contribu
    identidad = None
    tabla = _ultima_tabla_dwh(cur)
    if tabla:
        # PERFORMANCE: TOP 1 por nomencla (sin ROW_NUMBER sobre toda la
        # historia — la tabla tiene millones de filas y sin índices).
        cur.execute(f"""
            SELECT TOP 1 Nomencla, NombreRazonSocial, Domicilio, tipocontribuyente, Nombre_Barrio
            FROM [{tabla}] WITH (NOLOCK)
            WHERE Nomencla = ?
            ORDER BY FechaActualizacion DESC""", (codigo,))
        r = cur.fetchone()
        if r:
            identidad = {'nomenclatura': str(r[0]), 'nombre': str(r[1] or ''),
                         'domicilio': str(r[2] or ''), 'tipo': str(r[3] or ''),
                         'barrio': str(r[4] or '')}
    if not identidad:
        cur.execute("SELECT TOP 1 NOMENCLA, RAZONSOCI, TIPOCONTRIBUYENTE "
                    "FROM contribu c WITH (NOLOCK) WHERE c.NOMENCLA = ?", (codigo,))
        fila = cur.fetchone()
        if not fila:
            conn.close()
            return None
        identidad = {'nomenclatura': str(fila[0]), 'nombre': str(fila[1] or ''),
                     'domicilio': '', 'tipo': str(fila[2] or ''), 'barrio': ''}

    reg = oraculo_deuda.deuda_de_nomencla(conn, codigo, identidad['tipo'], tabla)
    conn.close()
    if not reg:
        return None
    return {
        'nomenclatura': identidad['nomenclatura'],
        'nombre': identidad['nombre'],
        'domicilio': identidad['domicilio'],
        'tipo': identidad['tipo'],
        'barrio': identidad['barrio'],
        'deuda': {
            'boletas': reg.get('boletas', 0),
            'planes_pago': reg.get('planes_pago', 0),
            'certificados': reg.get('certificados', 0),
            'valores': reg.get('valores', 0),
            'total': reg.get('total', 0),
        },
        'actualizado': reg.get('actualizado'),
        'fuente': reg.get('fuente'),
    }


def _deuda_interna(codigo):
    """Cálculo interno para tipos sin padrón (CG, DC, JF, PN, MA):
    cuotas pendientes netas de pagos por boleta + planes + certificados."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT TOP 1 c.NOMENCLA, c.RAZONSOCI, c.TIPOCONTRIBUYENTE
            FROM contribu c WITH (NOLOCK) WHERE c.NOMENCLA = ?""", (codigo,))
        fila = cur.fetchone()
        if not fila:
            return None
        cur.execute("""
            SELECT ISNULL(SUM((CASE WHEN IMPORTE0 > 0 THEN IMPORTE0 - ISNULL(DESCTO0,0) ELSE 0 END)
                            + (CASE WHEN ISNULL(IMPORTE1,0) > 0 THEN IMPORTE1 ELSE 0 END)
                            + (CASE WHEN ISNULL(IMPORTE2,0) > 0 THEN IMPORTE2 + ISNULL(RECARGO2,0) ELSE 0 END)
                            + (CASE WHEN ISNULL(IMPORTE3,0) > 0 THEN IMPORTE3 + ISNULL(RECARGO3,0) ELSE 0 END)), 0)
            FROM boletas WITH (NOLOCK) WHERE NOMENCLA = ? AND ANULA = 0""", (codigo,))
        brutas = float(cur.fetchone()[0] or 0)
        cur.execute("""SELECT ISNULL(SUM(ci.total),0) FROM cobritem ci WITH (NOLOCK)
                       INNER JOIN cobros c WITH (NOLOCK) ON ci.NROCOBRO = c.NROCOBRO
                       WHERE c.ANULADO = 0 AND c.NOMENCLA = ? AND ci.BOLETA IS NOT NULL""", (codigo,))
        pagos = float(cur.fetchone()[0] or 0)
        boletas = max(0.0, brutas - pagos)
        cur.execute("""SELECT ISNULL(SUM(CASE WHEN TOTALDEUDA - MONTOPAGADO > 0
                                THEN TOTALDEUDA - MONTOPAGADO ELSE 0 END),0)
                       FROM planpago WITH (NOLOCK) WHERE NOMENCLA = ? AND ANULA = 0 AND ESTADO IN (0,1,3)""",
                    (codigo,))
        planes = float(cur.fetchone()[0] or 0)
        cur.execute("""SELECT ISNULL(SUM(CAPITAL + INTERESES),0)
                       FROM certejec WITH (NOLOCK) WHERE NOMENCLA = ? AND ANULA = 0 AND ESTADO IN (1,2,3)""",
                    (codigo,))
        certs = float(cur.fetchone()[0] or 0)
        return {
            'nomenclatura': str(fila[0]).strip(),
            'nombre': (fila[1] or '').strip(),
            'domicilio': '',
            'tipo': str(fila[2] or '').strip(),
            'barrio': '',
            'deuda': {
                'boletas': round(boletas, 2),
                'planes_pago': round(planes, 2),
                'certificados': round(certs, 2),
                'valores': 0.0,
                'total': round(boletas + planes + certs, 2),
            },
            'actualizado': '',
            'fuente': 'operativo (tipo sin padrón)',
        }
    finally:
        conn.close()


def buscar_contribuyentes(q, limit=10):
    """Busca en el padrón DWH por nomenclatura o nombre (todas las palabras)."""
    import re as _re
    q = str(q or '').strip()
    if not q:
        return {'total': 0, 'resultados': []}
    limit = max(1, min(int(limit or 10), 50))
    like = f'%{q}%'
    # Palabras para coincidencia AND en el nombre (soporta espacios múltiples
    # en la base: 'PEREIRA  GISELA' matchea con 'pereira gisela').
    palabras = [p for p in _re.split(r'\s+', q.replace(',', ' ')) if p]

    conn = get_conn()
    cur = conn.cursor()
    tabla = _ultima_tabla_dwh(cur)
    if not tabla:
        conn.close()
        return {'total': 0, 'resultados': []}

    cond_nombre = ' AND '.join(['NombreRazonSocial LIKE ?'] * len(palabras)) \
        if palabras else '1=0'
    params = [like] + [f'%{p}%' for p in palabras]
    # Rango del DÍA más reciente (cada fila tiene su propio timestamp)
    # Alias 'DeudaTotal' (no 'Total': la tabla DWH tiene una columna Total y
    # el ORDER BY por el alias quedaba ambiguo → error 209).
    cur.execute(f"""
        SELECT TOP {limit} Nomencla, NombreRazonSocial, Domicilio, tipocontribuyente,
               Nombre_Barrio, TotalGral + ISNULL(InteresCertEjec, 0) as DeudaTotal,
               COUNT(*) OVER() as total
        FROM [{tabla}] WITH (NOLOCK)
        WHERE FechaActualizacion >= (SELECT MAX(CONVERT(date, FechaActualizacion)) FROM [{tabla}] WITH (NOLOCK))
          AND FechaActualizacion < DATEADD(day, 1, (SELECT MAX(CONVERT(date, FechaActualizacion)) FROM [{tabla}] WITH (NOLOCK)))
          AND (Nomencla LIKE ? OR ({cond_nombre}))
        ORDER BY DeudaTotal DESC""", params)
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
        # PERFORMANCE: solo el día más reciente (sin ROW_NUMBER sobre la historia)
        cur.execute(f"""
            SELECT Nomencla, TotalGral
            FROM [{tabla}] WITH (NOLOCK)
            WHERE Nomencla IN ({placeholders})
              AND FechaActualizacion >= (SELECT MAX(CONVERT(date, FechaActualizacion)) FROM [{tabla}] WITH (NOLOCK))
              AND FechaActualizacion < DATEADD(day, 1, (SELECT MAX(CONVERT(date, FechaActualizacion)) FROM [{tabla}] WITH (NOLOCK)))""",
            nomenclas)
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

    # PERFORMANCE: solo las filas del día más reciente (una por nomencla).
    # Sin ROW_NUMBER sobre toda la historia (millones de filas sin índices).
    cur.execute(f"""
        SELECT COUNT(*), SUM(TotalBoleta), SUM(TotalPlanPago), SUM(TotalCertEjec),
               SUM(TotalValores), SUM(TotalGral)
        FROM [{tabla}] WITH (NOLOCK)
        WHERE FechaActualizacion >= (SELECT MAX(CONVERT(date, FechaActualizacion)) FROM [{tabla}] WITH (NOLOCK))
          AND FechaActualizacion < DATEADD(day, 1, (SELECT MAX(CONVERT(date, FechaActualizacion)) FROM [{tabla}] WITH (NOLOCK)))""")
    n, boletas, planes, cert, valores, total = cur.fetchone()

    cur.execute(f"""
        SELECT tipocontribuyente, COUNT(*), SUM(TotalGral)
        FROM [{tabla}] WITH (NOLOCK)
        WHERE FechaActualizacion >= (SELECT MAX(CONVERT(date, FechaActualizacion)) FROM [{tabla}] WITH (NOLOCK))
          AND FechaActualizacion < DATEADD(day, 1, (SELECT MAX(CONVERT(date, FechaActualizacion)) FROM [{tabla}] WITH (NOLOCK)))
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
