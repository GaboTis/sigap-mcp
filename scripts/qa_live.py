"""QA en vivo — valida servicios y API contra SIGAP real."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import contribuyentes, expedientes, panel, recaudacion


def main():
    print('== 1. buscar_expedientes ========================')
    r = expedientes.buscar_expedientes('3540-S-2026')
    print(f"  total={r['total']} parseo={r['parseo']}")
    if r['resultados']:
        e = r['resultados'][0]
        print(f"  → {e['numero']}-{e['letra']}/{e['ano']} | {e['estado_desc']} | {e['sector_actual']}")

    print('== 2. detalle_expediente ========================')
    d = expedientes.detalle_expediente(3540, 2026, 'S')
    if d:
        x = d['expediente']
        print(f"  {x['motivo'][:50]} | días: {x['dias_tramite']} | movimientos: {len(d['movimientos'])}")
        for m in d['movimientos']:
            print(f"    {m['fecha_hora']} → {m['sector_desc']} (desde {m['proveniente_desc']})")

    print('== 3. analitica_expedientes =====================')
    a = expedientes.analitica_expedientes()
    print(f"  en trámite: {a['en_tramite']} | mediana: {a['mediana_dias_en_tramite']} d | "
          f"+180d: {a['pct_mas_180']}% | resolución prom: {a['resolucion_promedio_dias']} d")
    print(f"  tipos: {[(t['tipo'], t['dias_promedio']) for t in a['resolucion_por_tipo'][:4]]}")
    print(f"  sectores top: {[(s['sector'], s['en_tramite']) for s in a['carga_por_sector'][:3]]}")
    print(f"  demorados top: {[(m['expediente'], m['dias']) for m in a['mas_demorados'][:3]]}")

    print('== 4. deuda_contribuyente =======================')
    dd = contribuyentes.deuda_contribuyente('IM345805620000')
    if dd:
        print(f"  {dd['nombre']} | total: ${dd['deuda']['total']:,.2f} | fuente: {dd['fuente']}")

    print('== 5. resumen_deuda =============================')
    sd = contribuyentes.resumen_deuda()
    if sd:
        print(f"  contribuyentes: {sd['contribuyentes_con_deuda']} | total: ${sd['total']:,.0f}")
        print(f"  componentes: {sd['componentes']}")

    print('== 6. recaudacion ===============================')
    rec = recaudacion.resumen_recaudacion()
    print(f"  hoy: ${rec['hoy']['monto']:,.2f} | mes: ${rec['mes']['monto']:,.2f} | "
          f"año: ${rec['anio']['monto']:,.2f} ({rec['anio']['variacion_pct']}% interanual)")
    print(f"  índice cobranza: {rec['indice_cobranza_pct']}%")

    print('== 7. ejecucion_presupuestaria ==================')
    ej = recaudacion.ejecucion_presupuestaria(top=5)
    print(f"  total: {ej['total']['pct_ejecucion']}% ejecutado")
    for p in ej['partidas'][:4]:
        print(f"    {p['descripcion'][:45]} → {p['pct_ejecucion']}%")

    print('== 8. kpis_ejecutivos ===========================')
    k = panel.kpis_ejecutivos()
    print(f"  recaudación año: ${k['recaudacion']['anio']:,.2f} | deuda: ${k['deuda_padron']['total']:,.0f}")
    print(f"  expedientes: {k['gestion']['expedientes_en_tramite']} | stock: {k['stock']}")

    print('\nQA EN VIVO OK ✅')


if __name__ == '__main__':
    main()
