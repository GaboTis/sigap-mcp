"""Diccionario de datos de SIGAP — el "mapa semántico" del Oráculo de la DB.

Cada entrada dice QUÉ es la tabla, sus columnas clave y cómo filtrarla.
Fuente: relevamiento real del catálogo de SQL Server (597 tablas) + columnas
de las tablas core de deudas, cobros, pagos, contabilidad y expedientes.
"""
import logging
import re

from app.db import get_conn

logger = logging.getLogger('sigap.esquema')

# ═══════════════════════════════════════════════════════════════════════
# DICCIONARIO CURADO (tabla → descripción + claves + receta)
# ═══════════════════════════════════════════════════════════════════════
DICCIONARIO = {
    # ── DEUDAS ──
    'boletas': {
        'dominio': 'deudas',
        'descripcion': 'Boletas de tasas/impuestos emitidas (16,4 M). Cada boleta es una deuda puntual con '
                       'hasta 3 vencimientos embebidos (VTO1 base, VTO2/VTO3 con recargo). '
                       'UNICACUOTA=1 marca la cuota ANUAL (un solo vencimiento); TIPOBOLETA=P es la mensual.',
        'claves': 'NROBOLETA, NOMENCLA, TIPOBOLETA, ANO, MES, PERIODO, IMPORTE1/FECHAVTO1, IMPORTE2/RECARGO2/TASA2/FECHAVTO2, IMPORTE3/RECARGO3/TASA3/FECHAVTO3, UNICACUOTA, ANULA',
        'filtros': "ANULA=0 para vigentes; NOMENCLA='IM...'; UNICACUOTA=1 para anuales; "
                   'recargo vto = IMPORTE1*(TASA/100)*días desde VTO1 (TASA 0.150 = 0,15% diario)',
        'ejemplo': "SELECT TOP 20 NROBOLETA, NOMENCLA, TIPOBOLETA, ANO, MES, IMPORTE1, FECHAVTO1, IMPORTE2, FECHAVTO2 FROM boletas WHERE ANULA=0 AND NOMENCLA='IM344002000008' ORDER BY ANO DESC, MES DESC",
    },
    'boleitem': {
        'dominio': 'deudas',
        'descripcion': 'Ítems/conceptos de cada boleta (17 M): composición por tasa/concepto.',
        'claves': 'NROBOLETA, BOLETA, CODIGO, CONCEPTO, IMPORTE, ANO',
        'filtros': 'JOIN con boletas por NROBOLETA',
    },
    'certificados_ejecucion': {
        'dominio': 'deudas',
        'descripcion': 'Certificados de ejecución (juicios por deuda). Mirar también certejec/certejcomp en SIGAP.',
        'claves': 'NOMENCLA, NROCERTIF, FECHA, CAPITAL, INTERESES, TOTAL',
        'filtros': "NOMENCLA='IM...'",
    },
    'certejec': {
        'dominio': 'deudas',
        'descripcion': 'Certificados de ejecución en SIGAP (57 mil): deuda en juicio.',
        'claves': 'NOMENCLA, NROCERTIF, CAPITAL, INTERESES, FECHA, ESTADO',
        'filtros': "ESTADO vigente; NOMENCLA='IM...'",
    },
    'planpago': {
        'dominio': 'deudas',
        'descripcion': 'Planes de pago (44,9 mil): convenios de financiación de deuda.',
        'claves': 'NROPLAN, NOMENCLA, FECHA, CUOTAS, TOTALDEUDA, MONTOPAGADO, ESTADO, TASA',
        'filtros': "ESTADO='A' activo; MONTOPAGADO<TOTALDEUDA con saldo",
    },
    'plpgcomp': {
        'dominio': 'deudas',
        'descripcion': 'Comprobantes/boletas incluidos en cada plan de pago (1,6 M).',
        'claves': 'NROPLAN, BOLETA, IMPORTE, ANO',
        'filtros': 'JOIN planpago por NROPLAN',
    },
    'plpgcuot': {
        'dominio': 'deudas',
        'descripcion': 'Cuotas de los planes de pago (716 mil): vencimientos y pagos parciales.',
        'claves': 'NROPLAN, NROCUOTA, FECHAVTO, IMPORTE, MONTOPAGADO, ESTADO',
        'filtros': 'cuotas vencidas impagas: MONTOPAGADO<IMPORTE AND FECHAVTO<GETDATE()',
    },
    'intima': {
        'dominio': 'deudas',
        'descripcion': 'Intimaciones de pago enviadas (277 mil).',
        'claves': 'NOMENCLA, FECHA, TIPO, IMPORTE',
    },
    'libredeuda': {
        'dominio': 'deudas',
        'descripcion': 'Libres de deuda emitidos (48 mil).',
        'claves': 'NOMENCLA, FECHA, NRO, ESTADO',
    },
    'inticomp': {
        'dominio': 'deudas',
        'descripcion': 'Intereses por comprobante (12 M): interés acumulado por boleta.',
        'claves': 'BOLETA, FECHA, INTERES, ANO',
    },
    'contritem': {
        'dominio': 'deudas',
        'descripcion': 'Ítems de contribución/tasas por contribuyente (994 mil).',
        'claves': 'NOMENCLA, CODIGO, CONCEPTO, IMPORTE',
    },
    # ── COBROS (recaudación) ──
    'cobros': {
        'dominio': 'cobros',
        'descripcion': 'Cobros realizados (2,5 M). LA tabla de recaudación diaria.',
        'claves': 'NROCOBRO, FECHA, TOTALGRAL (total cobrado), TOTALNOMINAL, TOTALINTERES, FPAGO (medio de pago), COBRADOR, CAJERO, NOMENCLA, NRORECIBO, ANULADO, TIPOCOBRO, NROPARTE',
        'filtros': "ANULADO=0; FECHA>='2026-10-01' para el mes; COBRADOR=n para colector; FPAGO=medio",
        'ejemplo': "SELECT TOP 20 NROCOBRO, FECHA, NOMENCLA, TOTALGRAL, FPAGO, COBRADOR FROM cobros WHERE ANULADO=0 AND FECHA>=CONVERT(date,GETDATE()) ORDER BY NROCOBRO DESC",
    },
    'cobritem': {
        'dominio': 'cobros',
        'descripcion': 'Ítems de cada cobro (7,5 M): qué boletas se pagaron en cada cobro.',
        'claves': 'NROCOBRO, BOLETA, TOTAL, NOMINAL, INTERESES, TIPO',
        'filtros': 'JOIN cobros por NROCOBRO',
    },
    'recibo': {
        'dominio': 'cobros',
        'descripcion': 'Recibos oficiales de cobro (261 mil).',
        'claves': 'NUMERO, FECHA, IMPORTE, TOTAL, ESTADO, ANULADO',
        'filtros': 'ANULADO=0',
    },
    'cobrosweb': {
        'dominio': 'cobros',
        'descripcion': 'Cobros por la web/Mercado Pago (73,5 mil).',
        'claves': 'idcobro, idoperacion, merchant_order, producto, importe, fecha_operacion, codigocobrador',
        'filtros': "fecha_operacion>='2026-10-01'",
    },
    'cobrfpag': {
        'dominio': 'cobros',
        'descripcion': 'Medios de pago usados en cada cobro (2,5 M): tarjeta, cheque, efectivo, transferencia.',
        'claves': 'NROCOBRO, FPAGO, IMPORTE, FECHAEMIS, FECHAVTO, ENTIEMISOR, NROCTA, DEPOSITADO, CLAVEDEPO',
        'filtros': 'ANULADO=0; FPAGO=medio',
    },
    'cobrtotal': {
        'dominio': 'cobros',
        'descripcion': 'Totales de cobros (4,6 M) — detalle por cobro.',
        'claves': 'NROCOBRO, FECHA, TOTAL',
    },
    # ── PAGOS / TESORERÍA ──
    'ordenpago': {
        'dominio': 'pagos',
        'descripcion': 'Órdenes de pago a proveedores (42,5 mil): pagos emitidos por el municipio.',
        'claves': 'NUMERO, FECHA, PROVEEDOR, IMPORTE, TOTAL, FPAGO, ESTADO, ANULADO, TOTALFACTURAS',
        'filtros': "ANULADO=0; PROVEEDOR=cod; FECHA>='2026-01-01'",
        'ejemplo': "SELECT TOP 20 NUMERO, FECHA, PROVEEDOR, IMPORTE, TOTAL FROM ordenpago WHERE ANULADO=0 AND FECHA>=CONVERT(date,'2026-01-01') ORDER BY FECHA DESC",
    },
    'reciteso': {
        'dominio': 'pagos',
        'descripcion': 'Recibos de tesorería (273 mil): pago efectivo a proveedores con detalle de banco/cheque.',
        'claves': 'NUMERO, FECHA, ORDENPAGO, PROVEEDOR, IMPORTE, TOTAL, BANCO, NROCHEQUE, ANULADO',
        'filtros': 'ANULADO=0',
    },
    'cheques': {
        'dominio': 'pagos',
        'descripcion': 'Cheques emitidos (262 mil).',
        'claves': 'BANCO, CUENTA, NUMERO, FECHA, IMPORTE, EMITIDO, ANULADO, FECHADIFERIDO',
        'filtros': 'ANULADO=0; FECHADIFERIDO cheques diferidos',
    },
    'depositos': {
        'dominio': 'pagos',
        'descripcion': 'Depósitos bancarios (77 mil): plata que entró al banco.',
        'claves': 'NROBOLETA, FECHA, BANCO, CUENTA, IMPORTE, NROPARTE',
        'filtros': "FECHA>='2026-10-01'",
    },
    'anticipos': {
        'dominio': 'pagos',
        'descripcion': 'Anticipos de caja/viáticos (879).',
        'claves': 'NUMERO, FECHA, BENEFICIARIO, IMPORTE, ENTREGADO, ANULADO',
        'filtros': 'ANULADO=0',
    },
    'saldoscaja': {
        'dominio': 'pagos',
        'descripcion': 'Saldos de caja por día y medio de pago (38,7 mil).',
        'claves': 'FECHA, FPAGO, IMPORTE',
        'filtros': "FECHA>='2026-10-01'",
    },
    'cierre': {
        'dominio': 'pagos',
        'descripcion': 'Cierres de caja — ver cierrecajaitems y tablas cierre*.',
        'claves': 'FECHA, USUARIO, TOTAL',
    },
    # ── CONTABILIDAD / COMPRAS ──
    'ordencpa': {
        'dominio': 'contabilidad',
        'descripcion': 'Órdenes de compra (98 mil): pedidos de compra a proveedores.',
        'claves': 'NUMERO, FECHA, PROVEEDOR, TOTALESTIMADO, TIPOCONTRATACION, ESTADO, ANULADO, NROEXPEDIENTE, ANIOEXPEDIENTE, SOLICITANTE',
        'filtros': "ANULADO=0; ESTADO estado ('P' pendiente, 'A' autorizada); PROVEEDOR=cod",
        'ejemplo': "SELECT TOP 20 NUMERO, FECHA, PROVEEDOR, TOTALESTIMADO, ESTADO FROM ordencpa WHERE ANULADO=0 AND FECHA>=CONVERT(date,'2026-01-01') ORDER BY FECHA DESC",
    },
    'ocpaitem': {
        'dominio': 'contabilidad',
        'descripcion': 'Ítems de cada orden de compra (118 mil): artículo, cantidad y precio.',
        'claves': 'NUMERO, ARTICULO, CANTIDAD, VALORUNITARIO, VALORTOTAL',
        'filtros': 'JOIN ordencpa por NUMERO',
    },
    'proveedor': {
        'dominio': 'contabilidad',
        'descripcion': 'Padrón de proveedores (10,5 mil).',
        'claves': 'CODIGO, NOMBRE, CUIT, DOMICILIO, HABILITADO, tipoproveedor, ULTSALDO',
        'filtros': "NOMBRE LIKE '%...%'; HABILITADO=1",
    },
    'factprove': {
        'dominio': 'contabilidad',
        'descripcion': 'Facturas de proveedores (46,9 mil). Ver también factuprov.',
        'claves': 'NUMERO, NUMFACT, FECHA, IMPORTE, TOTAL, PROVEEDOR, ANULADO',
        'filtros': 'ANULADO=0; PROVEEDOR=cod',
    },
    'fpgespcomp': {
        'dominio': 'contabilidad',
        'descripcion': 'Comprobantes de gastos (2,3 M): detalle de cada gasto con período e importe.',
        'claves': 'NUMERO, BOLETA, PERIODO, IMPORTE, FECHAVTO, TOTALDEUDA, NROPLAN, NROCUOTA',
        'filtros': 'PERIODO por período; IMPORTE por monto',
    },
    'fpago': {
        'dominio': 'contabilidad',
        'descripcion': 'Formas de pago / tipos de compra (220): catálogo con rangos DESDE/HASTA y norma legal.',
        'claves': 'CODIGO, DESCRIPCION, DESDE, HASTA, NORMALEGAL',
        'filtros': 'catálogo, leer entero',
    },
    'partidas': {
        'dominio': 'contabilidad',
        'descripcion': 'Partidas presupuestarias (4,9 mil): crédito inicial y saldo actual por cuenta.',
        'claves': 'CUENTA, ANO, DESCRIPCION, IMPORTEINICIAL, SALDOACTUAL, PREVENTPTE, AFECTACPTE, DEFINITPTE, MANDPAGPTE',
        'filtros': "ANO=2026; CUENTA='...'",
        'ejemplo': "SELECT TOP 20 CUENTA, DESCRIPCION, IMPORTEINICIAL, SALDOACTUAL FROM partidas WHERE ANO=2026 ORDER BY CUENTA",
    },
    'parteegre': {
        'dominio': 'contabilidad',
        'descripcion': 'Partes de egresos (266 mil): cada pago imputado al presupuesto (gastos).',
        'claves': 'TIPO, ROTULO, CONCEPTO, NUMERO, IMPORTE, NROPARTE, NROCHEQUE',
        'filtros': "NROPARTE agrupa; CONCEPTO LIKE '%...%'",
    },
    'parteingre': {
        'dominio': 'contabilidad',
        'descripcion': 'Partes de ingresos (66 mil): cada ingreso imputado al presupuesto.',
        'claves': 'TIPO, ROTULO, CONCEPTO, NOMINAL, INTERESES, DESCTO, TOTAL, NROPARTE',
        'filtros': 'NROPARTE agrupa',
    },
    'asientos': {
        'dominio': 'contabilidad',
        'descripcion': 'Asientos contables (casi sin uso: contabilidad formal no cargada en SIGAP).',
        'claves': 'numero, fecha, tipocompte, totaldebe, totalhaber, descripcion, ejercicio',
        'filtros': 'ejercicio=2026',
    },
    'articulo': {
        'dominio': 'contabilidad',
        'descripcion': 'Catálogo de artículos/bienes (3,6 mil).',
        'claves': 'CODIGO, DESCRIPCION, UNIDAD, COSTO, rubro, vigente',
    },
    'imputdef': {
        'dominio': 'contabilidad',
        'descripcion': 'Imputaciones definitivas (242 mil): qué partida paga cada gasto.',
        'claves': 'NUMERO, PARTIDA, IMPORTE, FECHA',
    },
    'imputprev': {
        'dominio': 'contabilidad',
        'descripcion': 'Imputaciones preventivas (96,6 mil): reservas de presupuesto.',
        'claves': 'NUMERO, PARTIDA, IMPORTE, FECHA',
    },
    'imputacioncontratos': {
        'dominio': 'contabilidad',
        'descripcion': 'Imputaciones de contratos (357).',
        'claves': 'NUMERO, CONTRATO, PARTIDA, IMPORTE',
    },
    'asignaciones': {
        'dominio': 'contabilidad',
        'descripcion': 'Asignaciones presupuestarias (54,8 mil).',
        'claves': 'CUENTA, ANO, IMPORTE',
    },
    'auditoria': {
        'dominio': 'contabilidad',
        'descripcion': 'Auditoría de movimientos (813 mil): registro de operaciones del sistema.',
        'claves': 'FECHA, USUARIO, TABLA, OPERACION, DESCRIPCION',
    },
    # ── EXPEDIENTES ──
    'expediente': {
        'dominio': 'expedientes',
        'descripcion': 'Expedientes municipales (419 mil). Identificador: NUMERO-LETRA/AÑO.',
        'claves': 'NUMERO, LETRA, ANO, FECHAINICIO, ESTADO (E/I en curso, P pagado, C cerrado, A archivo), TIPOEXPEDIENTE, TEMA, MOTIVO, INICIADOR, SECTACTUAL, ANULADO',
        'filtros': "ANULADO=0; ESTADO IN ('E','I') en curso; MOTIVO LIKE '%CONTRAT%' contratos",
        'ejemplo': "SELECT TOP 20 NUMERO, LETRA, ANO, FECHAINICIO, ESTADO, MOTIVO FROM expediente WHERE ANULADO=0 AND ESTADO IN ('E','I') AND MOTIVO LIKE '%CONTRAT%' ORDER BY FECHAINICIO",
    },
    'expemovi': {
        'dominio': 'expedientes',
        'descripcion': 'Movimientos entre sectores de cada expediente (1,7 M): el recorrido.',
        'claves': 'NUMERO, ANO, FECHAHORA, SECTORACTUAL, ESTADOACTUAL, SECTORPROVENIENTE, OBSERVACIONES, USUARIO',
        'filtros': 'NUMERO+ANO del expediente',
    },
    'estaexpe': {
        'dominio': 'expedientes',
        'descripcion': 'Catálogo de estados de expediente (E/I en curso, P pagado, C cerrado, A archivo).',
        'claves': 'CODIGO, DESCRIPCION',
    },
    'tipoexpe': {
        'dominio': 'expedientes',
        'descripcion': 'Catálogo de tipos de expediente (SO solicitud, NO nota, AN antecedente, OF oficio…).',
        'claves': 'CODIGO, DESCRIPCION',
    },
    'sectmuni': {
        'dominio': 'expedientes',
        'descripcion': 'Catálogo de sectores municipales (228): mesa de entrada, tesorería, obras…',
        'claves': 'CODIGO, DESCRIPCION',
    },
    # ── PADRÓN ──
    'contribu': {
        'dominio': 'padron',
        'descripcion': 'Padrón de contribuyentes (96 mil): persona/parcela, deuda se obtiene por DWH/oráculo.',
        'claves': 'NOMENCLA (IM/CO/CM/CG/MA/PT/JF/DC + dígitos), RAZONSOCI, DNI, DNIOCUIT, CUIT, CALLEFISCAL, NUMEROFISCAL, SECCION, PARCELA, TIPOCONTRIBUYENTE',
        'filtros': "NOMENCLA='IM...'; DNI=...; RAZONSOCI LIKE '%...%'",
    },
    'datospers': {
        'dominio': 'padron',
        'descripcion': 'Datos personales adicionales (69 mil): teléfono, mail, domicilio.',
        'claves': 'NOMENCLA, TELEFONO, EMAIL, CELULAR, DOMICILIO',
    },
    'persona': {
        'dominio': 'padron',
        'descripcion': 'Personas físicas (29,9 mil).',
        'claves': 'CODIGO, NOMBRE, DNI',
    },
    'personajuridica': {
        'dominio': 'padron',
        'descripcion': 'Personas jurídicas (39,2 mil).',
        'claves': 'CODIGO, NOMBRE, CUIT',
    },
    'activcomer': {
        'dominio': 'padron',
        'descripcion': 'Actividades comerciales registradas (1,1 mil).',
        'claves': 'NOMENCLA, ACTIVIDAD, FECHA',
    },
}

