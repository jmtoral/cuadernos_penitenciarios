"""Descarga los PDFs listados en data/enlaces.csv a data/raw/pdf/ y escribe data/raw/manifiesto.csv.

data/enlaces.csv se arma a mano desde las páginas anuales de gob.mx: las páginas HTML
tienen un desafío anti-bots, los PDFs no. Para un mes nuevo, agrega su fila ahí.

Uso: python descargar.py [AAAA-MM_desde]
"""
import csv
import hashlib
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
RAIZ = Path(__file__).parent
PDF = RAIZ / "data/raw/pdf"
MANIFIESTO = RAIZ / "data/raw/manifiesto.csv"


def bajar(url, destino):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        datos = r.read()
    if not datos.startswith(b"%PDF"):
        raise ValueError(f"no es PDF: {url}")
    destino.write_bytes(datos)


def main(desde=""):
    PDF.mkdir(parents=True, exist_ok=True)
    previo = {}
    if MANIFIESTO.exists():
        previo = {r["periodo"]: r for r in csv.DictReader(open(MANIFIESTO, encoding="utf-8"))}
    filas = []
    for e in csv.DictReader(open(RAIZ / "data/enlaces.csv", encoding="utf-8")):
        if not e["periodo"]:  # liga rota conocida (dic-2003 apunta a dic-2023)
            continue
        destino = PDF / f"CE_{e['periodo']}.pdf"
        if e["periodo"] >= desde and not destino.exists():
            print("bajando", e["periodo"], e["url"])
            bajar(e["url"], destino)
            time.sleep(0.5)
        if not destino.exists():
            continue
        r = previo.get(e["periodo"])
        sha = hashlib.sha256(destino.read_bytes()).hexdigest()
        if not r or r["sha256"] != sha:
            r = {"periodo": e["periodo"], "archivo": destino.name, "url": e["url"],
                 "sha256": sha, "fecha_descarga": date.today().isoformat()}
        filas.append(r)
    filas.sort(key=lambda r: r["periodo"])
    with open(MANIFIESTO, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["periodo", "archivo", "url", "sha256", "fecha_descarga"])
        w.writeheader()
        w.writerows(filas)
    print(len(filas), "PDFs en el manifiesto")


if __name__ == "__main__":
    main(*sys.argv[1:])
