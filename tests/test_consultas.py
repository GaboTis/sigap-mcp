"""Tests de las guardas del servicio de consultas SQL (sin conexión a DB)."""
import pytest

from app.services.consultas import _validar


def test_select_simple_valido():
    sql = _validar('SELECT TOP 10 * FROM contribu')
    assert sql.startswith('SELECT')


def test_select_con_cte_valido():
    sql = _validar('WITH x AS (SELECT 1 AS n) SELECT * FROM x')
    assert sql.startswith('WITH')


def test_rechaza_update():
    with pytest.raises(ValueError):
        _validar('UPDATE contribu SET RAZONSOCI = NULL')


def test_rechaza_delete():
    with pytest.raises(ValueError):
        _validar('DELETE FROM boletas WHERE ANULA = 1')


def test_rechaza_insert():
    with pytest.raises(ValueError):
        _validar("INSERT INTO contribu VALUES ('X')")


def test_rechaza_exec():
    with pytest.raises(ValueError):
        _validar('EXEC sp_who')


def test_rechaza_select_into():
    with pytest.raises(ValueError):
        _validar('SELECT * INTO tabla_nueva FROM contribu')


def test_rechaza_dos_sentencias():
    with pytest.raises(ValueError):
        _validar('SELECT 1; SELECT 2')


def test_rechaza_no_select():
    with pytest.raises(ValueError):
        _validar('PRINT "hola"')


def test_rechaza_vacio():
    with pytest.raises(ValueError):
        _validar('   ')


def test_rechaza_muy_larga():
    with pytest.raises(ValueError):
        _validar('SELECT ' + 'a,' * 3000 + ' b')


def test_ignora_comentarios():
    sql = _validar("SELECT 1 -- comentario; DROP TABLE x")
    assert 'DROP' not in sql


def test_rechaza_openrowset():
    with pytest.raises(ValueError):
        _validar('SELECT * FROM OPENROWSET(...)')


def test_permite_rtrim_y_like():
    sql = _validar("SELECT RTRIM(NOMENCLA) FROM contribu WHERE NOMENCLA LIKE 'IM34%'")
    assert 'RTRIM' in sql
