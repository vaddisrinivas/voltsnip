const timeAgo = (dateString) => {
  const seconds = Math.floor((Date.now() - new Date(dateString)) / 1000);
  const units = [
    [31536000, "y"],
    [2592000, "mo"],
    [86400, "d"],
    [3600, "h"],
    [60, "m"],
  ];
  for (const [unit, label] of units) {
    const interval = seconds / unit;
    if (interval > 1) return `${Math.floor(interval)}${label} ago`;
  }
  return "just now";
};

const getLangIcon = (lang) => languageIcons[(lang || "").toLowerCase()] || defaultLangIcon;

const showToast = (message, type = "info") => {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = String(message ?? "");
  toast.onclick = () => toast.remove();
  $("toastContainer").appendChild(toast);
  setTimeout(() => toast.remove(), 3200);
};

const setActiveTab = (feedType) => {
  $$(".segmented__item").forEach((t) => {
    const active = t.dataset.feed === feedType;
    t.classList.toggle("is-active", active);
  });
};

const showLoadingSkeleton = () => {
  const grid = $("snippetGrid");
  $("emptyState").classList.add("visually-hidden");
  grid.classList.remove("visually-hidden");
  grid.innerHTML = Array.from({ length: 6 }, () =>
    '<div class="card skeleton"></div>'
  ).join("");
};

const renderSnippet = (snippet) => {
  const icon = getLangIcon(snippet.language);
  const isNew = (Date.now() - new Date(snippet.created_at).getTime()) < RECENT_THRESHOLD_MS;
  const isHot = snippet.upvote_count > 10 || snippet.view_count > 100;
  const title = snippet.title || "Untitled snippet";
  const description = snippet.description || "No description provided.";
  const tags = (snippet.tags || []).slice(0, 3);

  return `
    <article class="card snippet-card" onclick="openModal('${snippet.id}')">
      <div class="snippet-card__meta">
        <h3 class="snippet-card__title">${title}</h3>
      </div>
      <p class="card__text">${description}</p>
      <div class="tag-list">
        ${tags.map((tag) =>
          `<span class="tag" onclick="event.stopPropagation(); handleSearch('${tag}')">#${tag}</span>`
        ).join("")}
      </div>
      <div class="card__footer">
        <div class="mono">
          <span>${snippet.upvote_count || 0} upvotes</span>
          <span> • ${timeAgo(snippet.created_at)}</span>
          ${isNew ? " • new" : ""}
          ${isHot ? " • hot" : ""}
        </div>
        <span class="card__link">View Code →</span>
      </div>
    </article>`;
};

const renderSnippets = (snippets) => {
  state.currentSnippets = snippets || [];
  const grid = $("snippetGrid");
  if (!snippets || snippets.length === 0) {
    grid.classList.add("visually-hidden");
    $("emptyState").classList.remove("visually-hidden");
    return;
  }
  $("emptyState").classList.add("visually-hidden");
  grid.classList.remove("visually-hidden");
  grid.innerHTML = snippets.map(renderSnippet).join("");
};

const updateModalContent = (snippet, isLoading) => {
  const title = snippet.title || "Untitled snippet";
  const description = snippet.description || "No description provided.";
  const icon = getLangIcon(snippet.language);
  $("modalTitle").textContent = title;
  $("modalLang").innerHTML = `<i class="${icon}"></i> ${snippet.language || "Text"}`;
  $("modalLang").style.display = "none";
  $("modalDescription").textContent = description;
  $("modalDate").textContent = `Created ${timeAgo(snippet.created_at)} • ${new Date(snippet.created_at).toLocaleDateString()}`;
  $("modalTags").innerHTML = (snippet.tags || [])
    .map((tag) => `<span class="tag" onclick="closeModal(); handleSearch('${tag}')">#${tag}</span>`)
    .join("");
  $("modalUpvotes").textContent = snippet.upvote_count || 0;
  $("modalViews").textContent = snippet.view_count || 0;
  $("modalRefs").textContent = snippet.reference_count || 0;
  const codeEl = $("modalCode");
  const editor = $("modalCodeEditor");
  if (isLoading) {
    codeEl.textContent = "Loading code source...";
    if (editor) editor.value = "";
  } else {
    codeEl.textContent = snippet.code || "";
    codeEl.className = `language-${snippet.language || "text"}`;
    requestAnimationFrame(() => Prism.highlightElement(codeEl));
    if (editor) editor.value = snippet.code || "";
  }
};

const renderModalError = () => {
  $("modalContentArea").style.display = "none";
  $("modalLang").style.display = "none";
  document.querySelector(".modal__footer").style.display = "none";
  $("modalTags").innerHTML = "";
  $("modalTitle").textContent = "Snippet unavailable";
  const errorContainer = $("modalErrorState");
  errorContainer.innerHTML = `
    <div class="empty">
      <h3>Snippet not found</h3>
      <p>The snippet might have been removed or the link is broken.</p>
    </div>`;
  errorContainer.classList.remove("visually-hidden");
};
