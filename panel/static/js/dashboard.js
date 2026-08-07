// Обновление системной статистики каждые 5 секунд
setInterval(async () => {
  try {
    const stats = await apiFetch("/api/system-stats");
    document.getElementById("sys-cpu").textContent = stats.cpu_percent + "%";
    document.getElementById("sys-ram").textContent = stats.ram_percent + "%";
    document.getElementById("sys-disk").textContent = stats.disk_percent + "%";
  } catch (e) { /* тихо игнорируем */ }
}, 5000);

// Поиск
const searchInput = document.getElementById("search-input");
const searchResults = document.getElementById("search-results");
let searchTimer = null;

if (searchInput) {
  searchInput.addEventListener("input", () => {
    clearTimeout(searchTimer);
    const q = searchInput.value.trim();
    if (q.length < 2) {
      searchResults.classList.add("hidden");
      return;
    }
    searchTimer = setTimeout(async () => {
      const data = await apiFetch(`/api/search?q=${encodeURIComponent(q)}`);
      renderSearchResults(data.results);
    }, 300);
  });
}

function renderSearchResults(results) {
  if (!results.length) {
    searchResults.innerHTML = '<p class="muted">Ничего не найдено</p>';
  } else {
    searchResults.innerHTML = results.map(r => {
      if (r.type === "file") {
        return `<div class="tree-item">📄 ${r.path}</div>`;
      }
      return `<div class="tree-item">📄 ${r.path}:${r.line} — <span class="muted">${escapeHtml(r.text)}</span></div>`;
    }).join("");
  }
  searchResults.classList.remove("hidden");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
