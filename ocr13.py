"""OCR de la tabla de 13 meses de los cuadernos escaneados de enero de 2001 a 2005 (fase 5, versión mínima).

Cada tabla trae ene del año anterior a ene del año del cuaderno: con los 5 cuadernos sale la serie nacional
2000-01 a 2005-01 por fuero y situación jurídica (2005 completo ya viene en la tabla de ene-2006, con texto).

Método: la página se renderiza a ~200 dpi (la resolución del escaneo), un desenfoque leve borra el sombreado de
puntos y RapidOCR devuelve cajas con texto. Desde ahí es como extraer.py: renglones con ≥ 15 cifras y columnas
por el borde derecho. Los meses se asignan por orden de renglón, no por el texto "Ene" (que a veces sale "unc").

Chequeo, por renglón: procesados + sentenciados = subtotal de cada fuero y común + federal = total. Un renglón que
no cuadra hace fallar el cuaderno. Los incrementos absolutos vienen en negritas y se leen peor: si no coinciden
con la diferencia entre renglones sólo se avisa, porque las sumas ya confirman cada cifra.

Uso: python ocr13.py   →   data/processed/nacional_13m_ocr.csv
"""
import csv
import itertools
import re
from pathlib import Path

import numpy as np
import pypdfium2
from PIL import ImageFilter
from rapidocr_onnxruntime import RapidOCR

from extraer import COLS_13M, FUERO, NUM, SITUACION, columnas, norm, numero

RAIZ = Path(__file__).parent
PAGINA = {2001: 8, 2002: 8, 2003: 8, 2004: 8, 2005: 6}  # índice (desde 0) de la tabla en CE_AAAA-01.pdf
GRUPOS = ("c_p", "c_s", "c_sub", "f_p", "f_s", "f_sub", "total")


OCR = RapidOCR()


def imagen(anio, escala=2.8):
    pag = pypdfium2.PdfDocument(RAIZ / f"data/raw/pdf/CE_{anio}-01.pdf")[PAGINA[anio]]
    im = pag.render(scale=escala).to_pil()
    if im.height > im.width:  # 2001-2003: la tabla viene acostada
        im = im.rotate(90, expand=True)
    return im.convert("L").filter(ImageFilter.GaussianBlur(escala / 2.8)).convert("RGB")


def cajas(im):
    """[(y, x1, texto)]. Se quitan basuras pegadas ("14,111.", '"12,913') y "159.716" es "159,716": los
    porcentajes traen dos decimales."""
    res, _ = OCR(np.array(im))
    return [((b[0][1] + b[2][1]) / 2, max(p[0] for p in b), re.sub(r"^(-?\d{1,3})\.(\d{3})$", r"\1,\2", t.strip().strip(".,:;'`\"")))
            for b, t, _ in res or []]


def agrupar(cs):
    """Renglones de cajas, trazados de izquierda a derecha: la hoja puede venir chueca o combada (2002)."""
    filas = []
    for c in sorted(cs, key=lambda c: c[1]):
        cerca = [f for f in filas if abs(f[-1][0] - c[0]) <= 15]
        if cerca:
            min(cerca, key=lambda f: abs(f[-1][0] - c[0])).append(c)
        else:
            filas.append([c])
    return sorted(filas, key=lambda f: sum(c[0] for c in f) / len(f))


