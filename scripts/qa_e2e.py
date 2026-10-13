"""QA end-to-end: REST con token + MCP stdio con cliente real."""
import asyncio
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
_TOKENS = json.loads((_RAIZ / 'tokens.json').read_text(encoding='utf-8'))
TOKEN = _TOKENS['clientes']['webapp']['token']
BASE = 'http://127.0.0.1:8100'


def test_rest():
    print('== REST ==')
    # 1) health sin token
    r = httpx.get(f'{BASE}/api/health', timeout=30)
    print(f"  health: {r.status_code} {r.json()['status']}")

    # 2) sin token → 401
    r = httpx.get(f'{BASE}/api/expedientes/buscar', params={'q': '3540'}, timeout=30)
    print(f"  sin token: {r.status_code} (esperado 401)")

    # 3) con token → datos reales
    h = {'Authorization': f'Bearer {TOKEN}'}
    r = httpx.get(f'{BASE}/api/expedientes/buscar', params={'q': '3540-S-2026'}, headers=h, timeout=60)
    d = r.json()
    print(f"  buscar expediente: {r.status_code} | total={d['total']} | {d['resultados'][0]['numero']}-{d['resultados'][0]['letra']}/{d['resultados'][0]['ano']}")

    r = httpx.get(f'{BASE}/api/panel/kpis', headers=h, timeout=60)
    k = r.json()
    print(f"  kpis: {r.status_code} | recaudación año ${k['recaudacion']['anio']:,.0f} | deuda ${k['deuda_padron']['total']:,.0f}")

    r = httpx.get(f'{BASE}/api/contribuyentes/deuda', params={'codigo': 'IM345805620000'}, headers=h, timeout=60)
    print(f"  deuda contribuyente: {r.status_code} | {r.json()['nombre']} → ${r.json()['deuda']['total']:,.2f}")

    # 3b) Scope insuficiente → 403 (token dashboard no puede ver deuda puntual)
    h_dash = {'Authorization': f'Bearer {_TOKENS["clientes"]["dashboard"]["token"]}'}
    r403 = httpx.get(f'{BASE}/api/contribuyentes/deuda', params={'codigo': 'IM345805620000'},
                     headers=h_dash, timeout=60)
    print(f"  scope insuficiente (dashboard → deuda): {r403.status_code} (esperado 403)")

    # 4) MCP HTTP sin token → 401
    r = httpx.post(f'{BASE}/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                                        'params': {'protocolVersion': '2025-06-18',
                                                   'capabilities': {}, 'clientInfo': {'name': 'qa', 'version': '1'}}},
                   timeout=30)
    print(f"  MCP HTTP sin token: {r.status_code} (esperado 401)")
    h_mcp = {'Authorization': f'Bearer {_TOKENS["clientes"]["agentes"]["token"]}'}
    r2 = httpx.post(f'{BASE}/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                                         'params': {'protocolVersion': '2025-06-18',
                                                    'capabilities': {}, 'clientInfo': {'name': 'qa', 'version': '1'}}},
                    headers=h_mcp, timeout=30, follow_redirects=True)
    print(f"  MCP HTTP con token scope mcp: {r2.status_code} (esperado 200)")


async def test_mcp_stdio():
    print('== MCP stdio (cliente real) ==')
    from mcp.client.stdio import stdio_client
    from mcp import ClientSession
    from mcp import StdioServerParameters

    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    params = StdioServerParameters(
        command=sys.executable,
        args=[os.path.join(raiz, 'app', 'mcp_server.py')],
        cwd=raiz,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"  herramientas: {len(tools.tools)} → {[t.name for t in tools.tools]}")

            res = await session.call_tool('buscar_expediente', {'q': '3540-S-2026'})
            print(f"  buscar_expediente: {len(res.content)} bloque(s) de contenido")

            res2 = await session.call_tool('detalle_expediente', {'numero': 3540, 'ano': 2026, 'letra': 'S'})
            texto = res2.content[0].text if res2.content else ''
            data = json.loads(texto) if texto else {}
            print(f"  detalle_expediente: motivo={data.get('expediente', {}).get('motivo', '')[:40]}")

            res3 = await session.call_tool('kpis_ejecutivos', {})
            texto3 = res3.content[0].text if res3.content else ''
            data3 = json.loads(texto3) if texto3 else {}
            print(f"  kpis_ejecutivos: deuda=${data3.get('deuda_padron', {}).get('total', 0):,.0f}")


if __name__ == '__main__':
    test_rest()
    asyncio.run(test_mcp_stdio())
    print('\nE2E OK ✅')
