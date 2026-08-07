const PROJECT = window.PROJECT_NAME;

// ---------------------------------------------------------------- Вкладки
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
    if (btn.dataset.tab === "logs") loadLogs();
    if (btn.dataset.tab === "terminal") initTerminal();
    if (btn.dataset.tab === "packages") loadFreeze();
  });
});

// ---------------------------------------------------------------- Живая статистика процесса
async function refreshStats() {
  try {
    const data = await apiFetch(`/api/projects/${PROJECT}/status`);
    if (data.stats) {
      document.getElementById("stat-cpu").textContent = data.stats.cpu_percent + "%";
      document.getElementById("stat-ram").textContent = data.stats.ram_mb + " МБ";
      document.getElementById("stat-threads").textContent = data.stats.threads;
      document.getElementById("stat-pid").textContent = data.stats.pid;
    } else {
      document.getElementById("stat-cpu").textContent = "—";
      document.getElementById("stat-ram").textContent = "—";
      document.getElementById("stat-threads").textContent = "—";
      document.getElementById("stat-pid").textContent = "—";
    }
  } catch (e) {}
}
refreshStats();
setInterval(refreshStats, 4000);

// ---------------------------------------------------------------- Файловый менеджер
let currentFilePath = null;
let monacoEditor = null;

require.config({ paths: { vs: "https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs" } });
require(["vs/editor/editor.main"], () => {
  monacoEditor = monaco.editor.create(document.getElementById("monaco-editor"), {
    value: "// Выберите файл слева, чтобы начать редактирование",
    language: "python",
    theme: document.documentElement.getAttribute("data-theme") === "light" ? "vs" : "vs-dark",
    automaticLayout: true,
    fontSize: 13,
  });
  loadTree();
});

function languageForFile(name) {
  const ext = name.split(".").pop().toLowerCase();
  const map = {
    py: "python", js: "javascript", json: "json", html: "html", css: "css",
    md: "markdown", txt: "plaintext", yml: "yaml", yaml: "yaml", sh: "shell",
    cfg: "ini", ini: "ini", env: "plaintext",
  };
  return map[ext] || "plaintext";
}

async function loadTree(relPath = "", container = null) {
  const root = container || document.getElementById("file-tree");
  if (!container) root.innerHTML = "";
  const entries = await apiFetch(`/projects/${PROJECT}/files?path=${encodeURIComponent(relPath)}`);
  entries.forEach(entry => {
    const fullPath = relPath ? `${relPath}/${entry.name}` : entry.name;
    const item = document.createElement("div");
    item.className = "tree-item";
    item.innerHTML = `<span>${entry.is_dir ? "📁" : "📄"} ${entry.name}</span>`;
    root.appendChild(item);

    if (entry.is_dir) {
      const childrenBox = document.createElement("div");
      childrenBox.className = "tree-children hidden";
      root.appendChild(childrenBox);
      let loaded = false;
      item.addEventListener("click", async () => {
        childrenBox.classList.toggle("hidden");
        if (!loaded) {
          await loadTree(fullPath, childrenBox);
          loaded = true;
        }
      });
    } else {
      item.addEventListener("click", () => openFile(fullPath, item));
    }
  });
}

async function openFile(path, el) {
  document.querySelectorAll(".tree-item.selected").forEach(e => e.classList.remove("selected"));
  if (el) el.classList.add("selected");
  try {
    const data = await apiFetch(`/projects/${PROJECT}/files/content?path=${encodeURIComponent(path)}`);
    currentFilePath = path;
    document.getElementById("current-file-name").textContent = path;
    document.getElementById("save-btn").disabled = false;
    monaco.editor.setModelLanguage(monacoEditor.getModel(), languageForFile(path));
    monacoEditor.setValue(data.content);
  } catch (e) {
    alert(e.message);
  }
}

document.getElementById("save-btn").addEventListener("click", async () => {
  if (!currentFilePath) return;
  try {
    await apiFetch(`/projects/${PROJECT}/files/save`, {
      method: "POST",
      body: JSON.stringify({ path: currentFilePath, content: monacoEditor.getValue() }),
    });
    flashTemp("save-btn", "✔ Сохранено");
  } catch (e) {
    alert(e.message);
  }
});

function flashTemp(btnId, text) {
  const btn = document.getElementById(btnId);
  const original = btn.textContent;
  btn.textContent = text;
  setTimeout(() => (btn.textContent = original), 1200);
}

async function fmCreate(type) {
  const name = prompt(type === "dir" ? "Имя новой папки:" : "Имя нового файла:");
  if (!name) return;
  try {
    await apiFetch(`/projects/${PROJECT}/files/create`, {
      method: "POST",
      body: JSON.stringify({ path: name, type }),
    });
    document.getElementById("file-tree").innerHTML = "";
    loadTree();
  } catch (e) {
    alert(e.message);
  }
}

document.getElementById("upload-input").addEventListener("change", async (e) => {
  const files = e.target.files;
  if (!files.length) return;
  const formData = new FormData();
  formData.append("path", "");
  for (const f of files) formData.append("files", f);
  await fetch(`/projects/${PROJECT}/files/upload`, {
    method: "POST",
    body: formData,
    headers: { "X-CSRFToken": CSRF_TOKEN },
  });
  document.getElementById("file-tree").innerHTML = "";
  loadTree();
});

