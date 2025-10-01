import os
import sys
import django

# Aggiungi la root del progetto al path di Python
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Imposta l'ambiente Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from indexing.tasks import process_video

# --- IMPORTANTE ---
# Cambia questo ID con quello del video che vuoi analizzare
VIDEO_ID_TO_DEBUG = 4

if __name__ == "__main__":
    print(f"--- Avvio del debug per il video ID: {VIDEO_ID_TO_DEBUG} ---")
    try:
        process_video(VIDEO_ID_TO_DEBUG)
        print(f"--- Debug completato con successo per il video ID: {VIDEO_ID_TO_DEBUG} ---")
    except Exception as e:
        print(f"--- Errore durante il debug del video ID: {VIDEO_ID_TO_DEBUG} ---")
        print(f"Errore: {e}")