def releer(im, x0, x1, y):
    """Una celda por separado, a 1.5 veces la escala de la página completa."""
    caja = im.crop((int(x0), int(y - 30), int(x1 + 15), int(y + 30)))
    return [t for _, _, t in cajas(caja.resize((caja.width * 3 // 2, caja.height * 3 // 2))) if NUM.match(t)]


def tabla(anio):
    im = imagen(anio)
    cs = cajas(im)
    texto = norm(" ".join(t for *_, t in sorted(cs))).replace(" ", "")
    if "COMPORTAMIENTO" not in texto or "INCREMENTO" not in texto:
        raise ValueError(f"{anio}: la página {PAGINA[anio]} no parece la tabla de 13 meses")
    rs = []
    for f in agrupar(cs):
        # el año ("2000") no es cifra de la tabla: las cifras de 4 dígitos traen coma
        cifras = sorted((x1, t) for _, x1, t in f if NUM.match(t) and not re.fullmatch(r"(19|20)\d\d", t))
        if len(cifras) >= 15:  # "Incremento de la población" trae 14 y en dos renglones
            rs.append((sorted((x, y) for y, x, _ in f), 0, cifras, 0))
    if len(rs) == 14:  # "Incremento de la población", abajo de la tabla, completo en un renglón
        rs = rs[:13]
    if len(rs) != 13:
        raise ValueError(f"{anio}: {len(rs)} renglones con cifras, se esperaban 13")
    col = columnas(rs, [COLS_13M], f"13m {anio}")
    leidos = []  # por renglón: {columna: [(x1, texto)]}; puede haber basura ("7", "-8") junto a una cifra
    for _, _, cifras, _ in rs:
        v = {}
        for x, t in cifras:
            v.setdefault(col(x), []).append((x, t))
        leidos.append(v)
    centro = {n: np.median([x for v in leidos for x, _ in v.get(n, [])]) for n in COLS_13M}
    izq = dict(zip(COLS_13M, [centro[COLS_13M[0]] - 250] + [centro[n] for n in COLS_13M[:-1]]))  # borde de la celda
    grande = None
    valores, errores, avisos = [], [], []
    for i, ((xy, _, _, _), v) in enumerate(zip(rs, leidos)):
        n_cols = [f"{g}_n" for g in GRUPOS]
        cand = {n: {numero(t) for _, t in v.get(n, [])} for n in n_cols}
        if not cuadra({n: next(iter(c)) for n, c in cand.items() if len(c) == 1}):
            # el renglón no cuadra o le falta una cifra: se releen sus celdas y se busca la combinación que cuadra
            if grande is None:
                grande = imagen(anio, 4.2)
            for n in n_cols:
                y = np.interp(centro[n], *zip(*xy))  # altura del renglón en esa columna
                cand[n] |= {numero(t) for t in releer(grande, izq[n] * 1.5, centro[n] * 1.5, y * 1.5)}
        sols = [dict(zip(n_cols, c)) for c in itertools.product(*(cand[n] for n in n_cols)) if cuadra(dict(zip(n_cols, c)))]
        if len({tuple(s.values()) for s in sols}) != 1:
            errores.append(f"renglón {i}: {len(sols)} combinaciones cuadran con {cand}")
            valores.append({})
            continue
        valores.append({**{n: numero(ts[0][1]) for n, ts in v.items() if len(ts) == 1}, **sols[0]})
    for i, v in enumerate(valores):
        if i == 0 or not v or not valores[i - 1]:  # el primer renglón compara contra un mes fuera de la tabla
            continue
        for g in GRUPOS:
            n, ant = v.get(f"{g}_n"), valores[i - 1].get(f"{g}_n")
            if n is not None and ant is not None and n - ant != v.get(f"{g}_abs"):
                avisos.append(f"{i}:{g}")
    if errores:
        raise ValueError(f"{anio}: " + "; ".join(errores))
    return valores, avisos


def cuadra(v):
    """procesados + sentenciados = subtotal en cada fuero, común + federal = total (todas las cifras presentes)."""
    return all(k in v for k in ("c_p_n", "c_s_n", "c_sub_n", "f_p_n", "f_s_n", "f_sub_n", "total_n")) and (
        v["c_p_n"] + v["c_s_n"] == v["c_sub_n"] and v["f_p_n"] + v["f_s_n"] == v["f_sub_n"]
        and v["c_sub_n"] + v["f_sub_n"] == v["total_n"])


def main():
    salida = []
    for anio in PAGINA:
        valores, avisos = tabla(anio)
        for i, v in enumerate(valores):
            k = (anio - 1) * 12 + i
            for f in "cf":
                for s in "ps":
                    salida.append({"periodo_reportado": f"{k // 12}-{k % 12 + 1:02d}", "periodo_cuaderno": f"{anio}-01",
                                   "fuero": FUERO[f], "situacion": SITUACION[s], "valor": v[f"{f}_{s}_n"],
                                   "archivo": f"CE_{anio}-01.pdf"})
        print(anio, "ok", f"(incrementos ilegibles o distintos: {', '.join(avisos)})" if avisos else "")
    with open(RAIZ / "data/processed/nacional_13m_ocr.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(salida[0]))
        w.writeheader()
        w.writerows(salida)


if __name__ == "__main__":
    main()