// ---------------------------------------------------------------- Логи
let logAutoTimer = null;
async function loadLogs() {
  const filter = document.getElementById("log-filter").value.toLowerCase();
  const data = await apiFetch(`/projects/${PROJECT}/logs`);
  let text = data.log || "(пусто)";
  if (filter) {
    text = text.split("\n").filter(l => l.toLowerCase().includes(filter)).join("\n");
  }
  const el = document.getElementById("log-output");
  el.textContent = text;
  if (document.getElementById("log-autoscroll").checked) {
    el.scrollTop = el.scrollHeight;
  }
}
document.getElementById("log-filter").addEventListener("input", loadLogs);
function startLogPolling() {
  clearInterval(logAutoTimer);
  logAutoTimer = setInterval(() => {
    if (document.getElementById("tab-logs").classList.contains("active")) loadLogs();
  }, 2000);
}
startLogPolling();

// ---------------------------------------------------------------- Пакеты (pip)
document.getElementById("install-req-btn").addEventListener("click", async () => {
  const out = document.getElementById("pip-output");
  out.textContent = "Установка...";
  const data = await apiFetch(`/projects/${PROJECT}/requirements/install`, { method: "POST" });
  out.textContent = data.output;
});

document.getElementById("install-package-btn").addEventListener("click", async () => {
  const pkg = document.getElementById("package-input").value.trim();
  if (!pkg) return;
  const out = document.getElementById("pip-output");
  out.textContent = "Установка " + pkg + "...";
  const data = await apiFetch(`/projects/${PROJECT}/requirements/install-package`, {
    method: "POST",
    body: JSON.stringify({ package: pkg }),
  });
  out.textContent = data.output;
});

async function loadFreeze() {
  const data = await apiFetch(`/projects/${PROJECT}/requirements/freeze`);
  document.getElementById("freeze-output").textContent = data.freeze || "(общий venv не найден — создайте его: python3 -m venv /root/bots/venv)";
}
document.getElementById("refresh-freeze-btn").addEventListener("click", loadFreeze);

// ---------------------------------------------------------------- Терминал
let termInitialized = false;
function initTerminal() {
  if (termInitialized) return;
  termInitialized = true;

  const term = new Terminal({ fontSize: 13, theme: { background: "#0b0d11" } });
  const fitAddon = new FitAddon.FitAddon();
  term.loadAddon(fitAddon);
  term.open(document.getElementById("xterm-container"));
  fitAddon.fit();

  const socket = io("/terminal");
  socket.on("connect", () => {
    socket.emit("start", { cwd: `/root/bots/projects/${PROJECT}` });
  });
  socket.on("output", (data) => term.write(data));
  term.onData((data) => socket.emit("input", data));
  window.addEventListener("resize", () => {
    fitAddon.fit();
    socket.emit("resize", { cols: term.cols, rows: term.rows });
  });
}

// ---------------------------------------------------------------- Git
document.getElementById("git-remote-btn")?.addEventListener("click", async () => {
  const url = document.getElementById("git-remote-input").value.trim();
  const data = await apiFetch(`/projects/${PROJECT}/git/remote`, { method: "POST", body: JSON.stringify({ url }) });
  document.getElementById("git-output").textContent = data.output;
});
document.getElementById("git-init-btn")?.addEventListener("click", async () => {
  const data = await apiFetch(`/projects/${PROJECT}/git/init`, { method: "POST" });
  document.getElementById("git-output").textContent = data.output;
  location.reload();
});
document.getElementById("git-commit-btn")?.addEventListener("click", async () => {
  const message = document.getElementById("git-commit-input").value.trim() || "update";
  const data = await apiFetch(`/projects/${PROJECT}/git/commit`, { method: "POST", body: JSON.stringify({ message }) });
  document.getElementById("git-output").textContent = data.output;
});
document.getElementById("git-push-btn")?.addEventListener("click", async () => {
  const data = await apiFetch(`/projects/${PROJECT}/git/push`, { method: "POST", body: JSON.stringify({}) });
  document.getElementById("git-output").textContent = data.output;
});
document.getElementById("git-pull-btn")?.addEventListener("click", async () => {
  const data = await apiFetch(`/projects/${PROJECT}/git/pull`, { method: "POST", body: JSON.stringify({}) });
  document.getElementById("git-output").textContent = data.output;
});

// ---------------------------------------------------------------- Бэкапы
document.getElementById("create-backup-btn")?.addEventListener("click", async () => {
  await apiFetch(`/projects/${PROJECT}/backup`, { method: "POST" });
  location.reload();
});
async function restoreBackup(name) {
  if (!confirm(`Восстановить проект из бэкапа ${name}? Текущие файлы будут перезаписаны.`)) return;
  await apiFetch(`/projects/${PROJECT}/backup/${encodeURIComponent(name)}/restore`, { method: "POST" });
  location.reload();
}
async function deleteBackup(name) {
  if (!confirm(`Удалить бэкап ${name}?`)) return;
  await apiFetch(`/projects/${PROJECT}/backup/${encodeURIComponent(name)}/delete`, { method: "POST" });
  location.reload();
}

// ---------------------------------------------------------------- Планировщик
document.getElementById("save-schedule-btn")?.addEventListener("click", async () => {
  const value = document.getElementById("schedule-preset").value;
  await apiFetch(`/projects/${PROJECT}/schedule`, {
    method: "POST",
    body: JSON.stringify({ on_calendar: value }),
  });
  alert("Расписание сохранено");
});
