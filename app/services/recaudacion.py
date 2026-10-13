"""Servicio de recaudación.

Fuentes validadas:
- Recaudación = cobros.TOTALGRAL con ANULADO=0 (FPAGO no se usa, siempre 0).
- Emisión del año = boletas.IMPORTE1 con ANULA=0.
- Ejecución por partida = cobrpartid + EXISTS (la versión con LEFT JOIN
  cobritem duplicaba montos y tardaba ~50s).
"""
from datetime import datetime

from app.db import get_conn

_MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
          'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']


def _fecha(fmt):
    return datetime.now().strftime(fmt)


def resumen_recaudacion():
    """Recaudación hoy / mes / año con comparativa interanual."""
    hoy = datetime.now()
    hoy_str = hoy.strftime('%Y%m%d')
    mes_str = hoy.strftime('%Y%m01')
    ano = hoy.year

    conn = get_conn()
    cur = conn.cursor()

    def _suma(sql):
        cur.execute(sql)
        return cur.fetchone()

    n_hoy, m_hoy = _suma(f"""SELECT COUNT(*), ISNULL(SUM(TOTALGRAL),0) FROM cobros WITH (NOLOCK)
        WHERE ANULADO=0 AND FECHA>=CAST('{hoy_str}' AS datetime)""")
    n_mes, m_mes = _suma(f"""SELECT COUNT(*), ISNULL(SUM(TOTALGRAL),0) FROM cobros WITH (NOLOCK)
        WHERE ANULADO=0 AND FECHA>=CAST('{mes_str}' AS datetime)""")
    n_ano, m_ano = _suma(f"""SELECT COUNT(*), ISNULL(SUM(TOTALGRAL),0) FROM cobros WITH (NOLOCK)
        WHERE ANULADO=0 AND FECHA>=CAST('{ano}0101' AS datetime)""")

    # Mismo período del año anterior
    from datetime import timedelta
    inicio_prev = datetime(ano - 1, 1, 1).strftime('%Y%m%d')
    fin_prev = (hoy.replace(year=ano - 1, hour=0, minute=0, second=0, microsecond=0)
                + timedelta(days=1)).strftime('%Y%m%d')
    (m_prev,) = _suma(f"""SELECT ISNULL(SUM(TOTALGRAL),0) FROM cobros WITH (NOLOCK)
        WHERE ANULADO=0 AND FECHA>=CAST('{inicio_prev}' AS datetime)
          AND FECHA<CAST('{fin_prev}' AS datetime)""")

    (n_emi, m_emi) = _suma(f"""SELECT COUNT(*), ISNULL(SUM(IMPORTE1),0) FROM boletas WITH (NOLOCK)
        WHERE ANULA=0 AND ANO={ano}""")

    # Recaudación mensual últimos 3 años
    series = []
    for a in (ano - 2, ano - 1, ano):
        cur.execute(f"""SELECT MONTH(FECHA), SUM(TOTALGRAL) FROM cobros WITH (NOLOCK)
            WHERE ANULADO=0 AND YEAR(FECHA)={a} GROUP BY MONTH(FECHA)""")
        por_mes = {int(r[0]): float(r[1] or 0) for r in cur.fetchall()}
        series.append({'anio': a, 'valores': [por_mes.get(m, 0) for m in range(1, 13)]})
    conn.close()

    delta = ((float(m_ano or 0) - float(m_prev or 0)) / float(m_prev or 0) * 100) if m_prev else 0
    return {
        'hoy': {'monto': float(m_hoy or 0), 'recibos': int(n_hoy or 0)},
        'mes': {'mes': _MESES[hoy.month - 1], 'monto': float(m_mes or 0), 'recibos': int(n_mes or 0)},
        'anio': {'anio': ano, 'monto': float(m_ano or 0), 'recibos': int(n_ano or 0),
                 'mismo_periodo_anio_anterior': float(m_prev or 0),
                 'variacion_pct': round(delta, 1)},
        'emision_anio': {'monto': float(m_emi or 0), 'boletas': int(n_emi or 0)},
        'indice_cobranza_pct': round((float(m_ano or 0) / float(m_emi or 0) * 100) if m_emi else 0, 1),
        'mensual_3_anios': series,
    }


