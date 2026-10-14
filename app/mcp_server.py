"""Servidor MCP de SIGAP — datos municipales reales (solo lectura).

Modos de uso:
    1. Local (stdio):  python app/mcp_server.py
       → para Claude Desktop, Cursor y clientes MCP locales.
    2. HTTP: se monta sobre FastAPI en /mcp (ver app/main.py) con token.

Las herramientas exponen solo consultas curadas contra SQL Server SIGAP.
No hay SQL genérico ni operaciones de escritura.
"""
import os
import sys

# Permitir ejecutar desde cualquier cwd (stdio para clientes MCP locales)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.mcpserver import MCPServer

from app.services import consultas as svc_consultas
from app.services import contribuyentes as svc_contribuyentes
from app.services import expedientes as svc_expedientes
from app.services import panel as svc_panel
from app.services import recaudacion as svc_recaudacion

mcp = MCPServer(
    name="sigap-mcp",
    instructions=(
        "Servidor de datos municipales de Rawson (SIGAP, solo lectura). "
        "Herramientas: consulta de expedientes, deuda del padrón, recaudación, "
        "ejecución presupuestaria, KPIs ejecutivos y consultas SQL generadas por "
        "el agente (solo SELECT, limitadas y auditadas). "
        "Los expedientes se identifican como NUMERO-LETRA/AÑO (ej. 3540-S-2026)."
    ),
)


@mcp.tool(description="Busca expedientes por número, año o letra. "
                      "Acepta '3540', '3540/2026' o '3540-S-2026'. "
                      "Devuelve lista de coincidencias con estado y sector actual.")
def buscar_expediente(q: str, limit: int = 10) -> dict:
    return svc_expedientes.buscar_expedientes(q, limit)


@mcp.tool(description="Detalle completo de un expediente: datos generales, estado, "
                      "sector actual, días de tramitación y el recorrido completo "
                      "entre sectores (movimientos con fechas y usuarios). "
                      "numero es obligatorio; ano y letra ayudan a precisar la búsqueda.")
def detalle_expediente(numero: int, ano: int = None, letra: str = None) -> dict:
    return svc_expedientes.detalle_expediente(numero, ano, letra)


@mcp.tool(description="Analítica de gestión de expedientes para mejora de procesos: "
                      "cantidad en trámite, tiempos promedio/mediana, backlog (>180 días), "
                      "tiempo de resolución por tipo de trámite y carga actual por sector "
                      "(detecta cuellos de botella). Incluye los 10 más demorados.")
def analitica_expedientes() -> dict:
    return svc_expedientes.analitica_expedientes()


@mcp.tool(description="Deuda del padrón oficial de un contribuyente por nomenclatura "
                      "(ej. IM344002000008). Devuelve nombre, domicilio, barrio y el "
                      "desglose: boletas, planes de pago, certificados y total.")
def deuda_contribuyente(codigo: str) -> dict:
    return svc_contribuyentes.deuda_contribuyente(codigo)


@mcp.tool(description="Busca contribuyentes en el padrón oficial por nomenclatura o "
                      "nombre/razón social. Devuelve los de mayor deuda primero.")
def buscar_contribuyente(q: str, limit: int = 10) -> dict:
    return svc_contribuyentes.buscar_contribuyentes(q, limit)


@mcp.tool(description="Resumen de recaudación: hoy, mes actual y año, con comparativa "
                      "interanual, emisión de boletas del año, índice de cobranza y "
                      "recaudación mensual de los últimos 3 años.")
def recaudacion() -> dict:
    return svc_recaudacion.resumen_recaudacion()


@mcp.tool(description="Ejecución presupuestaria de ingresos por partida: presupuesto "
                      "definitivo vs ejecutado acumulado con porcentaje. "
                      "Parámetro opcional: ejercicio (año).")
def ejecucion_presupuestaria(ejercicio: int = None, top: int = 10) -> dict:
    return svc_recaudacion.ejecucion_presupuestaria(ejercicio, top)


@mcp.tool(description="Recaudación del año por canal de cobro: cajas, colectores, "
                      "Mercado Pago, agentes (Pago Fácil/Rapipago), banco, foto multas "
                      "y tesorería, con cantidad de cobros y montos. Parámetro opcional: anio.")
def canales_recaudacion(anio: int = None) -> dict:
    return svc_recaudacion.canales_recaudacion(anio)


@mcp.tool(description="Cobros anulados del año: total de cobros y montos por mes, y los "
                      "últimos registros anulados con motivo y nomenclatura. "
                      "Parámetros opcionales: anio, limit (default 20) y mes (1-12) "
                      "para filtrar los últimos registros a un mes específico.")
def anulaciones(anio: int = None, limit: int = 20, mes: int = None) -> dict:
    return svc_recaudacion.anulaciones(anio, limit, mes)


@mcp.tool(description="Ranking de colectores del año: recaudación por colector, cantidad "
                      "de cobros, contribuyentes asignados y deuda del padrón asignada. "
                      "Parámetro opcional: anio.")
def colectores(anio: int = None) -> dict:
    return svc_recaudacion.colectores(anio)


@mcp.tool(description="Cobros de HOY discriminados: total del día (cobros y monto), anulados, "
                      "pagos digitales, desglose por tipo de boleta (mensuales/varios/planes/"
                      "especiales), por partida presupuestaria y por cobrador. "
                      "Usar cuando preguntan cuánto se cobró hoy o de dónde sale ese monto.")
def cobros_del_dia() -> dict:
    return svc_recaudacion.cobros_del_dia()


@mcp.tool(description="Composición mensual de la recaudación del año: efectivo/caja, "
                      "depósito/cheque y pagos digitales (Mercado Pago + foto multas). "
                      "Parámetro opcional: anio.")
def medios_pago(anio: int = None) -> dict:
    return svc_recaudacion.medios_pago(anio)


@mcp.tool(description="KPIs ejecutivos consolidados para el intendente: recaudación "
                      "(hoy/mes/año + interanual), deuda del padrón por componente y tipo, "
                      "expedientes en trámite, planes de pago, contribuyentes activos, "
                      "órdenes de compra y pago, proveedores y stock.")
def kpis_ejecutivos() -> dict:
    return svc_panel.kpis_ejecutivos()


@mcp.tool(description="Lista las tablas de la base SIGAP con su cantidad aproximada de filas "
                      "(las más grandes primero). Usar antes de generar una consulta SQL "
                      "cuando no se conoce el nombre de la tabla. Parámetro opcional: filtro "
                      "parcial del nombre (ej. 'cobro', 'boleta', 'contribu').")
def listar_tablas(filtro: str = '') -> dict:
    return svc_consultas.listar_tablas(filtro)


@mcp.tool(description="Devuelve las columnas de una tabla de SIGAP (nombre, tipo y largo) "
                      "para poder armar una consulta SQL correcta.")
def columnas_tabla(tabla: str) -> dict:
    return svc_consultas.columnas_tabla(tabla)


@mcp.tool(description="Ejecuta una consulta SQL de SOLO LECTURA generada por el agente "
                      "contra la base SIGAP. Solo SELECT/WITH, máximo 200 filas, timeout "
                      "de 20 segundos y sin bloqueos (LOCK_TIMEOUT 10s). Devuelve columnas "
                      "y filas. Si falla, devuelve el error para corregir la consulta.")
def consulta_sql(sql: str) -> dict:
    return svc_consultas.ejecutar_sql(sql)


if __name__ == "__main__":
    mcp.run(transport="stdio")
