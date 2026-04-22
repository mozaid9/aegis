#!/usr/bin/env python3
import json
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import threading
import urllib.error
import urllib.request
from base64 import b64decode
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "web"
DB_PATH = BASE_DIR / "assistant_memory.db"
LOCAL_VENV_PYTHON = BASE_DIR / ".venv" / "bin" / "python"
LOCAL_TRANSCRIBE_SCRIPT = BASE_DIR / "scripts" / "transcribe_audio.py"
APP_NAME = "Aegis"
APP_TAGLINE = "A local personal command center for your Mac."
DEFAULT_MODEL = "llama3.2"
DEFAULT_WEB_PORT = 8000
DEFAULT_MEMORY_CATEGORY = "general"
MAX_CONTEXT_MESSAGES = 10
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
MEMORY_CATEGORIES = {"general", "preferences", "goals", "study", "tasks"}
DEFAULT_TRANSCRIBE_MODEL = "mlx-community/whisper-tiny"


SYSTEM_PROMPT = """You are Aegis, a capable local personal assistant.
Answer the user's actual question directly and clearly.
Be calm, practical, and concise.
Do not tease, roleplay, stall, or comment on being tested unless the user explicitly asks for that tone.
For technical questions, explain the concept directly, then add short structure or examples if helpful.
For productivity questions, give practical next steps.
Use saved memories only when they are genuinely relevant to the user's request.
Use recent chat history for continuity, but do not let old tone or banter distract you from the current question.
Never invent personal facts that are not in memory.
"""


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def init_db() -> None:
    conn = connect_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL DEFAULT 'general',
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    ensure_column(conn, "memories", "category", "TEXT NOT NULL DEFAULT 'general'")
    ensure_column(conn, "memories", "created_at", "TEXT")
    conn.execute(
        """
        UPDATE memories
        SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP)
        WHERE created_at IS NULL
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            model TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def normalize_category(category: str | None) -> str:
    value = (category or DEFAULT_MEMORY_CATEGORY).strip().lower()
    if value not in MEMORY_CATEGORIES:
        return DEFAULT_MEMORY_CATEGORY
    return value


def add_memory(content: str, category: str | None = None) -> dict:
    normalized_category = normalize_category(category)
    conn = connect_db()
    cur = conn.execute(
        "INSERT INTO memories (category, content, created_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        (normalized_category, content.strip()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, category, content, created_at FROM memories WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()
    conn.close()
    return dict(row)


def list_memories(category: str | None = None) -> list[dict]:
    conn = connect_db()
    if category and normalize_category(category) != DEFAULT_MEMORY_CATEGORY:
        rows = conn.execute(
            """
            SELECT id, category, content, created_at
            FROM memories
            WHERE category = ?
            ORDER BY id DESC
            """,
            (normalize_category(category),),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, category, content, created_at
            FROM memories
            ORDER BY id DESC
            """
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def delete_memory(memory_id: int) -> bool:
    conn = connect_db()
    cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def add_message(role: str, content: str, model: str | None = None) -> dict:
    conn = connect_db()
    cur = conn.execute(
        "INSERT INTO messages (role, content, model, created_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
        (role, content.strip(), model),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id, role, content, model, created_at FROM messages WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()
    conn.close()
    return dict(row)


def list_messages(limit: int | None = None) -> list[dict]:
    conn = connect_db()
    if limit is not None:
        rows = conn.execute(
            """
            SELECT id, role, content, model, created_at
            FROM (
                SELECT id, role, content, model, created_at
                FROM messages
                ORDER BY id DESC
                LIMIT ?
            )
            ORDER BY id ASC
            """,
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, role, content, model, created_at FROM messages ORDER BY id ASC"
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def clear_messages() -> None:
    conn = connect_db()
    conn.execute("DELETE FROM messages")
    conn.commit()
    conn.close()


def set_setting(key: str, value: str) -> None:
    conn = connect_db()
    conn.execute(
        """
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )
    conn.commit()
    conn.close()


def get_setting(key: str, default: str) -> str:
    conn = connect_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    if row is None:
        return default
    return str(row["value"])


def get_all_settings() -> dict:
    return {
        "model": get_setting("model", DEFAULT_MODEL),
        "speakReplies": get_setting("speakReplies", "false") == "true",
    }


def build_memory_block() -> str:
    memories = list_memories()
    if not memories:
        return "No saved memories yet."

    lines = []
    for memory in reversed(memories):
        lines.append(f"- [{memory['category']}] {memory['content']}")
    return "Saved memories:\n" + "\n".join(lines)


def build_chat_messages(model: str, user_text: str) -> list[dict]:
    recent_messages = list_messages(limit=MAX_CONTEXT_MESSAGES)
    messages = [
        {
            "role": "system",
            "content": (
                SYSTEM_PROMPT
                + "\n\n"
                + "Saved user context:\n"
                + build_memory_block()
                + "\n\n"
                + "Response rules:\n"
                + "- Lead with the answer.\n"
                + "- Avoid filler.\n"
                + "- If the user asks for explanation, explain step by step.\n"
                + "- If unsure, say what you are unsure about instead of bluffing.\n"
            ),
        }
    ]
    for message in recent_messages:
        messages.append({"role": message["role"], "content": message["content"]})
    messages.append({"role": "user", "content": user_text})
    return messages


def ollama_installed_models() -> list[str]:
    request = urllib.request.Request(OLLAMA_TAGS_URL, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            models = [item.get("name", "") for item in data.get("models", [])]
            return [model for model in models if model]
    except Exception:
        return []


def ollama_status() -> dict:
    models = ollama_installed_models()
    return {
        "running": bool(models),
        "installedModels": models,
    }


def chat_with_ollama(model: str, user_text: str) -> str:
    payload = {
        "model": model,
        "stream": False,
        "messages": build_chat_messages(model, user_text),
        "options": {
            "temperature": 0.2,
            "top_p": 0.9,
            "repeat_penalty": 1.08,
            "num_ctx": 4096,
        },
    }

    request = urllib.request.Request(
        OLLAMA_CHAT_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data["message"]["content"].strip()
    except urllib.error.URLError:
        return (
            "I couldn't reach Ollama. Make sure it is running first, then try "
            f"`ollama run {model}` in Terminal."
        )
    except Exception as exc:
        return f"Something went wrong while talking to the model: {exc}"


def speak_text(text: str) -> None:
    safe_text = text.strip()
    if not safe_text:
        return
    subprocess.run(["say", safe_text[:500]], check=False)


def speak_text_async(text: str) -> None:
    threading.Thread(target=speak_text, args=(text,), daemon=True).start()


def voice_input_status() -> dict:
    ffmpeg_path = subprocess.run(
        ["bash", "-lc", "command -v ffmpeg"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    available = LOCAL_VENV_PYTHON.exists() and LOCAL_TRANSCRIBE_SCRIPT.exists() and bool(ffmpeg_path)
    return {
        "available": available,
        "engine": "mlx-whisper" if available else None,
        "ffmpeg": bool(ffmpeg_path),
        "python": LOCAL_VENV_PYTHON.exists(),
    }


def decode_audio_blob(audio_b64: str, suffix: str) -> Path:
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        temp_file.write(b64decode(audio_b64))
        temp_file.flush()
        return Path(temp_file.name)
    finally:
        temp_file.close()


def convert_audio_to_wav(source_path: Path) -> Path:
    target = Path(tempfile.NamedTemporaryFile(delete=False, suffix=".wav").name)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        str(target),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg failed")
    return target


def transcribe_audio_file(audio_path: Path) -> str:
    command = [
        str(LOCAL_VENV_PYTHON),
        str(LOCAL_TRANSCRIBE_SCRIPT),
        str(audio_path),
        "--model",
        DEFAULT_TRANSCRIBE_MODEL,
        "--language",
        "en",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        error_text = result.stderr.strip() or result.stdout.strip() or "Transcription failed"
        raise RuntimeError(error_text)

    payload = json.loads(result.stdout)
    text = str(payload.get("text") or "").strip()
    if not text:
        raise RuntimeError("No speech detected")
    return text


def print_help() -> None:
    print(
        textwrap.dedent(
            """
            Commands:
              /help                          Show this help
              /remember [category] <text>    Save a memory
              /memories                      Show saved memories
              /forget <id>                   Delete one memory by id
              /model <name>                  Change model
              /quit                          Exit

            Web mode:
              python3 assistant.py web
            """
        ).strip()
    )


def parse_remember_command(user_input: str) -> tuple[str, str]:
    content = user_input[len("/remember ") :].strip()
    if not content:
        return DEFAULT_MEMORY_CATEGORY, ""

    maybe_category, separator, remainder = content.partition(" ")
    if separator and maybe_category.lower() in MEMORY_CATEGORIES:
        return maybe_category.lower(), remainder.strip()
    return DEFAULT_MEMORY_CATEGORY, content


class AssistantHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/bootstrap":
            self.respond_json(
                {
                    "appName": APP_NAME,
                    "tagline": APP_TAGLINE,
                    "settings": get_all_settings(),
                    "memories": list_memories(),
                    "messages": list_messages(),
                    "categories": sorted(MEMORY_CATEGORIES),
                    "ollama": ollama_status(),
                    "voiceInput": voice_input_status(),
                }
            )
            return

        if parsed.path == "/api/memories":
            query = parse_qs(parsed.query)
            category = query.get("category", [None])[0]
            self.respond_json({"memories": list_memories(category)})
            return

        if parsed.path == "/api/messages":
            self.respond_json({"messages": list_messages()})
            return

        if parsed.path == "/api/health":
            self.respond_json({"ok": True, "ollama": ollama_status()})
            return

        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        body = self.read_json()

        if parsed.path == "/api/chat":
            model = str(body.get("model") or get_setting("model", DEFAULT_MODEL)).strip() or DEFAULT_MODEL
            message = str(body.get("message") or "").strip()
            speak_replies = bool(body.get("speakReplies"))
            if not message:
                self.respond_json({"error": "Message cannot be empty."}, status=HTTPStatus.BAD_REQUEST)
                return

            set_setting("model", model)
            add_message("user", message, model)
            reply = chat_with_ollama(model, message)
            assistant_message = add_message("assistant", reply, model)

            if speak_replies:
                speak_text_async(reply)

            self.respond_json({"reply": reply, "message": assistant_message, "model": model})
            return

        if parsed.path == "/api/memories":
            content = str(body.get("content") or "").strip()
            category = normalize_category(str(body.get("category") or DEFAULT_MEMORY_CATEGORY))
            if not content:
                self.respond_json({"error": "Memory cannot be empty."}, status=HTTPStatus.BAD_REQUEST)
                return
            memory = add_memory(content, category)
            self.respond_json(memory, status=HTTPStatus.CREATED)
            return

        if parsed.path == "/api/settings":
            model = str(body.get("model") or get_setting("model", DEFAULT_MODEL)).strip() or DEFAULT_MODEL
            speak_replies = "true" if bool(body.get("speakReplies")) else "false"
            set_setting("model", model)
            set_setting("speakReplies", speak_replies)
            self.respond_json({"settings": get_all_settings()})
            return

        if parsed.path == "/api/speak":
            text = str(body.get("text") or "").strip()
            if not text:
                self.respond_json({"error": "Text cannot be empty."}, status=HTTPStatus.BAD_REQUEST)
                return
            speak_text_async(text)
            self.respond_json({"spoken": True})
            return

        if parsed.path == "/api/transcribe":
            if not voice_input_status()["available"]:
                self.respond_json(
                    {"error": "Local voice input is not ready on this machine."},
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return

            audio_data = str(body.get("audioData") or "").strip()
            mime_type = str(body.get("mimeType") or "audio/webm").strip()
            if not audio_data:
                self.respond_json({"error": "Audio data is missing."}, status=HTTPStatus.BAD_REQUEST)
                return

            suffix = ".webm"
            if "mp4" in mime_type or "m4a" in mime_type:
                suffix = ".m4a"
            elif "wav" in mime_type:
                suffix = ".wav"
            elif "ogg" in mime_type:
                suffix = ".ogg"

            source_path = None
            wav_path = None
            try:
                source_path = decode_audio_blob(audio_data, suffix)
                wav_path = convert_audio_to_wav(source_path) if source_path.suffix != ".wav" else source_path
                text = transcribe_audio_file(wav_path)
                self.respond_json({"text": text})
            except Exception as exc:
                self.respond_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            finally:
                if source_path and source_path.exists():
                    source_path.unlink(missing_ok=True)
                if wav_path and wav_path != source_path and wav_path.exists():
                    wav_path.unlink(missing_ok=True)
            return

        self.respond_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/messages":
            clear_messages()
            self.respond_json({"cleared": True})
            return

        if parsed.path.startswith("/api/memories/"):
            raw_id = parsed.path.rsplit("/", 1)[-1]
            if not raw_id.isdigit():
                self.respond_json({"error": "Invalid memory id."}, status=HTTPStatus.BAD_REQUEST)
                return

            deleted = delete_memory(int(raw_id))
            if not deleted:
                self.respond_json({"error": "Memory not found."}, status=HTTPStatus.NOT_FOUND)
                return

            self.respond_json({"deleted": True})
            return

        self.respond_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        return

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
            return {}
        except json.JSONDecodeError:
            return {}

    def respond_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run_web_server(port: int = DEFAULT_WEB_PORT) -> int:
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", port), AssistantHandler)
    print(f"{APP_NAME} Web")
    print(f"Open http://127.0.0.1:{port} in your browser")
    print("Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGoodbye.")
    finally:
        server.server_close()
    return 0


def run_terminal() -> int:
    init_db()
    current_model = get_setting("model", DEFAULT_MODEL)

    print(APP_NAME)
    print(APP_TAGLINE)
    print(f"Current model: {current_model}")
    print("Type /help for commands.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return 0

        if not user_input:
            continue

        if user_input == "/help":
            print_help()
            continue

        if user_input == "/quit":
            print("Goodbye.")
            return 0

        if user_input == "/memories":
            memories = list_memories()
            if not memories:
                print("Assistant: No memories saved yet.")
            else:
                print("Assistant:")
                for memory in reversed(memories):
                    print(f"  {memory['id']}. [{memory['category']}] {memory['content']}")
            continue

        if user_input.startswith("/remember "):
            category, content = parse_remember_command(user_input)
            if not content:
                print("Assistant: Please add text after /remember.")
                continue
            memory = add_memory(content, category)
            print(f"Assistant: Saved memory #{memory['id']} in {memory['category']}.")
            continue

        if user_input.startswith("/forget "):
            raw_id = user_input[len("/forget ") :].strip()
            if not raw_id.isdigit():
                print("Assistant: Please give a numeric memory id.")
                continue
            deleted = delete_memory(int(raw_id))
            if deleted:
                print(f"Assistant: Deleted memory #{raw_id}.")
            else:
                print(f"Assistant: Memory #{raw_id} was not found.")
            continue

        if user_input.startswith("/model "):
            model_name = user_input[len("/model ") :].strip()
            if not model_name:
                print("Assistant: Please give a model name.")
                continue
            current_model = model_name
            set_setting("model", current_model)
            print(f"Assistant: Switched model to {current_model}.")
            continue

        add_message("user", user_input, current_model)
        reply = chat_with_ollama(current_model, user_input)
        add_message("assistant", reply, current_model)
        print(f"Assistant: {reply}\n")


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "web":
        port = DEFAULT_WEB_PORT
        if len(sys.argv) > 2 and sys.argv[2].isdigit():
            port = int(sys.argv[2])
        return run_web_server(port)
    return run_terminal()


if __name__ == "__main__":
    sys.exit(main())
