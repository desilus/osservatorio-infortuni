"""
Malattie professionali – Open Data INAIL, dati semestrali per data di protocollo.

Si usa da scarica_inail.py:
    python scarica_inail.py --malattie ..\\csv_malattie\\DatiSemestraliMalattieProfessionaliDataProtItalia.csv

(oppure indicando la cartella che contiene quel file). Scrive portale/data/malattie.json
e un file per ogni altra regione e provincia in portale/data/malattie/.

Differenze rispetto agli infortuni:
- il territorio è la SEDE INAIL COMPETENTE (codice ISTAT della provincia); la regione si ricava
  dalla tabella delle province;
- si contano sia i CASI (righe) sia i LAVORATORI distinti (IdentificativoLavoratore) per anno;
- agente causale e settore correlato sono valorizzati solo per i casi riconosciuti (positivi);
- la malattia ha due codici ICD-10, denunciato e accertato: il portale permette di scegliere.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

import pandas as pd

import scarica_inail as S

TIP_MP = "https://dati.inail.it/opendata/downloads/datisemestralimalattieprofessionali/csv/{}.csv"
ND = "Non determinato"

INDENNIZZO = {"TE": "Inabilità temporanea", "CA": "Indennizzo in capitale", "RD": "Rendita diretta",
              "RS": "Rendita ai superstiti", "NE": "Nessun indennizzo"}
GRADI = ["Nessuna o non valutata", "1–5% (micro)", "6–15% (minima)", "16–25% (medio-inferiore)",
         "26–50% (medio-superiore)", "51–85% (macro)", "86–100% (quasi totale)"]
TAB = {"S": "Tabellata", "N": "Non tabellata"}
ASB = {"S": "Asbesto-correlata", "N": "Non asbesto-correlata"}

# Capitoli ICD-10, usati se la tabella TipologiaICDX non si scarica
CAPITOLI_ICD = [
    ("A00", "B99", "Malattie infettive e parassitarie"), ("C00", "D48", "Tumori"),
    ("D50", "D89", "Malattie del sangue e del sistema immunitario"), ("E00", "E90", "Malattie endocrine e metaboliche"),
    ("F00", "F99", "Disturbi psichici e comportamentali"), ("G00", "G99", "Malattie del sistema nervoso"),
    ("H00", "H59", "Malattie dell'occhio"), ("H60", "H95", "Malattie dell'orecchio"),
    ("I00", "I99", "Malattie del sistema circolatorio"), ("J00", "J99", "Malattie del sistema respiratorio"),
    ("K00", "K93", "Malattie dell'apparato digerente"), ("L00", "L99", "Malattie della cute"),
    ("M00", "M99", "Malattie del sistema osteomuscolare e del tessuto connettivo"),
    ("N00", "N99", "Malattie dell'apparato genitourinario"), ("R00", "R99", "Sintomi e segni non classificati"),
    ("S00", "T98", "Traumatismi e avvelenamenti"), ("Z00", "Z99", "Fattori che influenzano lo stato di salute"),
]
CATEGORIE_ICD = {
    "M51": "Altri disturbi dei dischi intervertebrali", "M50": "Disturbi dei dischi cervicali",
    "M75": "Lesioni della spalla", "M77": "Altre entesopatie", "M47": "Spondilosi", "M65": "Sinovite e tenosinovite",
    "M17": "Gonartrosi", "M18": "Artrosi della prima articolazione carpometacarpica", "M23": "Lesioni interne del ginocchio",
    "M70": "Disturbi dei tessuti molli da uso eccessivo", "M54": "Dorsalgia", "G56": "Mononeuropatie dell'arto superiore",
    "G55": "Compressioni delle radici e dei plessi nervosi", "H83": "Altre malattie dell'orecchio interno",
    "H90": "Ipoacusia trasmissiva e neurosensoriale", "H91": "Altre perdite dell'udito", "H72": "Perforazione del timpano",
    "C45": "Mesotelioma", "C34": "Tumore maligno dei bronchi e del polmone", "C67": "Tumore maligno della vescica",
    "C43": "Melanoma maligno della cute", "J44": "Broncopneumopatia cronica ostruttiva", "J45": "Asma",
    "J42": "Bronchite cronica", "J61": "Pneumoconiosi da amianto", "J92": "Placca pleurica", "I83": "Vene varicose",
}

# Provincia (codice ISTAT) -> regione, se la tabella Provincia.csv non si scarica
_r = lambda *c: [f"{x:03d}" for x in c]
PROV_REG_RISERVA = {p: reg for reg, codici in {
    "PIEMONTE": _r(1, 2, 3, 4, 5, 6, 96, 103), "VALLE D'AOSTA": _r(7), "LIGURIA": _r(8, 9, 10, 11),
    "LOMBARDIA": _r(12, 13, 14, 15, 16, 17, 18, 19, 20, 97, 98, 108), "TRENTINO ALTO ADIGE": _r(21, 22),
    "VENETO": _r(23, 24, 25, 26, 27, 28, 29), "FRIULI VENEZIA GIULIA": _r(30, 31, 32, 93),
    "EMILIA ROMAGNA": _r(33, 34, 35, 36, 37, 38, 39, 40, 99), "MARCHE": _r(41, 42, 43, 44, 109),
    "TOSCANA": _r(45, 46, 47, 48, 49, 50, 51, 52, 53, 100), "UMBRIA": _r(54, 55), "LAZIO": _r(56, 57, 58, 59, 60),
    "CAMPANIA": _r(61, 62, 63, 64, 65), "ABRUZZO": _r(66, 67, 68, 69), "MOLISE": _r(70, 94),
    "PUGLIA": _r(71, 72, 73, 74, 75, 110), "BASILICATA": _r(76, 77), "CALABRIA": _r(78, 79, 80, 101, 102),
    "SICILIA": _r(81, 82, 83, 84, 85, 86, 87, 88, 89), "SARDEGNA": _r(90, 91, 92, 95, 104, 105, 106, 107, 111),
}.items() for p in codici}


# --------------------------------------------------------------------------
# Tabelle tipologiche
# --------------------------------------------------------------------------
def tipologica_mp(nome: str) -> pd.DataFrame | None:
    """Come S.leggi_tipologica, ma dal percorso delle malattie professionali (cache separata)."""
    vecchio = S.TIPOLOGICHE
    try:
        S.TIPOLOGICHE = TIP_MP
        return S.leggi_tipologica_nome(nome, f"mp_{nome}")
    finally:
        S.TIPOLOGICHE = vecchio


def regione_key(descr: str) -> str | None:
    c = re.sub(r"[^a-z]", "", str(descr).lower())
    for k in sorted(S.REGIONI_NOMI, key=len, reverse=True):
        if c.startswith(re.sub(r"[^a-z]", "", k.lower())):
            return k
    return None


def norm_icd(c: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(c).upper())


def carica_tip_mp() -> dict:
    t = {}
    # ICD-10 -> classe e settore
    icd = tipologica_mp("TipologiaICDX")
    t["icd"] = {}
    if icd is not None and not icd.empty:
        k = S.colonna(icd, "ICDX", "prima")
        cl, dcl = S.colonna(icd, "ClasseICDX"), S.colonna(icd, "DescrClasseICDX")
        se, dse = S.colonna(icd, "SettoreICDX"), S.colonna(icd, "DescrSettoreICDX")
        for _, r in icd.iterrows():
            classe = str(r[dcl]).strip() if dcl else ""
            cod_cl = str(r[cl]).strip() if cl else ""
            if cod_cl and classe and not classe.startswith(cod_cl):
                classe = f"{cod_cl} {classe}"
            sett = str(r[dse]).strip() if dse else ""
            if classe or sett:
                t["icd"][norm_icd(r[k])] = (S.nome_proprio(classe) if classe else "", S.nome_proprio(sett) if sett else "")
    # agente causale -> gruppo e grande gruppo
    ag = tipologica_mp("AgenteCausale")
    t["agente"] = {}
    if ag is not None and not ag.empty:
        k = S.colonna(ag, "AgenteCausale", "prima")
        g, dg = S.colonna(ag, "Gruppo"), S.colonna(ag, "DescrGruppo")
        gg, dgg = S.colonna(ag, "GrandeGruppo"), S.colonna(ag, "DescrGrandeGruppo")
        da = S.colonna(ag, "DescrAgenteCausale")
        for _, r in ag.iterrows():
            dgr = str(r[dg]).strip() if dg else ""
            if not dgr or (g and dgr == str(r[g]).strip()):      # descrizione mancante o uguale al codice
                dgr = str(r[da]).strip() if da else str(r[k])
            dggr = str(r[dgg]).strip() if dgg else ""
            t["agente"][str(r[k]).strip()] = (S.nome_proprio(dgr), S.nome_proprio(dggr) if dggr else ND)
    t["settore"] = S.mappa(tipologica_mp("SettoreCorrelatoMalattia"), "SettoreCorrelatoMalattia", "DescrSettoreCorrelato")
    t["sub"] = S.mappa(tipologica_mp("SubSettoreCorrelatoMalattia"), "SubSettoreCorrelatoMalattia", "DescrSubSettoreCorrelato")
    # Definizione amministrativa, nazioni e province: INAIL usa per le malattie le stesse tabelle degli infortuni
    defin = S.leggi_tipologica("DefinizioneAmministrativa")
    t["definizione"] = {**S.DEFINIZIONE_RISERVA,
                        **S.mappa(defin, "DefinizioneAmministrativa", "DescrDefinizioneAmministrativa")}
    nz = S.leggi_tipologica("LuogoNascita")
    t["naz_ue"] = S.mappa(nz, "LuogoNascita", "FlagAppartenenzaUE", ripiego_valore=None)
    # province: nome e regione
    pr = S.leggi_tipologica("Provincia")
    t["prov_nome"], t["prov_reg"] = {}, {}
    if pr is not None and not pr.empty:
        k = S.colonna(pr, "Provincia", "prima")
        dn, dr = S.colonna(pr, "DescrProvincia"), S.colonna(pr, "DescrRegione")
        for _, r in pr.iterrows():
            cod = str(r[k]).strip().zfill(3)
            if dn and str(r[dn]).strip():
                t["prov_nome"][cod] = S.nome_proprio(str(r[dn]).strip())
            if dr and regione_key(r[dr]):
                t["prov_reg"][cod] = regione_key(r[dr])
    print("Tipologiche malattie: " + ", ".join(f"{k} {len(v)}" for k, v in t.items()))
    return t


# --------------------------------------------------------------------------
# Lettura e preparazione
# --------------------------------------------------------------------------
def trova_csv(percorso: Path, tipo: str = "prot", obbligatorio: bool = True) -> Path | None:
    """tipo 'prot' = per data di protocollo, 'dec' = per data di decesso (cercato nella stessa cartella)."""
    percorso = Path(percorso)
    if percorso.is_file():
        if tipo in percorso.name.lower():
            return percorso
        percorso = percorso.parent
    cand = sorted(p for p in percorso.iterdir()
                  if p.suffix.lower() == ".csv" and "malattie" in p.name.lower() and f"data{tipo}" in p.name.lower().replace("_", ""))
    if not cand:
        if obbligatorio:
            raise SystemExit(f"Nessun file DatiSemestraliMalattieProfessionaliData{tipo.title()}*.csv in {percorso}")
        return None
    return cand[-1]


def leggi(percorso: Path, tipo: str = "prot") -> pd.DataFrame | None:
    f = trova_csv(percorso, tipo, obbligatorio=(tipo == "prot"))
    if f is None:
        return None
    for enc in ("utf-8-sig", "cp1252"):
        try:
            df = pd.read_csv(f, sep=";", dtype=str, keep_default_na=False, encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    df.columns = [c.strip() for c in df.columns]
    print(f"[malattie] letto {f.name}: {len(df):,} righe".replace(",", "."))  # noqa
    return df


def classifica_icd(codici: pd.Series, tab: dict) -> tuple[pd.Series, pd.Series]:
    """codice ICD-10 -> (classe, settore). Prova il codice intero, poi 4 e 3 caratteri."""
    cache = {}

    def una(c):
        if c in cache:
            return cache[c]
        n = norm_icd(c)
        if not n or n == "ND":
            res = (ND, ND)
        else:
            res = None
            for lun in (len(n), 4, 3):
                if n[:lun] in tab and tab[n[:lun]][0]:
                    res = tab[n[:lun]]
                    break
            if res is None:     # riserva: categoria a 3 caratteri e capitolo ICD
                cat = n[:3]
                cap = next((d for a, b, d in CAPITOLI_ICD if a <= cat <= b), "Altro")
                res = (f"{cat} {CATEGORIE_ICD.get(cat, '')}".strip(), cap)
            res = (res[0] or ND, res[1] or ND)
        cache[c] = res
        return res

    coppie = codici.map(una)
    return coppie.map(lambda x: x[0]), coppie.map(lambda x: x[1])


def grado_classe(s: pd.Series) -> pd.Series:
    v = pd.to_numeric(s, errors="coerce").fillna(0)
    bins = [-1e9, 0, 5, 15, 25, 50, 85, 1e9]
    return pd.cut(v, bins=bins, labels=GRADI, right=True).astype(str)


def prepara(df: pd.DataFrame, tip: dict) -> pd.DataFrame:
    df = df.copy()
    data = pd.to_datetime(df["DataProtocollo"], format="%d/%m/%Y", errors="coerce")
    df = df[data.notna()].copy()
    data = data[data.notna()]
    df["anno"] = data.dt.year
    df["mese"] = data.dt.month - 1

    df["prov"] = df["SedeInailCompetente"].astype(str).str.strip().str.zfill(3)
    df["_regione"] = df["prov"].map(lambda p: tip["prov_reg"].get(p) or PROV_REG_RISERVA.get(p) or "ALTRO")
    senza = df.loc[df["_regione"] == "ALTRO", "prov"].value_counts()
    if len(senza):
        print(f"  ! {int(senza.sum())} casi con sede senza regione (codici: {', '.join(senza.index[:10])}): "
              "contano solo nel totale Italia", file=sys.stderr)

    df["genere"] = df["Genere"].map(S.GENERE).fillna("Non determinato")
    ln = df["LuogoNascita"].fillna("").str.strip().str.upper()
    flag = ln.map(tip["naz_ue"]).fillna("") if tip["naz_ue"] else ln.map(S.UE_RISERVA).fillna("N").where(ln != "", "")
    si = flag.str.upper().isin(["S", "SI", "1", "Y"])
    df["naz"] = "ND"
    df.loc[si, "naz"] = "UE"
    df.loc[(flag != "") & ~si, "naz"] = "EUE"
    df.loc[ln.isin(["ITAL", "ITALIA", "Z000"]), "naz"] = "ITA"
    df["naz"] = df["naz"].map(S.NAZ_LABEL)
    df["gestione"] = df["Gestione"].str.strip().map(S.GESTIONE).fillna("Non determinata")

    dec = lambda c: tip["definizione"].get(c, c) if c and c != "ND" else "Non definita"
    df["esito"] = df["DefinizioneAmministrativaCaso"].str.strip().map(dec)
    df["esito_lav"] = df["DefinizioneAmministrativaLavoratore"].str.strip().map(dec)
    df["tab"] = df["QualificazioneLegge"].str.strip().map(TAB).fillna(ND)
    df["asb"] = df["MalattiaAsbestoCorrelata"].str.strip().map(ASB).fillna(ND)

    df["icd_d"], df["icdset_d"] = classifica_icd(df["ICD10denunciato"], tip["icd"])
    df["icd_a"], df["icdset_a"] = classifica_icd(df["ICD10accertato"], tip["icd"])

    ag = df["AgenteCausale"].str.strip()
    df["agente"] = ag.map(lambda c: tip["agente"].get(c, (f"Agente {c}", ND))[0] if c and c != "ND" else ND)
    df["agente_gg"] = ag.map(lambda c: tip["agente"].get(c, (None, ND))[1] if c and c != "ND" else ND)
    se = df["SettoreCorrelatoMalattia"].str.strip()
    df["sett"] = se.map(lambda c: S.nome_proprio(tip["settore"].get(c, f"Settore {c}")) if c and c != "ND" else ND)
    su = df["SubSettoreCorrelatoMalattia"].str.strip()
    df["sub"] = su.map(lambda c: S.nome_proprio(tip["sub"].get(c, f"Sottosettore {c}")) if c and c != "ND" else ND)

    df["indennizzo"] = df["Indennizzo"].str.strip().map(INDENNIZZO).fillna(ND)
    df["grado"] = grado_classe(df["GradoMenomazioneCaso"])
    df["mort_den"] = df["DataMorte"].astype(str).str.strip() != ""
    df["mort_acc"] = df["DefinizioneAmministrativaEsitoMortale"].str.strip() == "P"
    df["giorni_ind"] = pd.to_numeric(df["GiorniIndennizzati"], errors="coerce").fillna(0)
    df["lav"] = df["IdentificativoLavoratore"].astype(str)

    # controllo decodifiche
    print("[malattie] controllo decodifiche:")
    for nome, col in (("ICD denunciato", "icd_d"), ("Agente causale", "agente"), ("Settore correlato", "sett")):
        v = df[col]
        noti = v[v != ND]
        print(f"  {nome:<20} {len(noti) / max(len(v), 1):6.1%} dei casi con un valore"
              + (f"   (senza tabella: {', '.join(noti[noti.str.match(r'^(Agente|Settore|Sottosettore) ')].unique()[:5])})"
                 if noti.str.match(r"^(Agente|Settore|Sottosettore) ").any() else ""))
    print(f"  mortali: {int(df['mort_den'].sum())} con data di morte, {int(df['mort_acc'].sum())} accertati")

    parti = [df.assign(terr="Italia")]
    lomb = df[df["_regione"] == "LOMBARDIA"]
    parti.append(lomb.assign(terr="Lombardia"))
    for codice, nome in S.PROVINCE.items():
        parti.append(lomb[lomb["prov"] == codice].assign(terr=nome))
    return pd.concat(parti, ignore_index=True)


PREF_DEC = "datisemestralimalattieprofessionalidatadec"


def leggi_decessi(percorso: Path) -> pd.DataFrame | None:
    """CSV 'data decesso' scaricati dal portale INAIL (uno per regione, ed eventualmente quello dell'Italia).
    La regione si ricava dal nome del file. Il file Italia, se c'è, serve solo come controllo dei totali
    (o come unica fonte, senza regione, se mancano i regionali)."""
    cartella = Path(percorso)
    cartella = cartella.parent if cartella.is_file() else cartella
    parti, italia, scelti = [], None, {}
    for f in sorted(cartella.iterdir()):
        nome = f.name.lower()
        if f.suffix.lower() != ".csv" or not nome.startswith(PREF_DEC):
            continue
        reg = S.regione_da_nome_file(f.name, PREF_DEC)
        if reg is None and "italia" in nome:
            italia = f
            continue
        if reg is None:
            print(f"  ! {f.name}: regione non riconosciuta, file ignorato", file=sys.stderr)
            continue
        if reg in scelti:      # stessa regione scaricata due volte: tengo il più recente
            vecchio = scelti[reg]
            tieni = f if f.stat().st_mtime >= vecchio.stat().st_mtime else vecchio
            print(f"  ! decessi {reg}: due file, uso {tieni.name}", file=sys.stderr)
            scelti[reg] = tieni
        else:
            scelti[reg] = f

    def leggi_csv(f):
        for enc in ("utf-8-sig", "cp1252"):
            try:
                return pd.read_csv(f, sep=";", dtype=str, keep_default_na=False, encoding=enc)
            except UnicodeDecodeError:
                continue

    for reg, f in scelti.items():
        parti.append(leggi_csv(f).assign(_regione=reg))
    tot_it = len(leggi_csv(italia)) if italia else None
    if parti:
        dd = pd.concat(parti, ignore_index=True)
        mancanti = [r for r in S.REGIONI_NOMI if r not in scelti]
        print(f"[malattie] decessi: {len(scelti)} file regionali, {len(dd)} righe"
              + (f" (file Italia: {tot_it} righe)" if tot_it is not None else ""))
        if mancanti:
            print(f"  ! decessi: mancano i file di {', '.join(mancanti)} — il totale Italia sarà incompleto",
                  file=sys.stderr)
        elif tot_it is not None and tot_it != len(dd):
            print(f"  ! decessi: la somma delle regioni ({len(dd)}) è diversa dal file Italia ({tot_it})",
                  file=sys.stderr)
        return dd
    if italia:
        print(f"[malattie] decessi: solo il file Italia ({tot_it} righe), senza dettaglio per regione")
        return leggi_csv(italia)
    return None


ETA_MORTE = ["Meno di 60 anni", "60–69 anni", "70–79 anni", "80–89 anni", "90 anni e oltre", "Non determinata"]
SIL = {"S": "Silicosi o asbestosi", "N": "Altre malattie"}


def prepara_decessi(dd: pd.DataFrame, tip: dict) -> pd.DataFrame:
    """File per data di decesso: una riga per lavoratore morto per malattia professionale riconosciuta.
    Non ha il territorio: si usa solo per l'Italia."""
    dd = dd.copy()
    data = pd.to_datetime(dd["DataMorte"], format="%d/%m/%Y", errors="coerce")
    dd = dd[data.notna()].copy()
    dd["anno"] = data[data.notna()].dt.year
    dd["genere"] = dd["Genere"].map(S.GENERE).fillna("Non determinato")
    ln = dd["LuogoNascita"].fillna("").str.strip().str.upper()
    flag = ln.map(tip["naz_ue"]).fillna("") if tip["naz_ue"] else ln.map(S.UE_RISERVA).fillna("N").where(ln != "", "")
    si = flag.str.upper().isin(["S", "SI", "1", "Y"])
    dd["naz"] = "ND"
    dd.loc[si, "naz"] = "UE"
    dd.loc[(flag != "") & ~si, "naz"] = "EUE"
    dd.loc[ln.isin(["ITAL", "ITALIA", "Z000"]), "naz"] = "ITA"
    dd["naz"] = dd["naz"].map(S.NAZ_LABEL)
    dd["gestione"] = dd["Gestione"].str.strip().map(S.GESTIONE).fillna("Non determinata")
    dd["sil"] = dd["MalattiaSilicosiAsbestosi"].str.strip().map(SIL).fillna(ND)
    eta = pd.to_numeric(dd["EtaMorte"], errors="coerce")
    dd["etam"] = pd.cut(eta, [-1, 59, 69, 79, 89, 200], labels=ETA_MORTE[:5]).astype(str).replace("nan", ETA_MORTE[5])
    dd["mort_den"] = False
    dd["mort_acc"] = False
    dd["giorni_ind"] = 0
    if "_regione" not in dd.columns:
        dd["_regione"] = None
    print(f"[malattie] decessi per anno di morte: " +
          ", ".join(f"{a}: {n}" for a, n in dd.groupby("anno").size().items()) +
          ("" if dd["_regione"].notna().all() else "  (senza regione: solo Italia)"))
    parti = [dd.assign(terr="Italia")]
    if dd["_regione"].notna().all():
        parti.append(dd[dd["_regione"] == "LOMBARDIA"].assign(terr="Lombardia"))
    return pd.concat(parti, ignore_index=True)


# --------------------------------------------------------------------------
# Cubi
# --------------------------------------------------------------------------
FILTRI = ["terr", "anno", "gestione", "genere", "naz", "esito", "tab", "asb"]
DIMS_DEC = ["terr", "anno", "gestione", "genere", "naz", "sil", "etam"]
FILTRI_LAV = ["terr", "anno", "gestione", "genere", "naz", "esito"]


def specifiche(df: pd.DataFrame) -> dict:
    """nome cubo -> (dataframe, dimensioni, tipo di misura)."""
    return {
        "base": (df, FILTRI, "casi"),
        "mese": (df, FILTRI + ["mese"], "casi"),
        "icd_d": (df.assign(icd=df["icd_d"]), FILTRI + ["icd"], "casi"),
        "icd_a": (df.assign(icd=df["icd_a"]), FILTRI + ["icd"], "casi"),
        "agente": (df, FILTRI + ["agente"], "casi"),
        "sub": (df, FILTRI + ["sub"], "casi"),
        "indennizzo": (df, FILTRI + ["indennizzo"], "casi"),
        "grado": (df, FILTRI + ["grado"], "casi"),
        "lav": (df.assign(esito=df["esito_lav"]), FILTRI_LAV, "lavoratori"),
    }


def raggruppa(df: pd.DataFrame, chiavi: list[str], tipo: str) -> pd.DataFrame:
    g = df.groupby(chiavi, observed=True)
    if tipo == "lavoratori":
        out = g.agg(n=("lav", "nunique")).reset_index()
        out["md"] = 0
        out["ma"] = 0
        out["gi"] = 0
        return out
    return g.agg(n=("anno", "size"), md=("mort_den", "sum"), ma=("mort_acc", "sum"),
                 gi=("giorni_ind", "sum")).reset_index()


def codifica(g: pd.DataFrame, dims: list[str], diz: dict, terr_zero=False) -> dict:
    col = {}
    for d in dims:
        if terr_zero and d == "terr":
            col[d] = [0] * len(g)
        elif d in diz and d != "mese":
            idx = g[d].map({v: i for i, v in enumerate(diz[d])})
            if idx.isna().any():
                raise ValueError(f"valori di '{d}' non previsti: {sorted(g.loc[idx.isna(), d].unique())[:5]}")
            col[d] = idx.astype(int).tolist()
        else:
            col[d] = g[d].astype(int).tolist()
    for m in ("n", "md", "ma"):
        col[m] = g[m].astype(int).tolist()
    col["gi"] = g["gi"].round().astype(int).tolist()
    return {"dims": dims, "righe": len(g), "col": col}


def esporta(df: pd.DataFrame, anni: list[int], tip: dict, dec: pd.DataFrame | None = None) -> Path:
    df = df[df["anno"].isin(anni)]
    if dec is not None:
        dec = dec[dec["anno"].isin(anni)]
    it = df[df["terr"] == "Italia"]
    tutti = pd.concat([it, dec]) if dec is not None else it
    o = lambda col, primo=(), base=None: S.ordina(
        pd.concat([(tutti if base is None else base)[c] for c in ([col] if isinstance(col, str) else col)]).dropna(),
        list(primo))
    diz = {
        "terr": S.TERRITORI,
        "gestione": o("gestione", S.GESTIONE.values()),
        "genere": o("genere", ["Maschi", "Femmine"]),
        "naz": o("naz", [S.NAZ_LABEL[k] for k in S.NAZ]),
        "sil": list(SIL.values()) + [ND],
        "etam": ETA_MORTE,
        "esito": o(["esito", "esito_lav"], ["Positivo", "Negativo", "In istruttoria"]),
        "tab": o("tab", TAB.values()),
        "asb": o("asb", ASB.values()),
        "icd": o(["icd_d", "icd_a"]),
        "agente": o("agente"),
        "sub": o("sub"),
        "indennizzo": o("indennizzo", INDENNIZZO.values()),
        "grado": [g for g in GRADI if g in set(it["grado"])],
        "mese": S.MESI,
    }
    # gerarchie: classe ICD -> settore ICD, agente -> grande gruppo, sottosettore -> settore
    def gerarchia(figlio_cols, padre_cols, chiave_diz):
        coppie = pd.concat([it[[f, p]].set_axis(["f", "p"], axis=1) for f, p in zip(figlio_cols, padre_cols)])
        padre_di = coppie.groupby("f")["p"].agg(lambda s: s.mode().iat[0])
        padri = S.ordina(padre_di.values)
        return padri, [padri.index(padre_di.get(v, padri[0])) for v in diz[chiave_diz]]
    diz["icd_sett"], diz["icd_map"] = gerarchia(["icd_d", "icd_a"], ["icdset_d", "icdset_a"], "icd")
    diz["agente_gg"], diz["agente_map"] = gerarchia(["agente"], ["agente_gg"], "agente")
    diz["sett"], diz["sub_map"] = gerarchia(["sub"], ["sett"], "sub")

    cubi = {nome: codifica(raggruppa(d, dims, tipo), dims, diz) for nome, (d, dims, tipo) in specifiche(df).items()}
    if dec is not None and len(dec):
        cubi["dec"] = codifica(raggruppa(dec, DIMS_DEC, "casi"), DIMS_DEC, diz)
    rilev = it["DataRilevazione"].astype(str)
    out = {
        "meta": {
            "dataset": "malattie", "anni": sorted(int(a) for a in it["anno"].unique()),
            "anni_dec": sorted(int(a) for a in dec["anno"].unique()) if dec is not None else [],
            "dec_regioni": bool(dec is not None and dec["_regione"].notna().all()),
            "rilevazione": rilev.mode().iat[0] if len(rilev) else None,
            "generato": dt.datetime.now().strftime("%d/%m/%Y %H:%M"), "mesi_ultimo_anno": 12,
            "chiamate_fallite": [], "demo": False,
            "fonte": "INAIL Open Data – Malattie professionali, dati semestrali per data di protocollo",
        },
        "diz": diz,
        "cubi": cubi,
    }
    dec_it = dec[dec["terr"] == "Italia"] if dec is not None and dec["_regione"].notna().all() else None
    out["meta"]["territori"] = territori(it, anni, diz, tip, dec_it)
    S.OUT.mkdir(parents=True, exist_ok=True)
    f = S.OUT / "malattie.json"
    f.write_text(json.dumps(out, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
    print(f"[malattie] scritto {f}  ({f.stat().st_size / 1e6:.1f} MB)")
    num = lambda x: f"{x:,}".replace(",", ".")
    print("[malattie] totali Italia:  " + "   ".join(
        f"{a}: {num(int((it['anno'] == a).sum()))} casi, {num(it.loc[it['anno'] == a, 'lav'].nunique())} lavoratori"
        for a in sorted(it["anno"].unique())))
    return f


def territori(it: pd.DataFrame, anni, diz: dict, tip: dict, dec: pd.DataFrame | None = None) -> dict:
    """Un file per ogni altra regione e provincia (sede INAIL), come per gli infortuni."""
    cartella = S.OUT / "malattie"
    cartella.mkdir(parents=True, exist_ok=True)
    for vecchio in cartella.glob("*.json"):
        vecchio.unlink()
    spec = specifiche(it)

    def per_chiave(chiave):
        res = {}
        for nome, (d, dims, tipo) in spec.items():
            altri = [x for x in dims if x != "terr"]
            g = raggruppa(d, [chiave] + altri, tipo)
            for k, gk in g.groupby(chiave, sort=False):
                res.setdefault(k, {})[nome] = codifica(gk.assign(terr=0), dims, diz, terr_zero=True)
        return res

    def scrivi(nome_file, cubi):
        (cartella / nome_file).write_text(json.dumps({"cubi": cubi}, ensure_ascii=True, separators=(",", ":")),
                                          encoding="utf-8")

    indice = {"regioni": [], "province": []}
    per_reg = per_chiave("_regione")
    if dec is not None:      # i decessi hanno solo la regione: vanno nei file delle regioni
        g = raggruppa(dec, ["_regione"] + [x for x in DIMS_DEC if x != "terr"], "casi")
        for k, gk in g.groupby("_regione", sort=False):
            per_reg.setdefault(k, {})["dec"] = codifica(gk.assign(terr=0), DIMS_DEC, diz, terr_zero=True)
    for reg, cubi in sorted(per_reg.items()):
        if reg not in S.REGIONI_NOMI:
            continue
        nome = S.REGIONI_NOMI[reg]
        voce = {"nome": nome, "codice": reg}
        if nome in S.TERRITORI:
            voce["rif"] = S.TERRITORI.index(nome)
        else:
            voce["file"] = f"malattie/regione-{S.slug(nome)}.json"
            scrivi(f"regione-{S.slug(nome)}.json", cubi)
        indice["regioni"].append(voce)
    reg_di = it.groupby("prov")["_regione"].agg(lambda s: s.mode().iat[0])
    for cod, cubi in sorted(per_chiave("prov").items()):
        nome = tip["prov_nome"].get(cod) or S.PROVINCE_RISERVA.get(cod)
        reg = reg_di.get(cod)
        if not nome or reg not in S.REGIONI_NOMI:
            continue
        voce = {"nome": nome, "codice": cod, "regione": S.REGIONI_NOMI[reg]}
        if cod in S.PROVINCE:
            voce["rif"] = S.TERRITORI.index(S.PROVINCE[cod])
        else:
            voce["file"] = f"malattie/provincia-{cod}.json"
            scrivi(f"provincia-{cod}.json", cubi)
        indice["province"].append(voce)
    indice["province"].sort(key=lambda v: (v["regione"], v["nome"]))
    peso = sum(f.stat().st_size for f in cartella.glob("*.json")) / 1e6
    print(f"[malattie] territori: {len(indice['regioni'])} regioni, {len(indice['province'])} province "
          f"({peso:.1f} MB in {cartella})")
    return indice


def esegui(percorso: Path, anni: list[int] | None = None) -> Path:
    tip = carica_tip_mp()
    df = prepara(leggi(percorso), tip)
    disponibili = sorted(int(a) for a in df["anno"].unique())
    anni = anni or disponibili[-3:]
    print(f"[malattie] anni di protocollo nel file: {disponibili}; uso: {anni}")
    # decessi: CSV "data decesso" per regione (o solo Italia) nella stessa cartella
    dd = leggi_decessi(percorso)
    if dd is None:
        print("  ! nessun file DatiSemestraliMalattieProfessionaliDataDec*.csv nella cartella: "
              "la sezione decessi resterà vuota", file=sys.stderr)
    dec = prepara_decessi(dd, tip) if dd is not None else None
    return esporta(df, anni, tip, dec)
