/* ============================================================================
 * Prompt Attack Annotation Platform — shared browser runtime (window.App)
 *
 * Plain ES2020, no build step, no framework. Every helper renders markup with
 * inline `style` attributes; the single <style id="pa-base"> block injected at
 * startup holds only what inline styles cannot express (keyframes, pseudo
 * elements, :hover / :focus states keyed by data-hover presets, media queries).
 *
 * Sections:
 *   1. tokens & constants        5. toast / tooltip
 *   2. icons                     6. modal / confirm / popconfirm
 *   3. small helpers & fmt       7. ui atoms (pills, inputs, switch, …)
 *   4. session & api client      8. table / pagination / tabs
 *                                9. shell (sidebar + header + content)
 * ========================================================================== */
(function () {
  "use strict";

  /* ── 1. Tokens & constants ─────────────────────────────────────────────── */
  const API_BASE = "/api/v1";
  const TOKEN_KEY = "pa_token";
  const PROFILE_KEY = "pa_profile";
  const SIDEBAR_KEY = "sidebarCollapsed";
  const SIDEBAR_EXPANDED = 268;
  const SIDEBAR_COLLAPSED = 88;
  const SIDEBAR_GAP = 16;
  const BRAND = "#2b2c7c";

  const FONT = '"Segoe UI", Tahoma, Geneva, Verdana, sans-serif';
  const MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
  // Plain white surfaces everywhere: solid backgrounds, light grey borders and soft
  // shadows (no gradients / backdrop blur) so text stays clearly readable.
  const BODY_BG = "#ffffff";
  const GLASS_BASE = "background:#ffffff;border:1px solid #e2e8f0;";
  const GLASS = GLASS_BASE + "box-shadow:0 1px 3px rgba(15,23,42,0.06);border-radius:18px;";
  const GLASS_STRONG = GLASS_BASE + "box-shadow:0 2px 8px rgba(15,23,42,0.08);";
  const GLASS_FIELD = "background:#ffffff;border:1px solid #e2e8f0;box-shadow:0 1px 2px rgba(15,23,42,0.04);";
  const MODAL_CONTENT =
    "background:#ffffff;border:1px solid #e2e8f0;box-shadow:0 30px 70px rgba(15,23,42,0.18);" +
    "border-radius:16px;overflow:hidden;";
  const MODAL_MASK = "background:rgba(30,32,60,0.28);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);";

  const INPUT_STYLE =
    "display:block;box-sizing:border-box;width:100%;height:36px;padding:0 11px;border:1px solid #cbd5e1;border-radius:8px;background:#fff;outline:none;" +
    "color:#0f172a;font-size:14px;font-family:inherit;transition:border-color .15s, box-shadow .15s;";

  // Sidebar / permission metadata (spec 2.2). `profile` is always shown last.
  const FEATURE_META = {
    dashboard: { order: 1, key: "dashboard", label: "Dashboard", page: "dashboard.html", icon: "AiOutlineDashboard" },
    projects: { order: 2, key: "projects", label: "Projects", page: "projects.html", icon: "AiOutlineProject" },
    queues: { order: 3, key: "queues", label: "Queues", page: "queues.html", icon: "AiOutlineInbox" },
    tasks: { order: 4, key: "tasks", label: "Tasks", page: "tasks.html", icon: "AiOutlineUnorderedList" },
    roles: { order: 5, key: "roles", label: "Roles", page: "roles.html", icon: "AiOutlineSafetyCertificate" },
    users: { order: 6, key: "users", label: "Users", page: "users.html", icon: "AiOutlineTeam" },
    annotation_queues: { order: 7, key: "annotation_queues", label: "Annotation Queues", page: "annotation-queues.html", icon: "AiOutlineForm" },
    profile: { order: 8, key: "profile", label: "Profile", page: "profile.html", icon: "AiOutlineUser" },
  };
  // Pages that highlight a different sidebar item than their own file name.
  const PAGE_ALIASES = { "queue-tasks": "queues" };

  const STATUS_MESSAGES = {
    400: "Invalid request.",
    401: "Session expired — please sign in again.",
    403: "You do not have permission to perform this action.",
    404: "Not found.",
    409: "Conflict — this resource was changed elsewhere.",
    413: "Payload too large.",
    422: "The server could not process the request.",
    429: "Too many requests — please slow down.",
    500: "Server error — please try again.",
    502: "Gateway error — please try again.",
    503: "Service temporarily unavailable.",
    504: "The server took too long to respond.",
  };

  // Pill tones: bg / text / border / dot.
  const TONES = {
    slate: { bg: "#f8fafc", text: "#475569", border: "#e2e8f0", dot: "#94a3b8" },
    blue: { bg: "#eff6ff", text: "#1d4ed8", border: "#bfdbfe", dot: "#3b82f6" },
    orange: { bg: "#fff7ed", text: "#c2410c", border: "#fed7aa", dot: "#f97316" },
    purple: { bg: "#faf5ff", text: "#7e22ce", border: "#e9d5ff", dot: "#a855f7" },
    emerald: { bg: "#ecfdf5", text: "#047857", border: "#a7f3d0", dot: "#10b981" },
    rose: { bg: "#fff1f2", text: "#be123c", border: "#fecdd3", dot: "#f43f5e" },
    amber: { bg: "#fffbeb", text: "#b45309", border: "#fde68a", dot: "#f59e0b" },
    indigo: { bg: "#eef2ff", text: "#3730a3", border: "#c7d2fe", dot: "#6366f1" },
  };
  const STATUS_TONES = {
    pending: "slate", inactive: "slate", skipped: "slate",
    active: "blue", in_progress: "blue",
    paused: "orange",
    submitted: "purple", in_review: "purple",
    approved: "emerald", completed: "emerald",
    rejected: "rose", declined: "rose",
    returned: "amber", assigned: "amber",
  };
  const PRIORITY_TONES = { low: "emerald", medium: "blue", high: "amber", critical: "rose" };
  const ICON_TONES = {
    blue: { bg: "#eff6ff", color: "#2563eb" },
    amber: { bg: "#fffbeb", color: "#d97706" },
    emerald: { bg: "#ecfdf5", color: "#059669" },
    indigo: { bg: "#eef2ff", color: "#4f46e5" },
  };

  /* ── The single stylesheet: keyframes, pseudo elements, states, media ──── */
  const BASE_CSS = [
    "@keyframes spin{to{transform:rotate(360deg)}}",
    "@keyframes modal-in{from{opacity:0;transform:scale(.96)}to{opacity:1;transform:scale(1)}}",
    "@keyframes toast-in{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:translateY(0)}}",
    "@keyframes shimmer{0%{background-position:100% 50%}100%{background-position:0 50%}}",
    "::placeholder{color:#94a3b8;opacity:1}",
    "::-webkit-scrollbar{width:8px;height:8px}::-webkit-scrollbar-track{background:transparent}",
    "::-webkit-scrollbar-thumb{background:rgba(100,116,139,.35);border-radius:8px}::-webkit-scrollbar-thumb:hover{background:rgba(100,116,139,.55)}",
    "[data-hover=row]:hover>td{background:rgba(248,250,252,.5)}",
    "[data-hover=navitem]:not([data-selected]):hover{background:rgba(43,44,124,.08)!important}",
    "[data-hover=navitem]:not([data-selected]):active{background:rgba(43,44,124,.10)!important}",
    "[data-hover=btn-default]:hover:not(:disabled){border-color:#1d4ed8!important;color:#1d4ed8!important}",
    "[data-hover=infobtn]:hover,[data-hover=infobtn][aria-expanded=true]{border-color:#1d4ed8!important;background:#eff6ff!important}",
    "[data-hover=btn-primary]:hover:not(:disabled){background:#1e40af!important}",
    "[data-hover=btn-modal-primary]:hover:not(:disabled){background:#1d4ed8!important}",
    "[data-hover=btn-emerald]:hover:not(:disabled){background:#047857!important}",
    "[data-hover=btn-danger]:hover:not(:disabled){background:#b91c1c!important}",
    "[data-hover=btn-danger-outline]:hover:not(:disabled){background:#fef2f2!important;border-color:#dc2626!important;color:#b91c1c!important}",
    "[data-hover=btn-cancel]:hover:not(:disabled){background:#f1f5f9!important}",
    "[data-hover=btn-text]:hover:not(:disabled){background:#f1f5f9!important}",
    "[data-hover=btn-danger-text]:hover:not(:disabled){background:#fff1f2!important;color:#e11d48!important}",
    "[data-hover=chip]:hover{border-color:#cbd5e1!important;background:#fff!important;box-shadow:0 10px 15px -3px rgba(0,0,0,.1),0 4px 6px -4px rgba(0,0,0,.1)}",
    "[data-hover=chip]:hover [data-chevron]{transform:rotate(180deg)}",
    "[data-hover=menuitem]:hover{background:#f1f5f9!important}",
    "[data-hover=pagitem]:hover:not(:disabled):not([data-active]){border-color:#1d4ed8!important;color:#1d4ed8!important}",
    "[data-hover=tab]:not([data-active]):hover{background:#f8fafc!important}",
    "[data-hover=fieldfocus]:focus,[data-hover=fieldfocus]:focus-within{outline:none;border-color:#1d4ed8!important;box-shadow:0 0 0 2px rgba(29,78,216,.12)!important}",
    "[data-hover=tile]:hover{transform:translateY(-2px)}",
    "[data-hover=link]:hover{text-decoration:underline!important}",
    "[data-hover=close]:hover{color:#475569!important}",
    "[data-hover=dropzone]:hover{border-color:#1d4ed8!important;background:#eff6ff!important}",
    "@media (max-width:768px){[data-hide=md]{display:none!important}}",
    "@media (max-width:640px){[data-hide=sm]{display:none!important}}",
  ].join("\n");

  function injectBaseStyle() {
    if (document.getElementById("pa-base")) return;
    const style = document.createElement("style");
    style.id = "pa-base";
    style.textContent = BASE_CSS;
    (document.head || document.documentElement).appendChild(style);
  }
  injectBaseStyle();

  /* ── 2. Icons (extracted from react-icons; keys used verbatim) ─────────── */
  // Icon table lives in js/icons.js (loaded before this file) so it caches separately.
  const ICONS = window.PA_ICONS || {};

  // The two non-AntDesign glyphs were exported with the Ant 1024 viewBox but
  // carry 24-unit paths: give them the geometry they were drawn for.
  if (ICONS.HiOutlineChevronDown) {
    Object.assign(ICONS.HiOutlineChevronDown, {
      viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2,
      strokeLinecap: "round", strokeLinejoin: "round",
    });
  }
  if (ICONS.BiLogOutCircle) ICONS.BiLogOutCircle.viewBox = "0 0 24 24";

  const warnedIcons = new Set();

  /**
   * icon(name, {size=16, color, style=""}) → inline-styled <span><svg/></span>.
   * Unknown names render an empty span (warned once per name).
   */
  function icon(name, opts) {
    const o = opts || {};
    const size = o.size == null ? 16 : o.size;
    const base =
      "display:inline-flex;align-items:center;justify-content:center;line-height:0;font-size:" + size + "px;" +
      (o.color ? "color:" + o.color + ";" : "") + (o.style || "");
    const def = ICONS[name];
    if (!def) {
      if (!warnedIcons.has(name)) {
        warnedIcons.add(name);
        console.warn("[App.icon] unknown icon: " + name);
      }
      return '<span style="' + base + '"></span>';
    }
    let attrs = ' viewBox="' + def.viewBox + '" fill="' + (def.fill || "currentColor") + '" width="1em" height="1em"';
    if (def.stroke) attrs += ' stroke="' + def.stroke + '"';
    if (def.strokeWidth != null) attrs += ' stroke-width="' + def.strokeWidth + '"';
    if (def.strokeLinecap) attrs += ' stroke-linecap="' + def.strokeLinecap + '"';
    if (def.strokeLinejoin) attrs += ' stroke-linejoin="' + def.strokeLinejoin + '"';
    return '<span style="' + base + '"><svg' + attrs + ' aria-hidden="true">' + def.inner + "</svg></span>";
  }

  /* ── 3. Small helpers & formatting ─────────────────────────────────────── */
  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  /** el(html) → the first element of the parsed html string. */
  function el(html) {
    const t = document.createElement("template");
    t.innerHTML = String(html).trim();
    return t.content.firstElementChild;
  }

  const qs = (sel, root) => (root || document).querySelector(sel);
  const qsa = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  function debounce(fn, ms) {
    let t = null;
    const wrapped = function () {
      const args = arguments;
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), ms == null ? 300 : ms);
    };
    wrapped.cancel = () => clearTimeout(t);
    return wrapped;
  }

  /** Replace a container's content with an html string, Node or nothing. */
  function fill(target, content) {
    if (!target) return;
    target.innerHTML = "";
    if (content == null || content === false) return;
    if (content instanceof Node) target.appendChild(content);
    else target.innerHTML = String(content);
  }

  function toDate(v) {
    if (!v) return null;
    const d = v instanceof Date ? v : new Date(v);
    return isNaN(d.getTime()) ? null : d;
  }
  const pad2 = (n) => String(n).padStart(2, "0");

  const fmt = {
    /** "Jun 05, 2026" */
    date(iso) {
      const d = toDate(iso);
      return d ? d.toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" }) : "—";
    },
    /** "Jun 5, 2026, 05:19 PM" (pinned to en-US like fmt.date so output is deterministic) */
    dateTime(iso) {
      const d = toDate(iso);
      return d
        ? d.toLocaleString("en-US", { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
        : "—";
    },
    /** "17:19" */
    time(iso) {
      const d = toDate(iso);
      return d ? pad2(d.getHours()) + ":" + pad2(d.getMinutes()) : "—";
    },
    /** 330 → "5m 30s", 300 → "5m", falsy → "—" */
    timer(seconds) {
      if (!seconds) return "—";
      const s = Math.max(0, Math.round(Number(seconds) || 0));
      const m = Math.floor(s / 60);
      const r = s % 60;
      return r ? m + "m " + r + "s" : m + "m";
    },
    bytes(n) {
      const v = Number(n) || 0;
      if (v < 1024) return v + " B";
      const units = ["KB", "MB", "GB", "TB"];
      let x = v / 1024;
      let i = 0;
      while (x >= 1024 && i < units.length - 1) { x /= 1024; i += 1; }
      return (x >= 10 ? Math.round(x) : Math.round(x * 10) / 10) + " " + units[i];
    },
    /** "just now" / "5m ago" / "3h ago" / "2d ago", older → fmt.date */
    relative(iso) {
      const d = toDate(iso);
      if (!d) return "—";
      const diff = Math.max(0, Date.now() - d.getTime()) / 1000;
      if (diff < 60) return "just now";
      if (diff < 3600) return Math.floor(diff / 60) + "m ago";
      if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
      if (diff < 7 * 86400) return Math.floor(diff / 86400) + "d ago";
      return fmt.date(d);
    },
  };

  /* ── 4. Session & API client ───────────────────────────────────────────── */
  function storageGet(store, key) { try { return store.getItem(key); } catch (e) { return null; } }
  function storageSet(store, key, value) { try { store.setItem(key, value); } catch (e) { /* private mode */ } }
  function storageRemove(store, key) { try { store.removeItem(key); } catch (e) { /* ignore */ } }

  const getToken = () => storageGet(sessionStorage, TOKEN_KEY) || null;
  const setToken = (t) => (t ? storageSet(sessionStorage, TOKEN_KEY, t) : storageRemove(sessionStorage, TOKEN_KEY));
  function getProfile() {
    const raw = storageGet(sessionStorage, PROFILE_KEY);
    if (!raw) return null;
    try { return JSON.parse(raw); } catch (e) { return null; }
  }
  const setProfile = (p) => storageSet(sessionStorage, PROFILE_KEY, JSON.stringify(p));
  function clearSession() {
    storageRemove(sessionStorage, TOKEN_KEY);
    storageRemove(sessionStorage, PROFILE_KEY);
    storageRemove(localStorage, "loginType");
  }

  /** Normalise a /auth/me payload (+ optional login response) into the stored profile shape. */
  function hydrateProfile(profile, loginResponse) {
    const p = profile || {};
    const lr = loginResponse || {};
    return Object.assign({}, p, {
      permissions: lr.permissions || p.permissions || [],
      role_name: p.role_name || (lr.role && lr.role.name) || (p.assigned_role && p.assigned_role.name) || "Administrator",
    });
  }

  function buildError(message, status, payload) {
    const err = new Error(message);
    err.status = status;
    err.payload = payload;
    return err;
  }

  // Single-flight refresh: the refresh cookie rotates on every call, so
  // concurrent 401s must share exactly one POST /auth/refresh.
  let refreshPromise = null;
  function refreshAccessToken() {
    if (!refreshPromise) {
      refreshPromise = (async () => {
        const run = async () => {
          try {
            const res = await fetch(API_BASE + "/auth/refresh", { method: "POST", credentials: "include" });
            if (!res.ok) return null;
            const data = await res.json().catch(() => null);
            const token = data && data.access_token;
            if (!token) return null;
            setToken(token);
            return token;
          } catch (e) {
            return null;
          }
        };
        try {
          // The refresh cookie is shared by every tab of this browser. A Web Lock
          // serialises refreshes across tabs so two tabs never race on the same
          // rotating token (the server also tolerates a short overlap).
          if (navigator.locks && typeof navigator.locks.request === "function") {
            return await navigator.locks.request("pa-auth-refresh", run);
          }
          return await run();
        } finally {
          refreshPromise = null;
        }
      })();
    }
    return refreshPromise;
  }

  function expireSession() {
    clearSession();
    if (!/index\.html$/.test(location.pathname) && !/\/$/.test(location.pathname)) {
      location.replace("index.html");
    }
  }

  /**
   * api(path, {method, body, headers, raw, auth}) → parsed JSON / text / Response.
   * Plain-object bodies are sent as JSON; FormData/Blob pass through untouched.
   * A 401 on an authenticated request triggers one silent refresh + replay;
   * if that fails the session is cleared and the browser goes to index.html
   * (unless opts.redirectOnAuthFail === false).
   */
  async function api(path, opts) {
    const o = opts || {};
    const method = (o.method || "GET").toUpperCase();
    const auth = o.auth !== false;
    const headers = Object.assign({}, o.headers || {});
    const token = auth ? getToken() : null;
    if (token) headers.Authorization = "Bearer " + token;

    let body = o.body;
    const isPlainObject =
      body && typeof body === "object" && !(body instanceof FormData) && !(body instanceof Blob) &&
      !(body instanceof URLSearchParams) && !(body instanceof ArrayBuffer);
    if (isPlainObject) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(body);
    }

    let res;
    try {
      res = await fetch(API_BASE + path, { method, headers, body, credentials: "include" });
    } catch (networkErr) {
      const msg = networkErr && networkErr.message;
      throw buildError(
        !msg || /Failed to fetch|NetworkError|Load failed/i.test(msg) ? "Network error — unable to reach server." : msg,
        0,
        null,
      );
    }

    // Server busy (admission control shed the request): wait for Retry-After
    // and replay once. Autosaves and heartbeats ride through a short spike
    // without surfacing an error to the annotator.
    if (res.status === 503 && !o._retried503) {
      const wait = Math.min(10, Math.max(1, Number(res.headers.get("retry-after")) || 2)) * 1000;
      await new Promise((resolve) => setTimeout(resolve, wait));
      return api(path, Object.assign({}, o, { _retried503: true }));
    }

    // Expired access token → refresh once and replay with the new bearer.
    if (res.status === 401 && auth && token) {
      if (!o._retry) {
        // Another request may already have rotated the token while this one was in flight:
        // replay with the newer bearer instead of starting a second refresh (mirrors apiClient.js).
        const current = getToken();
        if (current && current !== token) return api(path, Object.assign({}, o, { _retry: true }));
        const fresh = await refreshAccessToken();
        if (fresh) return api(path, Object.assign({}, o, { _retry: true }));
      }
      if (o.redirectOnAuthFail !== false) expireSession();
    }

    if (o.raw && res.ok) return res;

    const contentType = res.headers.get("content-type") || "";
    const isJson = contentType.includes("application/json");
    let payload = null;
    try {
      payload = isJson ? await res.json() : res.status === 204 ? null : await res.text();
    } catch (e) {
      payload = null;
    }

    if (!res.ok) {
      let detail = isJson && payload ? payload.detail || payload.message : null;
      if (Array.isArray(detail)) {
        // FastAPI validation errors: [{loc, msg}] → "field: msg"
        detail = detail
          .map((d) => (d && d.msg ? (d.loc ? d.loc.slice(-1)[0] + ": " : "") + d.msg : String(d)))
          .join("; ");
      } else if (detail && typeof detail === "object") {
        detail = detail.message || JSON.stringify(detail);
      }
      const message =
        detail || (typeof payload === "string" && payload) || STATUS_MESSAGES[res.status] ||
        "Request failed (" + res.status + ")";
      throw buildError(message, res.status, payload);
    }
    return payload;
  }

  /** Authenticated file download; honours Content-Disposition file names. */
  async function download(path, fallbackName) {
    const res = await api(path, { raw: true });
    const cd = res.headers.get("content-disposition") || "";
    let name = fallbackName || "download";
    const star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
    const plain = /filename="?([^";]+)"?/i.exec(cd);
    if (star) {
      try { name = decodeURIComponent(star[1]); } catch (e) { name = star[1]; }
    } else if (plain) {
      name = plain[1];
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.rel = "noopener";
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    a.remove();
    // Revoking the object URL while the browser is still writing the file cancels
    // the download and leaves an "Unconfirmed ....crdownload" behind for large
    // exports. Keep the URL alive well past any realistic write time.
    setTimeout(() => URL.revokeObjectURL(url), 5 * 60 * 1000);
    return name;
  }

  /** taxonomy() → the annotation taxonomy, cached per browser session for an
   *  hour: it is static configuration, and every workspace open would
   *  otherwise re-download it. */
  const TAXONOMY_KEY = "pa:taxonomy:v1";
  const TAXONOMY_TTL_MS = 60 * 60 * 1000;
  let taxonomyPromise = null;
  function taxonomy() {
    if (taxonomyPromise) return taxonomyPromise;
    try {
      const raw = sessionStorage.getItem(TAXONOMY_KEY);
      if (raw) {
        const cached = JSON.parse(raw);
        if (cached && cached.exp > Date.now() && cached.data) return Promise.resolve(cached.data);
      }
    } catch (e) { /* storage unavailable */ }
    taxonomyPromise = api("/annotation/taxonomy")
      .then((data) => {
        try { sessionStorage.setItem(TAXONOMY_KEY, JSON.stringify({ exp: Date.now() + TAXONOMY_TTL_MS, data })); } catch (e) { /* ignore */ }
        return data;
      })
      .finally(() => { taxonomyPromise = null; });
    return taxonomyPromise;
  }

  /** upload(file) → {file_url, file_name, file_type} */
  function upload(file) {
    const fd = new FormData();
    fd.append("file", file, file.name);
    return api("/upload/", { method: "POST", body: fd });
  }

  /** Silent restore: stored session, else refresh cookie → /auth/me. Never redirects. */
  async function tryRestoreSession() {
    const stored = getProfile();
    if (getToken() && stored) return stored;
    const token = await refreshAccessToken();
    if (!token) return null;
    try {
      const me = await api("/auth/me", { redirectOnAuthFail: false });
      const profile = hydrateProfile(me);
      setProfile(profile);
      return profile;
    } catch (e) {
      return null;
    }
  }

  /** ensureSession() → profile, or redirects to index.html and never resolves. */
  async function ensureSession() {
    const profile = await tryRestoreSession();
    if (profile) return profile;
    clearSession();
    location.replace("index.html");
    return new Promise(() => {});
  }

  function orderedFeatures(perms) {
    return (perms || [])
      .filter((k) => !!FEATURE_META[k])
      .sort((a, b) => FEATURE_META[a].order - FEATURE_META[b].order);
  }

  function firstFeaturePage(perms) {
    const ordered = orderedFeatures(perms);
    return ordered.length ? FEATURE_META[ordered[0]].page : "dashboard.html";
  }

  function currentPageFile() {
    const file = (location.pathname.split("/").pop() || "").toLowerCase();
    return file || "index.html";
  }

  /** Redirect away when the stored profile lacks `key` ("profile" is always allowed). */
  function requirePermission(key) {
    if (key === "profile") return true;
    const profile = getProfile() || {};
    const perms = profile.permissions || [];
    if (perms.includes(key)) return true;
    let target = firstFeaturePage(perms);
    if (target === currentPageFile()) target = "profile.html"; // never bounce to ourselves
    location.replace(target);
    return false;
  }

  async function logout() {
    try {
      await api("/auth/logout", { method: "POST", redirectOnAuthFail: false });
    } catch (e) {
      /* the session is going away regardless */
    }
    clearSession();
    location.replace("index.html");
  }

  /* ── 5. Toast & tooltip ────────────────────────────────────────────────── */
  const TOAST_ICONS = {
    success:
      '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><circle cx="8" cy="8" r="8" fill="#52c41a"/><path d="M4.5 8.2l2.3 2.3 4.7-4.9" stroke="#fff" stroke-width="1.6" fill="none" stroke-linecap="round"/></svg>',
    error:
      '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><circle cx="8" cy="8" r="8" fill="#ff4d4f"/><path d="M5.2 5.2l5.6 5.6M10.8 5.2l-5.6 5.6" stroke="#fff" stroke-width="1.6" stroke-linecap="round"/></svg>',
    warning:
      '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><circle cx="8" cy="8" r="8" fill="#faad14"/><path d="M8 4v5" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/><circle cx="8" cy="11.6" r="1" fill="#fff"/></svg>',
    info:
      '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><circle cx="8" cy="8" r="8" fill="#1677ff"/><path d="M8 7v5" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/><circle cx="8" cy="4.4" r="1" fill="#fff"/></svg>',
  };

  function toastRoot() {
    let root = document.getElementById("pa-toast-root");
    if (!root) {
      root = el(
        '<div id="pa-toast-root" aria-live="polite" style="position:fixed;top:16px;left:0;right:0;z-index:3000;display:flex;flex-direction:column;align-items:center;gap:8px;pointer-events:none"></div>',
      );
      document.body.appendChild(root);
    }
    return root;
  }

  function pushToast(type, msg, duration) {
    const notice = el(
      '<div style="display:inline-flex;align-items:center;gap:8px;background:#fff;border-radius:10px;' +
        "box-shadow:0 6px 24px rgba(15,23,42,.16), 0 1px 4px rgba(15,23,42,.08);padding:9px 14px;font-size:13.5px;color:#0f172a;" +
        'animation:toast-in .2s ease-out;pointer-events:auto;max-width:min(480px, calc(100vw - 32px));font-family:' + FONT + '">' +
        '<span style="display:inline-flex;flex-shrink:0;line-height:0">' + (TOAST_ICONS[type] || TOAST_ICONS.info) + "</span>" +
        "<span>" + escapeHtml(msg) + "</span></div>",
    );
    toastRoot().appendChild(notice);
    const ms = (duration == null ? 3 : duration) * 1000;
    const remove = () => notice.remove();
    if (ms > 0) setTimeout(remove, ms);
    return remove;
  }
  const toast = {
    success: (m, d) => pushToast("success", m, d),
    error: (m, d) => pushToast("error", m, d),
    warning: (m, d) => pushToast("warning", m, d),
    info: (m, d) => pushToast("info", m, d),
  };

  // Global tooltip: one floating element, delegated on [data-tip] anchors.
  let tipEl = null;
  let tipAnchor = null;
  let tipTimer = null;

  function positionFloating(node, rect, place, offset) {
    const w = node.offsetWidth;
    const h = node.offsetHeight;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let p = place;
    if (p === "bottom" && rect.bottom + offset + h > vh && rect.top - offset - h >= 0) p = "top";
    if (p === "top" && rect.top - offset - h < 0 && rect.bottom + offset + h <= vh) p = "bottom";
    let left;
    let top;
    if (p === "right") { left = rect.right + offset; top = rect.top + rect.height / 2 - h / 2; }
    else if (p === "left") { left = rect.left - offset - w; top = rect.top + rect.height / 2 - h / 2; }
    else if (p === "bottom") { left = rect.left + rect.width / 2 - w / 2; top = rect.bottom + offset; }
    else if (p === "bottomRight") { left = rect.right - w; top = rect.bottom + offset; }
    else { left = rect.left + rect.width / 2 - w / 2; top = rect.top - offset - h; }
    left = Math.max(4, Math.min(left, vw - w - 4));
    top = Math.max(4, Math.min(top, vh - h - 4));
    node.style.left = left + "px";
    node.style.top = top + "px";
  }

  function hideTip() {
    clearTimeout(tipTimer);
    tipAnchor = null;
    if (tipEl) { tipEl.remove(); tipEl = null; }
  }
  function showTip(anchor) {
    hideTip();
    const text = anchor.getAttribute("data-tip");
    if (!text) return;
    tipAnchor = anchor;
    tipTimer = setTimeout(() => {
      if (tipAnchor !== anchor || !document.body.contains(anchor)) return;
      tipEl = el(
        '<div role="tooltip" style="position:fixed;box-sizing:border-box;z-index:1070;max-width:280px;padding:5px 10px;border-radius:8px;background:rgba(15,23,42,.88);color:#fff;' +
          "font-size:12.5px;line-height:1.45;box-shadow:0 6px 16px rgba(0,0,0,.18);pointer-events:none;white-space:normal;font-family:" + FONT + '">' +
          escapeHtml(text) + "</div>",
      );
      document.body.appendChild(tipEl);
      positionFloating(tipEl, anchor.getBoundingClientRect(), anchor.getAttribute("data-tip-place") || "top", 6);
    }, 100);
  }

  function tooltipsInit() {
    if (tooltipsInit._done) return;
    tooltipsInit._done = true;
    const anchorOf = (t) => (t && t.closest ? t.closest("[data-tip]") : null);
    document.addEventListener("mouseover", (e) => {
      const a = anchorOf(e.target);
      if (a && a !== tipAnchor) showTip(a);
    });
    document.addEventListener("mouseout", (e) => {
      if (!tipAnchor) return;
      if (e.relatedTarget && tipAnchor.contains(e.relatedTarget)) return;
      if (anchorOf(e.target) === tipAnchor) hideTip();
    });
    document.addEventListener("focusin", (e) => { const a = anchorOf(e.target); if (a) showTip(a); });
    document.addEventListener("focusout", hideTip);
    document.addEventListener("mousedown", hideTip, true);
    document.addEventListener("scroll", hideTip, true);
    window.addEventListener("resize", hideTip);
  }

  /** tooltip(el, text) — attach (or update) a delegated tooltip. */
  function tooltip(node, text, place) {
    if (!node) return node;
    if (text) node.setAttribute("data-tip", text); else node.removeAttribute("data-tip");
    if (place) node.setAttribute("data-tip-place", place);
    tooltipsInit();
    return node;
  }

  /* ── 6. Modal / confirm / popconfirm ───────────────────────────────────── */
  let scrollLocks = 0;
  let bodyOverflowBefore = "";
  function lockScroll() {
    if (scrollLocks === 0) { bodyOverflowBefore = document.body.style.overflow; document.body.style.overflow = "hidden"; }
    scrollLocks += 1;
  }
  function unlockScroll() {
    scrollLocks = Math.max(0, scrollLocks - 1);
    if (scrollLocks === 0) document.body.style.overflow = bodyOverflowBefore;
  }

  const modalStack = [];
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || !modalStack.length) return;
    const top = modalStack[modalStack.length - 1];
    if (top.closable) { e.preventDefault(); top.close(); }
  });

  /**
   * modal({title, subtitle, icon, iconTone, width=520, body, footer, onClose, closable=true})
   * → {root, body, footer, close, setBody, setFooter}
   */
  function modal(cfg) {
    const c = cfg || {};
    const width = c.width == null ? 520 : c.width;
    const closable = c.closable !== false;
    const z = 1000 + modalStack.length * 10;
    const tone = ICON_TONES[c.iconTone] || ICON_TONES.blue;

    const root = el(
      '<div style="position:fixed;inset:0;z-index:' + z + ';font-family:' + FONT + '">' +
        '<div style="position:absolute;inset:0;' + MODAL_MASK + '"></div>' +
        '<div data-role="wrap" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:16px;overflow-y:auto">' +
        '<div role="dialog" aria-modal="true" style="position:relative;width:' + width + 'px;max-width:calc(100vw - 32px);animation:modal-in .18s ease-out">' +
        '<div style="position:relative;' + MODAL_CONTENT + '">' +
        (closable
          ? '<button type="button" data-role="close" data-hover="close" aria-label="Close" style="position:absolute;top:12px;right:14px;font-size:22px;line-height:1;color:#94a3b8;background:none;border:0;cursor:pointer;z-index:1;padding:0">×</button>'
          : "") +
        (c.title != null
          ? '<div style="padding:18px 22px 14px;border-bottom:1px solid #f1f5f9;display:flex;align-items:center;gap:12px">' +
            (c.icon
              ? '<div style="width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center;flex-shrink:0;background:' +
                tone.bg + ";color:" + tone.color + '">' + icon(c.icon, { size: 18 }) + "</div>"
              : "") +
            '<div style="min-width:0;padding-right:24px"><h3 style="margin:0;font-size:15px;font-weight:600;color:#0f172a;line-height:1.25">' +
            escapeHtml(c.title) + "</h3>" +
            (c.subtitle
              ? '<p style="margin:2px 0 0;font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.05em">' + escapeHtml(c.subtitle) + "</p>"
              : "") +
            "</div></div>"
          : "") +
        '<div data-role="body" style="box-sizing:border-box;padding:18px 22px;max-height:62vh;overflow-y:auto;font-size:14px;color:#334155"></div>' +
        '<div data-role="footer" style="padding:14px 22px;border-top:1px solid #f1f5f9;background:#fafbfc;display:flex;justify-content:flex-end;gap:8px"></div>' +
        "</div></div></div></div>",
    );
    const body = root.querySelector('[data-role="body"]');
    const footer = root.querySelector('[data-role="footer"]');
    const wrap = root.querySelector('[data-role="wrap"]');

    const setBody = (content) => fill(body, content);
    // Only an explicit `footer: null` (or false) hides the footer. Omitting it leaves an empty,
    // visible footer so pages can do `m.footer.appendChild(App.modalFooterButtons(...))`.
    const setFooter = (content) => {
      fill(footer, content);
      footer.style.display = content === null || content === false ? "none" : "flex";
    };
    setBody(c.body);
    setFooter(c.footer);
    if (typeof MutationObserver === "function") {
      new MutationObserver(() => {
        if (footer.childNodes.length && footer.style.display === "none") footer.style.display = "flex";
      }).observe(footer, { childList: true });
    }

    let closed = false;
    const handle = {
      root, body, footer, closable, setBody, setFooter,
      close() {
        if (closed) return;
        closed = true;
        const i = modalStack.indexOf(handle);
        if (i >= 0) modalStack.splice(i, 1);
        root.remove();
        unlockScroll();
        if (typeof c.onClose === "function") c.onClose();
      },
    };

    const closeBtn = root.querySelector('[data-role="close"]');
    if (closeBtn) closeBtn.addEventListener("click", handle.close);
    // Mask click honours the live `closable` flag (confirm() flips it on after creation).
    wrap.addEventListener("mousedown", (e) => { if (e.target === wrap && handle.closable) handle.close(); });

    lockScroll();
    modalStack.push(handle);
    document.body.appendChild(root);
    return handle;
  }

  /** confirm({title, content, okText, cancelText, danger}) → Promise<boolean> */
  function confirm(cfg) {
    const c = cfg || {};
    return new Promise((resolve) => {
      let settled = false;
      const done = (value, m) => {
        if (settled) return;
        settled = true;
        resolve(value);
        if (m) m.close();
      };
      const body =
        '<div style="display:flex;gap:12px;align-items:flex-start">' +
        icon("AiOutlineExclamationCircle", { size: 22, color: "#faad14", style: "flex-shrink:0;margin-top:1px" }) +
        '<div style="flex:1;min-width:0">' +
        (c.title ? '<div style="font-size:15px;font-weight:600;color:#0f172a;margin-bottom:6px">' + escapeHtml(c.title) + "</div>" : "") +
        (c.content != null ? '<div style="font-size:13.5px;color:#475569;line-height:1.55">' + (c.contentIsHtml ? c.content : escapeHtml(c.content)) + "</div>" : "") +
        "</div></div>";
      const m = modal({
        width: c.width || 420,
        closable: false,
        body,
        onClose: () => done(false),
      });
      // Esc still cancels a confirm even though it has no close "×".
      m.closable = true;
      const buttons = modalFooterButtons({
        cancelText: c.cancelText || "Cancel",
        okText: c.okText || "Confirm",
        okTone: c.danger ? "danger" : "blue",
        onCancel: () => done(false, m),
        onOk: () => done(true, m),
      });
      m.setFooter(buttons);
      setTimeout(() => buttons.okBtn.focus(), 0);
    });
  }

  /** popconfirm(anchorEl, {title, description, okText="Delete", cancelText="Cancel", danger=true}) → Promise<boolean> */
  function popconfirm(anchorEl, cfg) {
    const c = cfg || {};
    const danger = c.danger !== false;
    const smallBtn = "display:inline-flex;align-items:center;justify-content:center;height:24px;padding:0 8px;border-radius:6px;font-size:13px;font-family:inherit;cursor:pointer;white-space:nowrap;transition:.15s;";
    return new Promise((resolve) => {
      const pop = el(
        '<div role="dialog" style="position:fixed;z-index:1050;visibility:hidden;background:#fff;border:1px solid #e2e8f0;border-radius:12px;' +
          "box-shadow:0 12px 32px rgba(15,23,42,.16);padding:12px 14px;max-width:320px;box-sizing:border-box;font-family:" + FONT + ";color:#0f172a\">" +
          '<div style="display:flex;gap:8px;align-items:flex-start">' +
          icon("AiOutlineExclamationCircle", { size: 15, color: "#faad14", style: "margin-top:2px;flex-shrink:0" }) +
          "<div>" +
          (c.title ? '<div style="font-weight:600;font-size:13.5px;color:#0f172a">' + escapeHtml(c.title) + "</div>" : "") +
          (c.description ? '<div style="font-size:12.5px;color:#475569;margin-top:2px">' + escapeHtml(c.description) + "</div>" : "") +
          "</div></div>" +
          '<div style="display:flex;justify-content:flex-end;gap:8px;margin-top:10px">' +
          '<button type="button" data-role="cancel" data-hover="btn-default" style="' + smallBtn + 'border:1px solid #cbd5e1;background:#fff;color:#0f172a">' + escapeHtml(c.cancelText || "Cancel") + "</button>" +
          '<button type="button" data-role="ok" data-hover="' + (danger ? "btn-danger" : "btn-modal-primary") + '" style="' + smallBtn +
          "border:1px solid transparent;color:#fff;background:" + (danger ? "#dc2626" : "#2563eb") + '">' + escapeHtml(c.okText || "Delete") + "</button>" +
          "</div></div>",
      );
      document.body.appendChild(pop);
      const rect = anchorEl && anchorEl.getBoundingClientRect ? anchorEl.getBoundingClientRect() : { left: 0, right: 0, top: 0, bottom: 0, width: 0, height: 0 };
      positionFloating(pop, rect, "bottom", 6);
      pop.style.visibility = "visible";

      let settled = false;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        document.removeEventListener("mousedown", onOutside, true);
        document.removeEventListener("keydown", onKey, true);
        window.removeEventListener("scroll", onScroll, true);
        pop.remove();
        resolve(value);
      };
      const onOutside = (e) => {
        if (pop.contains(e.target)) return;
        if (anchorEl && anchorEl.contains && anchorEl.contains(e.target)) return;
        finish(false);
      };
      const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); finish(false); } };
      const onScroll = () => positionFloating(pop, anchorEl.getBoundingClientRect(), "bottom", 6);
      pop.querySelector('[data-role="cancel"]').addEventListener("click", () => finish(false));
      pop.querySelector('[data-role="ok"]').addEventListener("click", () => finish(true));
      // Register outside-click after the click that opened us has finished.
      setTimeout(() => {
        document.addEventListener("mousedown", onOutside, true);
        document.addEventListener("keydown", onKey, true);
        window.addEventListener("scroll", onScroll, true);
      }, 0);
    });
  }

  /* ── Buttons ───────────────────────────────────────────────────────────── */
  const SPINNER_1EM =
    '<span data-role="spinner" style="display:inline-block;width:1em;height:1em;border:2px solid currentColor;border-top-color:transparent;border-radius:50%;animation:spin .8s linear infinite;flex-shrink:0"></span>';

  /**
   * Disabled look (spec 2.1: opacity:.55; cursor:not-allowed) is applied INLINE rather than via a
   * global button:disabled rule. syncDisabledStyle() is called by setLoading/setDisabled and by a
   * document-wide observer so buttons that pages toggle with plain `.disabled = true` still match.
   */
  function syncDisabledStyle(btn) {
    if (!btn || btn.nodeType !== 1 || btn.tagName !== "BUTTON") return;
    if (btn.disabled) {
      if (btn.dataset.disabledStyled === "1") return;
      btn.dataset.disabledStyled = "1";
      btn.dataset.prevOpacity = btn.style.opacity;
      btn.dataset.prevCursor = btn.style.cursor;
      btn.style.opacity = ".55";
      btn.style.cursor = "not-allowed";
    } else if (btn.dataset.disabledStyled === "1") {
      delete btn.dataset.disabledStyled;
      btn.style.opacity = btn.dataset.prevOpacity || "";
      btn.style.cursor = btn.dataset.prevCursor || "";
      delete btn.dataset.prevOpacity;
      delete btn.dataset.prevCursor;
    }
  }
  function syncDisabledTree(node) {
    if (!node || node.nodeType !== 1) return;
    if (node.tagName === "BUTTON") syncDisabledStyle(node);
    if (node.querySelectorAll) node.querySelectorAll("button").forEach(syncDisabledStyle);
  }
  if (typeof MutationObserver === "function") {
    const disabledObserver = new MutationObserver((records) => {
      records.forEach((r) => {
        if (r.type === "attributes") syncDisabledStyle(r.target);
        else r.addedNodes.forEach(syncDisabledTree);
      });
    });
    const startObserving = () => {
      disabledObserver.observe(document.documentElement, {
        attributes: true, attributeFilter: ["disabled"], subtree: true, childList: true,
      });
      syncDisabledTree(document.body);
    };
    if (document.body) startObserving(); else document.addEventListener("DOMContentLoaded", startObserving, { once: true });
  }

  /** setLoading(btn, bool): prepend a 1em spinner and disable while loading. */
  function setLoading(btn, loading) {
    if (!btn) return;
    const existing = btn.querySelector(':scope > [data-role="spinner"]');
    if (loading) {
      if (!existing) btn.insertAdjacentHTML("afterbegin", SPINNER_1EM);
      btn.disabled = true;
      btn.setAttribute("aria-busy", "true");
      btn.dataset.loading = "1";
    } else {
      if (existing) existing.remove();
      delete btn.dataset.loading;
      btn.removeAttribute("aria-busy");
      btn.disabled = btn.dataset.disabled === "1";
    }
    syncDisabledStyle(btn);
  }
  function setDisabled(btn, disabled) {
    if (!btn) return;
    if (disabled) btn.dataset.disabled = "1"; else delete btn.dataset.disabled;
    btn.disabled = !!disabled || btn.dataset.loading === "1";
    syncDisabledStyle(btn);
  }

  const MODAL_BTN_BASE =
    "display:inline-flex;align-items:center;justify-content:center;gap:6px;height:36px;padding:0 16px;border-radius:8px;" +
    "font-size:14px;font-family:inherit;cursor:pointer;white-space:nowrap;transition:.15s;";
  const OK_TONES = {
    blue: { bg: "#2563eb", hover: "btn-modal-primary" },
    emerald: { bg: "#059669", hover: "btn-emerald" },
    danger: { bg: "#dc2626", hover: "btn-danger" },
  };

  /** modalFooterButtons({cancelText, okText, okTone, onCancel, onOk}) → Element with .okBtn/.cancelBtn */
  function modalFooterButtons(cfg) {
    const c = cfg || {};
    const tone = OK_TONES[c.okTone] || OK_TONES.blue;
    const wrap = el('<div style="display:flex;justify-content:flex-end;gap:8px"></div>');
    const cancelBtn = el(
      '<button type="button" data-hover="btn-cancel" style="' + MODAL_BTN_BASE + 'color:#475569;border:1px solid #e2e8f0;background:#fff">' +
        escapeHtml(c.cancelText || "Cancel") + "</button>",
    );
    const okBtn = el(
      '<button type="button" data-hover="' + tone.hover + '" style="' + MODAL_BTN_BASE + "font-weight:500;color:#fff;border:0;background:" + tone.bg + '">' +
        escapeHtml(c.okText || "Save") + "</button>",
    );
    cancelBtn.addEventListener("click", (e) => { if (typeof c.onCancel === "function") c.onCancel(e); });
    okBtn.addEventListener("click", (e) => { if (typeof c.onOk === "function") c.onOk(e); });
    wrap.appendChild(cancelBtn);
    wrap.appendChild(okBtn);
    wrap.okBtn = okBtn;
    wrap.cancelBtn = cancelBtn;
    return wrap;
  }

  /* ── 7. UI atoms ───────────────────────────────────────────────────────── */
  const PILL_BASE =
    "display:inline-flex;align-items:center;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;" +
    "text-transform:uppercase;letter-spacing:.05em;white-space:nowrap;line-height:1.5;";

  /** pill(text, tone, {dot}) */
  function pill(text, tone, opts) {
    const t = TONES[tone] || TONES.slate;
    const withDot = opts && opts.dot;
    return (
      '<span style="' + PILL_BASE + "border:1px solid " + t.border + ";background:" + t.bg + ";color:" + t.text + '">' +
      (withDot ? '<span style="width:6px;height:6px;border-radius:9999px;margin-right:6px;background:' + t.dot + ';flex-shrink:0"></span>' : "") +
      escapeHtml(text) + "</span>"
    );
  }
  function statusPill(status) {
    const key = String(status || "pending").toLowerCase();
    return pill(key, STATUS_TONES[key] || "slate", { dot: true });
  }
  function priorityPill(p) {
    const key = String(p || "medium").toLowerCase();
    return pill(key, PRIORITY_TONES[key] || "blue");
  }
  function typePill(t) {
    const key = String(t || "production").toLowerCase();
    return pill(key, key === "qa" ? "purple" : "blue");
  }
  function permChip(text) {
    return (
      '<span style="' + PILL_BASE.replace("padding:2px 8px", "padding:2px 6px") +
      'border:1px solid #e2e8f0;background:#f8fafc;color:#334155">' + escapeHtml(text) + "</span>"
    );
  }
  function slaBadge(hours) {
    return (
      '<span style="display:inline-flex;align-items:center;justify-content:center;font-family:' + MONO +
      ';font-weight:700;font-size:12px;background:#f1f5f9;color:#334155;padding:2px 8px;border-radius:4px">' +
      escapeHtml(hours == null ? "—" : hours + "h") + "</span>"
    );
  }
  function progress(pct, color, showInfo) {
    const v = Math.max(0, Math.min(100, Math.round(Number(pct) || 0)));
    return (
      '<div style="display:flex;align-items:center;gap:8px;width:100%">' +
      '<div style="flex:1;min-width:0;height:6px;border-radius:100px;background:rgba(148,163,184,0.25);overflow:hidden">' +
      '<div style="height:100%;border-radius:100px;background:' + (color || "#1d4ed8") + ";width:" + v + '%;transition:width .3s ease"></div></div>' +
      (showInfo ? '<span style="flex-shrink:0;font-size:12px;color:#475569;min-width:34px;text-align:right">' + v + "%</span>" : "") +
      "</div>"
    );
  }
  /** progressRing(pct, color, size, showLabel) → circular progress indicator; showLabel=false hides the centre percentage. */
  function progressRing(pct, color, size, showLabel) {
    const v = Math.max(0, Math.min(100, Math.round(Number(pct) || 0)));
    const s = size || 40;
    const stroke = Math.max(3, Math.round(s * 0.1));
    const r = (s - stroke) / 2;
    const c = 2 * Math.PI * r;
    const dash = (c * v) / 100;
    const fontSize = Math.max(9, Math.round(s * 0.26));
    return (
      '<span role="img" aria-label="' + v + '% complete" style="position:relative;display:inline-flex;align-items:center;justify-content:center;width:' + s + 'px;height:' + s + 'px;flex-shrink:0">' +
      '<svg width="' + s + '" height="' + s + '" viewBox="0 0 ' + s + ' ' + s + '" style="display:block;transform:rotate(-90deg)">' +
      '<circle cx="' + s / 2 + '" cy="' + s / 2 + '" r="' + r + '" fill="none" stroke="#e2e8f0" stroke-width="' + stroke + '"></circle>' +
      '<circle cx="' + s / 2 + '" cy="' + s / 2 + '" r="' + r + '" fill="none" stroke="' + (color || "#1d4ed8") + '" stroke-width="' + stroke + '" stroke-linecap="round" ' +
      'stroke-dasharray="' + dash.toFixed(2) + ' ' + (c - dash).toFixed(2) + '" style="transition:stroke-dasharray .3s ease"></circle>' +
      "</svg>" +
      (showLabel === false ? "" : '<span style="position:absolute;font-size:' + fontSize + 'px;font-weight:700;color:#0f172a;font-variant-numeric:tabular-nums;line-height:1">' + v + "%</span>") +
      "</span>"
    );
  }
  function avatarInitial(name, size) {
    const s = size || 32;
    const letter = String(name || "?").trim().charAt(0).toUpperCase() || "?";
    return (
      '<span style="width:' + s + "px;height:" + s + "px;font-size:" + Math.round(s * 0.42) + "px;border-radius:50%;background:#94a3b8;color:#fff;font-weight:600;" +
      'display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;overflow:hidden">' + escapeHtml(letter) + "</span>"
    );
  }
  function sectionLabel(text) {
    return '<div style="font-size:11px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:#334155">' + escapeHtml(text) + "</div>";
  }

  /**
   * infoButton({label}) → a small round "i" icon button for headers.
   * infoDropdown(btn, getRows) → toggles a fixed-position panel under `btn` listing
   * label/value rows. `getRows()` runs on every open and returns [{label, value, html}]
   * (value is escaped text; html is inserted as-is). The panel lives on <body> so a
   * header with overflow:auto never clips it. Closes on outside click, Escape, resize.
   */
  function infoButton(opts) {
    const o = opts || {};
    const btn = el(
      '<button type="button" aria-haspopup="dialog" aria-expanded="false" aria-label="' + escapeHtml(o.label || "Details") + '" title="' + escapeHtml(o.label || "Details") +
        '" data-hover="infobtn" style="display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;padding:0;border-radius:999px;border:1px solid #cbd5e1;background:#fff;color:#1d4ed8;cursor:pointer;flex-shrink:0;transition:.15s;vertical-align:middle">' +
        icon("AiOutlineInfoCircle", { size: 14, color: "#1d4ed8" }) + "</button>",
    );
    return btn;
  }
  function infoDropdown(btn, getRows) {
    let panel = null;
    const LABEL = "font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:#64748b;white-space:nowrap;padding-top:2px;";
    const VALUE = "font-size:13px;font-weight:600;color:#0f172a;word-break:break-word;min-width:0;";
    function close() {
      if (!panel) return;
      panel.remove();
      panel = null;
      btn.setAttribute("aria-expanded", "false");
    }
    function place() {
      if (!panel) return;
      const r = btn.getBoundingClientRect();
      const w = panel.offsetWidth || 280;
      const left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8));
      panel.style.top = Math.round(r.bottom + 6) + "px";
      panel.style.left = Math.round(left) + "px";
    }
    function open() {
      const rows = (typeof getRows === "function" ? getRows() : getRows) || [];
      panel = el(
        '<div role="dialog" aria-label="Details" style="position:fixed;z-index:70;min-width:260px;max-width:min(380px,calc(100vw - 16px));box-sizing:border-box;background:#fff;border:1px solid #cbd5e1;border-radius:10px;box-shadow:0 12px 32px rgba(15,23,42,0.14);padding:12px 14px;display:grid;grid-template-columns:auto minmax(0,1fr);column-gap:14px;row-gap:8px;align-items:start;white-space:normal"></div>',
      );
      rows.forEach((row) => {
        panel.appendChild(el('<div style="' + LABEL + '">' + escapeHtml(row.label || "") + "</div>"));
        const v = el('<div style="' + VALUE + (row.mono ? "font-family:" + MONO + ";" : "") + '"></div>');
        if (row.html != null) v.innerHTML = row.html;
        else v.textContent = row.value == null || row.value === "" ? "—" : String(row.value);
        panel.appendChild(v);
      });
      document.body.appendChild(panel);
      place();
      btn.setAttribute("aria-expanded", "true");
    }
    btn.addEventListener("click", (e) => { e.stopPropagation(); if (panel) close(); else open(); });
    document.addEventListener("mousedown", (e) => { if (panel && !panel.contains(e.target) && !btn.contains(e.target)) close(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
    window.addEventListener("resize", place);
    window.addEventListener("scroll", close, true);
    return { open, close, isOpen: () => !!panel };
  }

  /** searchBox({placeholder, value, onInput, width}) → glass affix wrapper Element (.input, .value) */
  function searchBox(cfg) {
    const c = cfg || {};
    const wrap = el(
      '<div data-hover="fieldfocus" style="' + GLASS_FIELD + "display:flex;box-sizing:border-box;align-items:center;gap:6px;padding:0 11px;height:36px;border-radius:8px;" +
        (c.width ? "width:" + (typeof c.width === "number" ? c.width + "px" : c.width) + ";" : "width:100%;") +
        'transition:border-color .15s, box-shadow .15s">' +
        icon("AiOutlineSearch", { size: 14, color: "#94a3b8", style: "flex-shrink:0" }) +
        '<input type="text" style="flex:1;min-width:0;height:34px;border:0;outline:none;background:transparent;padding:0;font-size:14px;font-family:inherit;color:#0f172a;box-shadow:none">' +
        '<button type="button" aria-label="Clear" data-hover="close" style="display:none;align-items:center;justify-content:center;border:0;background:none;padding:0;cursor:pointer;color:#94a3b8;font-size:16px;line-height:1;flex-shrink:0">×</button>' +
        "</div>",
    );
    const input = wrap.querySelector("input");
    const clear = wrap.querySelector("button");
    input.placeholder = c.placeholder || "Search...";
    input.value = c.value || "";
    const sync = () => { clear.style.display = input.value ? "inline-flex" : "none"; };
    input.addEventListener("input", () => { sync(); if (typeof c.onInput === "function") c.onInput(input.value); });
    clear.addEventListener("click", () => {
      input.value = "";
      sync();
      input.focus();
      if (typeof c.onInput === "function") c.onInput("");
    });
    sync();
    wrap.input = input;
    Object.defineProperty(wrap, "value", { get: () => input.value, set: (v) => { input.value = v == null ? "" : v; sync(); } });
    return wrap;
  }

  const CHEVRON_URI =
    "url(\"data:image/svg+xml," +
    encodeURIComponent(
      "<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='#94a3b8' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'><path d='M6 9l6 6 6-6'/></svg>",
    ) + '")';

  /** select({options, value, placeholder, onChange, width, glass, height}) → the native <select> */
  function select(cfg) {
    const c = cfg || {};
    const height = c.height || 36;
    const bgImage = CHEVRON_URI + " no-repeat right 10px center / 12px 12px";
    const style =
      "display:inline-block;box-sizing:border-box;outline:none;height:" + height + "px;padding:0 30px 0 11px;border-radius:8px;color:#0f172a;font-size:" + (height < 34 ? 13 : 14) + "px;" +
      "font-family:inherit;appearance:none;-webkit-appearance:none;-moz-appearance:none;cursor:pointer;line-height:normal;" +
      "transition:border-color .15s, box-shadow .15s;" +
      (c.width ? "width:" + (typeof c.width === "number" ? c.width + "px" : c.width) + ";" : "width:100%;") +
      (c.glass
        ? GLASS_FIELD + "background:" + bgImage + ", rgba(255,255,255,0.55);"
        : "border:1px solid #cbd5e1;background:" + bgImage + ", #fff;");
    const sel = el('<select data-hover="fieldfocus" style="' + style + '"></select>');
    // Explicit background (chevron + fill) for callers that toggle disabled styling: reading
    // style.background back from the element can return "" for this shorthand in Chrome.
    sel.dataset.baseBg = c.glass ? bgImage + ", rgba(255,255,255,0.55)" : bgImage + ", #fff";
    if (c.placeholder) {
      const ph = document.createElement("option");
      ph.value = "";
      ph.textContent = c.placeholder;
      ph.disabled = !c.allowEmpty;
      ph.hidden = !c.allowEmpty;
      sel.appendChild(ph);
    }
    (c.options || []).forEach((opt) => {
      const o = document.createElement("option");
      o.value = opt.value == null ? "" : String(opt.value);
      o.textContent = opt.label == null ? o.value : opt.label;
      if (opt.disabled) o.disabled = true;
      sel.appendChild(o);
    });
    sel.value = c.value == null ? "" : String(c.value);
    if (sel.value !== String(c.value == null ? "" : c.value) && c.placeholder) sel.selectedIndex = 0;
    if (typeof c.onChange === "function") sel.addEventListener("change", (e) => c.onChange(sel.value, e));
    return sel;
  }

  /** switchEl({checked, small, onChange}) → <button role=switch> with .checked / .setChecked() */
  function switchEl(cfg) {
    const c = cfg || {};
    const small = !!c.small;
    const w = small ? 28 : 44;
    const h = small ? 16 : 22;
    const knob = small ? 12 : 18;
    const btn = el(
      '<button type="button" role="switch" style="position:relative;display:inline-flex;align-items:center;width:' + w + "px;height:" + h +
        'px;border:none;border-radius:100px;cursor:pointer;padding:0;transition:background .2s;flex-shrink:0">' +
        '<span style="position:absolute;left:2px;width:' + knob + "px;height:" + knob +
        'px;border-radius:50%;background:#fff;box-shadow:0 2px 4px rgba(0,0,0,.2);transition:transform .2s"></span></button>',
    );
    const handle = btn.firstElementChild;
    let checked = !!c.checked;
    const paint = () => {
      btn.style.background = checked ? "#1d4ed8" : "rgba(100,116,139,.45)";
      btn.setAttribute("aria-checked", checked ? "true" : "false");
      handle.style.transform = checked ? "translateX(" + (w - knob - 4) + "px)" : "translateX(0)";
    };
    btn.setChecked = (v) => { checked = !!v; paint(); };
    Object.defineProperty(btn, "checked", { get: () => checked, set: (v) => btn.setChecked(v) });
    btn.addEventListener("click", async () => {
      if (btn.disabled) return;
      const next = !checked;
      let result = true;
      if (typeof c.onChange === "function") {
        try { result = await c.onChange(next, btn); } catch (e) { result = false; }
      }
      if (result !== false) btn.setChecked(next);
    });
    paint();
    return btn;
  }

  /** checkbox({checked, indeterminate, label, onChange, disabled}) → <label> with .input */
  /**
   * multiSelect({options, value, placeholder, onChange, width, height}) → wrapper element.
   * A dropdown that lets the user tick several options. The closed control looks like
   * select(); the open panel lists the options with checkboxes. Handle methods on the
   * returned element: getValue() → string[], setValue(list), setDisabled(bool), open(), close().
   */
  function multiSelect(cfg) {
    const c = cfg || {};
    const height = c.height || 36;
    const options = (c.options || []).map((o) => ({ value: o.value == null ? "" : String(o.value), label: o.label == null ? String(o.value) : String(o.label) }));
    const labelOf = {};
    options.forEach((o) => { labelOf[o.value] = o.label; });
    let value = [];
    let disabled = false;
    let openState = false;

    const wrap = el('<div data-multiselect style="position:relative;' + (c.width ? "width:" + (typeof c.width === "number" ? c.width + "px" : c.width) + ";" : "width:100%;") + 'min-width:0"></div>');
    const trigger = el(
      '<button type="button" data-hover="fieldfocus" aria-haspopup="listbox" aria-expanded="false" style="' +
        "display:flex;align-items:center;box-sizing:border-box;width:100%;height:" + height + "px;padding:0 30px 0 11px;border-radius:8px;border:1px solid #cbd5e1;" +
        "background:" + CHEVRON_URI + " no-repeat right 10px center / 12px 12px, #fff;color:#0f172a;font-size:" + (height < 34 ? 13 : 14) + "px;" +
        'font-family:inherit;text-align:left;cursor:pointer;transition:border-color .15s, box-shadow .15s;line-height:normal">' +
        '<span data-text style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span>' +
        '<span data-count style="display:none;flex-shrink:0;margin-left:8px;padding:1px 7px;border-radius:999px;background:#eff6ff;border:1px solid #bfdbfe;color:#1d4ed8;font-size:11px;font-weight:700"></span>' +
        "</button>",
    );
    const panel = el(
      '<div role="listbox" aria-multiselectable="true" style="display:none;position:absolute;left:0;right:0;top:calc(100% + 4px);z-index:60;box-sizing:border-box;max-height:260px;overflow-y:auto;' +
        'padding:6px;border-radius:10px;border:1px solid #cbd5e1;background:#fff;box-shadow:0 12px 32px rgba(15,23,42,0.14)"></div>',
    );
    const textEl = trigger.querySelector("[data-text]");
    const countEl = trigger.querySelector("[data-count]");
    const rows = {};
    options.forEach((o) => {
      const row = el(
        '<label data-hover="menuitem" style="display:flex;align-items:center;gap:9px;padding:7px 9px;border-radius:7px;cursor:pointer;font-size:13.5px;color:#0f172a;user-select:none">' +
          '<input type="checkbox" style="width:16px;height:16px;accent-color:#1d4ed8;margin:0;flex-shrink:0;cursor:inherit">' +
          "<span>" + escapeHtml(o.label) + "</span></label>",
      );
      const input = row.querySelector("input");
      input.value = o.value;
      input.addEventListener("change", () => {
        if (disabled) { input.checked = value.includes(o.value); return; }
        const next = input.checked ? value.concat([o.value]) : value.filter((v) => v !== o.value);
        setValue(next);
        if (typeof c.onChange === "function") c.onChange(value.slice());
      });
      rows[o.value] = input;
      panel.appendChild(row);
    });
    if (!options.length) panel.appendChild(el('<div style="padding:8px;font-size:13px;color:#94a3b8">No options</div>'));

    function paint() {
      const labels = value.map((v) => labelOf[v] == null ? v : labelOf[v]);
      if (labels.length) {
        textEl.textContent = labels.join(", ");
        textEl.style.color = "#0f172a";
        textEl.title = labels.join(", ");
      } else {
        textEl.textContent = c.placeholder || "Select…";
        textEl.style.color = "#94a3b8";
        textEl.title = "";
      }
      countEl.textContent = String(labels.length);
      countEl.style.display = labels.length > 1 ? "inline-flex" : "none";
      options.forEach((o) => { rows[o.value].checked = value.includes(o.value); });
    }
    function setValue(list) {
      const seen = new Set();
      value = (Array.isArray(list) ? list : []).map((v) => String(v)).filter((v) => labelOf[v] != null && !seen.has(v) && (seen.add(v), true));
      paint();
    }
    function setDisabled(flag) {
      disabled = !!flag;
      trigger.disabled = disabled;
      trigger.style.cursor = disabled ? "not-allowed" : "pointer";
      trigger.style.background = CHEVRON_URI + " no-repeat right 10px center / 12px 12px, " + (disabled ? "#f8fafc" : "#fff");
      trigger.style.color = disabled ? "#64748b" : "#0f172a";
      Object.keys(rows).forEach((k) => { rows[k].disabled = disabled; });
      if (disabled) close();
    }
    function onDocClick(e) { if (!wrap.contains(e.target)) close(); }
    function onKey(e) { if (e.key === "Escape") { close(); trigger.focus(); } }
    function open() {
      if (disabled || openState) return;
      openState = true;
      panel.style.display = "block";
      trigger.setAttribute("aria-expanded", "true");
      trigger.style.borderColor = "#2563eb";
      setTimeout(() => { document.addEventListener("mousedown", onDocClick); document.addEventListener("keydown", onKey); }, 0);
    }
    function close() {
      if (!openState) return;
      openState = false;
      panel.style.display = "none";
      trigger.setAttribute("aria-expanded", "false");
      trigger.style.borderColor = wrap.dataset.errBorder === "1" ? "#f87171" : "#cbd5e1";
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    }
    trigger.addEventListener("click", () => { if (openState) close(); else open(); });
    wrap.appendChild(trigger);
    wrap.appendChild(panel);
    wrap.trigger = trigger;
    wrap.getValue = () => value.slice();
    wrap.setValue = setValue;
    wrap.setDisabled = setDisabled;
    wrap.open = open;
    wrap.close = close;
    setValue(c.value);
    return wrap;
  }

  function checkbox(cfg) {
    const c = cfg || {};
    const wrap = el(
      '<label style="display:inline-flex;align-items:center;gap:8px;cursor:' + (c.disabled ? "not-allowed;opacity:.55" : "pointer") + ';font-size:14px;color:#0f172a;user-select:none">' +
        '<input type="checkbox" style="width:16px;height:16px;accent-color:#1d4ed8;cursor:inherit;margin:0;flex-shrink:0">' +
        (c.label != null ? "<span>" + (c.labelIsHtml ? c.label : escapeHtml(c.label)) + "</span>" : "") +
        "</label>",
    );
    const input = wrap.querySelector("input");
    input.checked = !!c.checked;
    input.indeterminate = !!c.indeterminate;
    input.disabled = !!c.disabled;
    if (c.value != null) input.value = c.value;
    if (typeof c.onChange === "function") input.addEventListener("change", (e) => c.onChange(input.checked, e));
    wrap.input = input;
    return wrap;
  }

  function spinner(size) {
    const s = size || 20;
    const bw = s >= 32 ? 3 : s <= 14 ? 2 : 2.5;
    return (
      '<span style="display:inline-block;width:' + s + "px;height:" + s + "px;border:" + bw +
      'px solid #1d4ed8;border-top-color:transparent;border-radius:50%;animation:spin .8s linear infinite"></span>'
    );
  }

  function skeleton(lines) {
    const n = lines == null ? 4 : lines;
    const widths = ["100%", "92%", "78%", "88%", "64%", "96%"];
    let html = '<div aria-busy="true" style="display:flex;flex-direction:column;gap:10px">';
    for (let i = 0; i < n; i += 1) {
      html +=
        '<div style="height:14px;border-radius:6px;width:' + widths[i % widths.length] +
        ";background:linear-gradient(90deg, rgba(148,163,184,.22) 25%, rgba(148,163,184,.38) 42%, rgba(148,163,184,.22) 60%);" +
        'background-size:400% 100%;animation:shimmer 1.4s ease infinite"></div>';
    }
    return html + "</div>";
  }

  const EMPTY_SVG =
    '<svg width="64" height="41" viewBox="0 0 64 41" aria-hidden="true"><g transform="translate(0 1)" fill="none" fill-rule="evenodd">' +
    '<ellipse fill="#f5f5f5" cx="32" cy="33" rx="32" ry="7"/><g fill-rule="nonzero" stroke="#d9d9d9">' +
    '<path d="M55 12.76L44.854 1.258C44.367.474 43.656 0 42.907 0H21.093c-.749 0-1.46.474-1.947 1.257L9 12.761V22h46v-9.24z"/>' +
    '<path d="M41.613 15.931c0-1.605.994-2.93 2.227-2.931H55v18.137C55 33.26 53.68 35 52.05 35h-40.1C10.32 35 9 33.259 9 31.137V13h11.16c1.233 0 2.227 1.323 2.227 2.928v.022c0 1.605 1.005 2.901 2.237 2.901h14.752c1.232 0 2.237-1.308 2.237-2.913v-.007z" fill="#fafafa"/>' +
    "</g></g></svg>";

  function emptyState(descHtml) {
    return (
      '<div style="display:flex;flex-direction:column;align-items:center;gap:8px;padding:32px 8px;color:#94a3b8;font-size:14px">' +
      EMPTY_SVG + '<div style="text-align:center">' + (descHtml == null ? "No data" : descHtml) + "</div></div>"
    );
  }

  /* ── 8. Table / pagination / tabs ──────────────────────────────────────── */
  // Light-blue header row so column titles stand out on the white cards.
  const TH_STYLE =
    "background:#eff6ff;color:#1e3a8a;font-weight:700;font-size:12px;text-transform:uppercase;letter-spacing:.05em;" +
    "padding:10px 8px;text-align:left;border-bottom:1px solid #bfdbfe;white-space:nowrap;";
  const TD_STYLE = "padding:8px;border-bottom:1px solid #f1f5f9;vertical-align:middle;";

  function cssWidth(w) {
    return typeof w === "number" ? w + "px" : w;
  }

  /**
   * table(container, {columns, rows, rowKey, loading, emptyText, emptyHtml, minWidth,
   *                   onRowClick, rowStyle, pagination}) — re-renders in place.
   */
  function table(container, cfg) {
    if (!container) return;
    const c = cfg || {};
    const columns = c.columns || [];
    const rows = c.rows || [];
    const anyEllipsis = columns.some((col) => col.ellipsis);

    container.innerHTML = "";
    const wrapper = el('<div style="position:relative"></div>');
    const scroller = el('<div style="overflow-x:auto"></div>');
    const tbl = el(
      '<table style="width:100%;border-collapse:collapse;font-size:14px;color:#0f172a;' +
        (c.minWidth ? "min-width:" + cssWidth(c.minWidth) + ";" : "") +
        (anyEllipsis ? "table-layout:fixed;" : "") + '"></table>',
    );

    // <colgroup> carries the column widths.
    const colgroup = document.createElement("colgroup");
    columns.forEach((col) => {
      const cEl = document.createElement("col");
      if (col.width) cEl.style.width = cssWidth(col.width);
      colgroup.appendChild(cEl);
    });
    tbl.appendChild(colgroup);

    // Header
    const thead = document.createElement("thead");
    const htr = document.createElement("tr");
    columns.forEach((col) => {
      const th = document.createElement("th");
      th.setAttribute("style", TH_STYLE + (col.align ? "text-align:" + col.align + ";" : "") + (col.headerStyle || ""));
      if (typeof col.headerRender === "function") fill(th, col.headerRender(col));
      else th.textContent = col.title == null ? "" : col.title;
      htr.appendChild(th);
    });
    thead.appendChild(htr);
    tbl.appendChild(thead);

    // Body
    const tbody = document.createElement("tbody");
    if (!rows.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = Math.max(1, columns.length);
      td.setAttribute("style", "padding:16px");
      fill(td, c.emptyHtml != null ? c.emptyHtml : emptyState(escapeHtml(c.emptyText || "No data")));
      tr.appendChild(td);
      tbody.appendChild(tr);
    } else {
      rows.forEach((row, i) => {
        const tr = document.createElement("tr");
        tr.setAttribute("data-hover", "row");
        const key = typeof c.rowKey === "function" ? c.rowKey(row, i) : c.rowKey ? row[c.rowKey] : row.id != null ? row.id : i;
        if (key != null) tr.dataset.key = String(key);
        let trStyle = "transition:background .15s;";
        if (typeof c.rowStyle === "function") trStyle += c.rowStyle(row, i) || "";
        if (typeof c.onRowClick === "function") {
          trStyle += "cursor:pointer;";
          tr.addEventListener("click", (e) => c.onRowClick(row, i, e));
        }
        tr.setAttribute("style", trStyle);
        columns.forEach((col) => {
          const td = document.createElement("td");
          td.setAttribute(
            "style",
            TD_STYLE + (col.align ? "text-align:" + col.align + ";" : "") +
              (col.ellipsis ? "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:0;" : "") + (col.cellStyle || ""),
          );
          let content;
          if (typeof col.render === "function") content = col.render(row, i);
          else content = col.key != null ? row[col.key] : "";
          if (content instanceof Node) td.appendChild(content);
          else if (content == null || content === false) td.innerHTML = "";
          else if (typeof col.render === "function") td.innerHTML = String(content);
          else td.textContent = String(content);
          if (col.ellipsis && !td.getAttribute("title") && td.textContent) td.title = td.textContent.trim();
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
    }
    tbl.appendChild(tbody);
    scroller.appendChild(tbl);
    wrapper.appendChild(scroller);

    if (c.loading) {
      wrapper.appendChild(
        el(
          '<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(255,255,255,.55);z-index:2">' +
            spinner(32) + "</div>",
        ),
      );
    }
    container.appendChild(wrapper);

    if (c.pagination && c.pagination !== false) {
      const pg = document.createElement("div");
      container.appendChild(pg);
      pagination(pg, c.pagination);
    }
  }

  const PAGE_ITEM =
    GLASS_FIELD + "display:inline-flex;align-items:center;justify-content:center;min-width:30px;height:30px;padding:0 6px;border-radius:4px;" +
    "cursor:pointer;font-size:13.5px;font-family:inherit;color:#0f172a;transition:border-color .15s, color .15s, background .15s;";

  /** pagination(container, {page, pageSize, total, showSizeChanger, pageSizeOptions, onChange}) */
  function pagination(container, cfg) {
    if (!container) return;
    const c = cfg || {};
    const total = Math.max(0, Number(c.total) || 0);
    const pageSize = Math.max(1, Number(c.pageSize) || 10);
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    const page = Math.min(Math.max(1, Number(c.page) || 1), totalPages);
    const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
    const end = Math.min(page * pageSize, total);
    const emit = (p, s) => { if (typeof c.onChange === "function") c.onChange(p, s); };

    // Page list: every page up to 7, else 1 … (page±2) … last.
    let items;
    if (totalPages <= 7) {
      items = Array.from({ length: totalPages }, (_, i) => i + 1);
    } else {
      const set = new Set([1, totalPages]);
      for (let p = page - 2; p <= page + 2; p += 1) if (p >= 1 && p <= totalPages) set.add(p);
      const sorted = Array.from(set).sort((a, b) => a - b);
      items = [];
      sorted.forEach((p, i) => {
        if (i > 0 && p - sorted[i - 1] > 1) items.push("gap");
        items.push(p);
      });
    }

    container.innerHTML = "";
    container.setAttribute(
      "style",
      "display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-top:16px;font-size:14px;flex-wrap:wrap",
    );
    container.appendChild(
      el('<span style="margin-right:auto;color:#64748b;font-size:13px">' + start + "–" + end + " of " + total + "</span>"),
    );

    const arrow = (label, symbol, disabled, target) => {
      const b = el(
        '<button type="button" aria-label="' + label + '" data-hover="pagitem" style="' + PAGE_ITEM +
          (disabled ? "color:#cbd5e1;" : "") + '">' + symbol + "</button>",
      );
      b.disabled = disabled;
      b.addEventListener("click", () => emit(target, pageSize));
      return b;
    };
    container.appendChild(arrow("Previous page", "‹", page <= 1, page - 1));
    items.forEach((p) => {
      if (p === "gap") {
        container.appendChild(el('<span style="color:#94a3b8;font-size:12px;letter-spacing:1px;padding:0 2px">…</span>'));
        return;
      }
      const active = p === page;
      const b = el(
        '<button type="button" data-hover="pagitem"' + (active ? ' data-active="" aria-current="page"' : "") + ' style="' + PAGE_ITEM +
          (active ? "background:rgba(29,78,216,.1);border-color:rgba(29,78,216,.45);color:#1d4ed8;font-weight:600;" : "") + '">' + p + "</button>",
      );
      if (!active) b.addEventListener("click", () => emit(p, pageSize));
      container.appendChild(b);
    });
    container.appendChild(arrow("Next page", "›", page >= totalPages, page + 1));

    if (c.showSizeChanger) {
      const opts = (c.pageSizeOptions || [10, 25, 50, 100]).map((o) => ({ label: o + " / page", value: Number(o) }));
      if (!opts.some((o) => o.value === pageSize)) opts.unshift({ label: pageSize + " / page", value: pageSize });
      const sizeSel = select({
        options: opts, value: pageSize, glass: true, height: 30, width: "auto",
        onChange: (v) => emit(1, Number(v)),
      });
      sizeSel.style.minWidth = "96px";
      sizeSel.style.borderRadius = "4px";
      sizeSel.style.marginLeft = "4px";
      container.appendChild(sizeSel);
    }
  }

  /** tabs(container, {items:[{key,label}], active, onChange, activeStyle:"solid"|"tint"}) */
  function tabs(container, cfg) {
    if (!container) return;
    const c = cfg || {};
    const tint = c.activeStyle === "tint";
    const group = el(
      '<div role="tablist" style="' + GLASS_FIELD + 'display:inline-flex;align-items:center;gap:6px;border-radius:8px;padding:4px"></div>',
    );
    (c.items || []).forEach((item) => {
      const active = item.key === c.active;
      let activeStyle = "";
      if (active) {
        if (!tint) activeStyle = "background:#1d4ed8;color:#fff;";
        else if (item.key === "qa") activeStyle = "background:#faf5ff;color:#7e22ce;border:1px solid #e9d5ff;";
        else activeStyle = "background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe;";
      }
      const btn = el(
        '<button type="button" role="tab" data-hover="tab"' + (active ? ' data-active="" aria-selected="true"' : ' aria-selected="false"') +
          ' style="padding:4px ' + (tint ? 16 : 12) + "px;border-radius:6px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;" +
          "border:1px solid transparent;background:transparent;color:#475569;cursor:pointer;font-family:inherit;white-space:nowrap;transition:.15s;line-height:1.5;" +
          activeStyle + '">' + escapeHtml(item.label) + "</button>",
      );
      btn.addEventListener("click", () => {
        if (item.key === c.active) return;
        tabs(container, Object.assign({}, c, { active: item.key }));
        if (typeof c.onChange === "function") c.onChange(item.key);
      });
      group.appendChild(btn);
    });
    container.innerHTML = "";
    container.appendChild(group);
    return group;
  }

  /* ── 9. Shell: sidebar + header + content ──────────────────────────────── */
  function isCollapsed() { return storageGet(localStorage, SIDEBAR_KEY) === "true"; }

  function navItemsFor(profile) {
    const perms = (profile && profile.permissions) || [];
    const keys = orderedFeatures(perms);
    if (!keys.includes("profile")) keys.push("profile");
    return keys.map((k) => FEATURE_META[k]);
  }

  function sidebarInnerHtml(collapsed, items, activeKey) {
    const brand = collapsed
      ? '<img src="public/han-digital-mark.png" alt="Han Digital" draggable="false" style="height:30px;width:auto;display:block">'
      : '<img src="public/Han-digital-Logo.png" alt="Han Digital" draggable="false" style="height:30px;width:auto;max-width:200px;display:block">';
    const toggle =
      '<button type="button" id="pa-collapse" aria-label="' + (collapsed ? "Expand sidebar" : "Collapse sidebar") + '" data-tip="' +
      (collapsed ? "Expand" : "Collapse") + '" data-tip-place="right" style="height:34px;width:34px;border-radius:12px;background:rgba(43,44,124,0.08);' +
      "border:1px solid rgba(43,44,124,0.12);color:" + BRAND + ';display:grid;place-items:center;cursor:pointer;padding:0;flex-shrink:0;transition:.15s">' +
      icon(collapsed ? "AiOutlineMenuUnfold" : "AiOutlineMenuFold", { size: 16 }) + "</button>";
    const brandRow =
      '<div style="display:flex;margin-bottom:12px;' +
      (collapsed ? "flex-direction:column;align-items:center;gap:12px" : "align-items:center;justify-content:space-between") + '">' +
      brand + toggle + "</div>";
    const nav = items
      .map((m) => {
        const selected = m.key === activeKey;
        return (
          '<a href="' + m.page + '" data-hover="navitem"' + (selected ? ' data-selected="" aria-current="page"' : "") +
          (collapsed ? ' data-tip="' + escapeHtml(m.label) + '" data-tip-place="right"' : "") +
          ' style="display:flex;align-items:center;justify-content:' + (collapsed ? "center" : "flex-start") + ";gap:" + (collapsed ? 0 : 10) +
          "px;height:46px;margin:4px 2px;padding:" + (collapsed ? "0" : "0 16px") + ";border-radius:14px;font-size:15px;font-weight:600;color:" + BRAND +
          ";text-decoration:none;transition:background .2s ease;" + (selected ? "background:rgba(43,44,124,0.14);" : "") + '">' +
          icon(m.icon, { size: collapsed ? 20 : 18, style: "flex-shrink:0" }) +
          (collapsed ? "" : '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + escapeHtml(m.label) + "</span>") +
          "</a>"
        );
      })
      .join("");
    return (
      '<div style="display:flex;flex-direction:column;box-sizing:border-box;height:100%;padding:16px 12px;color:' + BRAND + '">' + brandRow +
      '<div style="height:1px;background:rgba(43,44,124,0.12);margin:0 0 12px"></div>' +
      '<nav style="flex:1;overflow-y:auto;overflow-x:hidden">' + nav + "</nav></div>"
    );
  }

  let offlineModal = null;
  function showOffline() {
    if (offlineModal) return;
    offlineModal = modal({
      width: 420,
      closable: false,
      footer: null,
      body:
        '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;color:#0f172a">' +
        '<h5 style="margin:0;padding:16px 0;font-size:16px;font-weight:600">Network Status</h5>' +
        icon("AiOutlineWifi", { size: 64, color: "#03045E", style: "margin-bottom:20px" }) +
        '<h6 style="margin:0;padding:4px 0;font-size:16px;font-weight:500;color:#03045E">No Internet Connection</h6>' +
        '<p style="margin:8px 0 0;font-size:14px;color:#475569">You are offline. Please check your internet connection.</p>' +
        '<div style="display:flex;align-items:center;justify-content:center;padding-top:12px">' +
        '<button type="button" data-role="retry" style="background:#03045E;color:#fff;border:none;padding:6px 20px;border-radius:4px;cursor:pointer;font-family:inherit;font-size:14px">Retry</button>' +
        "</div></div>",
    });
    offlineModal.root.querySelector('[data-role="retry"]').addEventListener("click", () => { if (navigator.onLine) hideOffline(); });
  }
  function hideOffline() {
    if (!offlineModal) return;
    offlineModal.close();
    offlineModal = null;
  }
  function networkInit() {
    if (networkInit._done) return;
    networkInit._done = true;
    window.addEventListener("offline", showOffline);
    window.addEventListener("online", hideOffline);
    if (!navigator.onLine) showOffline();
  }

  /**
   * renderShell({page, title, subtitle}) → the inner max-width content column.
   * Builds sidebar + header + scroll container into <body>, replacing any
   * previous shell, and wires collapse, user menu, tooltips and offline modal.
   */
  function renderShell(cfg) {
    const c = cfg || {};
    const profile = getProfile() || {};
    const pageKey = String(c.page || currentPageFile().replace(/\.html$/, "")).replace(/\.html$/, "");
    const activeKey = PAGE_ALIASES[pageKey] || pageKey;
    const items = navItemsFor(profile);
    const displayName = profile.full_name || profile.username || profile.email || "System Admin";
    const roleName = profile.role_name || "Administrator";

    // Body chrome
    document.body.setAttribute(
      "style",
      "margin:0;min-width:320px;height:100vh;overflow:hidden;background:" + BODY_BG + ";font-family:" + FONT + ";color:#0f172a",
    );
    const oldSide = document.getElementById("pa-sidebar");
    const oldMain = document.getElementById("pa-main");
    if (oldSide) oldSide.remove();
    if (oldMain) oldMain.remove();

    // Sidebar
    const aside = el(
      '<aside id="pa-sidebar" style="position:fixed;top:' + SIDEBAR_GAP + "px;left:" + SIDEBAR_GAP + "px;bottom:" + SIDEBAR_GAP + "px;height:calc(100vh - " +
        SIDEBAR_GAP * 2 + "px);box-sizing:border-box;z-index:50;border-radius:26px;overflow:hidden;" + GLASS_STRONG + 'transition:background .3s ease, box-shadow .3s ease"></aside>',
    );

    // Content column
    const main = el(
      '<div id="pa-main" style="height:100vh;display:flex;flex-direction:column;transition:margin-left .2s;background:transparent">' +
        '<header style="margin:16px 16px 0;z-index:40;position:relative">' +
        '<div style="display:flex;align-items:center;justify-content:space-between;border-radius:16px;padding:12px 20px;gap:12px;' + GLASS_BASE +
        'box-shadow:0 1px 3px rgba(15,23,42,0.06);transition:all .3s">' +
        '<div style="display:flex;flex-direction:column;min-width:0"><div style="display:flex;align-items:flex-end;gap:12px;min-width:0">' +
        '<h1 style="margin:0;font-size:24px;font-weight:600;line-height:1;color:#0f172a;white-space:nowrap">' + escapeHtml(c.title || "Workspace") + "</h1>" +
        (c.subtitle ? '<span data-hide="md" style="font-size:14px;color:#64748b;padding-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + escapeHtml(c.subtitle) + "</span>" : "") +
        "</div></div>" +
        '<div id="pa-user" style="position:relative;flex-shrink:0">' +
        '<div id="pa-user-chip" role="button" tabindex="0" aria-haspopup="menu" data-hover="chip" style="display:flex;align-items:center;gap:12px;cursor:pointer;border:1px solid #e2e8f0;background:rgba(255,255,255,0.7);border-radius:16px;padding:8px;transition:all .3s">' +
        '<div style="width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,#2563eb,#0891b2);font-size:14px;font-weight:600;color:#fff;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 6px -1px rgba(0,0,0,.1);flex-shrink:0">' +
        escapeHtml(displayName.charAt(0).toUpperCase()) + "</div>" +
        '<div data-hide="sm" style="text-align:left;min-width:0">' +
        '<div style="font-size:14px;font-weight:600;line-height:1;color:#0f172a;white-space:nowrap">' + escapeHtml(displayName) + "</div>" +
        '<div style="font-size:10px;text-transform:uppercase;letter-spacing:.24em;color:#64748b;margin-top:4px;white-space:nowrap">' + escapeHtml(roleName) + "</div></div>" +
        '<span data-chevron style="display:inline-flex;transition:transform .3s;line-height:0">' + icon("HiOutlineChevronDown", { size: 16, color: "#64748b" }) + "</span>" +
        "</div>" +
        '<div id="pa-user-menu" role="menu" style="display:none;position:absolute;right:0;top:calc(100% + 6px);z-index:60;background:#fff;border:1px solid #e2e8f0;border-radius:10px;box-shadow:0 12px 32px rgba(15,23,42,.14);padding:4px;min-width:160px;flex-direction:column">' +
        '<button type="button" role="menuitem" data-action="profile" data-hover="menuitem" style="display:flex;align-items:center;gap:8px;padding:7px 10px;border:none;background:none;border-radius:6px;cursor:pointer;font-size:13.5px;font-family:inherit;color:#0f172a;text-align:left;width:100%">' +
        icon("AiOutlineUser", { size: 15 }) + "<span>Profile</span></button>" +
        '<button type="button" role="menuitem" data-action="logout" data-hover="menuitem" style="display:flex;align-items:center;gap:8px;padding:7px 10px;border:none;background:none;border-radius:6px;cursor:pointer;font-size:13.5px;font-family:inherit;color:#0f172a;text-align:left;width:100%">' +
        icon("BiLogOutCircle", { size: 18 }) + "<span>Log out</span></button>" +
        "</div></div></div></header>" +
        '<div id="content" style="flex:1;min-height:0;overflow-y:auto;overflow-x:hidden;padding:16px;background:transparent">' +
        '<div id="content-inner" style="box-sizing:border-box;padding:8px;max-width:1280px;margin:0 auto;display:flex;flex-direction:column;gap:16px"></div>' +
        "</div></div>",
    );

    const paintSidebar = () => {
      const collapsed = isCollapsed();
      const width = collapsed ? SIDEBAR_COLLAPSED : SIDEBAR_EXPANDED;
      aside.style.width = width + "px";
      aside.innerHTML = sidebarInnerHtml(collapsed, items, activeKey);
      main.style.marginLeft = width + SIDEBAR_GAP + "px";
      aside.querySelector("#pa-collapse").addEventListener("click", () => {
        storageSet(localStorage, SIDEBAR_KEY, isCollapsed() ? "false" : "true");
        hideTip();
        paintSidebar();
      });
    };
    paintSidebar();

    // User dropdown
    const chip = main.querySelector("#pa-user-chip");
    const menu = main.querySelector("#pa-user-menu");
    const closeMenu = () => { menu.style.display = "none"; chip.setAttribute("aria-expanded", "false"); };
    const toggleMenu = () => {
      const open = menu.style.display !== "none";
      menu.style.display = open ? "none" : "flex";
      chip.setAttribute("aria-expanded", open ? "false" : "true");
    };
    chip.addEventListener("click", toggleMenu);
    chip.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleMenu(); } });
    menu.querySelector('[data-action="profile"]').addEventListener("click", () => { closeMenu(); location.href = "profile.html"; });
    menu.querySelector('[data-action="logout"]').addEventListener("click", () => { closeMenu(); logout(); });
    document.addEventListener("mousedown", (e) => { if (!main.querySelector("#pa-user").contains(e.target)) closeMenu(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });

    document.body.appendChild(aside);
    document.body.appendChild(main);
    tooltipsInit();
    networkInit();
    toastRoot();
    return main.querySelector("#content-inner");
  }

  /* ── Public API ────────────────────────────────────────────────────────── */
  window.App = {
    API_BASE,
    ICONS,
    FEATURE_META,
    TONES,
    tokens: { FONT, MONO, BODY_BG, GLASS, GLASS_STRONG, GLASS_FIELD, MODAL_CONTENT, MODAL_MASK, INPUT_STYLE },
    icon,
    escapeHtml,
    el,
    fill,
    fmt,
    debounce,
    qs,
    qsa,
    getToken,
    getProfile,
    setProfile,
    hydrateProfile,
    tryRestoreSession,
    ensureSession,
    requirePermission,
    logout,
    firstFeaturePage,
    api,
    taxonomy,
    download,
    upload,
    renderShell,
    toast,
    confirm,
    popconfirm,
    modal,
    modalFooterButtons,
    setLoading,
    setDisabled,
    pill,
    statusPill,
    priorityPill,
    typePill,
    permChip,
    slaBadge,
    progress,
    progressRing,
    avatarInitial,
    searchBox,
    select,
    multiSelect,
    switchEl,
    checkbox,
    table,
    pagination,
    skeleton,
    spinner,
    emptyState,
    tabs,
    tooltip,
    tooltipsInit,
    sectionLabel,
    infoButton,
    infoDropdown,
  };
})();
