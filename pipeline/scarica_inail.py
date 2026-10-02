#!/usr/bin/env python3
"""
Scarica gli infortuni sul lavoro dalle Open API INAIL e prepara i dati
per il portale (Italia / Lombardia / Brescia / Bergamo).

Uso tipico:
    python scarica_inail.py                 # semestrale (ultimo triennio) + mensile
    python scarica_inail.py --solo mensile
    python scarica_inail.py --anni-semestrale 2023 2024 2025

Le risposte grezze vengono salvate in ./cache, quindi se lo script si
interrompe basta rilanciarlo: riparte da dove era arrivato.
Per riscaricare tutto (es. a una nuova pubblicazione) usare --rinfresca.

Requisiti: Python 3.9+, pandas, requests   (pip install pandas requests)
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import io
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

API = "https://dati.inail.it/api/OpenData/"
ENDPOINT = {
    "semestrale": "DatiConCadenzaSemestraleInfortuni",
    "mensile": "DatiConCadenzaMensileInfortuni",
}
TIPOLOGICHE = "https://dati.inail.it/opendata/downloads/daticoncadenzasemestraleinfortuni/csv/{}.csv"

# Regioni come le vuole l'API (maiuscolo). Per i nomi composti si provano
# più varianti: la prima che funziona viene ricordata in cache/regioni.json.
REGIONI = {
    "ABRUZZO": ["ABRUZZO"],
    "BASILICATA": ["BASILICATA"],
    "CALABRIA": ["CALABRIA"],
    "CAMPANIA": ["CAMPANIA"],
    "EMILIA ROMAGNA": ["EMILIA ROMAGNA", "EMILIA-ROMAGNA", "EMILIAROMAGNA"],
    "FRIULI VENEZIA GIULIA": ["FRIULI VENEZIA GIULIA", "FRIULI-VENEZIA GIULIA", "FRIULIVENEZIAGIULIA"],
    "LAZIO": ["LAZIO"],
    "LIGURIA": ["LIGURIA"],
    "LOMBARDIA": ["LOMBARDIA"],
    "MARCHE": ["MARCHE"],
    "MOLISE": ["MOLISE"],
    "PIEMONTE": ["PIEMONTE"],
    "PUGLIA": ["PUGLIA"],
    "SARDEGNA": ["SARDEGNA"],
    "SICILIA": ["SICILIA"],
    "TOSCANA": ["TOSCANA"],
    "TRENTINO ALTO ADIGE": ["TRENTINO ALTO ADIGE", "TRENTINO-ALTO ADIGE", "TRENTINOALTOADIGE"],
    "UMBRIA": ["UMBRIA"],
    "VALLE D'AOSTA": ["VALLE D'AOSTA", "VALLE D AOSTA", "VALLEDAOSTA", "VALLE DAOSTA"],
    "VENETO": ["VENETO"],
    "ALTRO": ["ALTRO"],
}

# Territori del portale. Codici provincia = codici ISTAT (campo LuogoAccadimento).
TERRITORI = ["Italia", "Lombardia", "Brescia", "Bergamo"]
PROVINCE = {"017": "Brescia", "016": "Bergamo"}

CLASSI_ETA = [
    ("Fino a 14 anni", 0, 14), ("Da 15 a 19 anni", 15, 19), ("Da 20 a 24 anni", 20, 24),
    ("Da 25 a 29 anni", 25, 29), ("Da 30 a 34 anni", 30, 34), ("Da 35 a 39 anni", 35, 39),
    ("Da 40 a 44 anni", 40, 44), ("Da 45 a 49 anni", 45, 49), ("Da 50 a 54 anni", 50, 54),
    ("Da 55 a 59 anni", 55, 59), ("Da 60 a 64 anni", 60, 64), ("Da 65 a 69 anni", 65, 69),
    ("Da 70 a 74 anni", 70, 74), ("75 anni e oltre", 75, 200),
]
ETA_ND = "Non determinata"

GIORNI = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
MESI = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]

# Etichette di riserva, usate se la tabella tipologica non si scarica.
GEST_TAR_RISERVA = {"1": "Industria", "2": "Artigianato", "3": "Terziario",
                    "4": "Altre attività", "ND": "Non determinata"}
DEFINIZIONE_RISERVA = {"P": "Positivo", "N": "Negativo", "F": "Franchigia", "I": "In istruttoria"}
# Codici Belfiore dei 27 paesi UE: usati solo se la tabella LuogoNascita non è disponibile
UE_RISERVA = {c: "S" for c in ("Z102 Z103 Z104 Z149 Z211 Z156 Z107 Z144 Z109 Z110 Z112 Z115 Z116 "
                               "Z145 Z146 Z120 Z121 Z126 Z127 Z128 Z129 Z155 Z150 Z131 Z132 Z134").split()}
MODALITA = {"N": "OL – in occasione di lavoro", "S": "IT – in itinere"}
GENERE = {"M": "Maschi", "F": "Femmine"}
# Gestione assicurativa INAIL (campo Gestione): la banca dati statistica ragiona per queste
GESTIONE = {"I": "Industria e servizi", "A": "Agricoltura", "S": "Conto Stato"}
NAZ = ["ITA", "UE", "EUE", "ND"]
NAZ_LABEL = {"ITA": "ITA – Italia", "UE": "UE – Unione europea",
             "EUE": "EUE – Extra UE", "ND": "Non determinata"}

BASE = Path(__file__).resolve().parent
CACHE = BASE / "cache"
OUT = BASE.parent / "portale" / "data"

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "portale-infortuni/1.0 (uso statistico)"


# --------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------
def parse_risposta(testo: str):
    """L'API antepone '<?xml ...?>' al JSON: lo togliamo prima del parsing."""
    testo = re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", testo.lstrip("﻿"))
    return json.loads(testo) if testo.strip() else {}


