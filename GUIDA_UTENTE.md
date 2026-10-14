# Auction XI 1.1.0-rc1

## Avvio sul PC

1. Estrai tutto lo ZIP in una cartella nuova. Conserva la versione precedente.
2. Su Windows apri **run_windows.bat**. Il primo avvio installa le dipendenze nella cartella dell'app e richiede Internet. Gli avvii successivi e i salvataggi locali non richiedono Internet.
3. Si apre la home. Scegli **In presenza**, configura le squadre e carica il listone Excel.
4. Condividi i link squadra dal pannello admin, usando l'indirizzo LAN stampato dal server. PC e telefoni devono essere sulla stessa Wi-Fi/hotspot. Per squadre senza telefono registra le offerte dal pannello admin.

L'avvio usa Python 3.12 o successivo; rileva anche Python fornito da Codex su questo PC. Se Python manca, mostra il collegamento al sito ufficiale. Non usa l'ambiente `.venv` copiato dalla vecchia cartella.

Su macOS/Linux: `bash run_mac_linux.sh` con Python 3.12+ disponibile.

## Riprendere un'asta esistente

La home locale mostra **RIPRENDI ASTA IN CORSO**, fase, nome, numero squadre e ultimo checkpoint. Le operazioni sono salvate nel database e copiate automaticamente in un checkpoint. **SALVA ORA** crea una copia aggiuntiva. Conserva tutta la cartella `app/data`: contiene database, checkpoint ed export.

Per trasferire la tua vecchia asta: chiudi entrambi i server, copia il precedente `app/data` nella nuova cartella prima del primo avvio. La migrazione aggiunge i nuovi campi e crea una copia prima di aggiornare un database esistente. Le vecchie aste restano In presenza. Non sovrascrivere un database della nuova versione se contiene già aste da conservare.

Vengono tenuti il checkpoint corrente e cinque precedenti. Se il database è corrotto, all'avvio viene recuperato il checkpoint valido più recente e il file danneggiato viene conservato. Se vuoi scegliere una copia precedente: chiudi il server, apri **ripristina_windows.bat**, scegli il checkpoint e conferma. Il ripristino riguarda l'intero database, comprese tutte le aste che vi erano salvate. Prima di ripristinare viene conservata anche la situazione corrente.

## Regole e correzioni

- Puoi spendere l'ultimo credito per riempire l'ultimo slot. Rosa completa con 0 crediti è valida.
- REGOLARIZZA si ricalcola dopo ogni modifica. Non viene azzerato ignorando eccessi o debiti.
- Random per ruolo: P→D→C→A; dopo A ricontrolla le rose e torna a P se incomplete. Quando complete, segnala di concludere l'asta.
- Qt.A è visibile live a tutti. Se il listone non la contiene, compare `—`.
- **Rose squadre** mostra le rose acquistate e si aggiorna dopo acquisti, svincoli e correzioni. Con battitore esterno i crediti avversari restano nascosti; i prezzi d'acquisto restano pubblici.
- Admin: scegli squadra, giocatore e operazione per aggiungere, rimuovere, spostare, cambiare prezzo o correggere crediti. **Ricalcola squadra** rivede contabilità e regolarizzazione. Le rettifiche crediti sono conservate separatamente dalla spesa effettiva.
- **Forza comunque** richiede una conferma esplicita e lascia REGOLARIZZA se necessario. Non consente proprietà duplicate né la chiusura di rose incoerenti.
- **Annulla ultima correzione admin** funziona quando non sono avvenute altre operazioni incompatibili; altrimenti il sistema spiega il blocco. Ogni correzione resta nel registro.

## Conclusione ed export

**CONCLUDI ASTA** mostra rose complete, regolarizzazioni, aste aperte e tutti i problemi. Quando validi, usa **CONFERMA CONCLUSIONE ASTA** per passare a Riepilogo svincolati. Segue la fase di rappezzamenti già esistente, poi Rose definitive.

Il CSV per Leghe contiene **squadra,id,costo**, separato da virgole, con ID ufficiale dal listone e costo definitivo. Non sostituisce ID mancanti con quelli interni: spiega quali giocatori richiedono un listone corretto. L'archivio Excel è un file separato con rose, crediti e rettifiche admin. Le correzioni successive richiedono di rigenerare i due export prima del reset.

La verifica definitiva del CSV richiede ancora un'importazione nella tua lega reale: schema e contenuto sono testati nell'app, accettazione sul portale non ancora eseguita.

## Da remoto

Usa l'indirizzo HTTPS del server online e scegli **Da remoto** nel setup. La scelta resta fissata per l'asta. La modalità non pubblica il PC automaticamente su Internet.

L'ordine iniziale segue l'elenco squadre; admin può riordinarlo e correggere il turno tra le chiamate. Solo il partecipante di turno può scegliere un giocatore libero oppure usare **PASSA**. La chiamata avvia 60 secondi; ogni offerta valida riporta a 60. Il server chiude una sola volta: aggiudica al leader, oppure lascia libero il giocatore senza offerte. Il turno passa al successivo anche dopo un invenduto. Annullare una chiamata mantiene il turno, così la scelta può essere corretta.

Admin può aggiudicare, annullare, sostituire la chiamata (annulla e scegli nuovamente), mettere in pausa e riprendere. In pausa le offerte sono bloccate. Dopo il riavvio del server, le chiamate remote aperte sono in pausa: l'admin riprende con il tempo residuo salvato dalla scadenza; se era già scaduto, riparte da 1 secondo. Usa PAUSA prima di interrompere volontariamente per congelare il tempo residuo.

La pubblicazione online è **rimandata su richiesta dell'utente**: nessun server a pagamento, abbonamento o costo attivato. La consegna operativa è per PC e rete locale. Le funzioni remote sono predisposte nel codice e verificate localmente; non c'è un indirizzo Internet pubblico. Vedi DEPLOYMENT.md.
