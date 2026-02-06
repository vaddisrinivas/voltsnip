const isLocal = ["localhost", "127.0.0.1"].includes(location.hostname) || location.protocol === "file:";
const API_URL = isLocal
  ? "http://localhost:8000"
  : "https://voltsnip-api.thetechcruise.com";

const $ = (id) => document.getElementById(id);
const $$ = (sel) => document.querySelectorAll(sel);

const state = {
  currentFeed: null,
  currentSnippets: [],
  searchTimeout: null,
  isEditingSnippet: false,
};

const languageIcons = {
  python: "devicon-python-plain",
  javascript: "devicon-javascript-plain",
  typescript: "devicon-typescript-plain",
  html: "devicon-html5-plain",
  css: "devicon-css3-plain",
  java: "devicon-java-plain",
  c: "devicon-c-plain",
  cpp: "devicon-cplusplus-plain",
  go: "devicon-go-original-wordmark",
  rust: "devicon-rust-plain",
  sql: "devicon-postgresql-plain",
  shell: "devicon-bash-plain",
  bash: "devicon-bash-plain",
  json: "devicon-vscode-plain",
  yaml: "devicon-vscode-plain",
  dockerfile: "devicon-docker-plain",
  markdown: "devicon-vscode-plain",
  swift: "devicon-swift-plain",
  kotlin: "devicon-kotlin-plain",
  ruby: "devicon-ruby-plain",
  php: "devicon-php-plain",
};

const defaultLangIcon = "devicon-vscode-plain";

const FEED_LIMIT = 50;
const SEARCH_LIMIT = 20;
const RECENT_THRESHOLD_MS = 24 * 60 * 60 * 1000;
const SNIPPET_CACHE_TTL_MS = 5 * 60 * 1000;

const THEME_LIGHT = "ember";
const THEME_DARK = "noir";

const ACCENT_PRESETS = [
  { name: "cobalt", light: "#1d4ed8", dark: "#60a5fa", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "emerald", light: "#047857", dark: "#34d399", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "rose", light: "#be123c", dark: "#fb7185", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "amber", light: "#b45309", dark: "#fbbf24", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "violet", light: "#6d28d9", dark: "#a78bfa", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "slate", light: "#64748b", dark: "#94a3b8", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "stone", light: "#71717a", dark: "#a8a8b3", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "teal", light: "#0f766e", dark: "#2dd4bf", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "indigo", light: "#4338ca", dark: "#818cf8", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "sky", light: "#0369a1", dark: "#38bdf8", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "mint", light: "#0f766e", dark: "#6ee7b7", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "lime", light: "#4d7c0f", dark: "#a3e635", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "orange", light: "#c2410c", dark: "#fb923c", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "coral", light: "#c2414c", dark: "#fb7185", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "magenta", light: "#a21caf", dark: "#f472b6", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "plum", light: "#7e22ce", dark: "#c084fc", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "cyan", light: "#0e7490", dark: "#22d3ee", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "petrol", light: "#0f4c5c", dark: "#3b82f6", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "bronze", light: "#92400e", dark: "#d97706", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "forest", light: "#166534", dark: "#4ade80", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "peach", light: "#c2410c", dark: "#fdba74", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "gold", light: "#a16207", dark: "#facc15", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "cherry", light: "#9f1239", dark: "#fb7185", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "ocean", light: "#155e75", dark: "#22d3ee", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "midnight", light: "#1e3a8a", dark: "#7c83ff", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "graphite", light: "#374151", dark: "#9ca3af", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "sunflower", light: "#b45309", dark: "#fcd34d", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "lagoon", light: "#0f766e", dark: "#38bdf8", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "moss", light: "#3f6212", dark: "#84cc16", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "ruby", light: "#9f1239", dark: "#f43f5e", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "orchid", light: "#a21caf", dark: "#f0abfc", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "sand", light: "#8a5a00", dark: "#f4d06f", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "clay", light: "#7c2d12", dark: "#fdba74", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "smoke", light: "#4b5563", dark: "#cbd5f5", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "ice", light: "#0e7490", dark: "#7dd3fc", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "berry", light: "#9d174d", dark: "#f472b6", lightContrast: "#ffffff", darkContrast: "#0a0a0a" },
  { name: "copper", light: "#9a3412", dark: "#fbbf24", lightContrast: "#ffffff", darkContrast: "#0a0a0a" }
];

const hexToRgba = (value, alpha) => {
  const r = parseInt(value.slice(1, 3), 16);
  const g = parseInt(value.slice(3, 5), 16);
  const b = parseInt(value.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

const applyRandomAccent = () => {
  const stored = sessionStorage.getItem("accentTheme");
  const preset = ACCENT_PRESETS.find((item) => item.name === stored)
    || ACCENT_PRESETS[Math.floor(Math.random() * ACCENT_PRESETS.length)];
  sessionStorage.setItem("accentTheme", preset.name);
  const root = document.documentElement;
  root.style.setProperty("--accent-light", preset.light);
  root.style.setProperty("--accent-dark", preset.dark);
  root.style.setProperty("--accent-light-contrast", preset.lightContrast);
  root.style.setProperty("--accent-dark-contrast", preset.darkContrast);
  root.style.setProperty("--glow-light", `0 0 0 3px ${hexToRgba(preset.light, 0.15)}`);
  root.style.setProperty("--glow-dark", `0 0 0 3px ${hexToRgba(preset.dark, 0.18)}`);
};
