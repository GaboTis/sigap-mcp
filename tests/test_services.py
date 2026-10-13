"""Tests de servicios y API con conexión SQL mockeada."""
import datetime
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import expedientes, contribuyentes, recaudacion, panel


class FakeCursor:
    def __init__(self, rows_list):
        self._rows = list(rows_list)
        self._sql = None

    def execute(self, sql, params=None):
        self._sql = sql
        self._params = params

    def fetchone(self):
        if self._rows:
            elem = self._rows.pop(0)
            return elem[0] if isinstance(elem, list) and len(elem) == 1 else elem
        raise AssertionError(f"Sin filas enlatadas para: {self._sql}")

    def fetchall(self):
        if self._rows:
            elem = self._rows.pop(0)
            return elem if isinstance(elem, list) else [elem]
        raise AssertionError(f"Sin filas enlatadas para: {self._sql}")


class FakeConn:
    def __init__(self, rows_list):
        self.cursor_obj = FakeCursor(rows_list)

    def cursor(self):
        return self.cursor_obj

    def close(self):
        pass


# ── Expedientes ───────────────────────────────────────────────

def test_parsear_busqueda():
    assert expedientes._parsear_busqueda('3540-S-2026') == (3540, 2026, 'S')
    assert expedientes._parsear_busqueda('3540/2026') == (3540, 2026, None)
    assert expedientes._parsear_busqueda('3540') == (3540, None, None)


BUSCAR_ROWS = [
    [(3540, 'S', 2026, datetime.datetime(2026, 4, 9), 'P', '63',
      'S/ CONTRATACIÓN DEL SR OMAR MRAD', 'NO', True, 4,
      'Pagado/Cancelado', 'NOTAS', 'SUBSECRETARIA DE TRANSFOR DIGITAL', 1)],
]


def test_buscar_expedientes():
    with patch('app.services.expedientes.get_conn', return_value=FakeConn(BUSCAR_ROWS)):
        r = expedientes.buscar_expedientes('3540-S-2026')
    assert r['total'] == 1
    assert r['parseo'] == {'numero': 3540, 'ano': 2026, 'letra': 'S'}
    assert r['resultados'][0]['estado_desc'] == 'Pagado/Cancelado'


DETALLE_ROWS = [
    [(3540, 'S', 2026, datetime.datetime(2026, 4, 9),
      datetime.datetime(2026, 4, 9, 12, 12, 57), 'P', 'NO', 'CONT',
      'S/ CONTRATACIÓN DEL SR OMAR MRAD', 'Interno', 'Interno', 4, True, 'VENGIU',
      '63', '98', '63',
      'Pagado/Cancelado', 'NOTAS', 'CONTRATACION', 'SUBSECRETARIA DE TRANSFOR DIGITAL',
      'SEC DE HACIENDA Y FINANZAS', 'SUBSECRETARIA DE TRANSFOR DIGITAL',
      'JULIO QUATTROPANI', 'JULIO QUATTROPANI', 13)],
    [(datetime.datetime(2026, 4, 9, 12, 12, 57), 'ME', 'MESA DE ENTRADA',
      'ME', 'MESA DE ENTRADA', 'I', 'EN CURSO', 4, '', 'VENGIU', None)],
]


def test_detalle_expediente():
    with patch('app.services.expedientes.get_conn', return_value=FakeConn(DETALLE_ROWS)):
        r = expedientes.detalle_expediente(3540, 2026, 'S')
    assert r is not None
    x = r['expediente']
    assert x['estado_desc'] == 'Pagado/Cancelado'
    assert x['dias_tramite'] == 13
    assert len(r['movimientos']) == 1


# ── Contribuyentes ────────────────────────────────────────────

DWH_ROWS = [
    [('DWH_Deudas_Items_202610',)],                     # descubrimiento de tabla
    [(3540, 'PINTO VICENTA', 'MERCEDITAS 332', 'IM', 'VILLA HIPODROMO',
      82871.85, 0.0, 17074.96, 0.0, 99946.81, '13/10/2026')],  # deuda (join rn=1)
]


def test_deuda_contribuyente():
    with patch('app.services.contribuyentes.get_conn', return_value=FakeConn(DWH_ROWS)):
        r = contribuyentes.deuda_contribuyente('IM345805620000')
    assert r is not None
    assert r['nombre'] == 'PINTO VICENTA'
    assert r['deuda']['total'] == 99946.81
    assert r['deuda']['boletas'] == 82871.85


# ── Recaudación ───────────────────────────────────────────────

REC_ROWS = [
    [(10, 1234.5)],        # hoy
    [(120, 5000.0)],       # mes
    [(1000, 60000.0)],     # año
    [(40000.0,)],          # mismo período año anterior
    [(900, 55000.0)],      # emisión
    [(1, 100.0)],          # serie año-2
    [(2, 200.0)],          # serie año-1
    [(3, 300.0)],          # serie año actual
]


def test_resumen_recaudacion():
    with patch('app.services.recaudacion.get_conn', return_value=FakeConn(REC_ROWS)):
        r = recaudacion.resumen_recaudacion()
    assert r['hoy']['monto'] == 1234.5
    assert r['anio']['monto'] == 60000.0
    assert r['anio']['mismo_periodo_anio_anterior'] == 40000.0
    assert r['indice_cobranza_pct'] == round(60000.0 / 55000.0 * 100, 1)
    assert len(r['mensual_3_anios']) == 3


# ── Panel ─────────────────────────────────────────────────────

PANEL_ROWS = [
    [(10, 1234.5)], [(120, 5000.0)], [(1000, 60000.0)],   # cobros hoy/mes/año
    [(362000,)], [(14000, 164000000.0)], [(82000,)],      # gestión
    [(1390, 40000000000.0)], [(130, 450000000.0)], [(9700,)],  # compras
    [(117,)], [(30,)],                                     # stock
]

DWH_RESUMEN_ROWS = [
    [('DWH_Deudas_Items_202610',)],                        # descubrimiento tabla
    [(95000, 100.0, 20.0, 5.0, 1.0, 126.0)],               # totales deuda (rn=1)
    [('IM', 47469, 114168259807.62)],                      # por tipo
]


def test_kpis_ejecutivos():
    with patch('app.services.panel.get_conn', return_value=FakeConn(PANEL_ROWS)), \
            patch('app.services.contribuyentes.get_conn', return_value=FakeConn(DWH_RESUMEN_ROWS)), \
            patch('app.services.recaudacion.get_conn', return_value=FakeConn(REC_ROWS)):
        r = panel.kpis_ejecutivos()
    assert r['gestion']['expedientes_en_tramite'] == 362000
    assert r['stock']['stock_bajo'] == 30
    assert r['deuda_padron']['total'] == 126.0


# ── API (auth) ────────────────────────────────────────────────

def test_health_sin_token():
    client = TestClient(app)
    r = client.get('/api/health')
    assert r.status_code == 200
    assert r.json()['status'] == 'ok'


def test_api_exige_token():
    client = TestClient(app)
    r = client.get('/api/expedientes/buscar', params={'q': '3540'})
    assert r.status_code == 401


def test_api_con_token_valido():
    client = TestClient(app)
    token = os.getenv('API_TOKEN', 'test')
    headers = {'Authorization': f'Bearer {token}'}
    with patch('app.services.expedientes.get_conn', return_value=FakeConn(BUSCAR_ROWS)):
        r = client.get('/api/expedientes/buscar', params={'q': '3540'}, headers=headers)
    assert r.status_code == 200
    assert r.json()['total'] == 1
