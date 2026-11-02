"""Servicio de expedientes municipales.

Queries validadas contra SIGAP real (2026-10-13):
- identificación = NUMERO + LETRA + ANO (ej. 3540-S-2026)
- "en trámite" = ESTADO IN ('E','I') (EN CURSO según estaexpe)
- FECHAINICIO con valores corruptos a futuro → siempre filtrar <= GETDATE()
- expemovi.SECTORPROVENIENTE reconstruye el recorrido entre sectores
"""
import re

from app.db import get_conn


def _parsear_busqueda(q):
    """Devuelve (numero, ano, letra) desde texto libre."""
    numero = ano = letra = None
    texto = (q or '').strip()
    m_ano = re.search(r'\b(20\d{2})\b', texto)
    if m_ano:
        ano = int(m_ano.group(1))
        texto = texto[:m_ano.start()] + texto[m_ano.end():]
    m_letra = re.search(r'(?<![A-Za-z])([A-Za-z])(?![A-Za-z])', texto)
    if m_letra:
        letra = m_letra.group(1).upper()
        texto = texto[:m_letra.start()] + texto[m_letra.end():]
    m_num = re.search(r'\b(\d{1,6})\b', texto)
    if m_num:
        numero = int(m_num.group(1))
    return numero, ano, letra


