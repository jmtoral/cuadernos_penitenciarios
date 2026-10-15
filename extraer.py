"""Extrae de los PDFs (épocas A, B y C, 2006+) las tablas de población por fuero/situación/sexo.

Lee data/raw/manifiesto.csv y escribe en data/processed/:
  poblacion.csv      nivel entidad (tabla por entidad) y centro (tabla por centro)
  capacidad.csv      espacios por entidad y centro
  nacional_13m.csv   tabla de comportamiento de 13 meses, tal cual
  impresos.csv       subtotales y totales impresos, solo para validar

Método: pdfplumber da palabras con coordenadas; las cifras están alineadas a la derecha,
así que las columnas se obtienen agrupando el borde derecho (x1) de todas las cifras de la
tabla. Si no sale el número de columnas esperado, la tabla falla en voz alta.

Uso: python extraer.py [AAAA-MM_desde] [AAAA-MM_hasta]
"""
import csv
import re
import sys
import unicodedata
from pathlib import Path

import pdfplumber

RAIZ = Path(__file__).parent
SALIDA = RAIZ / "data/processed"
MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO",
         "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
NUM = re.compile(r"^-?[\d,]+(\.\d+)?%?$")

# columnas (de izquierda a derecha) por tabla
COLS_ENT = ["c_p_H", "c_p_M", "c_p_sub", "c_s_H", "c_s_M", "c_s_sub", "c_tot",
            "f_p_H", "f_p_M", "f_p_sub", "f_s_H", "f_s_M", "f_s_sub", "f_tot", "total", "pct"]
# ene-jun 2017: % después de cada subtotal y de cada total de fuero
COLS_ENT_PCT = ["c_p_H", "c_p_M", "c_p_sub", "c_p_pct", "c_s_H", "c_s_M", "c_s_sub", "c_s_pct", "c_tot", "c_tot_pct",
                "f_p_H", "f_p_M", "f_p_sub", "f_p_pct", "f_s_H", "f_s_M", "f_s_sub", "f_s_pct", "f_tot", "f_tot_pct",
                "total", "pct"]
# 2007: la tabla no cabe en una hoja; el % final pasa a la página siguiente junto con el nombre repetido
COLS_ENT_PCT_SIN_FINAL = COLS_ENT_PCT[:-1]
# 2020-2021: % sólo después del subtotal de procesadas
COLS_ENT_PPCT = ["c_p_H", "c_p_M", "c_p_sub", "c_p_pct", "c_s_H", "c_s_M", "c_s_sub", "c_tot",
                 "f_p_H", "f_p_M", "f_p_sub", "f_p_pct", "f_s_H", "f_s_M", "f_s_sub", "f_tot", "total", "pct"]
COLS_CEN = ["espacios", "sobre_abs", "sobre_rel",
            "c_p_H", "c_p_M", "c_s_H", "c_s_M", "c_sub", "c_pct",
            "f_p_H", "f_p_M", "f_s_H", "f_s_M", "f_sub", "f_pct", "total"]
# 2017-2019: la tabla por centro no trae % del fuero común
COLS_CEN_SIN_PCT = [c for c in COLS_CEN if c != "c_pct"]
# 2021: la tabla por centro no trae columna TOTAL (mismo número de columnas que COLS_CEN_SIN_PCT)
COLS_CEN_SIN_TOTAL = COLS_CEN[:-1]
ESTADOS = {"AGUASCALIENTES", "BAJA CALIFORNIA", "BAJA CALIFORNIA SUR", "CAMPECHE", "CHIAPAS", "CHIHUAHUA",
           "CIUDAD DE MEXICO", "DISTRITO FEDERAL", "COAHUILA", "COAHUILA DE ZARAGOZA", "COLIMA", "DURANGO",
           "ESTADO DE MEXICO", "MEXICO", "GUANAJUATO", "GUERRERO", "HIDALGO", "JALISCO", "MICHOACAN",
           "MICHOACAN DE OCAMPO", "MORELOS", "NAYARIT", "NUEVO LEON", "OAXACA", "PUEBLA", "QUERETARO",
           "QUERETARO DE ARTEAGA", "QUINTANA ROO", "SAN LUIS POTOSI", "SINALOA", "SONORA", "TABASCO", "TAMAULIPAS",
           "TLAXCALA", "VERACRUZ", "VERACRUZ DE IGNACIO DE LA LLAVE", "YUCATAN", "ZACATECAS"}
