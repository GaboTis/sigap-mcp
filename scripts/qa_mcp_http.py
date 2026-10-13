"""Prueba MCP sobre HTTP con cliente real (sesión completa + tool call)."""
import asyncio
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('API_TOKEN', '')


async def main():
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    import httpx

    headers = {'Authorization': f'Bearer {TOKEN}'}
    http_client = httpx.AsyncClient(headers=headers, timeout=60)
    async with streamable_http_client('http://127.0.0.1:8100/mcp', http_client=http_client) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print('herramientas vía HTTP:', len(tools.tools))

            res = await session.call_tool('analitica_expedientes', {})
            texto = res.content[0].text if res.content else ''
            data = json.loads(texto) if texto else {}
            print('analitica vía HTTP → en trámite:', data.get('en_tramite'),
                  '| +180d:', data.get('pct_mas_180'), '%')

            res2 = await session.call_tool('recaudacion', {})
            print('recaudacion is_error:', res2.is_error, '| bloques:', len(res2.content))
            for bloque in res2.content:
                print('  bloque:', repr(getattr(bloque, 'text', None))[:400])
                txt = getattr(bloque, 'text', None)
                if txt and txt.strip().startswith('{'):
                    data2 = json.loads(txt)
                    print('recaudacion vía HTTP → año:', data2.get('anio', {}).get('monto'),
                          '| interanual:', data2.get('anio', {}).get('variacion_pct'), '%')
                    break
    print('MCP HTTP COMPLETO OK ✅')


asyncio.run(main())
