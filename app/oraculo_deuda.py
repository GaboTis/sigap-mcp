# ============================================================================
# SIGAPP KPI — ORÁCULO DE DEUDA (fuente única de verdad)
# Archivo: shared/deuda.py
# ============================================================================
"""
Un solo lugar para calcular la deuda de un contribuyente. TODOS los módulos
(lista, mapa, detalle, panel, MCP/bot) deben usar estas funciones para que
los valores sean idénticos en cualquier pantalla o canal.

Modelo auditado (octubre 2026):
1. Padrón DWH oficial (tipos IM, CO, CM, PT): la deuda viene de la última
   snapshot DWH_Deudas_Items_YYYYMM (fila más reciente por nomencla).
   TotalBoleta/TotalPlanPago/TotalValores YA incluyen su interés; solo el
   interés de certificados de ejecución va aparte (InteresCertEjec).
       DEUDA = TotalGral + InteresCertEjec
2. Tipos sin padrón (CG, DC, JF, PN, MA): cálculo interno por nomencla —
   boletas netas de pagos por boleta + planes de pago con saldo
   (TOTALDEUDA - MONTOPAGADO, estados 0/1/3) + certificados de ejecución
   (CAPITAL + INTERESES, estados 1/2/3).
3. Pagos: siempre por BOLETA (cobritem), nunca por contribuyente a secas.
4. La deuda vencida nunca puede superar la deuda total.

Para agregar un tipo al padrón o cambiar el cálculo interno, se edita
SOLO este archivo.
"""
import logging

logger = logging.getLogger(__name__)

# Tipos que el padrón DWH oficial cubre (se redescubren desde la base en
# `tipos_con_padron`, pero estos son el mínimo conocido).
TIPOS_PADRON_BASE = ('IM', 'CO', 'CM', 'PT')

# Tipos que se calculan internamente (sin padrón oficial)
TIPOS_INTERNOS = ('CG', 'DC', 'JF', 'PN', 'MA')


def obtener_tabla_dwh(conn):
    """Nombre de la snapshot DWH más reciente (DWH_Deudas_Items_YYYYMM)."""
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(table_name) FROM INFORMATION_SCHEMA.TABLES "
                   "WHERE table_name LIKE 'DWH_Deudas_Items_%' "
                   "AND table_name NOT LIKE '%web%'")
    fila = cursor.fetchone()
    cursor.close()
    return fila[0] if fila and fila[0] else None


def tipos_con_padron(conn):
    """Tipos de contribuyente presentes en el padrón DWH con deuda > 0."""
    tabla = obtener_tabla_dwh(conn)
    if not tabla:
        return list(TIPOS_PADRON_BASE)
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT DISTINCT LTRIM(RTRIM(tipocontribuyente)) "
                       f"FROM [{tabla}] WITH (NOLOCK) WHERE ISNULL(TotalGral, 0) > 0")
        tipos = [str(r[0]).strip() for r in cursor.fetchall() if r and r[0]]
        return tipos or list(TIPOS_PADRON_BASE)
    except Exception as e:
        logger.warning(f'deuda: no se pudo leer tipos del padrón: {e}')
        return list(TIPOS_PADRON_BASE)
    finally:
        cursor.close()


def _es_tipo_padron(tipo, conn=None, tipos_padron=None):
    tipo = str(tipo or '').strip().upper()
    if tipo in TIPOS_INTERNOS:
        return False
    if tipo in TIPOS_PADRON_BASE:
        return True
    if tipos_padron is not None:
        return tipo in tipos_padron
    if conn is not None:
        return tipo in tipos_con_padron(conn)
    return False


def sql_rango_ultimo_dia(tabla):
    """Fragmento WHERE: filas del DÍA más reciente de una snapshot DWH.

    Cada fila tiene su propio timestamp, así que NO sirve comparar con
    MAX(FechaActualizacion) (solo matchea las últimas filas escritas).
    Este rango toma todas las filas del último día (~una por nomencla)
    sin window pesado ni memory grant.
    """
    return (f"FechaActualizacion >= (SELECT MAX(CONVERT(date, FechaActualizacion)) "
            f"FROM [{tabla}] WITH (NOLOCK)) AND "
            f"FechaActualizacion < DATEADD(day, 1, (SELECT MAX(CONVERT(date, FechaActualizacion)) "
            f"FROM [{tabla}] WITH (NOLOCK)))")


