const API_MIN_INTERVAL_MS = 3000;

let apiInFlight = false;
let lastResponseAt = 0;
let pendingRequest = null;
let cooldownTimer = null;
let timerInterval = null;

const buildApiUrl = (path) => `${API_URL}${path}`;

const updateApiTimer = () => {
  const indicator = $("apiIndicator");
  if (!indicator) return;
  if (apiInFlight) {
    indicator.dataset.state = "waiting";
    return;
  }
  if (!lastResponseAt) {
    indicator.dataset.state = "ready";
    return;
  }
  const remaining = Math.max(0, API_MIN_INTERVAL_MS - (Date.now() - lastResponseAt));
  if (remaining === 0) {
    indicator.dataset.state = "ready";
  } else {
    indicator.dataset.state = "cooldown";
  }
};

const startApiTimer = () => {
  if (timerInterval) return;
  timerInterval = setInterval(updateApiTimer, 1000);
  updateApiTimer();
};

const makeSupersededError = () => {
  const err = new Error("Superseded by a newer request.");
  err.code = "superseded";
  return err;
};

const mapApiError = (status, fallback) => {
  if (status === 429) return "Rate limited. Please wait before trying again.";
  if (status >= 500) return "Server error. Try again soon.";
  return fallback || "Request failed.";
};

const canSendNow = () => {
  if (apiInFlight) return false;
  if (!lastResponseAt) return true;
  return Date.now() - lastResponseAt >= API_MIN_INTERVAL_MS;
};

const runRequest = (request) => {
  apiInFlight = true;
  updateApiTimer();
  request.executor()
    .then(request.resolve)
    .catch(request.reject)
    .finally(() => {
      apiInFlight = false;
      lastResponseAt = Date.now();
      schedulePending();
      updateApiTimer();
    });
};

const schedulePending = () => {
  if (!pendingRequest || apiInFlight) return;
  const remaining = Math.max(0, API_MIN_INTERVAL_MS - (Date.now() - lastResponseAt));
  if (remaining === 0) {
    const request = pendingRequest;
    pendingRequest = null;
    runRequest(request);
    return;
  }
  if (cooldownTimer) return;
  cooldownTimer = setTimeout(() => {
    cooldownTimer = null;
    if (!pendingRequest) return;
    const request = pendingRequest;
    pendingRequest = null;
    runRequest(request);
  }, remaining);
};

const queueRequest = (executor) => {
  startApiTimer();
  return new Promise((resolve, reject) => {
    const request = { executor, resolve, reject };
    if (canSendNow()) {
      runRequest(request);
    } else {
      if (pendingRequest) {
        pendingRequest.reject(makeSupersededError());
      }
      pendingRequest = request;
      updateApiTimer();
      schedulePending();
    }
  });
};

const fetchJSON = (url, errMsg) =>
  queueRequest(async () => {
    const cacheKey = `etag:${url}`;
    const cached = sessionStorage.getItem(cacheKey);
    const cache = cached ? JSON.parse(cached) : null;
    const headers = cache?.etag ? { "If-None-Match": cache.etag } : {};
    const res = await fetch(url, { headers });
    if (res.status === 304 && cache?.data) return cache.data;
    if (!res.ok) throw new Error(mapApiError(res.status, errMsg));
    const data = await res.json();
    const etag = res.headers.get("ETag");
    if (etag) sessionStorage.setItem(cacheKey, JSON.stringify({ etag, data }));
    return data;
  });

const fetchRaw = (url, options, errMsg) =>
  queueRequest(async () => {
    const res = await fetch(url, options);
    if (!res.ok) throw new Error(mapApiError(res.status, errMsg));
    return res;
  });