FEDERAL = re.compile(r"^(CEFERESO|CEFEREPSI|CENTROS? (PENITENCIARIOS? )?FEDERAL|COMPLEJO PENITENCIARIO|CPS|ISLAS MARIAS|COLONIA PENAL)")
PIE = ("FUENTE", "NOTA", "ELABORADO", "ELABORO")
COLS_13M = [f"{g}_{k}" for g in ("c_p", "c_s", "c_sub", "f_p", "f_s", "f_sub", "total")
            for k in ("n", "abs", "pct")]
FUERO = {"c": "comun", "f": "federal"}
SITUACION = {"p": "procesada", "s": "sentenciada"}
SITUACION_RAW = {"p": "Personas Procesadas", "s": "Personas Sentenciadas"}


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def numero(t):
    return float(t.rstrip("%").replace(",", "")) if "." in t else int(t.rstrip("%").replace(",", ""))


def filas_de(pagina):
    """Agrupa palabras por renglón (tolerancia 3pt). Devuelve [(y, [palabras])]."""
    filas = []
    for w in sorted(pagina.extract_words(), key=lambda w: (w["top"], w["x0"])):
        if filas and abs(filas[-1][0] - w["top"]) <= 3:
            filas[-1][1].append(w)
        else:
            filas.append((w["top"], [w]))
    return [(y, sorted(ws, key=lambda w: w["x0"])) for y, ws in filas]


def lineas(pagina):
    if not hasattr(pagina, "_lineas"):  # extract_text es caro; se consulta varias veces por página
        pagina._lineas = [norm(l) for l in (pagina.extract_text() or "").splitlines()]
    return pagina._lineas


def titulo(pagina):
    return " ".join(lineas(pagina)[:4])


def periodo_impreso(pagina):
    # 2006-2008: "Enero de 2006"
    hallados = re.findall(r"\b(" + "|".join(MESES) + r") (?:DE )?(\d{4})\b", " ".join(lineas(pagina)[:8]))
    if not hallados:
        return None
    mes, anio = hallados[-1]
    return f"{anio}-{MESES.index(mes) + 1:02d}"


def pegar(ws):
    """Une palabras partidas sin espacio entre ellas ("Ju" + "l")."""
    salida = []
    for w in ws:
        if salida and w["x0"] - salida[-1]["x1"] < 0.5 and not NUM.match(w["text"]):
            salida[-1] = {**salida[-1], "text": salida[-1]["text"] + w["text"], "x1": w["x1"]}
        else:
            salida.append(w)
    return salida


def x_encabezado(pagina, defecto):
    """Borde izquierdo de la zona de cifras: el renglón de encabezado con muchas H/M."""
    for _, ws in filas_de(pagina):
        hm = [w for w in ws if w["text"] in ("H", "M")]
        if len(hm) >= 6:
            return min(w["x0"] for w in hm) - 12
    return defecto


