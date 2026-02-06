const initTheme = () => {
  const savedTheme = localStorage.getItem("theme") || "system";
  const toggle = $("theme-toggle");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const theme = savedTheme === "dark" || (savedTheme === "system" && prefersDark)
    ? THEME_DARK
    : THEME_LIGHT;
  setTheme(theme);
  toggle.checked = theme === THEME_LIGHT;
  toggle.addEventListener("change", (e) => {
    const newTheme = e.target.checked ? THEME_LIGHT : THEME_DARK;
    setTheme(newTheme);
    localStorage.setItem("theme", newTheme === THEME_LIGHT ? "light" : "dark");
  });
};

const setTheme = (themeName) => {
  document.documentElement.setAttribute("data-theme", themeName);
};

const handleDeepLink = () => {
  const params = new URLSearchParams(location.search);
  const snippetId = params.get("snippet");
  const searchQuery = params.get("q");
  if (snippetId) openModal(snippetId);
  if (searchQuery) {
    $("searchInput").value = searchQuery;
    handleSearch(searchQuery);
  } else {
    showHowTo(state.currentFeed === null);
  }
};

const showHowTo = (shouldShow) => {
  const howTo = document.getElementById("how-to-use");
  if (!howTo) return;
  howTo.classList.toggle("visually-hidden", !shouldShow);
};

const setSnippetsOnly = (isActive) => {
  document.body.classList.toggle("snippets-only", isActive);
};

const setSnippetsVisible = (isVisible) => {
  document.body.classList.toggle("show-snippets", isVisible);
};

const SNIPPET_CACHE_PREFIX = "snippet_cache:";

const getCachedSnippet = (id) => {
  try {
    const raw = localStorage.getItem(`${SNIPPET_CACHE_PREFIX}${id}`);
    if (!raw) return null;
    const cached = JSON.parse(raw);
    const cachedAt = cached?._cachedAt;
    if (SNIPPET_CACHE_TTL_MS > 0 && cachedAt && Date.now() - cachedAt > SNIPPET_CACHE_TTL_MS) {
      localStorage.removeItem(`${SNIPPET_CACHE_PREFIX}${id}`);
      return null;
    }
    return cached;
  } catch (err) {
    console.warn("Snippet cache read failed", err);
    return null;
  }
};

const setCachedSnippet = (id, payload) => {
  try {
    const data = { ...payload, _cachedAt: Date.now() };
    localStorage.setItem(`${SNIPPET_CACHE_PREFIX}${id}`, JSON.stringify(data));
  } catch (err) {
    console.warn("Snippet cache write failed", err);
  }
};

const setEditState = (isEditing) => {
  state.isEditingSnippet = isEditing;
  const editor = $("modalCodeEditor");
  const codeBlock = $("modalCode");
  const toggle = document.querySelector(".code-block__actions .btn");
  if (editor) editor.classList.toggle("visually-hidden", !isEditing);
  if (codeBlock) codeBlock.parentElement.classList.toggle("visually-hidden", isEditing);
  if (toggle) toggle.textContent = isEditing ? "Done" : "Edit";
};

const isSuperseded = (err) => err && err.code === "superseded";

const updateUrl = (snippetId) => {
  const url = new URL(location);
  if (snippetId) url.searchParams.set("snippet", snippetId);
  else url.searchParams.delete("snippet");
  history.pushState({}, "", url);
};

const onKeydown = (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "k") {
    e.preventDefault();
    $("searchInput").focus();
  }
  if (e.key === "Escape" && !document.querySelector("dialog[open]")) {
    $("searchInput").blur();
  }
};

const onSearchInput = (e) => {
  clearTimeout(state.searchTimeout);
  state.searchTimeout = setTimeout(() => handleSearch(e.target.value), 400);
};

const switchFeed = async (feedType) => {
  state.currentFeed = feedType;
  showHowTo(false);
  setSnippetsOnly(true);
  setSnippetsVisible(true);
  const url = new URL(location);
  url.searchParams.delete("q");
  history.pushState({}, "", url);
  setActiveTab(feedType);
  showLoadingSkeleton();

  const cacheKey = `voltsnip_cache_${feedType}`;
  const cached = sessionStorage.getItem(cacheKey);
  if (cached) {
    const { data, ts } = JSON.parse(cached);
    if (Date.now() - ts < 5 * 60 * 1000) return renderSnippets(data);
  }

  try {
    const data = await fetchJSON(
      buildApiUrl(`/api/v1/feeds/${feedType}?limit=${FEED_LIMIT}`),
      "Failed to load feed"
    );
    sessionStorage.setItem(cacheKey, JSON.stringify({ data, ts: Date.now() }));
    renderSnippets(data);
  } catch (err) {
    if (isSuperseded(err)) return;
    console.error(err);
    showToast(err.message || "Failed to load feed", "error");
  }
};

