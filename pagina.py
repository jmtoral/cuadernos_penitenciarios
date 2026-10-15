"""Regenera docs/index.html (GitHub Pages) a partir de data/processed/ y docs/plantilla.html."""
import json
from pathlib import Path

import pandas as pd

P = Path("data/processed")
pob = pd.read_csv(P / "poblacion.csv", keep_default_na=False)
# 2000-01 a 2005-01 sale del OCR de los cuadernos escaneados (ocr13.py)
n13 = pd.concat([pd.read_csv(P / "nacional_13m_ocr.csv").assign(src="o"), pd.read_csv(P / "nacional_13m.csv").assign(src="t")])
cap = pd.read_csv(P / "capacidad.csv", keep_default_na=False)

# Serie nacional: tabla por entidad; antes de ella, el cuaderno más reciente que reporta el mes en su tabla de 13 meses
ent = pob[pob.nivel == "entidad"].groupby(["periodo", "fuero", "situacion"]).valor.sum().reset_index().assign(src="e")
previo = (n13[~n13.periodo_reportado.isin(ent.periodo)]
          .sort_values("periodo_cuaderno").groupby(["periodo_reportado", "fuero", "situacion"])[["valor", "src"]].last()
          .reset_index().rename(columns={"periodo_reportado": "periodo"}))
nac = pd.concat([previo, ent])
w = nac.pivot_table(index=["periodo", "src"], columns=["situacion", "fuero"], values="valor", aggfunc="sum")
data = [[p, int(r["procesada", "comun"]), int(r["procesada", "federal"]), int(r.sum()), s] for (p, s), r in w.iterrows()]

# Sobrepoblación: espacios y población por entidad; exceso centro por centro
k = ["periodo", "entidad_raw", "centro_raw", "ambito_centro"]
cen = (pob[pob.nivel == "centro"].groupby(k).valor.sum().rename("pob").to_frame()
       .join(cap[cap.nivel == "centro"].groupby(k).valor.sum().rename("esp"), how="inner"))
cen["exc"] = (cen.pob - cen.esp).clip(lower=0)
g = cen.groupby("periodo")
sobre = pd.DataFrame({
    "esp": cap[cap.nivel == "entidad"].groupby("periodo").valor.sum(),
    "pob": pob[pob.nivel == "entidad"].groupby("periodo").valor.sum(),
    "exc": g.exc.sum(), "n": g.exc.apply(lambda s: (s > 0).sum()), "tot": g.size(),
}).dropna()
sobre = [[p, *map(int, r)] for p, r in sobre.iterrows()]

# Población nacional a mitad de año (CONAPO, conapo.py) para las tasas por 100 mil
con = pd.read_csv(P / "poblacion_conapo.csv").groupby("anio")[["pob", "pob_15_mas"]].sum()
pobnac = [[int(a), int(r.pob), int(r.pob_15_mas)] for a, r in con.iterrows()]

js = lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":"))
html = open("docs/plantilla.html", encoding="utf-8", newline="").read()
html = html.replace("__DATA__", js(data)).replace("__SOBRE__", js(sobre)).replace("__POBNAC__", js(pobnac))
Path("docs/index.html").write_text(html, encoding="utf-8", newline="")
print(f"docs/index.html: {len(data)} meses nacionales ({data[-1][0]}), {len(sobre)} meses de sobrepoblación")
