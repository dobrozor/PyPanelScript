// Переключение темы
const themeToggle = document.getElementById("theme-toggle");
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  if (themeToggle) themeToggle.textContent = theme === "dark" ? "🌙" : "☀️";
}
const savedTheme = localStorage.getItem("panel-theme") || "dark";
applyTheme(savedTheme);
if (themeToggle) {
  themeToggle.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme");
    const next = current === "dark" ? "light" : "dark";
    localStorage.setItem("panel-theme", next);
    applyTheme(next);
  });
}

// Модальные окна
function showModal(id) { document.getElementById(id).classList.remove("hidden"); }
function hideModal(id) { document.getElementById(id).classList.add("hidden"); }

// CSRF-токен для AJAX-запросов (Flask-WTF ожидает заголовок X-CSRFToken)
const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]')?.content;

// Универсальный helper для fetch с JSON
async function apiFetch(url, options = {}) {
  const headers = Object.assign(
    { "Content-Type": "application/json", "X-CSRFToken": CSRF_TOKEN },
    options.headers || {}
  );
  const opts = Object.assign({}, options, { headers });
  const res = await fetch(url, opts);
  if (!res.ok) {
    let msg = "Ошибка запроса";
    try { const data = await res.json(); msg = data.error || msg; } catch (e) {}
    throw new Error(msg);
  }
  return res.json();
}