def renglones(paginas, defecto, por_encabezado=True):
    """Renglones de datos: (etiqueta, x0_etiqueta, [(x1, texto)], num_pagina).

    Etiqueta = palabras a la izquierda de la primera columna de cifras (x_cifras).
    Renglones sólo-etiqueta (nombres partidos en dos líneas) se pegan al renglón con cifras más cercano.
    """
    salida = []
    for pag in paginas:
        escala = max(1, pag.width / 1000)  # 2012-04: páginas de 2263 pt de ancho
        x_cifras = x_encabezado(pag, defecto * escala) if por_encabezado else defecto * escala
        datos, sueltos = [], []
        for y, ws in filas_de(pag):
            cifras = [(w["x1"], w["text"]) for w in ws if w["x1"] >= x_cifras and NUM.match(w["text"])]
            etiqueta = [w for w in ws if w["x1"] < x_cifras]
            # un nombre largo puede rebasar el límite ("...San Miguel de Allende"): palabras pegadas a la etiqueta
            for w in ws:
                if etiqueta and w["x1"] >= x_cifras and not NUM.match(w["text"]) and w["x0"] - etiqueta[-1]["x1"] < 8:
                    etiqueta.append(w)
            texto = re.sub(r"\s*(\*+|\(\d\))$", "", " ".join(w["text"] for w in etiqueta))  # notas al pie: "CHIAPAS**", "PUEBLA (3)"
            if norm(texto).startswith(PIE):
                continue
            if cifras and texto:
                datos.append([y, texto, etiqueta[0]["x0"], cifras, pag.page_number])
            elif len(cifras) >= 3:  # nombre partido arriba y abajo de las cifras: la etiqueta llega de `sueltos`
                datos.append([y, "", None, cifras, pag.page_number])
            elif texto and not cifras:
                sueltos.append((y, texto, etiqueta[0]["x0"]))
        for y, texto, x0 in sueltos:
            if re.match(r"CEFERESO|CENTROS PEN\w* FEDERALES$", norm(texto)):
                continue  # 2016-11: centro sin cifras o encabezado de grupo; no es parte del nombre vecino
            vecinos = [d for d in datos if abs(d[0] - y) < 12]
            # primero un renglón de cifras sin etiqueta; si no, el más cercano
            cerca = min(vecinos, key=lambda d: (d[1] != "", abs(d[0] - y)), default=None)
            if cerca:
                cerca[1] = (f"{texto} {cerca[1]}" if y < cerca[0] else f"{cerca[1]} {texto}").strip()
                cerca[2] = cerca[2] if cerca[2] is not None else x0
        salida += [tuple(d[1:]) for d in datos if d[1]]
    return salida


def columnas(renglones_, variantes, tabla, minimo=3):
    """Agrupa x1 de todas las cifras y asigna nombres de izquierda a derecha.

    variantes: listas de nombres de columna; se usa la que tenga tantas columnas como grupos.
    """
    xs = sorted((x, t) for *_, cifras, _ in renglones_ for x, t in cifras)
    grupos = [[xs[0]]]
    for x, t in xs[1:]:
        if x - grupos[-1][-1][0] <= 8:
            grupos[-1].append((x, t))
        else:
            grupos.append([(x, t)])
    # cifras sueltas (desalineadas o de notas al pie) forman grupos chicos: no son columnas, van a la más cercana
    grupos = [g for g in grupos if len(g) >= max(minimo, 0.05 * len(renglones_) if minimo > 1 else 1)]
    # si dos variantes tienen el mismo número de columnas, gana la que pone "%" donde el PDF trae "%"
    es_pct = [sum("%" in t or "." in t for _, t in g) > len(g) / 2 for g in grupos]
    candidatas = [v for v in variantes if len(v) == len(grupos)]
    nombres = max(candidatas, default=None,
                  key=lambda v: sum((n.endswith(("pct", "rel"))) == p for n, p in zip(v, es_pct)))
    if not nombres:
        raise ValueError(f"{tabla}: {len(grupos)} columnas, se esperaban {[len(v) for v in variantes]}: "
                         f"{[round(sum(x for x, _ in g) / len(g)) for g in grupos]}")
    centros = [sum(x for x, _ in g) / len(g) for g in grupos]
    col = lambda x: nombres[min(range(len(centros)), key=lambda i: abs(centros[i] - x))]
    col.nombres = nombres
    return col


