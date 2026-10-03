# Iris – instructions pour Claude Code

@PROJET.md

## Règles de travail
- Répondre en français. L'utilisateur avance bloc par bloc : expliquer le plan AVANT de coder.
- Lancer `pytest -q` après chaque modification ; ne jamais laisser de test rouge.
- Ne JAMAIS ajouter d'appel à un service d'IA/OCR externe (OpenAI, Google Vision...) : IA 100 % locale.
- Ne JAMAIS stocker d'identifiant direct de patiente (nom, téléphone, adresse, n° national).
- Ne jamais lire, afficher ni committer le fichier `.env` (secrets Meta, clé de chiffrement).
- Toute réponse WhatsApp passe par `services/outbox.enqueue`.
- Environnement : Windows + PowerShell, venv dans `.venv`, serveur `uvicorn app.main:app --port 8000`,
  tunnel `ngrok http 8000` (domaine fixe spotty-salt-salvage.ngrok-free.dev).
