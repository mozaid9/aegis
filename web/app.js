const appName = document.getElementById("app-name");
const tagline = document.getElementById("tagline");
const chat = document.getElementById("chat");
const chatForm = document.getElementById("chat-form");
const messageInput = document.getElementById("message");
const sendButton = document.getElementById("send-button");
const modelSelect = document.getElementById("model");
const speakRepliesToggle = document.getElementById("speak-replies");
const ollamaStatus = document.getElementById("ollama-status");
const clearChatButton = document.getElementById("clear-chat");
const speakLastButton = document.getElementById("speak-last");
const recordButton = document.getElementById("record-button");
const responseState = document.getElementById("response-state");
const memoryCount = document.getElementById("memory-count");
const messageCount = document.getElementById("message-count");
const voiceStatus = document.getElementById("voice-status");
const memoriesBox = document.getElementById("memories");
const memoryForm = document.getElementById("memory-form");
const memoryInput = document.getElementById("memory-input");
const memoryCategorySelect = document.getElementById("memory-category");
const memorySearch = document.getElementById("memory-search");
const refreshMemoriesButton = document.getElementById("refresh-memories");
const quickPromptButtons = document.querySelectorAll(".chip");
const toast = document.getElementById("toast");
const messageLength = document.getElementById("message-length");
const draftStatus = document.getElementById("draft-status");

const DRAFT_KEY = "aegis-chat-draft";

let allMemories = [];
let lastAssistantReply = "";
let bootstrapped = false;
let mediaRecorder = null;
let recordedChunks = [];
let voiceInputAvailable = false;


function setRecordButtonState(mode = "idle") {
  recordButton.dataset.mode = mode;
  if (mode === "recording") {
    recordButton.textContent = "Stop voice";
    return;
  }
  if (mode === "transcribing") {
    recordButton.textContent = "Transcribing...";
    return;
  }
  if (mode === "blocked") {
    recordButton.textContent = "Voice unavailable";
    return;
  }
  recordButton.textContent = "Start voice";
}


function formatTimestamp(value) {
  if (!value) {
    return "Saved earlier";
  }
  return new Date(value).toLocaleString();
}


function showToast(text) {
  toast.textContent = text;
  toast.classList.remove("hidden");
  clearTimeout(showToast.timeoutId);
  showToast.timeoutId = setTimeout(() => {
    toast.classList.add("hidden");
  }, 2200);
}


function setResponseState(text, mode = "ready") {
  responseState.textContent = text;
  responseState.dataset.mode = mode;
}


function updateCounts(messages = null) {
  memoryCount.textContent = String(allMemories.length);
  if (messages) {
    messageCount.textContent = String(messages.length);
  } else {
    messageCount.textContent = String(chat.querySelectorAll(".message").length);
  }
}


function preferredAudioMimeType() {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/mp4",
    "audio/ogg;codecs=opus",
    "audio/webm",
  ];
  return candidates.find((type) => window.MediaRecorder && MediaRecorder.isTypeSupported(type)) || "";
}


function updateDraftMeta() {
  messageLength.textContent = String(messageInput.value.trim().length);
}


function saveDraft() {
  localStorage.setItem(DRAFT_KEY, messageInput.value);
  draftStatus.textContent = messageInput.value ? "Draft saved automatically." : "Drafts save automatically in this browser.";
  updateDraftMeta();
}


function restoreDraft() {
  const draft = localStorage.getItem(DRAFT_KEY) || "";
  messageInput.value = draft;
  updateDraftMeta();
}


function messageElement(role, text, createdAt) {
  const item = document.createElement("article");
  item.className = `message ${role}`;

  const meta = document.createElement("div");
  meta.className = "message-meta";
  const label = role === "user" ? "You" : appName.textContent || "Assistant";
  meta.textContent = createdAt ? `${label} • ${formatTimestamp(createdAt)}` : label;

  const body = document.createElement("div");
  body.className = "message-body";
  body.textContent = text;

  item.append(meta, body);
  return item;
}


function addMessage(role, text, createdAt) {
  const item = messageElement(role, text, createdAt);
  chat.appendChild(item);
  chat.scrollTop = chat.scrollHeight;
  if (role === "assistant") {
    lastAssistantReply = text;
  }
  updateCounts();
  return item;
}


function renderMessages(messages) {
  chat.innerHTML = "";

  if (!messages.length) {
    addMessage("assistant", "Aegis is ready. Ask for help with studying, planning, notes, or anything you want to organize.");
    updateCounts([]);
    return;
  }

  messages.forEach((message) => {
    addMessage(message.role, message.content, message.created_at);
  });
  updateCounts(messages);
}


