# min_vid

A Django app for turning a raw video/audio file plus supporting assets (images, PDFs) into a captioned, overlaid output video — driven by an AI chat agent instead of a manual editing UI.

## How it works

1. A user uploads a video/audio file, which becomes a `VideoJob`.
2. The job moves through pipeline stages: **transcribed** → **captioned** → **rendered**.
3. Transcription and captioning are handled by `pipeline/` (Whisper-based transcription via Groq, caption generation, overlay compositing).
4. A LangGraph/LangChain agent (`chat/agent.py`), backed by an OpenAI-compatible chat model, exposes the pipeline steps as tools the user can invoke conversationally in a per-job chat session.
5. Every chat message and raw LLM call is logged (`chat/models.py`) so a job's history is fully auditable.
6. Users authenticate via Django's built-in auth; `user_accounts` attaches a profile with a free/pro plan to each user.

## Apps

- **videos** — `VideoJob` and `UploadedAsset` models, upload/status views, serving processed media.
- **chat** — chat sessions/messages, the agent definition, and the LangGraph tool-calling loop.
- **pipeline** — transcription, caption generation, and image/PDF overlay compositing; the tools the agent calls.
- **user_accounts** — per-user profile and subscription plan (free/pro), injected into templates via a context processor.

## Requirements

- Python (see `venv/` for the expected interpreter)
- A Groq API key (transcription) and a DeepSeek (or other OpenAI-compatible) API key (chat agent)

## Setup

```bash
# Activate the virtualenv
source venv/Scripts/activate   # Git Bash / PowerShell on Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment variables in a .env file at the project root:
#   GROQ_API_KEY=
#   DEEPSEEK_API_KEY=
#   DEEPSEEK_MODEL=
#   DEEPSEEK_TEMPERATURE=
#   DEEPSEEK_REASONING_EFFORT=

# Apply migrations
python manage.py migrate

# Run the dev server
python manage.py runserver
```

## Common commands

```bash
python manage.py runserver              # start dev server (http://127.0.0.1:8000)
python manage.py startapp <name>        # create a new app
python manage.py makemigrations         # generate migrations after model changes
python manage.py migrate                # apply migrations
python manage.py createsuperuser        # create an admin user
python manage.py test                   # run the test suite
python manage.py test <app>.<TestCase>  # run a single test case
python manage.py shell                  # interactive shell with project loaded
```

