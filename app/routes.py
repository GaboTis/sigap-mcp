"""REST API — misma capa de servicios que el MCP, para web/dashboards/bots.

Seguridad: cada ruta exige token con el scope correspondiente (ver app/auth.py).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import requiere_scope
from app.services import contribuyentes, expedientes, panel, recaudacion

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
