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

from app.services import contribuyentes as svc_contribuyentes
from app.services import expedientes as svc_expedientes
from app.services import panel as svc_panel
from app.services import recaudacion as svc_recaudacion

mcp = MCPServer(
    name="sigap-mcp",
    instructions=(
        "Servidor de datos municipales de Rawson (SIGAP, solo lectura). "
        "Herramientas: consulta de expedientes, deuda del padrón, recaudación, "
        "ejecución presupuestaria y KPIs ejecutivos. "
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


@mcp.tool(description="KPIs ejecutivos consolidados para el intendente: recaudación "
                      "(hoy/mes/año + interanual), deuda del padrón por componente y tipo, "
                      "expedientes en trámite, planes de pago, contribuyentes activos, "
                      "órdenes de compra y pago, proveedores y stock.")
def kpis_ejecutivos() -> dict:
    return svc_panel.kpis_ejecutivos()


if __name__ == "__main__":
    mcp.run(transport="stdio")
