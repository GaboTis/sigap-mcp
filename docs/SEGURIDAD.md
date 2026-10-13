# 🔒 Seguridad de sigap-mcp

> Datos expuestos: deudas, nombres, DNI, domicilios y expedientes de contribuyentes.
> Son **datos personales** (Ley 25.326 de Protección de Datos Personales, Argentina).
> Tratar con el mismo nivel de cuidado que los sistemas fiscales internos.

## Lo que ya está implementado (capa de aplicación)

| Control | Detalle |
|---------|---------|
| **Token por cliente** | `tokens.json` (gitignored): cada consumidor (dashboard, webapp, WhatsApp…) tiene su propio token revocable |
| **Scopes (least privilege)** | `dashboard` → solo KPIs/analítica · `whatsapp` → solo expedientes y deuda puntual. Sin acceso total salvo que se otorgue `*` |
| **Rate limiting** | 120 req/min por cliente y 30 req/min por IP sin token (configurable en `.env`); bloqueo de 5 min al exceder |
| **Auditoría** | `logs/access.log`: fecha, IP, cliente, método, ruta, código de respuesta y duración de cada pedido |
| **Security headers** | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` en API |
| **CORS con lista blanca** | Sin `CORS_ORIGINS` → solo same-origin. Con lista → solo esos orígenes |
| **Sin SQL genérico** | Solo herramientas curadas; queries parametrizadas; nombre de tabla DWH desde `INFORMATION_SCHEMA` |

## Antes de exponer a Internet (capa de red — OBLIGATORIO)

**Nunca exponer uvicorn (8100) directo a Internet.** Poner delante un reverse proxy
con TLS. Opciones:

### Caddy (recomendado, HTTPS automático)
```
tu-dominio.o-servidor {                    # o sub.dominio del municipio
    encode gzip
    @api path /api/* /mcp /dashboard
    handle @api {
        header {
            X-Content-Type-Options nosniff
            -Server
        }
        reverse_proxy 127.0.0.1:8100
    }
    respond 404
}
```
Con dominio propio → certificado TLS automático (Let's Encrypt).

### Nginx
```nginx
server {
    listen 443 ssl;
    server_name tu-dominio;
    ssl_certificate     /ruta/cert.pem;
    ssl_certificate_key /ruta/key.pem;

    location / { proxy_pass http://127.0.0.1:8100; proxy_set_header Host $host; }
}
```

### IIS (ARR + URL Rewrite) — entorno Windows municipal
- Sitio con binding HTTPS (certificado de la CA interna del municipio)
- Regla de URL Rewrite → `http://127.0.0.1:8100/{R:0}`

### IP allowlist (la medida más fuerte)
Si los consumidores son **servidores conocidos** (el bot de WhatsApp vive en un
servidor propio, Bot Maker en la nube, la app web en un hosting), limitar el acceso
solo a esas IPs:

- **Firewall del servidor**: regla de entrada al 443 solo desde las IPs de esos servidores
- **En el proxy** (Caddy):
```
@permitido not remote_ip 190.1.2.0/24 200.5.6.7
abort @permitido
```
- Meta (WhatsApp Cloud API) llama **server-to-server** desde IPs dinámicas de Meta:
  usar verificación con token en los webhooks y mantener el rate limit — no IP fija.

## Para el agente WhatsApp (datos personales)

1. **Verificar identidad** antes de revelar deuda/datos: pedir DNI + un dato de
   verificación (ej. último domicilio o número de contribuyente) y contrastarlo
   contra SIGAP antes de responder.
2. El token `whatsapp` **no tiene** scope de KPIs ni analítica: aunque el token se
   filtrara, no expone información agregada del municipio.
3. Registrar en el bot qué número de teléfono preguntó qué cosa (complementa la
   auditoría del servidor).
4. Nunca mostrar datos de terceros: solo responder por el contribuyente verificado.

## Operación

- **Rotar tokens**: cada X meses o ante sospecha, generar nuevos (`secrets.token_hex(24)`)
  y eliminar el comprometido de `tokens.json`.
- **Revocar un cliente**: borrar su entrada de `tokens.json` y reiniciar `sigap-mcp`
  (o `pm2 restart sigap-mcp`).
- **Monitorear** `logs/access.log`: muchos 401 seguidos = ataque de fuerza bruta
  (el rate limit ya los bloquea 5 min, pero conviene investigar la IP).
- **Backups**: `tokens.json` y `logs/access.log` entran en el backup diario.
- Si algo se filtra: la app es de **solo lectura** — el peor caso es lectura de
  datos, no alteración. Aun así, notificar conforme al procedimiento de brechas.

## Ejemplo de tokens.json (gitignored — nunca commitear)

```json
{
  "clientes": {
    "dashboard": { "token": "…48 hex…", "scopes": ["kpis", "recaudacion", "expedientes.analitica"] },
    "webapp":    { "token": "…48 hex…", "scopes": ["expedientes.read", "expedientes.analitica",
                                                    "contribuyentes.deuda", "contribuyentes.buscar",
                                                    "recaudacion", "kpis"] },
    "whatsapp":  { "token": "…48 hex…", "scopes": ["expedientes.read", "contribuyentes.deuda"] }
  }
}
```

## Scopes disponibles

| Scope | Qué permite |
|-------|-------------|
| `kpis` | `/api/panel/kpis` (KPIs ejecutivos consolidados) |
| `recaudacion` | `/api/recaudacion`, `/api/recaudacion/ejecucion` |
| `expedientes.read` | buscar y detalle de expedientes |
| `expedientes.analitica` | analítica agregada de gestión |
| `contribuyentes.deuda` | deuda puntual de un contribuyente |
| `contribuyentes.buscar` | búsqueda en el padrón |
| `mcp` | acceso al MCP HTTP (todas las herramientas MCP) |
| `*` | acceso total (solo uso administrativo interno) |