const handleSearch = async (query) => {
  if (!query) {
    const url = new URL(location);
    url.searchParams.delete("q");
    history.replaceState({}, "", url);
    $("snippetGrid").classList.add("visually-hidden");
    $("emptyState").classList.add("visually-hidden");
    showHowTo(state.currentFeed === null);
    setSnippetsOnly(state.currentFeed !== null);
    setSnippetsVisible(state.currentFeed !== null);
    return;
  }
  showHowTo(false);
  setSnippetsOnly(state.currentFeed !== null);
  setSnippetsVisible(true);
  $$(".segmented__item").forEach((t) => t.classList.remove("is-active"));
  const url = new URL(location);
  url.searchParams.set("q", query);
  history.replaceState({}, "", url);
  showLoadingSkeleton();
  try {
    const data = await fetchJSON(
      buildApiUrl(`/api/v1/search/semantic?q=${encodeURIComponent(query)}&k=${SEARCH_LIMIT}`),
      "Search failed"
    );
    renderSnippets(data);
  } catch (err) {
    if (isSuperseded(err)) return;
    console.error(err);
    $("snippetGrid").innerHTML = "";
    $("emptyState").classList.remove("visually-hidden");
    showToast(err.message || "Search failed", "error");
  }
};

const resetSearch = () => {
  $("searchInput").value = "";
  handleSearch("");
};

const loadStats = async () => {
  try {
    const data = await fetchJSON(buildApiUrl("/api/v1/stats"), "Failed to load stats");
    $("statTotal").textContent = data.total_snippets ?? "0";
    $("statViews").textContent = data.total_views ?? "0";
    $("statUpvotes").textContent = data.total_upvotes ?? "0";
  } catch (err) {
    if (isSuperseded(err)) return;
    console.error(err);
    showToast(err.message || "Failed to load stats", "error");
  }
};

const openModal = async (id) => {
  $("modalContentArea").style.display = "block";
  $("modalErrorState").classList.add("visually-hidden");
  $("modalLang").style.display = "inline-flex";
  document.querySelector(".modal__footer").style.display = "flex";
  const snippet = state.currentSnippets.find((s) => s.id === id);
  if (snippet) updateModalContent(snippet, true);
  const cachedSnippet = getCachedSnippet(id);
  if (cachedSnippet) updateModalContent(cachedSnippet, false);
  setEditState(false);
  $("snippetModal").showModal();
  updateUrl(id);
  if (cachedSnippet) {
    fetchRaw(
      buildApiUrl(`/api/v1/snippets/${id}/view`),
      { method: "POST" },
      "Failed to record view"
    ).catch(() => {});
    return;
  }
  try {
    const fullSnippet = await fetchJSON(
      buildApiUrl(`/api/v1/snippets/${id}`),
      "Failed to load"
    );
    setCachedSnippet(id, fullSnippet);
    fetchRaw(
      buildApiUrl(`/api/v1/snippets/${id}/view`),
      { method: "POST" },
      "Failed to record view"
    ).catch(() => {});
    updateModalContent(fullSnippet, false);
  } catch (err) {
    if (isSuperseded(err)) return;
    console.error(err);
    renderModalError();
    showToast(err.message || "Failed to load snippet", "error");
  }
};

const closeModal = () => {
  $("snippetModal").close();
  updateUrl(null);
};

const toggleEdit = () => {
  const editor = $("modalCodeEditor");
  if (!editor) return;
  const shouldEdit = !state.isEditingSnippet;
  setEditState(shouldEdit);
  if (!shouldEdit) {
    const code = editor.value || "";
    $("modalCode").textContent = code;
    requestAnimationFrame(() => Prism.highlightElement($("modalCode")));
    const snippetId = new URL(location).searchParams.get("snippet");
    if (snippetId) {
      const cached = getCachedSnippet(snippetId) || {};
      setCachedSnippet(snippetId, { ...cached, code });
    }
  } else {
    editor.focus();
  }
};

const copyCode = () => {
  const editor = $("modalCodeEditor");
  const code = state.isEditingSnippet && editor ? editor.value : $("modalCode").textContent;
  const btn = document.querySelector(".copy-btn");
  const original = btn ? btn.textContent : "Copy";
  navigator.clipboard.writeText(code).then(() => {
    if (btn) {
      btn.textContent = "Copied";
      btn.classList.add("is-copied");
      setTimeout(() => {
        btn.textContent = original;
        btn.classList.remove("is-copied");
      }, 1200);
    }
  });
};

const shareSnippet = async () => {
  const snippetId = new URL(location).searchParams.get("snippet");
  if (!snippetId) {
    showToast("Open a snippet first.", "error");
    return;
  }
  const url = new URL(location.href);
  url.searchParams.set("snippet", snippetId);
  try {
    if (navigator.share) {
      await navigator.share({ url: url.toString() });
    } else {
      await navigator.clipboard.writeText(url.toString());
      showToast("Share link copied.", "success");
    }
  } catch (err) {
    console.error(err);
    showToast("Unable to share link.", "error");
  }
};
