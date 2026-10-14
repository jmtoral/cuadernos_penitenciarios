"""Baja de datos.gob.mx (CKAN) las 4 tablas clave de cada mes publicado, para validar.

Salida: data/raw/ckan/<AAAA-MM>/<tabla>.csv
Los CSV directos (repodatos.atdt.gob.mx) dan 403; se usa datastore_search.
"""
import csv
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
API = "https://www.datos.gob.mx/api/3/action/"
SALIDA = Path(__file__).parent / "data/raw/ckan"
TABLAS = ("fue_sjur_sex_ent", "sobrepob_ent", "fue_sjur_sex_centro1", "fue_sjur_var_mensual")
MESES = {m: i + 1 for i, m in enumerate(
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split())}


def api(accion, **params):
    url = API + accion + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["result"]


def tabla_de(url):
    nombre = url.rsplit("/", 1)[-1]
    m = re.match(r"^(?:\d\d_)?(" + "|".join(TABLAS) + r")(?:_[a-z]{3}_?\d\d)?\.csv$", nombre)
    return m and m.group(1)


def main():
    paquetes = api("package_search", fq="organization:prs", rows=200)["results"]
    for p in paquetes:
        m = re.search(r"\((\w+), (\d{4})\)", p["title"])
        if not m or "penitenciari" not in p["title"].lower() or "vulnerable" in p["title"].lower():
            continue
        periodo = f"{m.group(2)}-{MESES[m.group(1).lower()]:02d}"
        for r in p["resources"]:
            tabla = tabla_de(r["url"])
            if not tabla:
                continue
            destino = SALIDA / periodo / f"{tabla}.csv"
            if destino.exists():
                continue
            filas = api("datastore_search", resource_id=r["id"], limit=5000)["records"]
            destino.parent.mkdir(parents=True, exist_ok=True)
            with open(destino, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=[k for k in filas[0] if k != "_id"], extrasaction="ignore")
                w.writeheader()
                w.writerows(filas)
            print(periodo, tabla, len(filas))


if __name__ == "__main__":
    main()
