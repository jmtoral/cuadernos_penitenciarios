"""Chequeos de README §6 sobre data/processed/*.csv → validacion.csv + reporte_validacion.md.

Los meses que fallan se marcan, no se descartan.
"""
import re
import unicodedata
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).parent
P = RAIZ / "data/processed"
CKAN = RAIZ / "data/raw/ckan"
CLAVES = ["fuero", "situacion"]
SUB = {("comun", "procesada"): "c_p_sub", ("comun", "sentenciada"): "c_s_sub",
       ("federal", "procesada"): "f_p_sub", ("federal", "sentenciada"): "f_s_sub"}


def norm(s):
    s = str(s)
    if "√" in s:  # algunos CSV de datos.gob.mx vienen con UTF-8 leído como Mac Roman
        s = s.encode("mac_roman").decode("utf-8", "ignore")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Z0-9]+", " ", s.upper()).strip()
    # el PDF usa nombres oficiales largos; los CSV, cortos
    return re.sub(r" (DE ZARAGOZA|DE OCAMPO|DE IGNACIO DE LA LLAVE|DE IGNACIO DE LA)$", "", s)


def main():
    pob = pd.read_csv(P / "poblacion.csv", keep_default_na=False)
    imp = pd.read_csv(P / "impresos.csv", keep_default_na=False)
    n13 = pd.read_csv(P / "nacional_13m.csv")
    err = pd.read_csv(P / "errores.csv")
    res = []

    def anotar(periodo, chequeo, difs):
        res.append({"periodo": periodo, "chequeo": chequeo, "ok": not difs, "detalle": "; ".join(difs[:10])})

    for _, e in err.iterrows():
        anotar(e["periodo"], "extraccion", [e["error"]])

    ent = pob[pob.nivel == "entidad"].copy()
    ent["fila"] = ent.centro_raw.where(ent.ambito_centro == "federal", ent.entidad_raw)
    cen = pob[pob.nivel == "centro"]
    imp_ent = imp[imp.tabla == "entidad"]
    imp_cen = imp[imp.tabla == "centro"]

    for periodo, e in ent.groupby("periodo"):
        # suma_sexo: H + M = subtotal impreso de cada renglón
        hm = e.groupby(["fila", *CLAVES]).valor.sum()
        ie = imp_ent[imp_ent.periodo == periodo].set_index(["fila", "columna"]).valor
        difs = [f"{fila} {f}/{s}: {v} vs {ie.get((fila, SUB[(f, s)]))}" for (fila, f, s), v in hm.items()
                if ie.get((fila, SUB[(f, s)])) is not None and ie[(fila, SUB[(f, s)])] != v]
        anotar(periodo, "suma_sexo", difs)

        # entidades_vs_nacional: suma de renglones = TOTAL impreso
        nac = e.groupby(CLAVES).valor.sum()
        # sin TOTAL legible (2017-04 trae cifras pegadas; 2022 a veces no lo imprime): subtotal estatal + federal
        for k in SUB.values():
            if ("TOTAL", k) not in ie and ("SUBTOTAL_estatal", k) in ie and ("SUBTOTAL_federal", k) in ie:
                ie[("TOTAL", k)] = ie[("SUBTOTAL_estatal", k)] + ie[("SUBTOTAL_federal", k)]
        if all(("TOTAL", k) in ie for k in SUB.values()):
            difs = [f"{f}/{s}: {v} vs {ie[('TOTAL', SUB[(f, s)])]}" for (f, s), v in nac.items()
                    if ie[("TOTAL", SUB[(f, s)])] != v]
            anotar(periodo, "entidades_vs_nacional", difs)
        else:  # no verificable con la propia tabla; nacional_vs_13m lo cubre
            res.append({"periodo": periodo, "chequeo": "entidades_vs_nacional", "ok": True,
                        "detalle": "no verificable: el PDF no imprime un total legible"})

        # centros_vs_entidad: suma de centros por entidad = tabla por entidad
        c = cen[cen.periodo == periodo]
        a = e.assign(k=e.entidad_raw.map(norm)).groupby(["k", *CLAVES]).valor.sum()
        b = c.assign(k=c.entidad_raw.map(norm)).groupby(["k", *CLAVES]).valor.sum()
        j = pd.concat([a.rename("entidad"), b.rename("centros")], axis=1).fillna(0)
        difs = [f"{k} {f}/{s}: {r.entidad:.0f} vs {r.centros:.0f}" for (k, f, s), r in j.iterrows() if r.entidad != r.centros]
        anotar(periodo, "centros_vs_entidad", difs)

        # nacional_vs_13m: el propio cuaderno, y revisiones en cuadernos posteriores (informativo)
        for nombre, cond in (("nacional_vs_13m", n13.periodo_cuaderno == periodo),
                             ("revisiones_13m", n13.periodo_cuaderno != periodo)):
            t = n13[cond & (n13.periodo_reportado == periodo)]
            difs = [f"{r.fuero}/{r.situacion} cuaderno {r.periodo_cuaderno}: {r.valor} vs {nac.get((r.fuero, r.situacion))}"
                    for r in t.itertuples() if r.valor != nac.get((r.fuero, r.situacion))]
            anotar(periodo, nombre, difs)

    # pdf_vs_csv: celda a celda contra datos abiertos (tabla por entidad y por centro)
    for d in sorted(CKAN.glob("20??-??")):
        periodo = d.name
        e = ent[ent.periodo == periodo]
        if e.empty:
            continue
        nuestro = e.assign(k=e.fila.map(norm)).set_index(["k", *CLAVES, "sexo"]).valor
        difs = []
        csv = pd.read_csv(d / "fue_sjur_sex_ent.csv")
        for _, r in csv.iterrows():
            k = norm(r["entidad_centro"])
            if k in ("SUBTOTAL", "TOTAL") or k.startswith("TOTAL"):
                continue
            for f in ("comun", "federal"):
                for s, sc in (("procesada", "procesadas"), ("sentenciada", "sentenciadas")):
                    for sexo, sx in (("H", "hombres"), ("M", "mujeres")):
                        v = r.get(f"fuero_{f}_{sc}_{sx}")
                        v = 0 if pd.isna(v) else int(v)
                        o = int(nuestro.get((k, f, s, sexo), 0))
                        if v != o:
                            difs.append(f"ent {r['entidad_centro']} {f}/{s}/{sexo}: pdf {o} csv {v}")
        c = cen[cen.periodo == periodo]
        nuestro_c = c.assign(k=c.entidad_raw.map(norm) + "|" + c.centro_raw.map(norm)).groupby(["k", *CLAVES, "sexo"]).valor.sum()
        csvc = pd.read_csv(d / "fue_sjur_sex_centro1.csv")
        vistos = set()
        for _, r in csvc.iterrows():
            estado = "Centros federales" if norm(r["estado"]).startswith("CENTROS") or "FEDERAL" in norm(r["estado"]) else r["estado"]
            k = norm(estado) + "|" + norm(r["centro"])
            vistos.add(k)
            for f in ("comun", "federal"):
                for s, sc in (("procesada", "procesadas"), ("sentenciada", "sentenciadas")):
                    for sexo, sx in (("H", "hombres"), ("M", "mujeres")):
                        v = r.get(f"fuero_{f}_{sc}_{sx}")
                        v = 0 if pd.isna(v) else int(v)
                        o = int(nuestro_c.get((k, f, s, sexo), 0))
                        if v != o:
                            difs.append(f"cen {estado} | {r['centro']} {f}/{s}/{sexo}: pdf {o} csv {v}")
        sobran = {k for k, *_ in nuestro_c.index} - vistos
        difs += [f"centro no está en el CSV: {k}" for k in sorted(sobran)]
        anotar(periodo, "pdf_vs_csv", difs)

    v = pd.DataFrame(res).sort_values(["periodo", "chequeo"])
    v.to_csv(P / "validacion.csv", index=False)
    duros = v[(~v.ok) & (v.chequeo != "revisiones_13m")]
    rev = v[(~v.ok) & (v.chequeo == "revisiones_13m")]
    meses = v.periodo.nunique()
    lineas = [
        "# Reporte de validación", "",
        f"- Meses revisados: {meses} ({v.periodo.min()} a {v.periodo.max()})",
        f"- Meses con algún chequeo fallido: {duros.periodo.nunique()}",
        f"- Meses con revisiones retroactivas en la tabla de 13 meses (informativo): {rev.periodo.nunique()}", "",
        "| chequeo | meses ok | meses con falla |", "|---|---|---|",
        *[f"| {c} | {int(g.ok.sum())} | {int((~g.ok).sum())} |" for c, g in v.groupby("chequeo")], "",
        "## Fallas", "",
        *[f"- **{r.periodo}** `{r.chequeo}`: {r.detalle}" for r in duros.itertuples()], "",
        "## Revisiones retroactivas (13 meses)", "",
        *[f"- **{r.periodo}**: {r.detalle}" for r in rev.itertuples()],
    ]
    (P / "reporte_validacion.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print("\n".join(lineas[:12 + v.chequeo.nunique()]))


if __name__ == "__main__":
    main()