# ── SQL del cálculo interno (una nomencla) ─────────────────────

_SQL_INTERNO = {
    'bruto_boletas': """
        SELECT ISNULL(SUM(
            (CASE WHEN b.IMPORTE0 > 0 THEN b.IMPORTE0 - ISNULL(b.DESCTO0, 0) ELSE 0 END)
          + (CASE WHEN ISNULL(b.IMPORTE1, 0) > 0 THEN b.IMPORTE1 ELSE 0 END)
          + (CASE WHEN ISNULL(b.IMPORTE2, 0) > 0 THEN b.IMPORTE2 + ISNULL(b.RECARGO2, 0) ELSE 0 END)
          + (CASE WHEN ISNULL(b.IMPORTE3, 0) > 0 THEN b.IMPORTE3 + ISNULL(b.RECARGO3, 0) ELSE 0 END)), 0)
        FROM boletas b WITH (NOLOCK)
        WHERE b.NOMENCLA = ? AND b.ANULA = 0
    """,
    'pagos': """
        SELECT ISNULL(SUM(ci.total), 0)
        FROM cobros co2 WITH (NOLOCK)
        JOIN cobritem ci WITH (NOLOCK) ON ci.NROCOBRO = co2.NROCOBRO
        WHERE co2.NOMENCLA = ? AND co2.ANULADO = 0
    """,
    'planes_saldo': """
        SELECT ISNULL(SUM(CASE WHEN TOTALDEUDA - MONTOPAGADO > 0
                               THEN TOTALDEUDA - MONTOPAGADO ELSE 0 END), 0)
        FROM planpago WITH (NOLOCK)
        WHERE NOMENCLA = ? AND ANULA = 0 AND ESTADO IN (0, 1, 3)
    """,
    'certificados': """
        SELECT ISNULL(SUM(CAPITAL + INTERESES), 0)
        FROM certejec WITH (NOLOCK)
        WHERE NOMENCLA = ? AND ANULA = 0 AND ESTADO IN (1, 2, 3)
    """,
}


def deuda_interna_nomencla(conn, codigo):
    """Deuda interna (tipos sin padrón) para UNA nomencla.

    Devuelve el mismo desglose que `deuda_de_nomencla` para poder
    comparar módulos. Modelo: boletas netas de pagos por boleta +
    planes con saldo + certificados.
    """
    cursor = conn.cursor()
    valores = {}
    for clave, sql in _SQL_INTERNO.items():
        cursor.execute(sql, (codigo,))
        valores[clave] = float(cursor.fetchone()[0] or 0)
    cursor.close()
    boletas_netas = max(0, valores['bruto_boletas'] - valores['pagos'])
    total = round(boletas_netas + valores['planes_saldo'] + valores['certificados'], 2)
    return {
        'total': total,
        'boletas': round(boletas_netas, 2),
        'planes_pago': round(valores['planes_saldo'], 2),
        'certificados': round(valores['certificados'], 2),
        'valores': 0,
        'bruto_boletas': round(valores['bruto_boletas'], 2),
        'pagos_directos': round(valores['pagos'], 2),
        'fuente': 'interna (tipo sin padrón DWH)',
        'actualizado': None,
    }