# Catálogo rápido para búsqueda semántica (sinónimos → dominios)
DOMINIOS_SINONIMOS = {
    'deudas': ('deuda', 'deudas', 'boleta', 'plan de pago', 'certificado', 'intimación',
               'moroso', 'deudor', 'libre deuda', 'interés', 'juicio'),
    'cobros': ('cobro', 'cobros', 'recaudación', 'recaudo', 'colector', 'caja', 'recibo de cobro'),
    'pagos': ('pago', 'pagos', 'orden de pago', 'cheque', 'depósito', 'tesorería', 'anticipo',
              'saldo de caja', 'proveedor pago'),
    'contabilidad': ('contabilidad', 'compra', 'compras', 'gasto', 'gastos', 'presupuesto',
                     'partida', 'egreso', 'ingreso', 'factura', 'orden de compra', 'artículo',
                     'imputación', 'ejecución presupuestaria', 'compromiso'),
    'expedientes': ('expediente', 'expedientes', 'trámite', 'movimiento de expediente', 'sector'),
    'padron': ('padrón', 'contribuyente', 'titular', 'domicilio', 'dni', 'cuit'),
}


def _buscar_dominio(q):
    ql = (q or '').lower()
    for dom, sinonimos in DOMINIOS_SINONIMOS.items():
        if any(s in ql for s in sinonimos):
            return dom
    return None


