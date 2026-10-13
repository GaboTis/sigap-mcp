# sigap-mcp — Capa de datos de SIGAP (solo lectura)

Servicio único de datos municipales de Rawson que expone **la misma información real
del SQL Server SIGAP** a través de dos interfaces:

| Interfaz | Transporte | Consumidores |
|----------|-----------|--------------|
| **MCP** (Model Context Protocol) | `stdio` (local) y HTTP (`/mcp`) | Agentes IA: Claude Desktop, Cursor, chatbots, agente WhatsApp |
| **REST** (FastAPI) | HTTP `/api/*` con Bearer token | App web SIGAP KPI, dashboards ejecutivos, bots |

Un solo deploy, una sola capa de seguridad: **solo lectura, queries parametrizadas,
sin SQL genérico** — solo herramientas curadas.

## 🚀 Instalación

```powershell
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env   # completar credenciales y API_TOKEN
```

## ▶️ Ejecutar

**API REST + MCP HTTP** (para web, dashboards y bots remotos):
```powershell
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8100
```
- `http://127.0.0.1:8100/api/health` — salud
- `http://127.0.0.1:8100/api/expedientes/buscar?q=3540-S-2026` (header `Authorization: Bearer <API_TOKEN>`)
- `http://127.0.0.1:8100/mcp` — MCP streamable HTTP (mismo token)

**MCP local (stdio)** para Claude Desktop / Cursor:
```powershell
.\venv\Scripts\python.exe app\mcp_server.py
```

> Si `API_TOKEN` está vacío, la API queda abierta (solo para uso local). Con token,
> todas las rutas `/api/*` y `/mcp` lo exigen.

## 🔧 Herramientas MCP

| Herramienta | Qué devuelve |
|-------------|--------------|
| `buscar_expediente(q, limit)` | Coincidencias por número/año/letra (`3540`, `3540/2026`, `3540-S-2026`) con estado y sector |
| `detalle_expediente(numero, ano, letra)` | Datos, días de tramitación y recorrido completo entre sectores |
| `analitica_expedientes()` | En trámite, tiempos (promedio/mediana), backlog +180 días, resolución por tipo, carga por sector, top demorados |
| `deuda_contribuyente(codigo)` | Deuda del padrón DWH por nomenclatura (boletas/planes/certificados/total) |
| `buscar_contribuyente(q, limit)` | Búsqueda en el padrón por nomenclatura o nombre |
| `recaudacion()` | Hoy/mes/año, interanual, índice de cobranza, mensual 3 años |
| `ejecucion_presupuestaria(ejercicio, top)` | Presupuesto vs ejecutado por partida |
| `kpis_ejecutivos()` | KPIs consolidados: recaudación, deuda, gestión, compras, stock |

## 🖥️ Conectar Claude Desktop (local)

En `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sigap": {
      "command": "C:\\Users\\User\\Documents\\CODE\\sigap-mcp\\venv\\Scripts\\python.exe",
      "args": ["C:\\Users\\User\\Documents\\CODE\\sigap-mcp\\app\\mcp_server.py"]
    }
  }
}
```

Ejemplo de conversación: *"¿Dónde está el expediente 3540-S-2026?"* →
la IA llama `detalle_expediente` y responde con datos reales.

## 💬 Agente WhatsApp / chatbots

1. Bot conectado a WhatsApp Business API (Meta) con un runtime LLM.
2. El LLM usa **MCP HTTP** (`http://<host>:8100/mcp` con Bearer token)
   o directamente la **REST API** (`/api/*` con token).
3. Flujo: el vecino escribe su consulta → la IA elige la herramienta →
   respuesta con datos reales de SIGAP.

## 📊 Dashboard ejecutivo / app web

Consumir la REST API con el header `Authorization: Bearer <API_TOKEN>`:
- `/api/panel/kpis` — KPIs ejecutivos completos
- `/api/expedientes/analitica` — analítica de gestión
- `/api/recaudacion` — recaudación con interanual

## 🔒 Seguridad

- Conexión a SIGAP **solo lectura** (queries SELECT con `WITH (NOLOCK)`).
- Queries **parametrizadas**; el nombre de la tabla DWH se descubre por
  `INFORMATION_SCHEMA` (nunca desde input del usuario).
- REST y MCP-HTTP exigen **Bearer token** (`API_TOKEN` de `.env`).
- MCP stdio no necesita token (proceso local, sin exposición de red).
- Para exponer el HTTP a otra máquina, usar `--host 0.0.0.0` + reverse proxy
  con TLS (o mantenerlo en 127.0.0.1 y túneles seguros).

## 📁 Estructura

```
app/
├── main.py            → FastAPI (REST) + montaje MCP HTTP
├── mcp_server.py      → servidor MCP (stdio) con 8 herramientas
├── routes.py          → endpoints REST con token
├── db.py              → conexión SQL Server (solo lectura)
└── services/          → lógica de dominio (consultas validadas)
    ├── expedientes.py
    ├── contribuyentes.py
    ├── recaudacion.py
    └── panel.py
tests/test_services.py → 9 tests con SQL mockeado
```

## 🧪 Tests

```powershell
.\venv\Scripts\python.exe -m pytest tests/ -q
.\venv\Scripts\python.exe scripts\qa_live.py   # validación contra SIGAP real
```
