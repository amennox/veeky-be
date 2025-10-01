import os
import sys
import django
import logging
from dotenv import load_dotenv

# Carica le variabili d'ambiente dal file .env
# Questo è il passo più importante per uno script standalone
load_dotenv()

# Aggiungi la root del progetto al path di Python per permettere gli import
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Imposta l'ambiente Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

# Importa i componenti necessari DOPO aver configurato Django
from opensearchpy import OpenSearch
from opensearchpy.exceptions import ConnectionError, AuthenticationException, TransportError
from indexing.opensearch_client import ensure_indices

# Configura un logger di base per vedere l'output
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def debug_opensearch_connection():
    """
    Tenta di connettersi a OpenSearch e di eseguire ensure_indices,
    fornendo un output di debug dettagliato.
    """
    logging.info("--- Inizio debug connessione OpenSearch e creazione indici ---")

    # Leggi le variabili d'ambiente (le stesse di opensearch_client.py)
    host = os.getenv("OPENSEARCH_HOST", "localhost")
    port = int(os.getenv("OPENSEARCH_PORT", "9200"))
    scheme = os.getenv("OPENSEARCH_SCHEME", "https")
    username = os.getenv("OPENSEARCH_USER")
    password = os.getenv("OPENSEARCH_PASSWORD")
    verify_certs_str = os.getenv("OPENSEARCH_VERIFY_CERTS", "true").lower()
    verify_certs = verify_certs_str in {"1", "true", "yes"}

    # Stampa i parametri di connessione che verranno usati
    logging.info(f"Parametri di connessione letti dal .env:")
    logging.info(f"  - HOST: {host}")
    logging.info(f"  - PORT: {port}")
    logging.info(f"  - SCHEME: {scheme}")
    logging.info(f"  - USER: {'Sì' if username else 'No'}")
    logging.info(f"  - PASSWORD: {'Sì' if password else 'No'}")
    logging.info(f"  - VERIFY_CERTS: {verify_certs}")

    http_auth = (username, password) if username and password else None
    client = None

    try:
        # 1. Tenta di inizializzare il client
        logging.info("Tentativo di inizializzazione del client OpenSearch...")
        client = OpenSearch(
            hosts=[{"host": host, "port": port, "scheme": scheme}],
            http_auth=http_auth,
            verify_certs=verify_certs,
            ssl_show_warn=False, # Disabilita i warning SSL per pulire l'output
            timeout=10,
        )
        logging.info("Client OpenSearch inizializzato con successo.")

        # 2. Tenta una chiamata API di base per verificare la connessione
        logging.info("Verifica della connessione con client.info()...")
        info = client.info()
        logging.info(f"Connessione riuscita! Versione OpenSearch: {info['version']['number']}")

        # 3. Esegui la funzione ensure_indices
        logging.info("Esecuzione della funzione ensure_indices...")
        ensure_indices(client)
        logging.info("Funzione ensure_indices completata con successo.")

        logging.info("--- DEBUG COMPLETATO CON SUCCESSO ---")

    except AuthenticationException as e:
        logging.error("ERRORE DI AUTENTICAZIONE: Le credenziali (utente/password) sono errate.", exc_info=True)
    except ConnectionError as e:
        logging.error("ERRORE DI CONNESSIONE: Impossibile connettersi all'host OpenSearch. Controlla host, porta e schema.", exc_info=True)
    except TransportError as e:
        logging.error(f"ERRORE DI TRASPORTO (status: {e.status_code}): {e.error}", exc_info=True)
        logging.error("Questo errore spesso indica un problema di configurazione (es. HTTP vs HTTPS) o certificati SSL.")
    except Exception as e:
        logging.error("Si è verificato un errore imprevisto.", exc_info=True)

if __name__ == "__main__":
    debug_opensearch_connection()