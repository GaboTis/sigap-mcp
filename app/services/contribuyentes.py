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