def buscar_expedientes(q, limit=10):
    """Busca expedientes por número/año/letra. Acepta '3540', '3540/2026', '3540-S-2026'."""
    numero, ano, letra = _parsear_busqueda(q)
    if numero is None:
        return {'total': 0, 'resultados': [], 'parseo': {'numero': None, 'ano': ano, 'letra': letra}}

    where = ['e.NUMERO=?', 'e.ANULADO=0']
    params = [numero]
    if ano:
        where.append('e.ANO=?')
        params.append(ano)
    if letra:
        where.append('e.LETRA=?')
        params.append(letra)
    limit = max(1, min(int(limit or 10), 50))

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT TOP {limit} e.NUMERO, e.LETRA, e.ANO, e.FECHAINICIO, e.ESTADO,
               e.SECTACTUAL, e.MOTIVO, e.TIPOEXPEDIENTE, e.CONTABILIZADO, e.FOLIO,
               ISNULL(ee.DESCRIPCION,'') as estado_desc,
               ISNULL(te.DESCRIPCION,'') as tipo_desc,
               ISNULL(sm.DESCRIPCION,'') as sector_desc,
               COUNT(*) OVER() as total
        FROM expediente e WITH (NOLOCK)
        LEFT JOIN estaexpe ee WITH (NOLOCK) ON ee.CODIGO=e.ESTADO
        LEFT JOIN tipoexpe te WITH (NOLOCK) ON te.CODIGO=e.TIPOEXPEDIENTE
        LEFT JOIN sectmuni sm WITH (NOLOCK) ON sm.CODIGO=e.SECTACTUAL
        WHERE {' AND '.join(where)}
        ORDER BY e.ANO DESC, e.FECHAINICIO DESC""", params)
    raw = cur.fetchall()
    conn.close()

    total = int(raw[0][13]) if raw else 0
    resultados = [{
        'numero': int(r[0]), 'letra': str(r[1] or ''), 'ano': int(r[2]),
        'fecha_inicio': r[3].strftime('%d/%m/%Y'),
        'estado': str(r[4] or ''), 'estado_desc': str(r[10] or ''),
        'sector_actual': str(r[12] or ''), 'motivo': str(r[6] or ''),
        'tipo': str(r[11] or ''), 'contabilizado': bool(r[8]), 'folio': int(r[9] or 0),
    } for r in raw]
    return {'total': total, 'resultados': resultados,
            'parseo': {'numero': numero, 'ano': ano, 'letra': letra}}


def detalle_expediente(numero, ano=None, letra=None):
    """Detalle completo: datos, recorrido entre sectores e imágenes."""
    numero = int(numero)
    where = ['e.NUMERO=?', 'e.ANULADO=0']
    params = [numero]
    if ano:
        where.append('e.ANO=?')
        params.append(int(ano))
    if letra:
        where.append('e.LETRA=?')
        params.append(str(letra).upper())

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT e.NUMERO, e.LETRA, e.ANO, e.FECHAINICIO, e.FECHACARGA, e.ESTADO,
               e.TIPOEXPEDIENTE, e.TEMA, e.MOTIVO, e.INICIADOR, e.DESTINO, e.FOLIO,
               e.CONTABILIZADO, e.USUARIO, e.SECTORINICIA, e.SECTORDESTINO, e.SECTACTUAL,
               ISNULL(ee.DESCRIPCION,'') as estado_desc,
               ISNULL(te.DESCRIPCION,'') as tipo_desc,
               ISNULL(tx.DESCRIPCION,'') as tema_desc,
               ISNULL(s_ini.DESCRIPCION,'') as sector_inicia_desc,
               ISNULL(s_des.DESCRIPCION,'') as sector_destino_desc,
               ISNULL(s_act.DESCRIPCION,'') as sector_actual_desc,
               ISNULL(s_ini.RESPONSABLE,'') as resp_inicia,
               ISNULL(s_act.RESPONSABLE,'') as resp_actual,
               DATEDIFF(DAY, e.FECHAINICIO,
                   CASE WHEN e.ESTADO IN ('E','I') THEN GETDATE()
                        ELSE COALESCE((SELECT MAX(m.FECHAHORA) FROM expemovi m WITH (NOLOCK)
                                       WHERE m.NUMERO=e.NUMERO AND m.ANO=e.ANO), e.FECHAINICIO)
                   END) as dias_tramite
        FROM expediente e WITH (NOLOCK)
        LEFT JOIN estaexpe ee WITH (NOLOCK) ON ee.CODIGO=e.ESTADO
        LEFT JOIN tipoexpe te WITH (NOLOCK) ON te.CODIGO=e.TIPOEXPEDIENTE
        LEFT JOIN temaexpe tx WITH (NOLOCK) ON tx.CODIGO=e.TEMA
        LEFT JOIN sectmuni s_ini WITH (NOLOCK) ON s_ini.CODIGO=e.SECTORINICIA
        LEFT JOIN sectmuni s_des WITH (NOLOCK) ON s_des.CODIGO=e.SECTORDESTINO
        LEFT JOIN sectmuni s_act WITH (NOLOCK) ON s_act.CODIGO=e.SECTACTUAL
        WHERE {' AND '.join(where)}
        ORDER BY e.ANO DESC, e.FECHAINICIO DESC""", params)
    rows = cur.fetchall()
    if not rows:
        conn.close()
        return None
    r = rows[0]

    expediente = {
        'numero': int(r[0]), 'letra': str(r[1] or ''), 'ano': int(r[2]),
        'fecha_inicio': r[3].strftime('%d/%m/%Y'),
        'fecha_carga': r[4].strftime('%d/%m/%Y %H:%M'),
        'estado': str(r[5] or ''), 'estado_desc': str(r[17] or ''),
        'tipo': str(r[6] or ''), 'tipo_desc': str(r[18] or ''),
        'tema': str(r[7] or ''), 'tema_desc': str(r[19] or ''),
        'motivo': str(r[8] or ''), 'iniciador': str(r[9] or ''),
        'destino': str(r[10] or ''), 'folio': int(r[11] or 0),
        'contabilizado': bool(r[12]), 'usuario': str(r[13] or ''),
        'sector_inicia': str(r[14] or ''), 'sector_inicia_desc': str(r[20] or ''),
        'sector_destino': str(r[15] or ''), 'sector_destino_desc': str(r[21] or ''),
        'sector_actual': str(r[16] or ''), 'sector_actual_desc': str(r[22] or ''),
        'resp_inicia': str(r[23] or ''), 'resp_actual': str(r[24] or ''),
        'dias_tramite': int(r[25] or 0),
    }

    cur.execute("""
        SELECT m.FECHAHORA, m.SECTORACTUAL, ISNULL(sm.DESCRIPCION,'') as sector_desc,
               m.SECTORPROVENIENTE, ISNULL(sp.DESCRIPCION,'') as prov_desc,
               m.ESTADOACTUAL, ISNULL(ee.DESCRIPCION,'') as estado_desc,
               m.FOJAS, m.OBSERVACIONES, m.USUARIO, m.FECHARECEPCION
        FROM expemovi m WITH (NOLOCK)
        LEFT JOIN sectmuni sm WITH (NOLOCK) ON sm.CODIGO=m.SECTORACTUAL
        LEFT JOIN sectmuni sp WITH (NOLOCK) ON sp.CODIGO=m.SECTORPROVENIENTE
        LEFT JOIN estaexpe ee WITH (NOLOCK) ON ee.CODIGO=m.ESTADOACTUAL
        WHERE m.NUMERO=? AND m.ANO=?
        ORDER BY m.FECHAHORA""", (numero, expediente['ano']))
    movimientos = [{
        'fecha_hora': m[0].strftime('%d/%m/%Y %H:%M'),
        'sector': str(m[1] or ''), 'sector_desc': str(m[2] or ''),
        'proveniente': str(m[3] or ''), 'proveniente_desc': str(m[4] or ''),
        'estado': str(m[5] or ''), 'estado_desc': str(m[6] or ''),
        'fojas': int(m[7] or 0), 'observaciones': str(m[8] or ''),
        'usuario': str(m[9] or ''),
        'fecha_recepcion': m[10].strftime('%d/%m/%Y %H:%M') if m[10] and m[10].year > 1900 else None,
    } for m in cur.fetchall()]
    conn.close()

    return {'expediente': expediente, 'movimientos': movimientos}