def chiama_api(endpoint: str, regione: str, anno: int, mese: int, tentativi: int = 4):
    params = {"Regione": regione, "AnnoAccadimento": str(anno), "MeseAccadimento": f"{mese:02d}"}
    ultimo = None
    for i in range(tentativi):
        try:
            r = SESSION.get(API + endpoint, params=params, timeout=180)
            if r.status_code == 200:
                return parse_risposta(r.content.decode("utf-8", errors="replace"))
            ultimo = f"HTTP {r.status_code}"
        except (requests.RequestException, ValueError) as e:
            ultimo = str(e)
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"{regione} {anno}-{mese:02d}: {ultimo}")


def estrai_record(dati) -> list[dict]:
    if isinstance(dati, list):
        return dati
    if isinstance(dati, dict):
        if "Errore" in dati:
            raise ValueError(dati["Errore"])
        for v in dati.values():
            if isinstance(v, list):
                return v
    return []


def nome_regione_valido(endpoint: str, regione: str, anno: int, mese: int, memo: dict) -> str:
    if regione in memo:
        return memo[regione]
    errori = []
    for variante in REGIONI[regione]:
        try:
            estrai_record(chiama_api(endpoint, variante, anno, mese, tentativi=2))
            memo[regione] = variante
            return variante
        except Exception as e:  # noqa: BLE001
            errori.append(f"{variante!r}: {e}")
    raise RuntimeError(f"Nessun nome valido per {regione}: " + "; ".join(errori))