def sin_etiqueta_derecha(pag):
    """2006-2012: la tabla por entidad repite el nombre a la derecha de las cifras ("... 31,763 15.25 DISTRITO FEDERAL 1").

    Se recorta la página donde empieza ese segundo bloque: la primera palabra con letras que sigue a un renglón de cifras.
    """
    bordes = []
    for _, ws in filas_de(pag):
        n = 0
        for w in ws:
            if NUM.match(w["text"]):
                n += 1
            elif n >= 10 and re.search(r"[A-Za-z]", w["text"]):
                bordes.append(w["x0"])
                break
    x0, y0, _, y1 = pag.bbox  # 2007-04: la página no empieza en (0, 0)
    return pag.crop((x0, y0, min(bordes) - 0.5, y1)) if bordes else pag


def paginas_con(pdf, *claves, sin=(), con_periodo=True):
    """Páginas de tabla cuyo título tiene las claves; el índice queda fuera porque no trae "MES AAAA"."""
    return [p for p in pdf.pages if all(k in titulo(p) for k in claves) and not any(k in titulo(p) for k in sin)
            and (periodo_impreso(p) or not con_periodo)]


def por_titulo(paginas):
    """Agrupa páginas consecutivas con el mismo título: comparten acomodo de columnas."""
    grupos = []
    for p in paginas:
        if grupos and titulo(grupos[-1][-1]) == titulo(p):
            grupos[-1].append(p)
        else:
            grupos.append([p])
    return grupos


def emitir_poblacion(salida, base, valores):
    for f in "cf":
        for s in "ps":
            for sexo in "HM":
                v = valores.get(f"{f}_{s}_{sexo}")
                if v is not None:
                    salida.append({**base, "fuero": FUERO[f], "situacion_raw": SITUACION_RAW[s],
                                   "situacion": SITUACION[s], "sexo": sexo, "valor": v})


def tabla_entidad(pdf, periodo, meta, poblacion, impresos):
    sin = ("ESPACIOS", "CAPACIDAD", "EDAD", "ESCOLARIDAD", "ORIGEN", "INDIGENA", "INCIDENCIA", "EN LOS CENTROS", "EN LAS INSTITUCIONES")
    # 2010: algunos meses no imprimen el mes en el título; el filtro de cifras de abajo deja fuera al índice
    pags = paginas_con(pdf, "SEGUN FUERO, SITUACION JURIDICA Y SEXO", sin=sin) or         paginas_con(pdf, "SEGUN FUERO, SITUACION JURIDICA Y SEXO", sin=sin, con_periodo=False)
    # 2007: la hoja que sólo trae el nombre repetido (y quizá el % final) no es parte de la tabla
    pags = [p for p in pags if any(sum(bool(NUM.match(w["text"])) for w in ws) >= 10 for _, ws in filas_de(p))]
    if not pags:
        raise ValueError("no encontré la tabla por entidad")
    ambito = "estatal"
    grupos = por_titulo(pags)
    filas = []
    for i, g in enumerate(grupos):  # 2020-2021: estados y centros federales en páginas con título distinto
        rs = renglones([sin_etiqueta_derecha(p) for p in g], 190)
        rs = [(re.sub(r"^\d+ (?=\D)", "", r[0]), *r[1:]) for r in rs]  # 2006-2012: "1 DISTRITO FEDERAL" (lugar por tamaño)
        # 2016-11: "Total" de estados, CEFERESO, "Total" federal y "Total del mes de <mes>": los dos primeros son subtotales
        mes_actual = MESES[int(periodo[5:]) - 1]
        sig = [norm(r[0]) for r in rs[1:]] + [""]
        rs = [("Subtotal", *r[1:]) if norm(r[0]) == "TOTAL" and s and (not s.startswith("TOTAL") or s.startswith(f"TOTAL DEL MES DE {mes_actual}"))
              else r for r, s in zip(rs, sig)]
        col = columnas(rs, [COLS_ENT, COLS_ENT_PPCT, COLS_ENT_PCT, COLS_ENT_PCT_SIN_FINAL], "entidad")
        fin = next((j for j, r in enumerate(rs) if norm(r[0]).startswith("TOTAL")), len(rs))
        filas += [(r, col) for r in rs[:fin]]  # tras "Total" viene "Total del mes de <mes anterior>" (2020-2022)
        if fin < len(rs):
            fila = "TOTAL" if i == len(grupos) - 1 else f"TOTAL_g{i}"
            impresos += [{**meta, "tabla": "entidad", "fila": fila, "columna": col(x), "valor": numero(t)} for x, t in rs[fin][2]]
    for (etiqueta, _, cifras, pagina), col in filas:
        valores = {col(x): numero(t) for x, t in cifras}
        clave = norm(etiqueta)
        if clave == "SUBTOTAL":
            impresos += [{**meta, "tabla": "entidad", "fila": f"SUBTOTAL_{ambito}", "columna": k, "valor": v} for k, v in valores.items()]
            ambito = "federal"
            continue
        if FEDERAL.match(clave):
            ambito = "federal"
        # 2006-2012: renglones ordenados por tamaño; un estado chico puede venir después de un centro federal
        amb = "estatal" if clave in ESTADOS else ambito
        base = {**meta, "nivel": "entidad", "entidad_raw": etiqueta if amb == "estatal" else "Centros federales",
                "centro_raw": "" if amb == "estatal" else etiqueta, "ambito_centro": amb, "pagina": pagina}
        emitir_poblacion(poblacion, base, valores)
        impresos += [{**meta, "tabla": "entidad", "fila": etiqueta, "columna": k, "valor": v}
                     for k, v in valores.items() if not re.search(r"_[HM]$", k)]


