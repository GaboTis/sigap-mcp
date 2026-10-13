"""REST API — misma capa de servicios que el MCP, para web/dashboards/bots.

Seguridad: cada ruta exige token con el scope correspondiente (ver app/auth.py).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import requiere_scope
from app.services import consultas, contribuyentes, expedientes, panel, recaudacion

router = APIRouter()


@router.get('/api/health')
def health():
    return {'status': 'ok', 'servicio': 'sigap-mcp', 'modo': 'solo lectura'}


@router.get('/api/expedientes/buscar', dependencies=[Depends(requiere_scope('expedientes.read'))])
def api_buscar_expedientes(q: str, limit: int = Query(10, ge=1, le=50)):
    return expedientes.buscar_expedientes(q, limit)


@router.get('/api/expedientes/detalle', dependencies=[Depends(requiere_scope('expedientes.read'))])
def api_detalle_expediente(numero: int, ano: int = None, letra: str = None):
    det = expedientes.detalle_expediente(numero, ano, letra)
    if det is None:
        raise HTTPException(status_code=404, detail='Expediente no encontrado')
    return det


@router.get('/api/expedientes/analitica', dependencies=[Depends(requiere_scope('expedientes.analitica'))])
def api_analitica_expedientes():
    return expedientes.analitica_expedientes()


@router.get('/api/contribuyentes/por-dni', dependencies=[Depends(requiere_scope('contribuyentes.identidad'))])
def api_por_dni(dni: int):
    """Búsqueda por DNI — SOLO para verificación de identidad (agente)."""
    return contribuyentes.buscar_por_dni(dni)


@router.post('/api/contribuyentes/verificar', dependencies=[Depends(requiere_scope('contribuyentes.identidad'))])
def api_verificar_identidad(body: dict):
    """Verificación determinística: compara la respuesta del usuario con el padrón."""
    dni = int(body.get('dni') or 0)
    nomenclatura = str(body.get('nomenclatura') or '').strip()
    respuesta = str(body.get('respuesta') or '').strip()
    if dni <= 0 or not nomenclatura or not respuesta:
        raise HTTPException(status_code=400, detail='dni, nomenclatura y respuesta son requeridos')
    return contribuyentes.verificar_identidad(dni, nomenclatura, respuesta)


@router.get('/api/contribuyentes/deuda', dependencies=[Depends(requiere_scope('contribuyentes.deuda'))])
def api_deuda_contribuyente(codigo: str):
    d = contribuyentes.deuda_contribuyente(codigo)
    if d is None:
        raise HTTPException(status_code=404, detail='Contribuyente no encontrado en el padrón')
    return d


@router.get('/api/contribuyentes/buscar', dependencies=[Depends(requiere_scope('contribuyentes.buscar'))])
def api_buscar_contribuyentes(q: str, limit: int = Query(10, ge=1, le=50)):
    return contribuyentes.buscar_contribuyentes(q, limit)


@router.get('/api/recaudacion', dependencies=[Depends(requiere_scope('recaudacion'))])
def api_recaudacion():
    return recaudacion.resumen_recaudacion()


@router.get('/api/recaudacion/ejecucion', dependencies=[Depends(requiere_scope('recaudacion'))])
def api_ejecucion(ejercicio: int = None, top: int = Query(10, ge=1, le=50)):
    return recaudacion.ejecucion_presupuestaria(ejercicio, top)


@router.get('/api/panel/kpis', dependencies=[Depends(requiere_scope('kpis'))])
def api_kpis_ejecutivos():
    return panel.kpis_ejecutivos()


# ── Consultas SQL del agente (solo lectura, con guardas) ──────

@router.get('/api/consulta/esquema', dependencies=[Depends(requiere_scope('sql.consultas'))])
def api_listar_tablas(filtro: str = Query('', max_length=100)):
    """Catálogo de tablas de SIGAP con cantidad de filas (para que el agente arme SQL)."""
    return consultas.listar_tablas(filtro)


@router.get('/api/consulta/columnas', dependencies=[Depends(requiere_scope('sql.consultas'))])
def api_columnas_tabla(tabla: str = Query(..., max_length=100)):
    """Columnas de una tabla de SIGAP."""
    return consultas.columnas_tabla(tabla)


@router.post('/api/consulta/sql', dependencies=[Depends(requiere_scope('sql.consultas'))])
def api_ejecutar_sql(body: dict):
    """Ejecuta una consulta SELECT generada por el agente (validada y limitada)."""
    sql = str(body.get('sql') or '').strip()
    if not sql:
        raise HTTPException(status_code=400, detail='El campo "sql" es requerido.')
    resultado = consultas.ejecutar_sql(sql)
    if not resultado.get('ok'):
        raise HTTPException(status_code=422, detail=resultado.get('error', 'Error en la consulta'))
    return resultado
