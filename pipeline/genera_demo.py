#!/usr/bin/env python3
"""
Genera DATI DI ESEMPIO per provare il portale senza scaricare nulla.

Simula le risposte dell'API INAIL (compreso il prefisso <?xml ...?>) e fa
girare la stessa pipeline di scarica_inail.py. I numeri sono inventati:
servono solo a vedere grafici e filtri. Per i dati veri usa scarica_inail.py.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import scarica_inail as S  # noqa: E402

rng = np.random.default_rng(42)

# Denunce medie al mese per regione (ordine di grandezza plausibile)
VOLUME = {"LOMBARDIA": 8000, "VENETO": 5200, "EMILIA ROMAGNA": 5800, "PIEMONTE": 3700,
          "TOSCANA": 3600, "LAZIO": 3300, "CAMPANIA": 2000, "PUGLIA": 2100, "SICILIA": 1900}
ATECO = ["C 25", "C 24", "C 28", "C 10", "C 22", "F", "G 46", "G 47", "H 49", "H 52",
         "I 56", "N 81", "N 82", "Q 86", "Q 87", "M 71", "A 01", "ND"]
P_ATECO = np.array([8, 4, 5, 4, 3, 10, 6, 6, 5, 6, 6, 5, 4, 7, 4, 2, 3, 12], float)
P_ATECO /= P_ATECO.sum()
ATECO_GT = {"C": "1", "F": "2", "G": "3", "H": "3", "I": "3", "N": "3", "Q": "3", "M": "3", "A": "4"}
NAZIONI = ["ITAL", "ITAL", "ITAL", "ITAL", "ITAL", "ITAL", "Z129", "Z100", "Z330", "Z352", "Z210"]

TIP_FINTE = {
    "LuogoNascita": "LuogoNascita;DescrNazioneNascita;FlagAppartenenzaUE\nITAL;ITALIA;S\n"
                    "Z129;ROMANIA;S\nZ100;ALBANIA;N\nZ330;MAROCCO;N\nZ352;SENEGAL;N\nZ210;CINA;N\n",
    "GestioneTariffaria": "GestioneTariffaria;DescrGestioneTariffaria\n1;Industria\n2;Artigianato\n"
                          "3;Terziario\n4;Altre attività\nND;Non determinata\n",
    "DefinizioneAmministrativa": "DefinizioneAmministrativa;DescrDefinizioneAmministrativa\n"
                                 "P;Positivo\nN;Negativo\nI;In istruttoria\n",
    "SettoreAttivitaEconomica": "SettoreAttivitaEconomica;DescrAteco;CodAtecoLiv1;DescrAtecoLiv1\n"
        "C 25;FABBRICAZIONE DI PRODOTTI IN METALLO;C;ATTIVITA' MANIFATTURIERE\n"
        "C 24;METALLURGIA;C;ATTIVITA' MANIFATTURIERE\n"
        "C 28;FABBRICAZIONE DI MACCHINARI ED APPARECCHIATURE N.C.A.;C;ATTIVITA' MANIFATTURIERE\n"
        "C 10;INDUSTRIE ALIMENTARI;C;ATTIVITA' MANIFATTURIERE\n"
        "C 22;FABBRICAZIONE DI ARTICOLI IN GOMMA E MATERIE PLASTICHE;C;ATTIVITA' MANIFATTURIERE\n"
        "F;COSTRUZIONI;F;COSTRUZIONI\n"
        "G 46;COMMERCIO ALL'INGROSSO;G;COMMERCIO\nG 47;COMMERCIO AL DETTAGLIO;G;COMMERCIO\n"
        "H 49;TRASPORTO TERRESTRE;H;TRASPORTO E MAGAZZINAGGIO\n"
        "H 52;MAGAZZINAGGIO E ATTIVITA' DI SUPPORTO AI TRASPORTI;H;TRASPORTO E MAGAZZINAGGIO\n"
        "I 56;ATTIVITA' DEI SERVIZI DI RISTORAZIONE;I;ALLOGGIO E RISTORAZIONE\n"
        "N 81;ATTIVITA' DI SERVIZI PER EDIFICI E PAESAGGIO;N;NOLEGGIO E SERVIZI ALLE IMPRESE\n"
        "N 82;SERVIZI DI SUPPORTO ALLE IMPRESE;N;NOLEGGIO E SERVIZI ALLE IMPRESE\n"
        "Q 86;ASSISTENZA SANITARIA;Q;SANITA' E ASSISTENZA SOCIALE\n"
        "Q 87;SERVIZI DI ASSISTENZA SOCIALE RESIDENZIALE;Q;SANITA' E ASSISTENZA SOCIALE\n"
        "M 71;ATTIVITA' DEGLI STUDI DI ARCHITETTURA E D'INGEGNERIA;M;ATTIVITA' PROFESSIONALI\n"
        "A 01;COLTIVAZIONI AGRICOLE E PRODUZIONE DI PRODOTTI ANIMALI;A;AGRICOLTURA\n",
}


def record_finti(endpoint, regione, anno, mese):
    base = VOLUME.get(regione.replace("-", " "), 900 if regione != "ALTRO" else 60)
    trend = {2022: 1.15, 2023: 1.0, 2024: 0.98, 2025: 0.97, 2026: 0.95}.get(anno, 1)
    stag = [0.95, 1.0, 1.05, 1.0, 1.05, 1.05, 1.1, 0.7, 1.0, 1.05, 1.05, 0.9][mese - 1]
    sem = "Semestrale" in endpoint
    if not sem and anno == 2026 and mese > 7:
        return []  # come il vero mensile: ultima rilevazione a luglio
    n = rng.poisson(base * trend * stag / 4)  # ridotto per tenere leggera la demo
    eta = np.clip(rng.normal(44, 12, n).round().astype(int), 15, 80)
    ateco = rng.choice(ATECO, n, p=P_ATECO)
    p_f = np.where(np.char.startswith(ateco.astype(str), "Q"), 0.75, 0.25)
    genere = np.where(rng.random(n) < p_f, "F", "M")
    giorno = rng.integers(1, 29, n)
    prov = ({"LOMBARDIA": ["015", "016", "017", "012", "013", "019", "098", "108"],
             "MOLISE": ["070", "094"]}.get(regione, ["001"]))
    p_prov = [0.38, 0.14, 0.15, 0.09, 0.06, 0.06, 0.04, 0.08] if regione == "LOMBARDIA" else None
    out = []
    for i in range(n):
        a = ateco[i]
        r = {
            "DataRilevazione": "30/04/2026" if sem else "31/07/2026",
            "LuogoNascita": NAZIONI[rng.integers(len(NAZIONI))],
            "Regione": "03", "Genere": genere[i], "Gestione": "I",
            "IdentificativoCaso": str(rng.integers(1e7, 9e7)),
            "DataProtocollo": f"{min(giorno[i] + 3, 28):02d}/{mese:02d}/{anno}",
            "DataAccadimento": f"{giorno[i]:02d}/{mese:02d}/{anno}",
            "DataMorte": f"{giorno[i]:02d}/{mese:02d}/{anno}" if rng.random() < 0.0015 else None,
            "LuogoAccadimento": rng.choice(prov, p=p_prov),
            "IdentificativoInfortunato": str(rng.integers(1e6, 9e7)),
            "Eta": str(eta[i]),
            "ModalitaAccadimento": "S" if rng.random() < 0.18 else "N",
            "ConSenzaMezzoTrasporto": "N",
            "SettoreAttivitaEconomica": a,
            "GestioneTariffaria": ATECO_GT.get(a[0], "ND") if a != "ND" else "ND",
            "GrandeGruppoTariffario": "ND",
        }
        if sem:
            esito = rng.choice(["P", "N", "I"], p=[0.66, 0.31, 0.03])
            r.update({"DataDefinizione": r["DataProtocollo"], "DefinizioneAmministrativa": esito,
                      "GiorniIndennizzati": str(int(rng.gamma(2, 15))) if esito == "P" else "0",
                      "DefinizioneAmministrativaEsitoMortale": ("P" if rng.random() < 0.8 else "N") if r["DataMorte"] else None})
        out.append(r)
    return out


class RispostaFinta:
    def __init__(self, testo, status=200):
        self.status_code = status
        self.content = testo.encode("utf-8")

    def raise_for_status(self):
        pass


def get_finto(url, params=None, timeout=None):
    if url.endswith(".csv"):
        nome = url.rsplit("/", 1)[1][:-4]
        return RispostaFinta(TIP_FINTE.get(nome, "Codice;Descr\n"))
    endpoint = url.rsplit("/", 1)[1]
    reg = params["Regione"]
    # Come l'API vera: nomi composti accettati solo in una forma
    if reg in ("EMILIA-ROMAGNA", "EMILIAROMAGNA", "VALLE D AOSTA", "FRIULI-VENEZIA GIULIA"):
        return RispostaFinta('<?xml version="1.0" encoding="UTF-8"?>{"Errore": "Regione non valida."}')
    if len(params["MeseAccadimento"]) != 2:
        return RispostaFinta("Internal Server Error", 500)
    rec = record_finti(endpoint, reg, int(params["AnnoAccadimento"]), int(params["MeseAccadimento"]))
    corpo = json.dumps({endpoint: rec}, ensure_ascii=False)
    return RispostaFinta('<?xml version="1.0" encoding="UTF-8"?>' + corpo)


if __name__ == "__main__":
    import tempfile
    S.SESSION.get = get_finto
    S.CACHE = Path(tempfile.mkdtemp(prefix="inail_demo_"))
    sys.argv = [sys.argv[0], "--anni-semestrale", "2023", "2024", "2025",
                "--anni-mensile", "2025", "2026", "--paralleli", "1"]
    S.dt_oggi = None
    S.main()
    for nome in ("semestrale", "mensile"):
        f = S.OUT / f"{nome}.json"
        d = json.loads(f.read_text())
        d["meta"]["demo"] = True
        f.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
    print("Dati di esempio pronti.")