def tabla_centro(pdf, periodo, meta, poblacion, capacidad, impresos):
    pags = paginas_con(pdf, "SOBREPOBLACION Y POBLACION", "SEGUN FUERO")  # "ESPACIOS, ..." (2016+) o "CAPACIDAD, ..." (2014-2016); "...Y CENTRO" o "...E INSTITUCION PENITENCIARIA FEDERAL"
    if not pags:
        raise ValueError("no encontré la tabla por centro")
    concepto = "Capacidad" if titulo(pags[0]).strip().startswith("CAPACIDAD") else "Espacios"
    rs = renglones(pags, 230, por_encabezado=False)
    hasta = next((i for i, r in enumerate(rs) if norm(r[0]) == "TOTAL"), len(rs))
    col = columnas(rs[:hasta + 1], [COLS_CEN, COLS_CEN_SIN_PCT, COLS_CEN_SIN_TOTAL], "centro")
    # 2010-10: una página viene a otra escala; las columnas se ubican página por página con los mismos nombres
    por_pagina = {}
    for n in {r[3] for r in rs[:hasta + 1]}:
        try:
            # en una sola página una columna puede tener 1-2 cifras (Islas Marías); se aceptan grupos de 1
            por_pagina[n] = columnas([r for r in rs[:hasta + 1] if r[3] == n], [col.nombres], "centro", minimo=1)
        except ValueError:  # página con columnas vacías: se usa el acomodo de toda la tabla
            por_pagina[n] = col
    entidad, ambito = None, "estatal"
    for etiqueta, x0, cifras, pagina in rs[:hasta + 1]:
        valores = {por_pagina[pagina](x): numero(t) for x, t in cifras}
        if norm(etiqueta) == "TOTAL":
            impresos += [{**meta, "tabla": "centro", "fila": "TOTAL", "columna": k, "valor": v} for k, v in valores.items()]
            break
        # notas al pie: "AGUASCALIENTES 2", "4 2 GUANAJUATO" (2010), "SAN LUIS POTO*S*Í", "GUANAJUATO*" (2008)
        limpia = re.sub(r"^(\d+ )+|( \d+)+$", "", etiqueta.replace("*", "")).strip()
        if norm(limpia) in ESTADOS:
            etiqueta = limpia
        # 2014-2015: el grupo federal se llama "Instituciones Penitenciarias Federales"
        grupo = norm(etiqueta) in ESTADOS or re.fullmatch(r"(CENTROS? PENITENCIARIOS?|INSTITUCIONES PENITENCIARIAS) FEDERAL(ES)?", norm(etiqueta))
        if FEDERAL.match(norm(etiqueta)) and ambito == "estatal" and not grupo:
            entidad, ambito = "Centros federales", "federal"  # sin renglón de grupo (2017-2019)
        if grupo:
            federal = norm(etiqueta) not in ESTADOS  # "Distrito Federal" es estado
            entidad, ambito = ("Centros federales", "federal") if federal else (etiqueta, "estatal")
            impresos += [{**meta, "tabla": "centro", "fila": entidad, "columna": k, "valor": v} for k, v in valores.items()]
            if "espacios" in valores:
                capacidad.append({**meta, "nivel": "entidad", "entidad_raw": entidad, "centro_raw": "",
                                  "ambito_centro": ambito, "concepto_raw": concepto, "valor": valores["espacios"], "pagina": pagina})
            continue
        if entidad is None:
            raise ValueError(f"centro sin entidad: {etiqueta}")
        base = {**meta, "nivel": "centro", "entidad_raw": entidad, "centro_raw": etiqueta,
                "ambito_centro": ambito, "pagina": pagina}
        emitir_poblacion(poblacion, base, valores)
        if "espacios" in valores:
            capacidad.append({**base, "concepto_raw": concepto, "valor": valores["espacios"]})
        impresos += [{**meta, "tabla": "centro", "fila": f"{entidad} | {etiqueta}", "columna": k, "valor": v}
                     for k, v in valores.items() if k in ("c_sub", "f_sub", "total")]