def scarica(dataset: str, anni: list[int], mesi: list[int], rinfresca: bool, paralleli: int) -> pd.DataFrame:
    endpoint = ENDPOINT[dataset]
    cartella = CACHE / dataset
    cartella.mkdir(parents=True, exist_ok=True)
    memo_file = CACHE / "regioni.json"
    memo = json.loads(memo_file.read_text(encoding="utf-8")) if memo_file.exists() else {}

    # Prima risolviamo i nomi delle regioni (una chiamata ciascuna).
    for reg in REGIONI:
        try:
            nome_regione_valido(endpoint, reg, anni[0], mesi[0], memo)
        except RuntimeError as e:
            print(f"  ! {e}", file=sys.stderr)
    memo_file.write_text(json.dumps(memo, ensure_ascii=False, indent=1), encoding="utf-8")

    oggi = dt.date.today()
    lavori = []
    for reg, nome_api in memo.items():
        for anno in anni:
            for mese in mesi:
                if (anno, mese) > (oggi.year, oggi.month):
                    continue  # mesi futuri: nessun dato
                f = cartella / f"{reg.replace(' ', '_').replace(chr(39), '')}_{anno}_{mese:02d}.json"
                if f.exists() and not rinfresca:
                    continue
                lavori.append((reg, nome_api, anno, mese, f))

    print(f"[{dataset}] {len(lavori)} chiamate da fare (il resto è già in cache)")
    falliti = []

    def esegui(job):
        reg, nome_api, anno, mese, f = job
        rec = estrai_record(chiama_api(endpoint, nome_api, anno, mese))
        f.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        return len(rec)

    with cf.ThreadPoolExecutor(max_workers=paralleli) as ex:
        futuri = {ex.submit(esegui, j): j for j in lavori}
        for i, fut in enumerate(cf.as_completed(futuri), 1):
            reg, _, anno, mese, _ = futuri[fut]
            try:
                n = fut.result()
                print(f"  {i}/{len(lavori)}  {reg:<22} {anno}-{mese:02d}  {n:>6} record")
            except Exception as e:  # noqa: BLE001
                falliti.append(f"{reg} {anno}-{mese:02d}: {e}")
                print(f"  {i}/{len(lavori)}  {reg:<22} {anno}-{mese:02d}  ERRORE {e}", file=sys.stderr)

    if falliti:
        print(f"\n[{dataset}] {len(falliti)} chiamate fallite: rilancia lo script per riprovarle.",
              file=sys.stderr)

    righe = []
    for reg in memo:
        for anno in anni:
            for mese in mesi:
                f = cartella / f"{reg.replace(' ', '_').replace(chr(39), '')}_{anno}_{mese:02d}.json"
                if f.exists():
                    for r in json.loads(f.read_text(encoding="utf-8")):
                        r["_regione"] = reg
                        righe.append(r)
    return pd.DataFrame(righe), falliti


# --------------------------------------------------------------------------
# In alternativa all'API: CSV già scaricati dal portale (anche dentro gli .zip)
# --------------------------------------------------------------------------
def regione_da_nome_file(nome_file: str, prefisso: str) -> str | None:
    """'DatiConCadenzaSemestraleInfortuniLombardia_csv (1).zip' -> 'LOMBARDIA'.
    Tollera suffissi come _csv, ' (1)', ' - Copia' aggiunti da browser o Windows."""
    resto = nome_file[len(prefisso):]
    compatto = re.sub(r"[^a-z]", "", resto.lower())
    for reg in sorted(REGIONI, key=len, reverse=True):
        chiave = re.sub(r"[^a-z]", "", reg.lower())
        if compatto.startswith(chiave):
            return reg
    return None


