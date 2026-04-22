# Aegis

`Aegis` is your free, local personal assistant for macOS.

It is designed to feel more like a real personal command center than a basic chatbot:

- private and local
- free to run
- browser-based
- remembers useful things about you
- keeps chat history on your Mac
- can speak replies with macOS built-in voice
- can transcribe your voice locally with `mlx-whisper`

## What Changed

This project used to be branded as `My Own AI`.

It is now rebranded as `Aegis`.

Why this name:

- shorter
- more memorable
- feels more like a real assistant
- fits the “protective, helpful system” vibe

## What Aegis Does

- talks to local models through `Ollama`
- runs in a browser
- stores memories in categories
- keeps conversation history
- saves your preferred model
- supports spoken replies
- stays fully free if you keep using local tools

## Free Stack

Everything here can stay free:

- `Ollama`
- local models like `llama3.2`, `phi4-mini`, and `gemma3:1b`
- `Python 3`
- `SQLite`
- macOS `say`
- `mlx-whisper`
- `ffmpeg`

Planned free upgrades:

- safer local automations

## Best Models For Your MacBook Air

Start with:

1. `llama3.2`
2. `phi4-mini`
3. `gemma3:1b`

If the assistant feels slow, switch to a lighter model in the UI.

## Run Aegis

First make sure Ollama is running:

```bash
ollama run llama3.2
```

Then start the app:

```bash
cd /Users/zaid/Documents/MyOwnAI
python3 assistant.py web
```

Open:

```text
http://127.0.0.1:8000
```

## Main Features

### Conversation

- persistent local chat history
- nicer browser UI
- draft saving in the browser
- quick-start prompt buttons

### Memory

Memories can be saved as:

- `preferences`
- `goals`
- `study`
- `tasks`
- `general`

You can also search memories in the interface.

### Voice

Enable `Voice replies` to have Aegis speak answers using your Mac’s built-in speech.

Use `Start voice` in the chat box to record a short message and transcribe it locally.
The recorded speech is added to the message box so you can review it before sending.

## Good Uses

Try things like:

- Build me a realistic study plan for tonight.
- Organize my tasks into now, next, and later.
- Use what you know about me to help me plan tomorrow.
- Turn these messy notes into clean action points.

## Files

- [assistant.py](/Users/zaid/Documents/MyOwnAI/assistant.py:1)
- [web/index.html](/Users/zaid/Documents/MyOwnAI/web/index.html:1)
- [web/app.js](/Users/zaid/Documents/MyOwnAI/web/app.js:1)
- [web/styles.css](/Users/zaid/Documents/MyOwnAI/web/styles.css:1)

## Next Best Upgrade

The next major upgrade should be safe local actions and automations, so Aegis can help you do things instead of only talking about them.
