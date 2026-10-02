# Osservatorio infortuni INAIL

Portale con due pagine, **Semestrale** (casi definiti, ultimo triennio) e **Mensile** (denunce dell'anno in corso
contro lo stesso periodo dell'anno prima). Confronta Italia, Lombardia, provincia di Brescia e provincia di Bergamo
con filtri incrociati: genere, in itinere / in occasione di lavoro, nazionalità, gestione tariffaria, Ateco
e, nel semestrale, esito della definizione.

```
pipeline/scarica_inail.py   scarica i dati dalle Open API INAIL e li prepara per il portale
pipeline/genera_demo.py     crea dati di esempio, senza scaricare nulla
portale/index.html          il portale
portale/data/*.json         i dati letti dal portale (scritti dallo script)
.github/workflows/          aggiornamento automatico mensile (facoltativo)
```

## 1. Scaricare i dati veri

Serve Python 3.9 o successivo.

```
pip install pandas requests
cd pipeline
python scarica_inail.py
```

Lo script:
- scarica le tabelle tipologiche (Ateco, nazioni, gestione tariffaria, definizione amministrativa);
- chiama l'API per ogni regione e ogni mese: circa 750 chiamate per il semestrale e 450 per il mensile;
- toglie il prefisso `<?xml …?>` che l'API mette davanti al JSON;
- decodifica i codici;
- aggrega i dati per i quattro territori;
- scrive `portale/data/semestrale.json` e `portale/data/mensile.json`.

La prima volta ci vuole un po'. Le risposte restano salvate in `pipeline/cache`: se lo script si interrompe, rilancialo
e riparte da dove era arrivato. Alla pubblicazione successiva di INAIL usa `--rinfresca` per riscaricare tutto.

Opzioni utili:

```
python scarica_inail.py --solo mensile
python scarica_inail.py --anni-semestrale 2023 2024 2025     # default: i tre anni prima di quello corrente
python scarica_inail.py --paralleli 2                          # meno chiamate contemporanee se il server rallenta
```

A fine esecuzione lo script segnala le chiamate fallite. Anche il portale lo segnala in alto a destra,
così sai se i numeri sono incompleti.

### In alternativa: partire dai CSV che scarichi già

Se l'API non risponde, scarica dal portale INAIL i file delle regioni (gli .zip vanno bene così come sono)
e mettili tutti in una cartella, ad esempio `csv_inail`. Poi:

```
python scarica_inail.py --da-csv ../csv_inail
```

Lo script riconosce da solo semestrali e mensili e la regione dal nome del file
(`DatiConCadenzaSemestraleInfortuniLombardia_csv.zip` diventa LOMBARDIA).
Per avere il dato Italia servono i file di tutte le regioni, compresa "Altro".

### Il controllo delle decodifiche

All'inizio lo script scarica le tabelle tipologiche INAIL e stampa quanti record riesce a decodificare:

```
  decodifica Ateco                   99.8% dei record
  decodifica Luogo di nascita       100.0% dei record
```

Se una percentuale è bassa, lo script elenca i codici non trovati: è il segnale che una tabella
non si è scaricata o è cambiata. Le tabelle restano in `pipeline/cache/tipologiche`.

## 2. Vedere il portale sul tuo computer

Il portale legge i file JSON, quindi va aperto tramite un piccolo server e non con doppio clic:

```
cd portale
python -m http.server 8000
```

Poi apri http://localhost:8000 nel browser.

## 3. Metterlo online gratis e aggiornarlo da solo (GitHub)

1. Crea un repository su GitHub e carica questa cartella.
2. In *Settings → Pages* scegli *Deploy from a branch*, ramo `main`, cartella `/` (root).
   Il portale sarà su `https://<utente>.github.io/<repository>/portale/`.
3. Il file `.github/workflows/aggiorna-dati.yml` esegue lo script il 5 di ogni mese e salva i nuovi dati.
   In *Settings → Actions → General* abilita *Read and write permissions*.
   Puoi anche lanciarlo a mano da *Actions → Aggiorna dati INAIL → Run workflow*.

## Come leggere i dati

- **Territori.** Italia comprende tutte le regioni, compresa la voce "Altro" di INAIL.
  Brescia e Bergamo sono individuate dal luogo di accadimento (codici ISTAT 017 e 016).
- **Mensile.** Totali, età, Ateco e giorni della settimana confrontano lo stesso periodo:
  se il 2026 arriva a luglio, anche il 2025 si ferma a luglio. Il grafico per mese mostra invece l'anno precedente intero.
- **Esito mortale.** Nel semestrale contano i casi mortali *accertati* da INAIL
  (campo DefinizioneAmministrativaEsitoMortale = positivo). Nel mensile, dove l'accertamento non c'è ancora,
  contano i casi con data di morte valorizzata. Il filtro Tipologia M mostra solo questi casi.
- **Dati mancanti nelle Open API.** Ora dell'evento e dimensione aziendale non sono presenti.
  Il giorno della settimana è ricavato dalla data di accadimento.

Fonte: INAIL Open Data, licenza IODL 2.0.