def leggi_csv(cartella: Path, dataset: str) -> tuple[pd.DataFrame, list]:
    import zipfile
    prefisso = ENDPOINT[dataset].lower()
    scelti: dict[str, Path] = {}
    for f in sorted(Path(cartella).iterdir()):
        nome = f.name.lower()
        if not nome.startswith(prefisso) or not nome.endswith((".csv", ".zip")):
            continue
        regione = regione_da_nome_file(f.name, prefisso)
        if regione is None:
            print(f"  ! {f.name}: regione non riconosciuta, file ignorato", file=sys.stderr)
            continue
        if regione in scelti:
            # stesso file scaricato due volte: teniamo il più recente
            vecchio = scelti[regione]
            tieni, scarta = (f, vecchio) if f.stat().st_mtime >= vecchio.stat().st_mtime else (vecchio, f)
            print(f"  ! {regione}: trovati due file, uso {tieni.name} e ignoro {scarta.name}", file=sys.stderr)
            scelti[regione] = tieni
        else:
            scelti[regione] = f

    parti = []
    for regione, f in scelti.items():
        if f.name.lower().endswith(".zip"):
            with zipfile.ZipFile(f) as z:
                for interno in z.namelist():
                    if interno.lower().endswith(".csv"):
                        parti.append(pd.read_csv(z.open(interno), sep=";", dtype=str,
                                                 keep_default_na=False).assign(_regione=regione))
        else:
            parti.append(pd.read_csv(f, sep=";", dtype=str, keep_default_na=False).assign(_regione=regione))
        print(f"  letto {f.name} → {regione}")

    if not parti:
        raise SystemExit(f"Nessun file {ENDPOINT[dataset]}*.csv/.zip trovato in {cartella}. "
                         f"Se hai solo l'altro dataset usa --solo.")
    mancanti = [r for r in REGIONI if r not in scelti]
    if mancanti:
        print(f"  ! regioni mancanti: {', '.join(mancanti)} — il totale Italia sarà incompleto", file=sys.stderr)
    df = pd.concat(parti, ignore_index=True)
    df = df.replace("", None)
    return df, ([f"File mancante: {r}" for r in mancanti])


# --------------------------------------------------------------------------
# Tabelle tipologiche
# --------------------------------------------------------------------------
def leggi_tipologica(nome: str) -> pd.DataFrame | None:
    f = CACHE / "tipologiche" / f"{nome}.csv"
    f.parent.mkdir(parents=True, exist_ok=True)
    if not f.exists():
        try:
            r = SESSION.get(TIPOLOGICHE.format(nome), timeout=60)
            r.raise_for_status()
            f.write_bytes(r.content)
        except requests.RequestException as e:
            print(f"  ! tabella {nome} non scaricata ({e}): uso etichette di riserva", file=sys.stderr)
            return None
    raw = f.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            testo = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sep = ";" if testo.splitlines()[0].count(";") >= testo.splitlines()[0].count(",") else ","
    return pd.read_csv(io.StringIO(testo), sep=sep, dtype=str, keep_default_na=False)


def colonna(df: pd.DataFrame, nome: str, ripiego: str | None = None) -> str | None:
    """Trova una colonna per nome (senza badare a maiuscole/spazi); altrimenti applica il ripiego."""
    norm = {c.strip().strip('"').lower(): c for c in df.columns}
    if nome.lower() in norm:
        return norm[nome.lower()]
    if ripiego == "prima":
        return df.columns[0]
    if ripiego == "descr":
        cand = [c for c in df.columns if c.strip().strip('"').lower().startswith("descr")]
        return cand[0] if cand else (df.columns[1] if len(df.columns) > 1 else None)
    return None


def mappa(df: pd.DataFrame | None, chiave: str, valore: str, ripiego_valore: str | None = "descr") -> dict:
    """Codice -> descrizione. Se i nomi di colonna non sono quelli attesi usa la prima colonna
    come codice e la prima colonna 'Descr…' come descrizione."""
    if df is None or df.empty:
        return {}
    k = colonna(df, chiave, "prima")
    v = colonna(df, valore, ripiego_valore)
    if k is None or v is None:
        print(f"  ! colonne {chiave}/{valore} non trovate (colonne presenti: {list(df.columns)})", file=sys.stderr)
        return {}
    return dict(zip(df[k].astype(str).str.strip(), df[v].astype(str).str.strip()))