def listar_expedientes(tema=None, estado='en_curso', limite=50):
    """Listado filtrable de expedientes.

    - tema: texto libre buscado en MOTIVO (ej. 'contrat' → expedientes de
      contrataciones; también puede ir en TEMA como LIKE).
    - estado: 'en_curso' (default, ESTADO IN ('E','I')), 'todos', 'pagado',
      'cerrado', 'archivo'.
    - Orden: por ANTIGÜEDAD (FECHAINICIO ascendente); las fechas corruptas
      (1900) van al final.
    """
    tema = str(tema or '').strip()
    estado = str(estado or 'en_curso').strip().lower()
    limite = max(1, min(int(limite or 50), 500))

    where = ['e.ANULADO=0']
    params = []
    if tema:
        like = f'%{tema.upper()}%'
        where.append("(e.MOTIVO LIKE ? OR e.TEMA LIKE ?)")
        params += [like, like]
    estados = {
        'en_curso': "('E','I')",
        'todos': None,
        'pagado': "('P')",
        'cerrado': "('C')",
        'archivo': "('A')",
    }
    if estado in estados and estados[estado]:
        where.append(f'e.ESTADO IN {estados[estado]}')

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT TOP {limite} e.NUMERO, e.LETRA, e.ANO, e.FECHAINICIO, e.ESTADO,
               e.SECTACTUAL, e.MOTIVO, e.TIPOEXPEDIENTE, e.INICIADOR,
               ISNULL(ee.DESCRIPCION,'') as estado_desc,
               ISNULL(te.DESCRIPCION,'') as tipo_desc,
               ISNULL(sm.DESCRIPCION,'') as sector_desc,
               COUNT(*) OVER() as total
        FROM expediente e WITH (NOLOCK)
        LEFT JOIN estaexpe ee WITH (NOLOCK) ON ee.CODIGO=e.ESTADO
        LEFT JOIN tipoexpe te WITH (NOLOCK) ON te.CODIGO=e.TIPOEXPEDIENTE
        LEFT JOIN sectmuni sm WITH (NOLOCK) ON sm.CODIGO=e.SECTACTUAL
        WHERE {' AND '.join(where)}
        ORDER BY CASE WHEN e.FECHAINICIO <= '1901-01-01' THEN 1 ELSE 0 END,
                 e.FECHAINICIO ASC, e.ANO ASC""", params)
    raw = cur.fetchall()
    conn.close()

    total = int(raw[0][12]) if raw else 0
    resultados = [{
        'expediente': f"{int(r[0])}{'-' + str(r[1]) if r[1] else ''}/{int(r[2])}",
        'numero': int(r[0]), 'letra': str(r[1] or ''), 'ano': int(r[2]),
        'fecha_inicio': r[3].strftime('%d/%m/%Y') if r[3] and r[3].year > 1900 else None,
        'estado': str(r[4] or ''), 'estado_desc': str(r[9] or ''),
        'sector_actual': str(r[10] or ''), 'motivo': str(r[6] or ''),
        'tipo': str(r[11] or ''), 'iniciador': str(r[8] or ''),
    } for r in raw]
    return {'total': total, 'limite': limite, 'resultados': resultados,
            'filtros': {'tema': tema or None, 'estado': estado}}


def analitica_expedientes():
    """KPIs de gestión: cantidades, tiempos y carga por sector (para mejora de procesos)."""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""SELECT COUNT(*) FROM expediente WITH (NOLOCK)
        WHERE ANULADO=0 AND ESTADO IN ('E','I') AND FECHAINICIO<=GETDATE()""")
    en_tramite = int(cur.fetchone()[0] or 0)

    cur.execute("""SELECT AVG(CAST(d AS float)) FROM (
        SELECT DATEDIFF(DAY, FECHAINICIO, GETDATE()) d FROM expediente WITH (NOLOCK)
        WHERE ANULADO=0 AND ESTADO IN ('E','I') AND FECHAINICIO<=GETDATE()) x""")
    prom_tramite = float(cur.fetchone()[0] or 0)

    # Mediana sin PERCENTILE_CONT (BD en modo compat < 110)
    cur.execute("""SELECT AVG(CAST(d AS float)) FROM (
        SELECT TOP 2 d FROM (
            SELECT d, ROW_NUMBER() OVER (ORDER BY d) rn, COUNT(*) OVER () c
            FROM (SELECT DATEDIFF(DAY, FECHAINICIO, GETDATE()) d FROM expediente WITH (NOLOCK)
                  WHERE ANULADO=0 AND ESTADO IN ('E','I') AND FECHAINICIO<=GETDATE()) x
        ) y WHERE rn IN ((c+1)/2, (c+2)/2)
    ) z""")
    mediana_tramite = float(cur.fetchone()[0] or 0)

    cur.execute("""SELECT
        SUM(CASE WHEN d<7 THEN 1 ELSE 0 END), SUM(CASE WHEN d BETWEEN 7 AND 30 THEN 1 ELSE 0 END),
        SUM(CASE WHEN d BETWEEN 31 AND 90 THEN 1 ELSE 0 END), SUM(CASE WHEN d BETWEEN 91 AND 180 THEN 1 ELSE 0 END),
        SUM(CASE WHEN d>180 THEN 1 ELSE 0 END)
        FROM (SELECT DATEDIFF(DAY, FECHAINICIO, GETDATE()) d FROM expediente WITH (NOLOCK)
              WHERE ANULADO=0 AND ESTADO IN ('E','I') AND FECHAINICIO<=GETDATE()) x""")
    buckets = [int(v or 0) for v in cur.fetchone()]
    mas_180 = buckets[4]

    # Resolución real: finalizados (inicio → último movimiento)
    cur.execute("""SELECT COUNT(*), AVG(CAST(x.dias AS float)) FROM (
        SELECT e.NUMERO, e.ANO,
               DATEDIFF(DAY, e.FECHAINICIO, COALESCE(MAX(m.FECHAHORA), e.FECHAINICIO)) dias
        FROM expediente e WITH (NOLOCK)
        LEFT JOIN expemovi m WITH (NOLOCK) ON m.NUMERO=e.NUMERO AND m.ANO=e.ANO
        WHERE e.ANULADO=0 AND e.ESTADO IN ('C','P','A') AND e.FECHAINICIO<=GETDATE()
        GROUP BY e.NUMERO, e.ANO, e.FECHAINICIO
    ) x""")
    n_fin, prom_resolucion = cur.fetchone()

    # Resolución por tipo (finalizados)
    cur.execute("""SELECT TOP 10 ISNULL(te.DESCRIPCION,'SIN TIPO'), COUNT(*), AVG(CAST(x.dias AS float))
        FROM (
            SELECT e.NUMERO, e.ANO, e.TIPOEXPEDIENTE,
                   DATEDIFF(DAY, e.FECHAINICIO, COALESCE(MAX(m.FECHAHORA), e.FECHAINICIO)) dias
            FROM expediente e WITH (NOLOCK)
            LEFT JOIN expemovi m WITH (NOLOCK) ON m.NUMERO=e.NUMERO AND m.ANO=e.ANO
            WHERE e.ANULADO=0 AND e.ESTADO IN ('C','P','A') AND e.FECHAINICIO<=GETDATE()
            GROUP BY e.NUMERO, e.ANO, e.TIPOEXPEDIENTE, e.FECHAINICIO
        ) x LEFT JOIN tipoexpe te WITH (NOLOCK) ON te.CODIGO=x.TIPOEXPEDIENTE
        GROUP BY te.DESCRIPCION ORDER BY COUNT(*) DESC""")
    tiempos_tipo = [{'tipo': str(r[0]), 'cantidad': int(r[1]), 'dias_promedio': round(float(r[2] or 0), 1)}
                    for r in cur.fetchall()]

    # Carga por sector actual (cuellos de botella)
    cur.execute("""SELECT TOP 10 ISNULL(sm.DESCRIPCION,'SIN SECTOR'), COUNT(*), AVG(CAST(x.edad AS float))
        FROM (
            SELECT e.SECTACTUAL,
                   DATEDIFF(DAY, COALESCE(MAX(m.FECHAHORA), e.FECHAINICIO), GETDATE()) edad
            FROM expediente e WITH (NOLOCK)
            LEFT JOIN expemovi m WITH (NOLOCK) ON m.NUMERO=e.NUMERO AND m.ANO=e.ANO
            WHERE e.ANULADO=0 AND e.ESTADO IN ('E','I') AND e.FECHAINICIO<=GETDATE()
            GROUP BY e.NUMERO, e.ANO, e.SECTACTUAL, e.FECHAINICIO
        ) x LEFT JOIN sectmuni sm WITH (NOLOCK) ON sm.CODIGO=x.SECTACTUAL
        GROUP BY sm.DESCRIPCION ORDER BY COUNT(*) DESC""")
    carga_sector = [{'sector': str(r[0]), 'en_tramite': int(r[1]), 'edad_promedio_dias': round(float(r[2] or 0), 1)}
                    for r in cur.fetchall()]

    # Top demorados (a destrabar)
    cur.execute("""SELECT TOP 10 e.NUMERO, e.LETRA, e.ANO, ISNULL(te.DESCRIPCION,'—'),
        ISNULL(sm.DESCRIPCION,'—'), DATEDIFF(DAY, e.FECHAINICIO, GETDATE()) dias, e.MOTIVO
        FROM expediente e WITH (NOLOCK)
        LEFT JOIN tipoexpe te WITH (NOLOCK) ON te.CODIGO=e.TIPOEXPEDIENTE
        LEFT JOIN sectmuni sm WITH (NOLOCK) ON sm.CODIGO=e.SECTACTUAL
        WHERE e.ANULADO=0 AND e.ESTADO IN ('E','I') AND e.FECHAINICIO<=GETDATE()
        ORDER BY dias DESC""")
    demorados = [{'expediente': f"{int(r[0])}{'-' + str(r[1]) if r[1] else ''}/{int(r[2])}",
                  'tipo': str(r[3]), 'sector': str(r[4]), 'dias': int(r[5]), 'motivo': str(r[6] or '')}
                 for r in cur.fetchall()]
    conn.close()

    return {
        'en_tramite': en_tramite,
        'promedio_dias_en_tramite': round(prom_tramite, 1),
        'mediana_dias_en_tramite': round(mediana_tramite, 1),
        'antiguedad': {'menos_7': buckets[0], '7_a_30': buckets[1], '31_a_90': buckets[2],
                       '91_a_180': buckets[3], 'mas_180': buckets[4]},
        'pct_mas_180': round(mas_180 / en_tramite * 100, 1) if en_tramite else 0,
        'finalizados_historicos': int(n_fin or 0),
        'resolucion_promedio_dias': round(float(prom_resolucion or 0), 1),
        'resolucion_por_tipo': tiempos_tipo,
        'carga_por_sector': carga_sector,
        'mas_demorados': demorados,
        'nota': ('Los tiempos "en trámite" incluyen expedientes históricos que SIGAP nunca '
                 'cerró (desde 2004). Para medir atención real usar resolucion_por_tipo.'),
    }
