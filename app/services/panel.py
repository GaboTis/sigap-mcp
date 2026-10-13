"""Servicio del Panel Ejecutivo — KPIs municipales consolidados.

Reúne: recaudación, deuda del padrón DWH, gestión administrativa,
compras/egresos y stock. Todo desde SIGAP (solo lectura).
"""
from datetime import datetime

from app.db import get_conn
from app.services import contribuyentes, recaudacion


def kpis_ejecutivos():
    """KPIs consolidados para el intendente."""
    hoy = datetime.now()
    hoy_str = hoy.strftime('%Y%m%d')
    manana_str = (hoy.replace(hour=0, minute=0, second=0, microsecond=0)
                  + __import__('datetime').timedelta(days=1)).strftime('%Y%m%d')
    mes_str = hoy.strftime('%Y%m01')
    ano = hoy.year

    conn = get_conn()
    cur = conn.cursor()

    def _uno(sql):
        cur.execute(sql)
        return cur.fetchone()

    # ── Recaudación ──
    n_hoy, m_hoy = _uno(f"""SELECT COUNT(*), ISNULL(SUM(TOTALGRAL),0) FROM cobros WITH (NOLOCK)
        WHERE ANULADO=0 AND FECHA>=CAST('{hoy_str}' AS datetime) AND FECHA<CAST('{manana_str}' AS datetime)""")
    n_mes, m_mes = _uno(f"""SELECT COUNT(*), ISNULL(SUM(TOTALGRAL),0) FROM cobros WITH (NOLOCK)
        WHERE ANULADO=0 AND FECHA>=CAST('{mes_str}' AS datetime)""")
    n_ano, m_ano = _uno(f"""SELECT COUNT(*), ISNULL(SUM(TOTALGRAL),0) FROM cobros WITH (NOLOCK)
        WHERE ANULADO=0 AND FECHA>=CAST('{ano}0101' AS datetime)""")

    # ── Gestión ──
    (exp_tramite,) = _uno("""SELECT COUNT(*) FROM expediente WITH (NOLOCK)
        WHERE ANULADO=0 AND ESTADO IN ('E','I') AND FECHAINICIO<=GETDATE()""")
    (n_planes, saldo_planes) = _uno("""SELECT COUNT(*), ISNULL(SUM(TOTALDEUDA-MONTOPAGADO),0)
        FROM planpago WITH (NOLOCK) WHERE ANULA=0 AND MONTOPAGADO < TOTALDEUDA""")
    (contrib_activos,) = _uno("""SELECT COUNT(*) FROM contribu WITH (NOLOCK)
        WHERE FECHABAJA=CONVERT(datetime,'1900-01-01')""")

    # ── Compras / Egresos ──
    n_oc, m_oc = _uno(f"""SELECT COUNT(*), ISNULL(SUM(TOTALESTIMADO),0) FROM ordencpa WITH (NOLOCK)
        WHERE ANULADO=0 AND YEAR(FECHA)={ano}""")
    n_op_mes, m_op_mes = _uno(f"""SELECT COUNT(*), ISNULL(SUM(IMPORTE),0) FROM reciteso WITH (NOLOCK)
        WHERE ANULADO=0 AND FECHA>=CAST('{mes_str}' AS datetime)""")
    (prov_hab,) = _uno("SELECT COUNT(*) FROM proveedor WITH (NOLOCK) WHERE HABILITADO=1")

    # ── Stock ──
    (stock_ok,) = _uno("""SELECT COUNT(DISTINCT CODIGO) FROM stock WITH (NOLOCK) WHERE CANTIDAD>0""")
    (stock_bajo,) = _uno("""SELECT COUNT(DISTINCT CODIGO) FROM stock WITH (NOLOCK)
        WHERE CANTIDAD>0 AND CANTIDAD<=5""")
    conn.close()

    deuda = contribuyentes.resumen_deuda() or {}
    rec = recaudacion.resumen_recaudacion()

    return {
        'actualizado': hoy.strftime('%d/%m/%Y %H:%M'),
        'recaudacion': {
            'hoy': float(m_hoy or 0), 'hoy_recibos': int(n_hoy or 0),
            'mes': float(m_mes or 0), 'mes_recibos': int(n_mes or 0),
            'anio': float(m_ano or 0), 'anio_recibos': int(n_ano or 0),
            'variacion_interanual_pct': rec['anio']['variacion_pct'],
            'indice_cobranza_pct': rec['indice_cobranza_pct'],
        },
        'deuda_padron': deuda,
        'gestion': {
            'expedientes_en_tramite': int(exp_tramite or 0),
            'planes_vigentes': int(n_planes or 0),
            'planes_saldo': float(saldo_planes or 0),
            'contribuyentes_activos': int(contrib_activos or 0),
        },
        'compras': {
            'ordenes_compra_anio': int(n_oc or 0),
            'ordenes_compra_monto': float(m_oc or 0),
            'ordenes_pago_mes': int(n_op_mes or 0),
            'ordenes_pago_mes_monto': float(m_op_mes or 0),
            'proveedores_habilitados': int(prov_hab or 0),
        },
        'stock': {'articulos_con_stock': int(stock_ok or 0), 'stock_bajo': int(stock_bajo or 0)},
    }