def carica_tipologiche() -> dict:
    t = {}
    ateco = leggi_tipologica("SettoreAttivitaEconomica")
    t["ateco"] = mappa(ateco, "SettoreAttivitaEconomica", "DescrAteco")
    naz = leggi_tipologica("LuogoNascita")
    t["naz_ue"] = mappa(naz, "LuogoNascita", "FlagAppartenenzaUE", ripiego_valore=None)
    if not t["naz_ue"]:
        t["naz_ue_riserva"] = True
    t["gest_tar"] = {**GEST_TAR_RISERVA,
                     **mappa(leggi_tipologica("GestioneTariffaria"), "GestioneTariffaria", "DescrGestioneTariffaria")}
    t["definizione"] = {**DEFINIZIONE_RISERVA,
                        **mappa(leggi_tipologica("DefinizioneAmministrativa"),
                                "DefinizioneAmministrativa", "DescrDefinizioneAmministrativa")}
    print("Tabelle tipologiche caricate: " + ", ".join(
        f"{k} {len(v)} codici" for k, v in t.items() if isinstance(v, dict)))
    return t


def resoconto(df: pd.DataFrame, codice: str, tabella: dict, nome: str, ignora=("", "ND", "-1", "X")):
    """Stampa quanti codici del dataset sono stati trovati nella tabella tipologica."""
    c = df[codice].fillna("").astype(str).str.strip()
    c = c[~c.isin(ignora)]
    if c.empty:
        return
    trovati = c.isin(tabella.keys())
    mancanti = c[~trovati].value_counts().head(5)
    print(f"  decodifica {nome:<22} {trovati.mean():6.1%} dei record"
          + (f"   (codici non trovati più frequenti: {', '.join(mancanti.index)})" if len(mancanti) else ""))


# --------------------------------------------------------------------------
# Elaborazione
# --------------------------------------------------------------------------
def classe_eta(s: pd.Series) -> pd.Series:
    eta = pd.to_numeric(s, errors="coerce")
    out = pd.Series(ETA_ND, index=s.index)
    for nome, lo, hi in CLASSI_ETA:
        out[(eta >= lo) & (eta <= hi)] = nome
    return out


def prepara(df: pd.DataFrame, tip: dict, dataset: str) -> pd.DataFrame:
    df = df.copy()
    print(f"[{dataset}] controllo decodifiche con le tabelle tipologiche:")
    resoconto(df, "SettoreAttivitaEconomica", tip["ateco"], "Ateco")
    resoconto(df, "LuogoNascita", {**tip["naz_ue"], "ITAL": "S"}, "Luogo di nascita")
    resoconto(df, "GestioneTariffaria", tip["gest_tar"], "Gestione tariffaria")
    if dataset == "semestrale":
        resoconto(df, "DefinizioneAmministrativa", tip["definizione"], "Definizione amm.va")
    data = pd.to_datetime(df["DataAccadimento"], format="%d/%m/%Y", errors="coerce")
    df = df[data.notna()].copy()
    data = data[data.notna()]
    df["anno"] = data.dt.year
    df["mese"] = data.dt.month - 1
    df["giorno"] = data.dt.weekday
    df["eta"] = classe_eta(df["Eta"])
    df["genere"] = df["Genere"].map(GENERE).fillna("Non determinato")
    df["modalita"] = df["ModalitaAccadimento"].map(MODALITA).fillna("Non determinata")

    ln = df["LuogoNascita"].fillna("").str.strip().str.upper()
    if tip.get("naz_ue_riserva"):
        # senza tabella: UE dai codici Belfiore noti, ogni altro codice estero = Extra UE
        flag = ln.map(UE_RISERVA).fillna("N").where(ln != "", "")
    else:
        flag = ln.map(tip["naz_ue"]).fillna("")
    df["naz"] = "ND"
    df.loc[flag.str.upper().isin(["S", "SI", "1", "Y"]), "naz"] = "UE"
    df.loc[(flag != "") & ~flag.str.upper().isin(["S", "SI", "1", "Y"]), "naz"] = "EUE"
    df.loc[ln.isin(["ITAL", "ITALIA", "Z000"]), "naz"] = "ITA"
    df["naz"] = df["naz"].map(NAZ_LABEL)

    gt = df["GestioneTariffaria"].fillna("ND").str.strip()
    df["gest"] = gt.map(tip["gest_tar"]).fillna("Non determinata")

    at = df["SettoreAttivitaEconomica"].fillna("ND").str.strip().replace("", "ND")
    def etichetta_ateco(c):
        if c in ("ND", "X", "-1"):
            return "X Non determinato"
        d = tip["ateco"].get(c)
        return f"{c} {d}".strip() if d else c
    df["ateco"] = at.map(etichetta_ateco)

    df["gestione"] = df["Gestione"].fillna("").str.strip().map(GESTIONE).fillna("Non determinata")

    # Mortali DENUNCIATI = data di morte compilata (come la banca dati statistica INAIL, "Denunciati")
    df["mort_den"] = df["DataMorte"].notna() & (df["DataMorte"].astype(str).str.strip() != "")
    # Mortali ACCERTATI = esito mortale definito positivo (solo semestrale)
    df["mort_acc"] = False
    if dataset == "semestrale" and "DefinizioneAmministrativaEsitoMortale" in df.columns:
        em = df["DefinizioneAmministrativaEsitoMortale"].fillna("").astype(str).str.strip()
        positivi = {c for c, d in tip["definizione"].items() if d.upper().startswith("POSITIV")} or {"P"}
        df["mort_acc"] = em.isin(positivi)
        print(f"  mortali denunciati: {int(df['mort_den'].sum())}, di cui accertati: {int(df['mort_acc'].sum())} "
              f"(esito mortale: {dict(em[df['mort_den']].value_counts())})")
    else:
        print(f"  mortali denunciati: {int(df['mort_den'].sum())}")

    if dataset == "semestrale":
        d = df["DefinizioneAmministrativa"].fillna("").str.strip()
        df["esito"] = d.map(lambda c: tip["definizione"].get(c, c) or "Non definita")
        df["giorni_ind"] = pd.to_numeric(df.get("GiorniIndennizzati"), errors="coerce").fillna(0)
    else:
        df["giorni_ind"] = 0

    # Territori: una riga può appartenere a più territori (Italia ⊃ Lombardia ⊃ Brescia)
    parti = [df.assign(terr="Italia")]
    lomb = df[df["_regione"] == "LOMBARDIA"]
    parti.append(lomb.assign(terr="Lombardia"))
    prov = lomb["LuogoAccadimento"].fillna("").str.strip().str.zfill(3)
    for codice, nome in PROVINCE.items():
        parti.append(lomb[prov == codice].assign(terr=nome))
    return pd.concat(parti, ignore_index=True)


