# Osservatorio infortuni e malattie professionali INAIL

Portale web che sostituisce i report Power BI sui dati aperti INAIL. Confronta **Italia, Lombardia, provincia di Brescia
e provincia di Bergamo**, più una regione o provincia a scelta, con filtri incrociati.

Il portale ha quattro schede:

| Scheda | Cosa mostra | Da dove vengono i dati |
|---|---|---|
| **Semestrale · denunce ed esiti** | Denunce di infortunio degli ultimi tre anni completi, con l'esito della definizione | CSV semestrali Open Data INAIL, uno per regione |
| **Mensile · denunce** | Denunce dell'anno in corso contro lo stesso periodo dell'anno prima | CSV mensili Open Data INAIL (o Open API) |
| **Orari · Brescia** | Infortuni accertati positivi per ora e giorno della settimana, provincia di Brescia | Excel della banca dati statistica INAIL |
| **Malattie professionali** | Malattie denunciate per anno di protocollo, casi e lavoratori, decessi | CSV Open Data INAIL delle malattie professionali |

In ogni scheda:
- il pulsante **? Info** apre una legenda che spiega misure e filtri;
- il pulsante **⤓ PDF** crea un report della pagina con i filtri attivi.

## Struttura della cartella

```
osservatorio-infortuni/
├─ pipeline/
│  ├─ scarica_inail.py     script principale: legge i dati e scrive i file per il portale
│  ├─ malattie.py          parte dello script dedicata alle malattie professionali
│  ├─ genera_demo.py       crea dati inventati per provare il portale
│  └─ cache/               tabelle tipologiche scaricate (si ricrea da sola)
├─ portale/
│  ├─ index.html           il portale
│  └─ data/                file JSON letti dal portale (scritti dallo script)
│     ├─ semestrale.json, mensile.json, orari.json, malattie.json
│     └─ semestrale/, mensile/, malattie/   un file per ogni altra regione e provincia
├─ csv_inail/              CSV/ZIP infortuni scaricati da INAIL        (anche su GitHub)
├─ csv_malattie/           CSV malattie professionali scaricati da INAIL (anche su GitHub)
├─ ora_brescia/            Excel ora e giorno della banca dati          (anche su GitHub)
└─ .venv/                  ambiente Python                              (solo in locale, non su GitHub)
```

Su GitHub vanno il codice, i JSON in `portale/data`, che bastano per far funzionare il sito, e le tre cartelle dei dati grezzi,
così chi clona il repository può rigenerare tutto. Restano fuori, con `.gitignore`, solo il venv e la cache dello script.
GitHub rifiuta i file oltre 100 MB: per gli infortuni conviene tenere gli `.zip` invece dei `.csv` estratti.

---

## 1. Prima installazione (una volta sola)

Serve Python 3.9 o successivo. Da PowerShell, nella cartella del progetto:

```
cd C:\Users\matteo.anselmi\Documents\osservatorio-infortuni
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install pandas requests openpyxl python-calamine
```

Se PowerShell blocca `Activate.ps1`, lancia una volta `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

Le tre cartelle per i dati grezzi (`csv_inail`, `csv_malattie`, `ora_brescia`) arrivano con il repository; se mancano, creale accanto a `pipeline`.

## 2. Procurarsi i dati grezzi

**Infortuni (cartella `csv_inail`).**
Dal portale Open Data INAIL scarica il dataset semestrale degli infortuni di **tutte** le regioni, compresa la voce "Altro":
il totale Italia è la loro somma. Vanno bene sia gli `.zip` sia i `.csv`.
Lo script riconosce la regione dal nome del file (`DatiConCadenzaSemestraleInfortuniLombardia_csv.zip` diventa LOMBARDIA)
e, se un file è scaricato due volte (`… (1).csv`), tiene il più recente.
Se scarichi anche i file mensili (`DatiConCadenzaMensileInfortuni…`), mettili nella stessa cartella.

**Malattie professionali (cartella `csv_malattie`).**
- `DatiSemestraliMalattieProfessionaliDataProtItalia.csv`: il file per data di protocollo dell'Italia. È obbligatorio.
- I file per data di decesso, uno per regione (`DatiSemestraliMalattieProfessionaliDataDecLombardia.csv`, …),
  più facoltativamente quello dell'Italia, che serve da controllo. Senza file regionali la sezione decessi è solo nazionale.

**Orari Brescia (cartella `ora_brescia`).**
Excel esportati dalla banca dati statistica INAIL: Infortuni → Definiti → Industria e Servizi →
Caratteristiche infortunio, "Ora solare e giorno", provincia di Brescia.
Ogni file è una combinazione di anno, genere, modalità, tipo (C o M) e nazionalità, quindi per un anno completo
servono 24 file. Il nome dei file non conta.

## 3. Aggiornare i dati in locale

Ad ogni nuova pubblicazione INAIL: scarica i file nuovi nelle cartelle (sostituendo i vecchi), poi lancia in sequenza:

```
cd C:\Users\matteo.anselmi\Documents\osservatorio-infortuni
.\.venv\Scripts\Activate.ps1
cd pipeline