def tabla_13m(pdf, periodo, meta, nacional):
    # 2006-2010: "...E INCREMENTO MENSUAL" en vez de "...Y VARIACION MENSUAL"
    pags = paginas_con(pdf, "COMPORTAMIENTO", "VARIACION") or paginas_con(pdf, "COMPORTAMIENTO", "INCREMENTO MENSUAL") or         [p for p in paginas_con(pdf, "COMPORTAMIENTO", "VARIACION", con_periodo=False)  # 2012-04: "ABRIL - 2011 ABRIL - 2012"
         if "I N D I C E" not in titulo(p)]
    if not pags:
        raise ValueError("no encontré la tabla de 13 meses")
    abrev = {m[:3]: i for i, m in enumerate(MESES)} | {"AUG": 7}  # 2016-02 trae "Aug"
    rs = []  # renglón = palabra de mes + cifras a su derecha; se ignoran renglones con dos meses ("Dic 2021 - Dic 2022")
    for _, ws in filas_de(pags[0]):
        ws = pegar(ws)  # 2014-07: "Jul" viene partido en "Ju" + "l"
        meses = [w for w in ws if norm(w["text"]).rstrip(".*")[:3] in abrev and len(norm(w["text"]).rstrip(".*")) <= 4]
        if len(meses) != 1:
            continue
        cifras = [(w["x1"], w["text"]) for w in ws if w["x0"] > meses[0]["x1"] and (NUM.match(w["text"]) or set(w["text"]) == {"#"})]  # "######": celda desbordada en Excel (2008)
        if len(cifras) >= 18:  # el renglón "Incremento ... Ene 2017 -" trae menos cifras
            rs.append((meses[0]["text"], 0, cifras, pags[0].page_number))
    # 13 renglones; en algunos cuadernos de 2017 falta el del propio mes (ya está en la tabla por entidad)
    # y en 2014-07 el primero (su etiqueta cae en otro renglón): se anclan al final si el último es el mes del cuaderno
    if len(rs) not in (12, 13):
        raise ValueError(f"13m: {len(rs)} renglones de mes")
    col = columnas(rs, [COLS_13M], "13m")
    anio, mes = map(int, periodo.split("-"))
    al_final = abrev[norm(rs[-1][0]).rstrip(".*")[:3]] == mes - 1
    for i, (etiqueta, _, cifras, _) in enumerate(rs):
        k = anio * 12 + mes - 1 - ((len(rs) - 1 - i) if al_final else (12 - i))
        reportado = f"{k // 12}-{k % 12 + 1:02d}"
        if abrev[norm(etiqueta).rstrip(".*")[:3]] != k % 12:
            raise ValueError(f"13m: renglón {etiqueta} no es {reportado}")
        valores = {col(x): numero(t) for x, t in cifras if t[0] != "#"}
        faltan = [f"{f}_{s}_n" for f in "cf" for s in "ps" if f"{f}_{s}_n" not in valores]
        if faltan:
            raise ValueError(f"13m: {reportado} sin {faltan}")
        for f in "cf":
            for s in "ps":
                nacional.append({"periodo_reportado": reportado, "periodo_cuaderno": periodo, "fuero": FUERO[f],
                                 "situacion": SITUACION[s], "valor": valores[f"{f}_{s}_n"], "archivo": meta["archivo"]})