def cubo(df: pd.DataFrame, dims: list[str], diz: dict) -> dict:
    """Conteggi aggregati, con le dimensioni codificate come indici dei dizionari."""
    g = (df.groupby(dims, observed=True)
           .agg(n=("anno", "size"), md=("mort_den", "sum"), ma=("mort_acc", "sum"), gi=("giorni_ind", "sum"))
           .reset_index())
    col = {}
    for d in dims:
        if d in diz:
            idx = {v: i for i, v in enumerate(diz[d])}
            col[d] = g[d].map(idx).astype(int).tolist()
        else:
            col[d] = g[d].astype(int).tolist()
    col["n"] = g["n"].astype(int).tolist()
    col["md"] = g["md"].astype(int).tolist()
    if g["ma"].sum() > 0:
        col["ma"] = g["ma"].astype(int).tolist()
    col["gi"] = g["gi"].round().astype(int).tolist()
    return {"dims": dims, "righe": len(g), "col": col}


def ordina(valori, ordine=None):
    valori = list(dict.fromkeys(v for v in valori if pd.notna(v)))
    if ordine:
        return [v for v in ordine if v in valori] + sorted(v for v in valori if v not in ordine)
    return sorted(valori)


def esporta(df: pd.DataFrame, dataset: str, anni: list[int], falliti: list[str]) -> Path:
    df = df[df["anno"].isin(anni)]
    filtri = ["terr", "anno", "gestione", "genere", "modalita", "naz", "gest", "ateco"]
    if dataset == "semestrale":
        filtri.append("esito")

    diz = {
        "terr": TERRITORI,
        "gestione": ordina(df["gestione"], list(GESTIONE.values())),
        "genere": ordina(df["genere"], ["Maschi", "Femmine"]),
        "modalita": ordina(df["modalita"], list(MODALITA.values())),
        "naz": ordina(df["naz"], [NAZ_LABEL[k] for k in NAZ]),
        "gest": ordina(df["gest"], ["Industria", "Artigianato", "Terziario", "Altre attività"]),
        "ateco": ordina(df["ateco"]),
        "eta": [c[0] for c in CLASSI_ETA] + [ETA_ND],
    }
    if dataset == "semestrale":
        diz["esito"] = ordina(df["esito"])

    rilev = df["DataRilevazione"].dropna().astype(str)
    mesi_ultimo = int(df.loc[df["anno"] == max(anni), "mese"].max()) + 1 if len(df) else 0
    # Mensile: totali e grafici confrontano lo STESSO periodo (gen → ultimo mese disponibile).
    # Il cubo "mese" resta completo per mostrare l'andamento dell'anno precedente.
    stesso_periodo = df[df["mese"] < mesi_ultimo] if dataset == "mensile" else df
    out = {
        "meta": {
            "dataset": dataset,
            "rilevazione": rilev.mode().iat[0] if len(rilev) else None,
            "generato": dt.datetime.now().strftime("%d/%m/%Y %H:%M"),
            "anni": sorted(int(a) for a in df["anno"].unique()),
            "mesi_ultimo_anno": mesi_ultimo,
            "chiamate_fallite": falliti,
            "fonte": "INAIL Open Data – " + ENDPOINT[dataset],
            "demo": False,
        },
        "diz": {**diz, "giorno": GIORNI, "mese": MESI},
        "cubi": {
            "base": cubo(stesso_periodo, filtri, diz),
            "eta": cubo(stesso_periodo, filtri + ["eta"], diz),
            "giorno": cubo(stesso_periodo, filtri + ["giorno"], diz),
            "mese": cubo(df, filtri + ["mese"], diz),
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / f"{dataset}.json"
    f.write_text(json.dumps(out, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
    print(f"[{dataset}] scritto {f}  ({f.stat().st_size / 1e6:.1f} MB, "
          + ", ".join(f"{k}: {v['righe']} righe" for k, v in out["cubi"].items()) + ")")
    return f


# --------------------------------------------------------------------------
def main():
    oggi = dt.date.today()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--solo", choices=["semestrale", "mensile"])
    p.add_argument("--anni-semestrale", type=int, nargs="+",
                   help="default: i tre anni prima di quello corrente")
    p.add_argument("--anni-mensile", type=int, nargs="+",
                   help="default: anno corrente e precedente")
    p.add_argument("--rinfresca", action="store_true", help="ignora la cache e riscarica tutto")
    p.add_argument("--paralleli", type=int, default=4, help="chiamate contemporanee (default 4)")
    p.add_argument("--da-csv", metavar="CARTELLA", type=Path,
                   help="non usare l'API: leggi i CSV/ZIP già scaricati dal portale INAIL in questa cartella")
    a = p.parse_args()

    tip = carica_tipologiche()

    def dati(dataset, anni, mesi):
        if a.da_csv:
            print(f"[{dataset}] lettura dei file in {a.da_csv}")
            return leggi_csv(a.da_csv, dataset)
        return scarica(dataset, anni, mesi, a.rinfresca, a.paralleli)

    if a.solo in (None, "semestrale"):
        anni = a.anni_semestrale or [oggi.year - 3, oggi.year - 2, oggi.year - 1]
        raw, falliti = dati("semestrale", anni, list(range(1, 13)))
        esporta(prepara(raw, tip, "semestrale"), "semestrale", anni, falliti)

    if a.solo in (None, "mensile"):
        anni = a.anni_mensile or [oggi.year - 1, oggi.year]
        raw, falliti = dati("mensile", anni, list(range(1, 13)))
        esporta(prepara(raw, tip, "mensile"), "mensile", anni, falliti)


if __name__ == "__main__":
    main()
