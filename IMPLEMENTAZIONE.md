# Implementazione dei punti 1–12

Versione: **1.1.0-rc1**. La versione estratta dallo ZIP originale è conservata nella cartella AuctionXI-audit; questa implementazione è nella cartella AuctionXI.

| Punto | Realizzato |
|---|---|
| 1 | Ricontrollo rose e ciclo A→P se incomplete; segnalazione quando complete. |
| 2 | Riserva per slot residui mantenuta; ultimo credito valido sull'ultimo slot. |
| 3 | Flush prima del ricalcolo; ricalcolo dopo acquisti, svincoli, rollback, rappezzamenti e correzioni; comando admin. |
| 4 | Validazione completa anche della contabilità e degli stati aperti; errori persistenti; riepilogo e conferma. |
| 5 | Correzioni transazionali, trasferimento, prezzo, crediti, ricalcolo, conferma di forzatura, storico prima/dopo e undo prudente. |
| 6 | Rose pubbliche consultabili e aggiornate realtime; crediti protetti anche nelle API; controlli admin separati. |
| 7 | Qt.A live admin e partecipante; colonna opzionale e fallback `—`. |
| 8 | Database persistente, checkpoint atomici corrente+5, salvataggio manuale, ripresa locale, recupero corruzione e ripristino offline. |
| 9 | CSV squadra,id,costo con ID ufficiali e prezzo finale; archivio XLSX separato con rettifiche. |
| 10 | Modalità presenza/remoto persistita; vecchie aste migrate a presenza; nessun cambio a metà asta. Pubblicazione online rimandata su richiesta dell'utente. |
| 11 | Ordine/dealer, PASSA, scadenza server 60 s, reset su offerta valida, chiusura unica, override admin, pausa e ripresa. |
| 12 | Scelta del solo partecipante di turno, filtri liberi/nome/ruolo/club, controllo disponibilità serializzato. |

## Scelte nei casi limite

- Dopo un invenduto il turno remoto avanza; dopo un annullamento admin resta al chiamante.
- Al riavvio, una chiamata remota aperta si mette in pausa, conservando leader e offerta; admin riprende esplicitamente. Nessuna assegnazione automatica durante il recupero.
- Correzioni admin non equivalgono a svincoli di gioco: non consumano quota svincoli e non introducono ban automatici. Un ban preesistente sulla squadra destinataria richiede Forza comunque per essere rimosso, ed è registrato nello snapshot per l'undo.
- Undo admin conservativo: rifiutato se sono avvenute altre operazioni dopo la correzione. Il rollback dell'aggiudicazione è bloccato dopo correzioni o quando uno svincolato necessario al ripristino è già stato riacquistato.
- Ricalcolo crediti: iniziali + rettifiche admin − prezzo totale della rosa corrente. Spesi corrisponde alla rosa attuale, non include rettifiche arbitrarie.
- Single process/istanza SQLite: lock OS impedisce un secondo server sullo stesso database. Non usare più worker o replicare il database su diversi server.
- Import crea un catalogo per asta: un nuovo listone non modifica ruoli o quotazioni delle aste precedenti.

## Verifiche e limiti della consegna

Test automatici su database temporanei; nessun reset del database dell'utente. Inclusa simulazione di 10 squadre con 250 aggiudicazioni, rappezzamento, export e reset. Test per ultimo slot, ciclo random, correzioni, privacy, timer, concorrenza, websocket, checkpoint, riavvio e migrazione. Vedi QA_REPORT.md per il risultato finale.

Verifica browser locale: ripresa dalla home, riepilogo errori di chiusura, ricerca e scelta del dealer, Qt.A, offerta e reset countdown, sincronizzazione admin e aggiornamento della rosa pubblica già aperta. Non equivale a un test su reti domestiche diverse.

Resta da verificare l'import reale su Leghe Fantacalcio. Pubblicazione Internet e prova da reti diverse sono rimandate su richiesta dell'utente; nessun hosting a pagamento viene consegnato o attivato. La build Docker opzionale non è stata eseguita su questo PC perché Docker non è disponibile.