def deuda_padron_nomencla(conn, codigo, tabla=None):
    """Deuda del padrón (fila más reciente por nomencla) + interés de
    certificados. Devuelve None si no hay fila.

    Estrategia (el MSSQL de producción NO se toca):
    1. Primero NUESTRO PostgreSQL (tabla dwh_padron, espejo nocturno vía ETL)
       — respuesta en milisegundos con índice.
    2. Fallback: MSSQL con TOP 1 por nomencla (stream, sin memory grant),
       por si el ETL no corrió todavía.
    """
    try:
        import os

        import psycopg2
        import psycopg2.extras
        pg = psycopg2.connect(
            host=os.getenv('PG_HOST', 'postgres'),
            port=os.getenv('PG_PORT', '5432'),
            dbname=os.getenv('PG_DATABASE', 'sigap_kpi'),
            user=os.getenv('PG_USER', 'sigap'),
            password=os.getenv('PG_PASSWORD', 'sigap_dev_2026'))
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as curpg:
            curpg.execute('SELECT * FROM dwh_padron WHERE Nomencla = %s', (codigo,))
            d = curpg.fetchone()
        pg.close()
        if d:
            return {
                'total': round(float(d.get('totalgral', 0) or 0)
                               + float(d.get('interescertejec', 0) or 0), 2),
                'boletas': round(float(d.get('totalboleta', 0) or 0), 2),
                'planes_pago': round(float(d.get('totalplanpago', 0) or 0), 2),
                'certificados': round(float(d.get('totalcertejec', 0) or 0)
                                      + float(d.get('interescertejec', 0) or 0), 2),
                'valores': round(float(d.get('totalvalores', 0) or 0), 2),
                'nominal': round(float(d.get('totalnominal', 0) or 0), 2),
                'interes_certificados': round(float(d.get('interescertejec', 0) or 0), 2),
                'fuente': 'postgresql (ETL padrón)',
                'actualizado': str(d.get('fechaactualizacion') or '') if d.get('fechaactualizacion') else None,
            }
    except Exception as e:
        logger.warning(f'deuda: padrón PG no disponible ({e}) — usando MSSQL')

    tabla = tabla or obtener_tabla_dwh(conn)
    if not tabla:
        return None
    cursor = conn.cursor()
    try:
        cursor.execute(f"""
            SELECT TOP 1 TotalBoleta, TotalPlanPago, TotalCertEjec, TotalValores,
                   TotalGral, InteresCertEjec, TotalNominal, FechaActualizacion
            FROM [{tabla}] WITH (NOLOCK)
            WHERE Nomencla = ?
            ORDER BY FechaActualizacion DESC
        """, (codigo,))
        d = cursor.fetchone()
        if not d:
            return None
        boletas = float(d[0] or 0)
        planes = float(d[1] or 0)
        cert = float(d[2] or 0)
        valores = float(d[3] or 0)
        total_gral = float(d[4] or 0)
        interes_cert = float(d[5] or 0)
        return {
            'total': round(total_gral + interes_cert, 2),
            'boletas': round(boletas, 2),
            'planes_pago': round(planes, 2),
            'certificados': round(cert + interes_cert, 2),
            'valores': round(valores, 2),
            'nominal': round(float(d[6] or 0), 2),
            'interes_certificados': round(interes_cert, 2),
            'fuente': tabla,
            'actualizado': str(d[7] or '') if d[7] else None,
        }
    except Exception as e:
        logger.warning(f'deuda: padrón no disponible para {codigo}: {e}')
        return None
    finally:
        cursor.close()


def deuda_de_nomencla(conn, codigo, tipo=None, tabla=None, tipos_padron=None):
    """ORÁCULO: deuda total de una nomencla, coherente para toda la app.

    Devuelve:
        {'total', 'boletas', 'planes_pago', 'certificados', 'valores',
         'fuente', 'actualizado', ...}

    - Tipos con padrón (IM/CO/CM/PT): padrón DWH oficial.
    - Tipos internos (CG/DC/JF/PN/MA): cálculo interno por nomencla.
    - Si el padrón no tiene fila para un tipo con padrón, cae al cálculo
      interno para nunca mostrar 0 de más.
    """
    if _es_tipo_padron(tipo, conn, tipos_padron):
        reg = deuda_padron_nomencla(conn, codigo, tabla)
        if reg and (reg['total'] > 0 or reg['boletas'] > 0
                    or reg['certificados'] > 0 or reg['valores'] > 0
                    or reg['planes_pago'] > 0):
            return reg
    return deuda_interna_nomencla(conn, codigo)


# ── Agregado por tipo (panel ejecutivo) ────────────────────────

