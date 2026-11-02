# -*- coding: utf-8 -*-
"""Cazador de apellidos: busca TODAS las variantes de una persona en SIGAP."""
import re
import unicodedata

from app.db import get_conn


def _norm(s):
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = s.encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', s).strip().upper()


def _variantes(apellido):
    """Variantes plausibles de un apellido: QU↔CU, dobles letras colapsadas,
    y las dos mitades separadas (para apellidos compuestos)."""
    base = _norm(apellido)
    out = {base}
    if 'QU' in base:
        out.add(base.replace('QU', 'CU'))
    elif 'CU' in base:
        out.add(base.replace('CU', 'QU'))
    for doble, simple in (('TT', 'T'), ('PP', 'P'), ('NN', 'N'), ('LL', 'L'),
                          ('SS', 'S'), ('RR', 'R'), ('CC', 'C'), ('FF', 'F')):
        for v in list(out):
            if doble in v:
                out.add(v.replace(doble, simple))
    return sorted(out)


def _fragmentos(apellido):
    """Además de las variantes, mitades del apellido (compuestos con espacio)."""
    frags = set(_variantes(apellido))
    v = _norm(apellido)
    if len(v) >= 8 and ' ' not in v:
        frags.add(v[: len(v) // 2] + ' ' + v[len(v) // 2:])
    return sorted(frags)


def buscar_persona(apellido, nombre=None):
    """Caza un apellido en TODAS las fuentes: padrón, sectores, usuarios,
    expedientes y movimientos. Devuelve todo lo encontrado agrupado."""
    apellido = _norm(apellido).split()[-1] if apellido else ''
    nombre_norm = _norm(nombre).split()[0] if nombre else ''
    if len(apellido) < 4:
        return {'ok': False, 'message': 'El apellido debe tener al menos 4 letras'}
    frags = _fragmentos(apellido)
    like_nombre = f'%{nombre_norm}%' if nombre_norm else None

    conn = get_conn()
    cur = conn.cursor()

    # 1) Contribuyentes (padrón)
    contrib = []
    total_contrib = 0
    for f in frags:
        sql = 'SELECT NOMENCLA, RAZONSOCI, DNI, CUIT FROM contribu WITH (NOLOCK) WHERE RAZONSOCI LIKE ?'
        params = [f'%{f}%']
        if like_nombre:
            sql += ' AND RAZONSOCI LIKE ?'
            params.append(like_nombre)
        cur.execute(sql, params)
        for r in cur.fetchall():
            registro = {'nomencla': str(r[0]).strip(),
                        'nombre': str(r[1]).strip(),
                        'dni': int(r[2] or 0), 'cuit': int(r[3] or 0),
                        'variante': f}
            if registro['nomencla'] not in {c['nomencla'] for c in contrib}:
                contrib.append(registro)
            total_contrib += 1

    # 2) Sectores (responsables)
    sectores = []
    for f in frags:
        cur.execute('SELECT CODIGO, DESCRIPCION, RESPONSABLE FROM sectmuni '
                    'WITH (NOLOCK) WHERE RESPONSABLE LIKE ?', (f'%{f}%',))
        for r in cur.fetchall():
            registro = {'codigo': str(r[0]).strip(), 'sector': str(r[1]).strip(),
                        'responsable': str(r[2]).strip(), 'variante': f}
            if registro['codigo'] not in {s['codigo'] for s in sectores}:
                sectores.append(registro)

    # 3) Usuarios del sistema
    usuarios = []
    for f in frags:
        cur.execute("SELECT USUARIO_ID, APELLIDO, NOMBRE, TITULO, GRUPO_ID "
                    "FROM usuario WITH (NOLOCK) WHERE APELLIDO LIKE ? OR NOMBRE LIKE ?",
                    (f'%{f}%', f'%{f}%'))
        for r in cur.fetchall():
            registro = {'usuario': str(r[0]).strip(), 'apellido': str(r[1]).strip(),
                        'nombre': str(r[2]).strip(), 'titulo': str(r[3]).strip(),
                        'grupo': str(r[4]).strip(), 'variante': f}
            if registro['usuario'] not in {u['usuario'] for u in usuarios}:
                usuarios.append(registro)

    # 4) Menciones en expedientes (motivo)
    total_exp = 0
    ejemplos_exp = []
    for f in frags:
        cur.execute('SELECT COUNT(*) FROM expediente WITH (NOLOCK) WHERE MOTIVO LIKE ?',
                    (f'%{f}%',))
        total_exp += cur.fetchone()[0]
        cur.execute("SELECT TOP 2 NUMERO, LETRA, ANO, MOTIVO FROM expediente WITH (NOLOCK) "
                    "WHERE MOTIVO LIKE ? ORDER BY ANO DESC", (f'%{f}%',))
        for r in cur.fetchall():
            ejemplos_exp.append({'expediente': f"{r[0]}-{str(r[1] or '').strip()}/{r[2]}",
                                 'motivo': str(r[3]).strip()[:90]})

    # 5) Menciones en movimientos (observaciones)
    total_mov = 0
    ejemplos_mov = []
    for f in frags:
        cur.execute('SELECT COUNT(*) FROM expemovi WITH (NOLOCK) '
                    'WHERE OBSERVACIONES LIKE ?', (f'%{f}%',))
        total_mov += cur.fetchone()[0]
        cur.execute("SELECT TOP 2 NUMERO, ANO, OBSERVACIONES FROM expemovi WITH (NOLOCK) "
                    "WHERE OBSERVACIONES LIKE ? ORDER BY FECHAHORA DESC", (f'%{f}%',))
        for r in cur.fetchall():
            ejemplos_mov.append({'expediente': f'{r[0]}/{r[1]}',
                                 'observacion': str(r[2]).strip()[:90]})
    conn.close()

    return {
        'ok': True,
        'apellido': apellido,
        'variantes_buscadas': frags,
        'contribuyentes': {'total': total_contrib, 'resultados': contrib[:12]},
        'sectores': sectores,
        'usuarios': usuarios,
        'expedientes': {'total': total_exp, 'ejemplos': ejemplos_exp[:4]},
        'movimientos': {'total': total_mov, 'ejemplos': ejemplos_mov[:4]},
    }