def buscar_esquema(q: str = '') -> dict:
    """Busca tablas del diccionario por nombre, dominio o sinónimos."""
    q = (q or '').strip()
    ql = q.lower()
    dominio = _buscar_dominio(q)
    resultados = []
    for nombre, info in DICCIONARIO.items():
        puntaje = 0
        if ql and ql in nombre.lower():
            puntaje += 100
        elif dominio and info['dominio'] == dominio:
            puntaje += 60
        elif ql and any(p in info['descripcion'].lower() or p in nombre.lower()
                        for p in ql.split() if len(p) > 2):
            puntaje += 30
        if puntaje:
            resultados.append({
                'tabla': nombre, 'dominio': info['dominio'],
                'descripcion': info['descripcion'],
                'claves': info['claves'], 'puntaje': puntaje,
            })
    resultados.sort(key=lambda r: -r['puntaje'])
    top = resultados[:12]
    return {
        'total': len(top),
        'dominio_detectado': dominio,
        'tablas': [{k: v for k, v in r.items() if k != 'puntaje'} for r in top],
    }


def esquema_tabla(tabla: str) -> dict:
    """Diccionario + columnas reales + muestra de una tabla."""
    tabla = (tabla or '').strip()
    if not re.match(r'^[A-Za-z0-9_]+$', tabla):
        return {'error': 'Nombre de tabla inválido.'}
    info = DICCIONARIO.get(tabla.lower()) or DICCIONARIO.get(tabla)
    resp = {'tabla': tabla, 'diccionario': info}
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT COLUMN_NAME, DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION
        """, (tabla,))
        columnas = [{'nombre': r[0], 'tipo': r[1]} for r in cur.fetchall()]
        resp['columnas'] = columnas
        if not columnas:
            resp['error'] = f'La tabla "{tabla}" no existe en SIGAP.'
            return resp
        try:
            cur.execute(f'SELECT TOP 2 * FROM [{tabla}] WITH (NOLOCK)')
            cols = [d[0] for d in cur.description]
            muestra = []
            for fila in cur.fetchall():
                muestra.append({c: (str(v)[:40] if v is not None else None)
                                for c, v in zip(cols, fila)})
            resp['muestra'] = muestra
        except Exception as e:
            resp['muestra'] = []
            resp['muestra_error'] = str(e)[:150]
        return resp
    finally:
        conn.close()