def deuda_interna_sin_padron(cur):
    """Deuda operativa agregada de los tipos que el padrón DWH no incluye
    (CG, DC, JF, PN, MA): boletas netas de pagos + planes con saldo +
    certificados. Devuelve {'total': float, 'por_tipo': dict}."""
    tipos_sql = ', '.join(f"'{t}'" for t in TIPOS_INTERNOS)
    cur.execute(f"""SELECT c.TIPOCONTRIBUYENTE,
                       SUM((CASE WHEN b.IMPORTE0>0 THEN b.IMPORTE0-ISNULL(b.DESCTO0,0) ELSE 0 END)
                         + (CASE WHEN ISNULL(b.IMPORTE1,0)>0 THEN b.IMPORTE1 ELSE 0 END)
                         + (CASE WHEN ISNULL(b.IMPORTE2,0)>0 THEN b.IMPORTE2+ISNULL(b.RECARGO2,0) ELSE 0 END)
                         + (CASE WHEN ISNULL(b.IMPORTE3,0)>0 THEN b.IMPORTE3+ISNULL(b.RECARGO3,0) ELSE 0 END))
                FROM contribu c WITH (NOLOCK)
                LEFT JOIN boletas b WITH (NOLOCK) ON b.NOMENCLA=c.NOMENCLA AND b.ANULA=0
                WHERE c.TIPOCONTRIBUYENTE IN ({tipos_sql})
                GROUP BY c.TIPOCONTRIBUYENTE""")
    bruto = {str(r[0]).strip(): float(r[1] or 0) for r in cur.fetchall()}
    cur.execute(f"""SELECT c.TIPOCONTRIBUYENTE, ISNULL(SUM(ci.total),0)
                    FROM contribu c WITH (NOLOCK)
                    LEFT JOIN cobros co2 WITH (NOLOCK) ON co2.NOMENCLA = c.NOMENCLA AND co2.ANULADO = 0
                    LEFT JOIN cobritem ci WITH (NOLOCK) ON ci.NROCOBRO = co2.NROCOBRO
                    WHERE c.TIPOCONTRIBUYENTE IN ({tipos_sql})
                    GROUP BY c.TIPOCONTRIBUYENTE""")
    pagos = {str(r[0]).strip(): float(r[1] or 0) for r in cur.fetchall()}
    cur.execute(f"""SELECT c.TIPOCONTRIBUYENTE,
                       ISNULL(SUM(CASE WHEN pp.TOTALDEUDA - pp.MONTOPAGADO > 0
                                       THEN pp.TOTALDEUDA - pp.MONTOPAGADO ELSE 0 END),0)
                    FROM contribu c WITH (NOLOCK)
                    LEFT JOIN planpago pp WITH (NOLOCK) ON pp.NOMENCLA = c.NOMENCLA
                      AND pp.ANULA = 0 AND pp.ESTADO IN (0,1,3)
                    WHERE c.TIPOCONTRIBUYENTE IN ({tipos_sql})
                    GROUP BY c.TIPOCONTRIBUYENTE""")
    planes = {str(r[0]).strip(): float(r[1] or 0) for r in cur.fetchall()}
    cur.execute(f"""SELECT c.TIPOCONTRIBUYENTE, ISNULL(SUM(ce.CAPITAL + ce.INTERESES),0)
                    FROM contribu c WITH (NOLOCK)
                    LEFT JOIN certejec ce WITH (NOLOCK) ON ce.NOMENCLA = c.NOMENCLA
                      AND ce.ANULA = 0 AND ce.ESTADO IN (1,2,3)
                    WHERE c.TIPOCONTRIBUYENTE IN ({tipos_sql})
                    GROUP BY c.TIPOCONTRIBUYENTE""")
    certs = {str(r[0]).strip(): float(r[1] or 0) for r in cur.fetchall()}
    por_tipo = {}
    for t in set(bruto) | set(planes) | set(certs):
        por_tipo[t] = round(max(0, bruto.get(t, 0) - pagos.get(t, 0))
                            + planes.get(t, 0) + certs.get(t, 0), 2)
    return {'total': round(sum(por_tipo.values()), 2), 'por_tipo': por_tipo}