CAMPOS = {
    "poblacion": ["periodo", "nivel", "entidad_raw", "centro_raw", "ambito_centro", "fuero", "situacion_raw",
                  "situacion", "sexo", "valor", "archivo", "url", "pagina"],
    "capacidad": ["periodo", "nivel", "entidad_raw", "centro_raw", "ambito_centro", "concepto_raw", "valor",
                  "archivo", "url", "pagina"],
    "nacional_13m": ["periodo_reportado", "periodo_cuaderno", "fuero", "situacion", "valor", "archivo"],
    "impresos": ["periodo", "tabla", "fila", "columna", "valor", "archivo", "url"],
    "errores": ["periodo", "archivo", "error"],
}


def main(desde="2006-01", hasta="9999-99"):
    salidas = {k: [] for k in CAMPOS}
    for m in csv.DictReader(open(RAIZ / "data/raw/manifiesto.csv", encoding="utf-8")):
        if not desde <= m["periodo"] <= hasta:
            continue
        meta = {"periodo": m["periodo"], "archivo": m["archivo"], "url": m["url"]}
        print(m["periodo"], end=" ", flush=True)
        try:
            with pdfplumber.open(RAIZ / "data/raw/pdf" / m["archivo"]) as pdf:
                impreso = periodo_impreso(paginas_con(pdf, "SEGUN FUERO, SITUACION JURIDICA Y SEXO")[0])
                if impreso != m["periodo"]:
                    raise ValueError(f"el PDF dice {impreso}, el manifiesto {m['periodo']}")
                tmp = {k: [] for k in CAMPOS}
                tabla_entidad(pdf, m["periodo"], meta, tmp["poblacion"], tmp["impresos"])
                tabla_centro(pdf, m["periodo"], meta, tmp["poblacion"], tmp["capacidad"], tmp["impresos"])
                try:  # la tabla de 13 meses es testigo: si falla, el mes conserva sus otras tablas
                    tabla_13m(pdf, m["periodo"], meta, tmp["nacional_13m"])
                except Exception as e:
                    tmp["nacional_13m"] = []
                    salidas["errores"].append({**meta, "error": str(e)})
            for k in tmp:
                salidas[k] += tmp[k]
            print("ok")
        except Exception as e:  # el mes queda registrado como error; no se descarta en silencio
            print("ERROR", e)
            salidas["errores"].append({**meta, "error": str(e)})
    SALIDA.mkdir(parents=True, exist_ok=True)
    for nombre, filas in salidas.items():
        with open(SALIDA / f"{nombre}.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CAMPOS[nombre], extrasaction="ignore")
            w.writeheader()
            w.writerows(filas)
        print(nombre, len(filas))


if __name__ == "__main__":
    main(*sys.argv[1:])
