# QA — Auction XI 1.1.0-rc1

Verifica finale del 13 ottobre 2026: **27 test passati**, un avviso di deprecazione della libreria di test senza fallimenti.

Copertura: suite originale adattata al nuovo CSV e alle API autenticate; simulazione 10 squadre, 250 acquisti, rappezzamento, export e reset; ultimo credito/slot; cicli random e riapertura dopo svincolo; correzioni, trasferimenti, rettifiche e undo; chiusura e privacy crediti; Qt.A facoltativa; ID ufficiale e prezzi finali; chiamate simultanee; timer, pausa, invenduto, chiusura unica e override; websocket con due partecipanti; checkpoint corrente+5; corruzione, database vuoto/mancante, ripristino manuale; riavvio in pausa; migrazione additiva; blocco del secondo server.

Tutti i test usano un database temporaneo: non cancellano le aste dell'utente.

Verifiche aggiuntive: compilazione Python e sintassi JavaScript; run_windows.bat --check riuscito sul PC corrente; browser locale con home/ripresa, errori persistenti di chiusura, scelta dealer, Qt.A, rilancio/reset timer, sincronizzazione admin e aggiornamento della rosa pubblica già aperta. Nessun errore console rilevato nelle pagine verificate.

Non eseguiti: import reale sul portale Leghe Fantacalcio, collegamento da reti domestiche diverse, build Docker (Docker non disponibile). Pubblicazione online rimandata su richiesta dell'utente; nessun hosting a pagamento attivato.