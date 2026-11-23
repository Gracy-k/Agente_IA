const $ = (id) => document.getElementById(id);
const form = $("promptForm"),
  promptBox = $("prompt"),
  sendBtn = $("sendBtn");
let currentChatId = null,
  busy = false,
  currentMessages = [];

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(data.error || `Erro HTTP ${response.status}`);
  return data;
}
async function loadModels() {
  try {
    const data = await api("/api/models"),
      select = $("modelSelect");
    select.innerHTML = "";
    (data.models.length ? data.models : [data.default]).forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      select.appendChild(option);
    });
    $("connection").textContent = "Ollama conectado";
  } catch (e) {
    $("connection").textContent = "Ollama desconectado";
  }
}
function escapeHtml(s) {
  return String(s).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
}
function renderMarkdownLite(text) {
  const source = String(text);
  let html = "",
    last = 0;
  const fence = /```([\w+-]*)[ \t]*\n([\s\S]*?)(?:```|$)/g;
  let match;
  while ((match = fence.exec(source)) !== null) {
    const before = source.slice(last, match.index);
    if (before)
      html += `<div>${escapeHtml(before).replace(/\n/g, "<br>")}</div>`;
    const lang = match[1] || "text",
      code = match[2] || "";
    html += `<pre><code data-lang="${escapeHtml(lang)}">${escapeHtml(code)}</code></pre>`;
    last = fence.lastIndex;
  }
  const rest = source.slice(last);
  if (rest) html += `<div>${escapeHtml(rest).replace(/\n/g, "<br>")}</div>`;
  return html;
}
function addMessage(kind, label, body, scroll = true, image = null) {
  const article = document.createElement("article");
  article.className = `message ${kind}`;
  const head = document.createElement("div");
  head.className = "message-head";
  head.textContent = label;
  const content = document.createElement("div");
  content.className = "message-body";
  content.innerHTML = renderMarkdownLite(body);
  if (image) {
    const link = document.createElement("a");
    link.href = `/imagens/${encodeURIComponent(image)}`;
    link.target = "_blank";
    const img = document.createElement("img");
    img.className = "generated-image";
    img.src = link.href;
    img.alt = "Imagem gerada";
    img.loading = "lazy";
    link.append(img);
    content.prepend(link);
  }
  article.append(head, content);
  if (kind === "assistant") {
    const toolbar = document.createElement("div");
    toolbar.className = "code-actions response-actions";
    const copyAll = document.createElement("button");
    copyAll.type = "button";
    copyAll.textContent = "Copiar resposta";
    copyAll.onclick = () => copyText(body, copyAll, "Copiado!");
    toolbar.append(copyAll);
    if (image) {
      const download = document.createElement("a");
      download.className = "button-link";
      download.href = `/imagens/${encodeURIComponent(image)}`;
      download.download = image;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "Baixar imagem";
      download.append(btn);
      toolbar.append(download);
    }
    const blocks = [...content.querySelectorAll("pre code")];
    const saveAll = document.createElement("button");
    saveAll.type = "button";
    saveAll.textContent = "Salvar arquivo…";
    saveAll.onclick = () =>
      openSaveDialog(
        blocks.length ? blocks[0].textContent : body,
        blocks.length ? blocks[0].dataset.lang : "text",
      );
    toolbar.append(saveAll);
    article.append(toolbar);
    blocks.forEach((code) => {
      const actions = document.createElement("div");
      actions.className = "code-actions";
      const copy = document.createElement("button");
      copy.type = "button";
      copy.textContent = "Copiar código";
      copy.onclick = () => copyText(code.textContent, copy, "Copiado!");
      const save = document.createElement("button");
      save.type = "button";
      save.textContent = "Salvar arquivo…";
      save.onclick = () => openSaveDialog(code.textContent, code.dataset.lang);
      actions.append(copy, save);
      code.parentElement.after(actions);
    });
  }
  $("conversation").appendChild(article);
  if (scroll) article.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return { article, content };
}
async function copyText(text, button, label) {
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = label;
  } catch (e) {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    try {
      document.execCommand("copy");
      button.textContent = label;
    } catch (_) {
      alert("Não foi possível copiar automaticamente.");
    }
    area.remove();
  }
}
function showWelcome() {
  $("welcome").style.display = "block";
  $("conversation").innerHTML = "";
  currentMessages = [];
}
async function refreshChatList() {
  try {
    const data = await api("/api/chats"),
      list = $("chatList"),
      filter = ($("chatSearch")?.value || "").toLowerCase();
    list.innerHTML = "";
    const chats = data.chats.filter((c) =>
      c.title.toLowerCase().includes(filter),
    );
    if (!chats.length) {
      const empty = document.createElement("div");
      empty.className = "history-empty";
      empty.textContent = filter
        ? "Nenhuma conversa encontrada."
        : "Suas conversas aparecerão aqui.";
      list.append(empty);
      return;
    }
    chats.forEach((chat) => {
      const item = document.createElement("div");
      item.className =
        "chat-item" + (chat.id === currentChatId ? " active" : "");
      const open = document.createElement("button");
      open.className = "chat-open";
      open.textContent = chat.title;
      open.title = chat.title;
      open.onclick = () => openChat(chat.id);
      const del = document.createElement("button");
      del.className = "chat-delete";
      del.type = "button";
      del.textContent = "×";
      del.title = "Excluir conversa";
      del.onclick = async () => {
        if (!confirm(`Excluir a conversa “${chat.title}”?`)) return;
        try {
          await api(`/api/chats/${chat.id}`, { method: "DELETE" });
          if (currentChatId === chat.id) {
            currentChatId = null;
            showWelcome();
          }
          await refreshChatList();
        } catch (e) {
          alert(e.message);
        }
      };
      item.append(open, del);
      list.append(item);
    });
  } catch (e) {
    console.error("Falha ao carregar histórico:", e);
  }
}
async function createChat() {
  const data = await api("/api/chats", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model: $("modelSelect").value }),
  });
  currentChatId = data.id;
  showWelcome();
  await refreshChatList();
  return data.id;
}
async function openChat(id) {
  try {
    const data = await api(`/api/chats/${id}`);
    currentChatId = id;
    $("welcome").style.display = "none";
    $("conversation").innerHTML = "";
    currentMessages = [];
    data.messages.forEach((m) => {
      currentMessages.push(m);
      addMessage(
        m.role,
        m.role === "user" ? "VOCÊ" : `ASSISTENTE · ${data.chat.model}`,
        m.content,
        false,
        m.image,
      );
    });
    await refreshChatList();
    promptBox.focus();
  } catch (e) {
    alert(e.message);
  }
}
function suggestedFilename(language) {
  const lang = String(language || "").toLowerCase();
  const names = {
    python: "codigo.py",
    py: "codigo.py",
    html: "index.html",
    css: "style.css",
    javascript: "script.js",
    js: "script.js",
    typescript: "script.ts",
    ts: "script.ts",
    jsx: "App.jsx",
    tsx: "App.tsx",
    react: "App.jsx",
    vue: "App.vue",
    svelte: "App.svelte",
    json: "dados.json",
    sql: "consulta.sql",
    java: "Main.java",
    cpp: "main.cpp",
    c: "main.c",
    markdown: "README.md",
    md: "README.md",
    text: "anotacoes.txt",
    txt: "anotacoes.txt",
    xml: "documento.xml",
    yaml: "config.yaml",
    yml: "config.yml",
    php: "index.php",
    sh: "script.sh",
    bash: "script.sh",
  };
  return names[lang] || "codigo.txt";
}
function openSaveDialog(code, language) {
  $("filePath").value = suggestedFilename(language);
  $("saveDialog").showModal();
  $("confirmSave").onclick = async (event) => {
    event.preventDefault();
    const path = $("filePath").value.trim();
    if (!path) {
      alert("Informe um caminho.");
      return;
    }
    try {
      const data = await api("/api/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, content: code }),
      });
      $("saveDialog").close();
      alert(`Novo arquivo salvo em workspace/${data.path}`);
    } catch (e) {
      alert(e.message);
      $("filePath").focus();
      $("filePath").select();
    }
  };
}
async function streamAnswer(prompt, pending, assistantMessage) {
  const response = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt,
      model: $("modelSelect").value,
      chat_id: currentChatId,
      mode: $("modeSelect").value,
      size: $("sizeSelect").value,
    }),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.error || `Erro HTTP ${response.status}`);
  }
  const reader = response.body.getReader(),
    decoder = new TextDecoder();
  let buffer = "",
    answer = "",
    image = null,
    done = false;
  while (!done) {
    const { value, done: ended } = await reader.read();
    if (ended) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop();
    for (const event of events) {
      const line = event.split("\n").find((x) => x.startsWith("data: "));
      if (!line) continue;
      const packet = JSON.parse(line.slice(6));
      if (packet.error) throw new Error(packet.error);
      if (packet.status) {
        assistantMessage.content.innerHTML = `<div class="agent-status">${escapeHtml(packet.status)}</div>`;
        $("responseStatus").textContent = packet.status;
      }
      if (packet.image) image = packet.image;
      if (packet.token) {
        answer += packet.token;
        assistantMessage.content.innerHTML = renderMarkdownLite(answer);
      }
      if (packet.done) done = true;
    }
  }
  assistantMessage.article.remove();
  const rendered = addMessage(
    "assistant",
    `ASSISTENTE · ${$("modelSelect").value}`,
    answer,
    true,
    image,
  );
  currentMessages.push(
    { role: "user", content: prompt },
    { role: "assistant", content: answer },
  );
  await refreshChatList();
  $("responseStatus").textContent = "Resposta concluída";
  return rendered;
}
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const prompt = promptBox.value.trim();
  if (!prompt || busy) return;
  busy = true;
  sendBtn.disabled = true;
  $("responseStatus").textContent = "";
  try {
    if (!currentChatId) await createChat();
    $("welcome").style.display = "none";
    addMessage("user", "VOCÊ", prompt);
    promptBox.value = "";
    const assistantMessage = {
      article: null,
      content: document.createElement("div"),
    };
    const placeholder = document.createElement("article");
    placeholder.className = "message assistant";
    const head = document.createElement("div");
    head.className = "message-head";
    head.textContent = "ASSISTENTE · gerando";
    assistantMessage.content.className = "message-body";
    placeholder.append(head, assistantMessage.content);
    $("conversation").append(placeholder);
    assistantMessage.article = placeholder;
    await streamAnswer(prompt, null, assistantMessage);
  } catch (err) {
    const pending = $("conversation").querySelector(".pending");
    if (pending) pending.remove();
    const partial = $("conversation").querySelector(
      ".message.assistant:last-child",
    );
    if (partial && partial.querySelector(".message-body")?.textContent) {
    }
    addMessage("assistant", "ERRO", err.message);
    $("responseStatus").textContent = "Ocorreu um erro";
  } finally {
    busy = false;
    sendBtn.disabled = false;
    $("responseStatus").textContent = "Pronto";
    promptBox.focus();
  }
});
promptBox.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});
document.querySelectorAll(".suggestion").forEach((btn) =>
  btn.addEventListener("click", () => {
    promptBox.value = btn.dataset.prompt;
    promptBox.focus();
  }),
);
$("newChat").addEventListener("click", async () => {
  currentChatId = null;
  showWelcome();
  await refreshChatList();
  promptBox.focus();
});
$("chatSearch").addEventListener("input", refreshChatList);
function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("codelocal-theme", theme);
  $("themeToggle").textContent = theme === "dark" ? "☀ Claro" : "☾ Escuro";
}
setTheme(localStorage.getItem("codelocal-theme") || "dark");
$("themeToggle").addEventListener("click", () =>
  setTheme(
    document.documentElement.dataset.theme === "dark" ? "light" : "dark",
  ),
);
$("exportChat").addEventListener("click", async () => {
  if (!currentChatId) {
    alert("Abra uma conversa para exportá-la.");
    return;
  }
  try {
    const data = await api(`/api/chats/${currentChatId}`);
    const md =
      `# ${data.chat.title}\n\n` +
      data.messages
        .map(
          (m) =>
            `## ${m.role === "user" ? "Você" : "Assistente"}\n\n${m.content}`,
        )
        .join("\n\n---\n\n");
    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" }),
      url = URL.createObjectURL(blob),
      a = document.createElement("a");
    a.href = url;
    a.download = "conversa-codelocal.md";
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert(e.message);
  }
});
function syncModeUi() {
  const mode = $("modeSelect").value;
  $("sizeSelect").hidden = mode === "codigo" || mode === "web";
  promptBox.placeholder =
    mode === "imagem"
      ? "Descreva a imagem que deseja gerar (em português mesmo)…"
      : "Descreva o código que deseja criar, cole um trecho para revisar ou peça uma imagem…";
}
$("modeSelect").addEventListener("change", syncModeUi);
syncModeUi();
async function checkStatus() {
  try {
    const data = await api("/api/status");
    $("modeSelect").querySelector('[value="imagem"]').textContent =
      data.imagem.available ? "▨ Imagem" : "▨ Imagem (indisponível)";
    $("modeSelect").querySelector('[value="imagem"]').title = data.imagem.detail;
    $("voiceBtn").title = data.voz.available ? "Conversar por voz" : data.voz.detail;
  } catch (_) {}
}
(async () => {
  checkStatus();
  await loadModels();
  await refreshChatList();
})();

// Ligações usadas pelo modo de voz (static/voz.js)
window.currentChatIdForVoice = () => currentChatId;
window.createChatForVoice = createChat;
window.showVoiceTurn = async (data) => {
  $("welcome").style.display = "none";
  addMessage("user", "VOCÊ · voz", data.text);
  addMessage("assistant", `ASSISTENTE · ${$("modelSelect").value}`, data.answer, true, data.image);
  await refreshChatList();
};
