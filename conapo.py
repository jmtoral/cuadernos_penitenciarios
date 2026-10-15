"""Población a mitad de año (CONAPO, proyecciones por municipio) agregada por entidad y año.

Fuente: datos.gob.mx, "Proyecciones de población, indicadores demográficos" (pobproy_inddemo.csv),
recurso e9160552-769b-41ee-88d1-afc765552608. Se baja con datastore_search (el CSV directo da 403).

Salida: data/processed/poblacion_conapo.csv
  anio, cve_ent, entidad, pob, hombres, mujeres, pob_15_mas, hombres_15_mas, mujeres_15_mas
El denominador para tasas de población penitenciaria es pob_15_mas: el grupo publicado más cercano a la
población adulta (CONAPO no publica 18+ en este recurso).
"""
import csv
import json
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
RECURSO = "e9160552-769b-41ee-88d1-afc765552608"
CAMPOS = ["ANO", "CLAVE_ENT", "NOM_ENT", "POB_MIT_MUN", "HOM_MIT_ANO", "MUJ_MIT_ANO",
          "POB_00_014", "HOM_00_014", "MUJ_00_014"]
SALIDA = Path(__file__).parent / "data/processed/poblacion_conapo.csv"


def pagina(offset, limite=32000):
    q = urllib.parse.urlencode({"resource_id": RECURSO, "limit": limite, "offset": offset, "fields": ",".join(CAMPOS)})
    req = urllib.request.Request("https://www.datos.gob.mx/api/3/action/datastore_search?" + q, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        res = json.load(r)["result"]
    return res["records"], res["total"]


def main():
    suma = defaultdict(lambda: defaultdict(int))
    nombres, offset = {}, 0
    while True:
        filas, total = pagina(offset)
        for f in filas:
            k = (int(f["ANO"]), int(f["CLAVE_ENT"]))
            nombres[k[1]] = f["NOM_ENT"]
            for c in CAMPOS[3:]:
                suma[k][c] += int(f[c] or 0)
        offset += len(filas)
        print(offset, "de", total)
        if not filas or offset >= total:
            break
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["anio", "cve_ent", "entidad", "pob", "hombres", "mujeres", "pob_15_mas", "hombres_15_mas", "mujeres_15_mas"])
        for (anio, ent), s in sorted(suma.items()):
            w.writerow([anio, f"{ent:02d}", nombres[ent], s["POB_MIT_MUN"], s["HOM_MIT_ANO"], s["MUJ_MIT_ANO"],
                        s["POB_MIT_MUN"] - s["POB_00_014"], s["HOM_MIT_ANO"] - s["HOM_00_014"], s["MUJ_MIT_ANO"] - s["MUJ_00_014"]])
    print(SALIDA, len(suma), "renglones")


if __name__ == "__main__":
    main()