function renderModelOptions(installedModels, currentModel) {
  const defaults = ["llama3.2", "phi4-mini", "gemma3:1b"];
  const models = Array.from(new Set([...installedModels, ...defaults, currentModel])).filter(Boolean);
  modelSelect.innerHTML = "";

  models.forEach((model) => {
    const option = document.createElement("option");
    option.value = model;
    option.textContent = model;
    if (model === currentModel) {
      option.selected = true;
    }
    modelSelect.appendChild(option);
  });
}


function renderCategoryOptions(categories) {
  memoryCategorySelect.innerHTML = "";
  categories.forEach((category) => {
    const option = document.createElement("option");
    option.value = category;
    option.textContent = category[0].toUpperCase() + category.slice(1);
    memoryCategorySelect.appendChild(option);
  });
}


function memoryElement(memory) {
  const row = document.createElement("article");
  row.className = "memory-row";

  const textWrap = document.createElement("div");
  textWrap.className = "memory-copy";

  const badge = document.createElement("span");
  badge.className = `memory-badge ${memory.category}`;
  badge.textContent = memory.category;

  const text = document.createElement("div");
  text.className = "memory-text";
  text.textContent = memory.content;

  const time = document.createElement("div");
  time.className = "memory-time";
  time.textContent = formatTimestamp(memory.created_at);

  textWrap.append(badge, text, time);

  const button = document.createElement("button");
  button.className = "ghost small";
  button.textContent = "Delete";
  button.addEventListener("click", async () => {
    await fetch(`/api/memories/${memory.id}`, { method: "DELETE" });
    await loadMemories();
    showToast("Memory deleted");
  });

  row.append(textWrap, button);
  return row;
}


function renderMemories(memories) {
  memoriesBox.innerHTML = "";

  if (!memories.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No matching memories yet.";
    memoriesBox.appendChild(empty);
    return;
  }

  memories.forEach((memory) => {
    memoriesBox.appendChild(memoryElement(memory));
  });
}


function applyMemoryFilter() {
  const query = memorySearch.value.trim().toLowerCase();
  if (!query) {
    renderMemories(allMemories);
    return;
  }

  const filtered = allMemories.filter((memory) => {
    return memory.content.toLowerCase().includes(query) || memory.category.toLowerCase().includes(query);
  });
  renderMemories(filtered);
}


function setOllamaStatus(ollama) {
  if (ollama.running) {
    ollamaStatus.textContent = "Ready";
    ollamaStatus.className = "pill ok";
    return;
  }

  ollamaStatus.textContent = "Start Ollama";
  ollamaStatus.className = "pill warn";
}


function setVoiceStatus(voiceInput) {
  voiceInputAvailable = Boolean(voiceInput && voiceInput.available);
  voiceStatus.textContent = voiceInputAvailable ? "Ready" : "Unavailable";
  recordButton.disabled = !voiceInputAvailable || !window.MediaRecorder;
  setRecordButtonState(voiceInputAvailable && window.MediaRecorder ? "idle" : "blocked");
  if (!window.MediaRecorder) {
    voiceStatus.textContent = "Browser blocked";
  }
}


async function loadMemories() {
  const response = await fetch("/api/memories");
  const data = await response.json();
  allMemories = data.memories || [];
  applyMemoryFilter();
  updateCounts();
}


async function saveSettings() {
  const response = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: modelSelect.value,
      speakReplies: speakRepliesToggle.checked,
    }),
  });
  const data = await response.json();
  renderModelOptions([], data.settings.model);
}


async function bootstrap() {
  const response = await fetch("/api/bootstrap");
  const data = await response.json();

  appName.textContent = data.appName || "Aegis";
  tagline.textContent = data.tagline || "A local personal command center for your Mac.";
  document.title = data.appName || "Aegis";
  renderModelOptions(data.ollama.installedModels || [], data.settings.model);
  renderCategoryOptions(data.categories || []);
  allMemories = data.memories || [];
  applyMemoryFilter();
  renderMessages(data.messages || []);
  setOllamaStatus(data.ollama || { running: false });
  setVoiceStatus(data.voiceInput || { available: false });
  speakRepliesToggle.checked = Boolean(data.settings.speakReplies);
  bootstrapped = true;
}


async function sendMessage(message) {
  const model = modelSelect.value || "llama3.2";
  addMessage("user", message, new Date().toISOString());
  messageInput.value = "";
  saveDraft();
  sendButton.disabled = true;
  sendButton.textContent = "Thinking...";
  setResponseState("Thinking", "busy");

  const placeholder = addMessage("assistant", "Thinking...");

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        model,
        speakReplies: speakRepliesToggle.checked,
      }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Request failed");
    }

    placeholder.querySelector(".message-body").textContent = data.reply || "No response.";
    placeholder.querySelector(".message-meta").textContent = `${appName.textContent} • ${formatTimestamp(data.message.created_at)}`;
    lastAssistantReply = data.reply || "";
    setResponseState("Ready", "ready");
    updateCounts();
  } catch (error) {
    placeholder.querySelector(".message-body").textContent = "Something went wrong while contacting Aegis.";
    setResponseState("Error", "warn");
    showToast(error.message || "Could not send message");
  } finally {
    sendButton.disabled = false;
    sendButton.textContent = "Send";
  }
}


chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (!message) {
    return;
  }
  await sendMessage(message);
});


messageInput.addEventListener("keydown", async (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    const message = messageInput.value.trim();
    if (message) {
      await sendMessage(message);
    }
  }
});


messageInput.addEventListener("input", saveDraft);


async function blobToBase64(blob) {
  const arrayBuffer = await blob.arrayBuffer();
  let binary = "";
  const bytes = new Uint8Array(arrayBuffer);
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}


async function stopRecordingAndTranscribe() {
  if (!mediaRecorder) {
    return;
  }
  mediaRecorder.stop();
}


async function startRecording() {
  if (!voiceInputAvailable) {
    showToast("Local voice input is not ready");
    return;
  }

  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const mimeType = preferredAudioMimeType();
  mediaRecorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
  recordedChunks = [];

  mediaRecorder.addEventListener("dataavailable", (event) => {
    if (event.data.size > 0) {
      recordedChunks.push(event.data);
    }
  });

  mediaRecorder.addEventListener("stop", async () => {
    const tracks = mediaRecorder.stream.getTracks();
    tracks.forEach((track) => track.stop());

    const blob = new Blob(recordedChunks, { type: mediaRecorder.mimeType || "audio/webm" });
    const audioData = await blobToBase64(blob);
    setRecordButtonState("transcribing");
    recordButton.disabled = true;
    setResponseState("Transcribing voice", "busy");

    try {
      const response = await fetch("/api/transcribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          audioData,
          mimeType: blob.type || "audio/webm",
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Could not transcribe audio");
      }

      messageInput.value = [messageInput.value.trim(), data.text].filter(Boolean).join(messageInput.value.trim() ? "\n" : "");
      saveDraft();
      setResponseState("Ready", "ready");
      showToast("Voice input added to message");
      messageInput.focus();
    } catch (error) {
      setResponseState("Voice failed", "warn");
      showToast(error.message || "Could not transcribe audio");
    } finally {
      mediaRecorder = null;
      recordedChunks = [];
      setRecordButtonState("idle");
      recordButton.disabled = !voiceInputAvailable || !window.MediaRecorder;
    }
  });

  mediaRecorder.start();
  setRecordButtonState("recording");
  setResponseState("Recording", "busy");
  showToast("Recording started");
}


memoryForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = memoryInput.value.trim();
  if (!content) {
    return;
  }

  const response = await fetch("/api/memories", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content,
      category: memoryCategorySelect.value,
    }),
  });
  const data = await response.json();
  if (!response.ok) {
    showToast(data.error || "Could not save memory");
    return;
  }

  memoryInput.value = "";
  await loadMemories();
  showToast("Memory saved");
});


modelSelect.addEventListener("change", async () => {
  if (!bootstrapped) {
    return;
  }
  await saveSettings();
  showToast("Model saved");
});


speakRepliesToggle.addEventListener("change", async () => {
  if (!bootstrapped) {
    return;
  }
  await saveSettings();
  showToast(speakRepliesToggle.checked ? "Voice replies on" : "Voice replies off");
});


refreshMemoriesButton.addEventListener("click", async () => {
  await loadMemories();
  showToast("Memories refreshed");
});


memorySearch.addEventListener("input", applyMemoryFilter);


clearChatButton.addEventListener("click", async () => {
  await fetch("/api/messages", { method: "DELETE" });
  renderMessages([]);
  setResponseState("Ready", "ready");
  showToast("Chat history cleared");
});


recordButton.addEventListener("click", async () => {
  try {
    if (mediaRecorder && mediaRecorder.state === "recording") {
      await stopRecordingAndTranscribe();
      return;
    }
    await startRecording();
  } catch (error) {
    mediaRecorder = null;
    setRecordButtonState("idle");
    setResponseState("Voice failed", "warn");
    showToast(error.message || "Could not access microphone");
  }
});


speakLastButton.addEventListener("click", async () => {
  if (!lastAssistantReply) {
    showToast("No assistant reply to speak yet");
    return;
  }
  await fetch("/api/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: lastAssistantReply }),
  });
  showToast("Speaking");
});


quickPromptButtons.forEach((button) => {
  button.addEventListener("click", () => {
    messageInput.value = button.dataset.prompt || "";
    saveDraft();
    messageInput.focus();
  });
});


restoreDraft();
bootstrap().catch(() => {
  renderMessages([]);
  setResponseState("Offline", "warn");
  showToast("Could not load Aegis");
});
