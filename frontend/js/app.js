document.addEventListener("DOMContentLoaded", () => {
  applyRandomAccent();
  initTheme();
  fetchRaw(buildApiUrl("/health"), { method: "GET" }, "Warmup failed").catch(() => {});
  handleDeepLink();
  document.addEventListener("keydown", onKeydown);
  $("searchInput").addEventListener("input", onSearchInput);
  if (!new URLSearchParams(location.search).get("q")) {
    $("snippetGrid").classList.add("visually-hidden");
    $("emptyState").classList.add("visually-hidden");
    showHowTo(true);
  }
  loadStats();
  setActiveTab(state.currentFeed);
});

Object.assign(window, {
  switchFeed,
  handleSearch,
  resetSearch,
  openModal,
  closeModal,
  copyCode,
  toggleEdit,
  shareSnippet,
});