def ejecucion_presupuestaria(ejercicio=None, top=10):
    """Ejecución de ingresos por partida: presupuesto vs ejecutado."""
    ejercicio = int(ejercicio or datetime.now().year)
    hoy = datetime.now()
    fd_str = f'01/01/{ejercicio}'
    fh_str = hoy.strftime('%d/%m/%Y')

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""SELECT CUENTA, DESCRIPCION, IMPORTEINICIAL FROM partidas WITH (NOLOCK)
        WHERE ANO=? AND DH='I'""", (ejercicio,))
    partidas = {str(r[0]).strip(): (str(r[1]).strip(), float(r[2] or 0)) for r in cur.fetchall()}

    cur.execute("""WITH CobrosConTipo AS (
        SELECT c.NROCOBRO, c.NOMENCLA, c.FECHA, c.ANULADO,
            CASE WHEN EXISTS (SELECT 1 FROM cobritem ci WITH (NOLOCK) WHERE ci.NROCOBRO=c.NROCOBRO) THEN 'DIRECTO'
                 WHEN EXISTS (SELECT 1 FROM planpago pp WITH (NOLOCK) WHERE pp.NOMENCLA=c.NOMENCLA) THEN 'PLAN'
                 ELSE 'OTRO' END as TipoPago
        FROM cobros c WITH (NOLOCK)
        WHERE c.FECHA>=CONVERT(datetime,?,103) AND c.FECHA<=CONVERT(datetime,?,103)),
    IngresosPorPartida AS (
        SELECT cp.partida as PARTIDA, ct.TipoPago,
            SUM(CASE WHEN ISNULL(ct.ANULADO,0)=0 THEN ISNULL(cp.total,0) ELSE 0 END) as acumulado
        FROM cobrpartid cp WITH (NOLOCK) INNER JOIN CobrosConTipo ct ON cp.nrocobro=ct.NROCOBRO
        WHERE cp.ejercicio=? GROUP BY cp.partida, ct.TipoPago)
    SELECT PARTIDA, SUM(acumulado) as total,
        SUM(CASE WHEN TipoPago='DIRECTO' THEN acumulado ELSE 0 END) as directos,
        SUM(CASE WHEN TipoPago='PLAN' THEN acumulado ELSE 0 END) as planes
    FROM IngresosPorPartida GROUP BY PARTIDA""", (fd_str, fh_str, ejercicio))
    ejecutado = {}
    import re as _re
    for r in cur.fetchall():
        # Normalizar: quitar padding, espacios no separables (\xa0) y sufijo de año
        partida = _re.sub(r'\s+\d{4}$', '', str(r[0]).strip()).strip()
        partida = partida.replace('\xa0', ' ').strip()
        ej = float(r[1] or 0)
        directos = float(r[2] or 0)
        planes = float(r[3] or 0)
        if partida in ejecutado:
            # Misma partida puede venir con padding normal y con \xa0 → acumular
            ejecutado[partida]['ejecutado'] += ej
            ejecutado[partida]['directos'] += directos
            ejecutado[partida]['planes'] += planes
        else:
            ejecutado[partida] = {'ejecutado': ej, 'directos': directos, 'planes': planes}
    conn.close()

    filas = []
    for cuenta, (desc, presupuesto) in partidas.items():
        ej = ejecutado.get(cuenta, {}).get('ejecutado', 0)
        if presupuesto > 0 or ej > 0:
            filas.append({
                'partida': cuenta, 'descripcion': desc, 'presupuesto': round(presupuesto, 2),
                'ejecutado': round(ej, 2), 'pct_ejecucion': round(ej / presupuesto * 100, 1) if presupuesto else 0,
                'directos': round(ejecutado.get(cuenta, {}).get('directos', 0), 2),
                'planes': round(ejecutado.get(cuenta, {}).get('planes', 0), 2),
            })
    filas.sort(key=lambda f: f['presupuesto'], reverse=True)
    total_pres = sum(f['presupuesto'] for f in filas)
    total_ej = sum(f['ejecutado'] for f in filas)
    return {
        'ejercicio': ejercicio,
        'total': {'presupuesto': round(total_pres, 2), 'ejecutado': round(total_ej, 2),
                  'pct_ejecucion': round(total_ej / total_pres * 100, 1) if total_pres else 0},
        'partidas': filas[:top],
    }