# facoltativo: cancella le tabelle tipologiche salvate, così si riscaricano aggiornate
Remove-Item -Recurse -Force cache\tipologiche -ErrorAction SilentlyContinue

# infortuni semestrali
python scarica_inail.py --solo semestrale --da-csv ..\csv_inail

# orari Brescia
python scarica_inail.py --ora-giorno ..\ora_brescia

# malattie professionali (protocollo e decessi)
python scarica_inail.py --malattie ..\csv_malattie
```

Non serve lanciarli tutti: se è cambiato solo un dataset, basta il comando corrispondente.

**Perché `--solo semestrale`.** Senza quell'opzione lo script, dopo il semestrale, cerca anche i file mensili e,
se non li trova, si ferma con un errore. Se in `csv_inail` ci sono anche i mensili, togli `--solo semestrale`
per elaborarli entrambi, oppure usa `--solo mensile` per fare solo quelli.

### Cosa controllare nell'output

- **Infortuni.**
  - Le percentuali di decodifica (Ateco, luogo di nascita…) devono essere vicine al 100%.
  - Se lo script elenca codici non trovati, una tabella tipologica non si è scaricata o è cambiata.
  - La riga "regioni mancanti" deve essere vuota, altrimenti il totale Italia è incompleto.
- **Orari.**
  - Lo script stampa i totali per anno.
  - Segnala anche gli anni con file mancanti e i file doppi o con etichette incoerenti (per esempio un file M che ha più casi del suo C).
  - Il totale accertati positivi di un anno deve essere vicino a quello della scheda Semestrale per Brescia con
    Gestione = Industria e servizi ed Esito = Positivo.
- **Malattie.**
  - Lo script stampa casi e lavoratori per anno.
  - Ordini di grandezza sul file di aprile 2026: circa 72.500 / 88.300 / 98.300 casi nel 2023–2025, cioè 49.000 / 58.000 / 63.000 lavoratori.
  - Per i decessi confronta la somma delle regioni con il file Italia.
- **Messaggio "il file scaricato è vuoto o non è un CSV".** Una tabella tipologica non si è scaricata bene.
  Lo script la cancella da solo: rilancia il comando.

### Opzioni utili

```
--anni-semestrale 2023 2024 2025     anni del semestrale (default: i tre anni prima di quello corrente)
--anni-malattie 2023 2024 2025       anni di protocollo delle malattie (default: gli ultimi tre presenti nel file)
--solo semestrale | mensile          elabora un solo dataset infortuni
```

Senza `--da-csv` lo script scarica gli infortuni dalle **Open API** INAIL, regione per regione e mese per mese
(circa 750 chiamate per il semestrale e 450 per il mensile). Le risposte restano in `pipeline/cache`.
Altre opzioni per questa modalità: `--rinfresca` per riscaricare tutto, `--paralleli 2` se il server rallenta.

### Dati di esempio

`python genera_demo.py` scrive in `portale/data` dati inventati. Serve solo per provare il portale senza i file veri:
in testa al portale compare la scritta "Dati di esempio". **Non pubblicarli**: rilancia i comandi sopra prima del push.

## 4. Vedere il portale sul proprio computer

Il portale legge i file JSON, quindi va aperto tramite un piccolo server e non con doppio clic:

```
cd ..\portale
python -m http.server 8000
```

Apri http://localhost:8000. Controlla le quattro schede, poi chiudi il server con Ctrl+C.

## 5. Pubblicare su GitHub Pages

Il sito è pubblicato da GitHub Pages: ramo `main`, cartella `/`. L'indirizzo è
`https://<utente>.github.io/osservatorio-infortuni/portale/`. Dopo aver aggiornato i dati:

```
cd C:\Users\matteo.anselmi\Documents\osservatorio-infortuni
git status
git add -A
git commit -m "Dati INAIL aggiornati"
git push
```

Prima di `git add` guarda `git status`. Non deve mai comparire `.venv`. Se compare, il `.gitignore` deve contenere:

```
.venv/
pipeline/cache/
__pycache__/
```

Dopo un paio di minuti il sito è aggiornato. Se il browser mostra ancora la versione vecchia, ricarica con Ctrl+F5.

**Credenziali.** Il push usa il Gestore credenziali di Windows o un token personale (PAT) di GitHub.
Il token è come una password: non va mai scritto nei file del progetto, perché il repository è pubblico.

### Lavorare in due

- Il collega clona il repository, crea il **suo** venv (il punto 1) e trova già nel repository le cartelle dei dati grezzi.
- Per pubblicare va aggiunto come collaboratore (Settings → Collaborators) e usa il **suo** token.
- Prima di lavorare fate sempre `git pull`.
- Decidete chi rigenera i JSON: se lo fate in due insieme, i file di dati vanno in conflitto.

---

## Come leggere i dati

### Infortuni

- **Territori.**
  - Italia comprende tutte le regioni, compresa la voce INAIL "Altro".
  - Brescia e Bergamo sono individuate dal luogo di accadimento (codici ISTAT 017 e 016).
  - Le altre regioni e province si scelgono dai menu in alto e compaiono come quinta riga del confronto.
  - "Altro" non è una regione: resta solo nel totale Italia.
- **Semestrale.**
  - Senza filtro Esito si vedono tutte le denunce; con Esito = Positivo gli infortuni riconosciuti.
  - L'ultimo anno può ancora cambiare leggermente alle rilevazioni successive.
- **Mensile.**
  - Totali, età, Ateco e giorni della settimana confrontano lo stesso periodo nei due anni.
  - Il grafico per mese mostra l'anno precedente intero.
- **Mortali.**
  - *Mortali denunciati* = denunce con data di morte.
  - *Mortali accertati* = esito mortale riconosciuto da INAIL, solo nel semestrale.
- **Dati non presenti negli Open Data.**
  - L'ora dell'evento manca: per Brescia c'è la scheda Orari.
  - Manca la dimensione aziendale: al suo posto c'è la gestione tariffaria.
  - Il giorno della settimana è ricavato dalla data.

### Malattie professionali

- **Anno di protocollo.** È l'anno in cui INAIL ha registrato la denuncia. La malattia può essere insorta molti anni prima.
- **Territorio.** È la sede INAIL che tratta il caso, non il luogo di lavoro.
- **Casi e lavoratori.**
  - Un caso è una malattia denunciata.
  - I lavoratori sono le persone distinte nell'anno.
  - I lavoratori non si possono contare (compare "–") con i filtri Tabellata, Asbesto, Gruppo di malattie,
    Settore correlato o con una tipologia M.
- **ICD-10.**
  - Il selettore sceglie il codice denunciato (indicato nella denuncia) o quello accertato da INAIL.
  - Il filtro **Gruppo di malattie** usa il settore ICD-10 del codice denunciato.
- **Agente causale e settore correlato.**
  - Esistono solo per i casi riconosciuti.
  - Con il filtro **Settore correlato** restano solo i riconosciuti.
- **Tipologie M.**
  - *Casi con decesso* = casi di lavoratori morti, anche anni prima della denuncia.
  - *Decesso riconosciuto* = morte attribuita da INAIL alla malattia.
- **Sezione Decessi.**
  - Viene dal file per data di decesso: lavoratori morti per malattia professionale riconosciuta, per anno di morte.
  - Non è confrontabile con le colonne "Casi con decesso" e "Decesso riconosciuto", che contano le denunce dell'anno.
  - Esiste solo per Italia e regioni: per Brescia e Bergamo mostra la Lombardia.
  - Valgono solo i filtri genere, nazionalità e gestione.
  - Gli anni recenti crescono con gli aggiornamenti.

### Orari · Brescia

- Sono solo i casi **accertati positivi** della gestione Industria e servizi, non le denunce.
  Tipo C = infortuni riconosciuti, tipo M = mortali accertati.

## Report PDF

Il pulsante **⤓ PDF** apre la finestra di stampa del browser: come stampante scegli **Salva come PDF**.
Funziona anche con Ctrl+P. Il report:
- riporta in testa territorio, filtri attivi, data e ora;
- è in A4 orizzontale, a colori chiari anche se usi il tema scuro;
- ha un nome file già proposto, per esempio `Report - Denunce ed esiti - Brescia - 2026-10-08`.

---

Fonte: INAIL Open Data, licenza IODL 2.0; banca dati statistica INAIL per gli orari.
