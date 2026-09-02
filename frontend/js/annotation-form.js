/* ============================================================================
 * Prompt Attack Annotation Platform — shared annotation form (window.AnnotationForm)
 *
 * Loaded AFTER js/app.js by workspace.html and qa-workspace.html. Plain ES2020,
 * no framework, inline styles only (hover/focus states reuse the data-hover
 * presets that app.js already injects).
 *
 *   AnnotationForm.mount(container, {taxonomy, value, readOnly, onChange})
 *     -> { getValue(), setValue(v), validate() -> string[], setReadOnly(bool), destroy() }
 *   AnnotationForm.deriveOutput(value) -> {jailbreak, prompt_injection, prompt_leakage}
 *   AnnotationForm.emptyValue(taxonomy) -> a blank value with taxonomy defaults applied
 *
 * Value shape (SPEC2 §2):
 *   { data_type, data_structure, attack_type: [], attack_subcategory: [], domain, role,
 *     verified: bool, language, source_description, document_edited: bool,
 *     severity: {J, I, L}, intention, source }
 * ========================================================================== */
(function () {
  "use strict";

  /* ── Constants ─────────────────────────────────────────────────────────── */
  const SEVERITY_KEYS = ["J", "I", "L"];
  const SEVERITY_TYPE = { J: "jailbreak", I: "prompt_injection", L: "prompt_leakage" };
  const SEVERITY_TITLE = { J: "Jailbreak", I: "Prompt injection", L: "Prompt leakage" };
  const SEVERITY_SHORT = { J: "Jailbreak", I: "Injection", L: "Leakage" };
  const OUTPUT_KEYS = ["jailbreak", "prompt_injection", "prompt_leakage"];
  const OUTPUT_TITLE = { jailbreak: "Jailbreak", prompt_injection: "Prompt injection", prompt_leakage: "Prompt leakage" };
  const SINGLE_FIELDS = ["data_type", "data_structure", "domain", "role", "intention", "language", "source"];
  const BENIGN = "benign";

  const FIELD_LABELS = {
    data_type: "Data type",
    data_structure: "Data structure",
    attack_type: "Attack type",
    attack_subcategory: "Attack subcategory",
    domain: "Domain",
    role: "Role",
    verified: "Verification status",
    language: "Language",
    document_edited: "Document edited",
    source_description: "Source description",
    severity_J: "Severity J",
    severity_I: "Severity I",
    severity_L: "Severity L",
    intention: "Intention",
    source: "Source",
  };

  // Used only when mount() receives no taxonomy (e.g. GET /annotation/taxonomy unavailable).
  // The backend file backend/app/core/taxonomy.py remains the source of truth.
  const FALLBACK_TAXONOMY = {
    data_type: [
      { value: "single_turn", label: "Single-turn" }, { value: "multi_turn", label: "Multi-turn" },
      { value: "agentic", label: "Agentic" }, { value: "general_text", label: "General Text" },
    ],
    data_structure: [
      { value: "general_text", label: "General text" }, { value: "json", label: "JSON" }, { value: "xml", label: "XML" },
      { value: "list_table", label: "List/Table" }, { value: "code", label: "Code" }, { value: "markdown_html", label: "Markdown/HTML" },
      { value: "mixed", label: "Mixed" },
    ],
    attack_type: [
      { value: "jailbreak", label: "Jailbreak" }, { value: "prompt_injection", label: "Prompt Injection" },
      { value: "prompt_leakage", label: "Prompt Leakage" }, { value: "benign", label: "Benign" },
    ],
    attack_subcategory: {
      jailbreak: [
        { value: "role_playing_jailbreaks", label: "Role-playing jailbreaks (DAN / persona)" },
        { value: "hypothetical_framing", label: "Hypothetical / fictional framing" },
        { value: "encoding_obfuscation", label: "Encoding & obfuscation" },
        { value: "multi_step_escalation", label: "Multi-step escalation" },
        { value: "authority_impersonation", label: "Authority impersonation" },
        { value: "emotional_manipulation", label: "Emotional manipulation" },
        { value: "refusal_suppression", label: "Refusal suppression" },
        { value: "few_shot_priming", label: "Few-shot priming" },
        { value: "competing_objectives", label: "Competing objectives" },
        { value: "other_jailbreak", label: "Other jailbreak" },
      ],
      prompt_injection: [
        { value: "direct_instruction_override", label: "Direct instruction override" },
        { value: "indirect_injection", label: "Indirect injection (documents / tools / web)" },
        { value: "delimiter_escape", label: "Delimiter / format escape" },
        { value: "payload_splitting", label: "Payload splitting" },
        { value: "context_manipulation", label: "Context manipulation" },
        { value: "tool_call_hijacking", label: "Tool-call hijacking" },
        { value: "goal_hijacking", label: "Goal hijacking" },
        { value: "other_injection", label: "Other injection" },
      ],
      prompt_leakage: [
        { value: "system_prompt_extraction", label: "System prompt extraction" },
        { value: "instruction_repetition_request", label: "Instruction repetition request" },
        { value: "conversation_history_extraction", label: "Conversation history extraction" },
        { value: "memory_extraction", label: "Memory extraction" },
        { value: "tool_config_extraction", label: "Tool / config extraction" },
        { value: "other_leakage", label: "Other leakage" },
      ],
      benign: [],
    },
    domain: [
      { value: "medical", label: "Medical" }, { value: "accounting", label: "Accounting" }, { value: "it_support", label: "IT Support" },
      { value: "education", label: "Education" }, { value: "legal", label: "Legal" }, { value: "finance", label: "Finance" },
      { value: "e_commerce", label: "E-commerce" }, { value: "customer_service", label: "Customer service" },
      { value: "software_development", label: "Software development" }, { value: "creative_writing", label: "Creative writing" },
      { value: "other", label: "Other" },
    ],
    role: [
      { value: "system_prompt", label: "System prompt" }, { value: "user", label: "User" }, { value: "assistant", label: "Assistant" },
      { value: "memory", label: "Memory" }, { value: "tool_input", label: "Tool input" }, { value: "tool_output", label: "Tool output" },
      { value: "environmental_feedback", label: "Environmental feedback" }, { value: "general", label: "General" },
    ],
    language: [
      { value: "en", label: "English" }, { value: "hi", label: "Hindi" }, { value: "es", label: "Spanish" }, { value: "fr", label: "French" },
      { value: "de", label: "German" }, { value: "zh", label: "Chinese" }, { value: "ar", label: "Arabic" }, { value: "other", label: "Other" },
    ],
    intention: [
      { value: "benign", label: "Benign" }, { value: "adversarial", label: "Adversarial" }, { value: "hard_to_say", label: "Hard to say" },
    ],
    source: [
      { value: "real_user", label: "Real user" }, { value: "synthetic", label: "Synthetic" }, { value: "red_team", label: "Red team" },
      { value: "other", label: "Other" },
    ],
    severity_levels: [0, 1, 2, 3, 4, 5],
    defaults: { language: "en", source: "real_user", verified: false, document_edited: false },
  };

  /* ── Small helpers ─────────────────────────────────────────────────────── */
  function A() {
    if (!window.App) throw new Error("annotation-form.js requires js/app.js to be loaded first.");
    return window.App;
  }
  const esc = (s) => A().escapeHtml(s);
  const h = (html) => A().el(html);

  function toOptions(list) {
    if (!Array.isArray(list)) return [];
    return list
      .map((o) => {
        if (o == null) return null;
        if (typeof o === "object") {
          const value = o.value == null ? "" : String(o.value);
          return { value, label: o.label == null ? value : String(o.label) };
        }
        return { value: String(o), label: String(o) };
      })
      .filter(Boolean);
  }

  /** Coerce whatever the caller passed into a fully-populated taxonomy object. */
  function normTaxonomy(t) {
    const src = t && typeof t === "object" ? t : {};
    const fb = FALLBACK_TAXONOMY;
    const out = {};
    ["data_type", "data_structure", "attack_type", "domain", "role", "language", "intention", "source"].forEach((k) => {
      const list = toOptions(src[k]);
      out[k] = list.length ? list : toOptions(fb[k]);
    });
    const subSrc = src.attack_subcategory && typeof src.attack_subcategory === "object" && !Array.isArray(src.attack_subcategory)
      ? src.attack_subcategory
      : fb.attack_subcategory;
    out.attack_subcategory = {};
    out.attack_type.forEach((o) => { out.attack_subcategory[o.value] = toOptions(subSrc[o.value]); });
    Object.keys(subSrc).forEach((k) => { if (!out.attack_subcategory[k]) out.attack_subcategory[k] = toOptions(subSrc[k]); });
    const levels = Array.isArray(src.severity_levels) && src.severity_levels.length
      ? src.severity_levels.map((n) => Number(n)).filter((n) => Number.isInteger(n))
      : fb.severity_levels.slice();
    out.severity_levels = levels.length ? levels : fb.severity_levels.slice();
    out.defaults = Object.assign({}, fb.defaults, src.defaults && typeof src.defaults === "object" ? src.defaults : {});
    // Index maps for ordering / lookups.
    out._order = {};
    out._labels = {};
    Object.keys(out).forEach((k) => {
      if (k.charAt(0) === "_" || !Array.isArray(out[k])) return;
      out._order[k] = {};
      out._labels[k] = {};
      out[k].forEach((o, i) => { out._order[k][o.value] = i; out._labels[k][o.value] = o.label; });
    });
    out._subGroup = {}; // subcategory value -> attack type
    out._subOrder = {}; // subcategory value -> global order (group order * 1000 + index)
    out._labels.attack_subcategory = {};
    out.attack_type.forEach((at, gi) => {
      (out.attack_subcategory[at.value] || []).forEach((o, i) => {
        if (out._subGroup[o.value] == null) {
          out._subGroup[o.value] = at.value;
          out._subOrder[o.value] = gi * 1000 + i;
          out._labels.attack_subcategory[o.value] = o.label;
        }
      });
    });
    return out;
  }

  function toBool(v) {
    if (typeof v === "boolean") return v;
    if (typeof v === "number") return v !== 0;
    if (typeof v === "string") return /^(true|1|yes|y|verified)$/i.test(v.trim());
    return false;
  }
  function toList(v) {
    if (Array.isArray(v)) return v.map((x) => (x == null ? "" : String(x).trim())).filter(Boolean);
    if (typeof v === "string") return v.split(",").map((x) => x.trim()).filter(Boolean);
    return [];
  }
  function toSeverity(n) {
    const x = typeof n === "string" ? parseInt(n, 10) : Number(n);
    if (!Number.isFinite(x)) return 0;
    return Math.max(0, Math.min(5, Math.round(x)));
  }
  function uniq(list) {
    const seen = new Set();
    return list.filter((x) => (seen.has(x) ? false : (seen.add(x), true)));
  }
  const isBenignOnly = (types) => types.length === 1 && types[0] === BENIGN;

  /* ── Public: emptyValue / deriveOutput ─────────────────────────────────── */
  function emptyValue(taxonomy) {
    const tax = normTaxonomy(taxonomy);
    const d = tax.defaults || {};
    return {
      data_type: "",
      data_structure: "",
      attack_type: [],
      attack_subcategory: [],
      domain: "",
      role: "",
      verified: toBool(d.verified),
      language: d.language == null ? "en" : String(d.language),
      source_description: "",
      document_edited: toBool(d.document_edited),
      severity: { J: 0, I: 0, L: 0 },
      intention: "",
      source: d.source == null ? "real_user" : String(d.source),
    };
  }

  function deriveOutput(value) {
    const types = toList(value && value.attack_type);
    return {
      jailbreak: types.includes("jailbreak"),
      prompt_injection: types.includes("prompt_injection"),
      prompt_leakage: types.includes("prompt_leakage"),
    };
  }

  /** Clean copy: taxonomy-ordered lists, pruned subcategories, coerced severities/booleans, defaults. */
  function normalise(value, tax) {
    const v = value && typeof value === "object" ? value : {};
    const base = emptyValue(tax);
    const out = {};
    SINGLE_FIELDS.forEach((f) => {
      const raw = v[f] == null ? "" : String(v[f]).trim();
      out[f] = raw || base[f];
    });
    const knownTypes = tax._order.attack_type;
    let types = uniq(toList(v.attack_type)).filter((t) => knownTypes[t] != null);
    types.sort((a, b) => knownTypes[a] - knownTypes[b]);
    out.attack_type = types;
    const selected = new Set(types);
    let subs = uniq(toList(v.attack_subcategory)).filter((s) => tax._subGroup[s] != null && selected.has(tax._subGroup[s]));
    subs.sort((a, b) => tax._subOrder[a] - tax._subOrder[b]);
    out.attack_subcategory = subs;
    out.verified = toBool(v.verified);
    out.document_edited = toBool(v.document_edited);
    out.source_description = v.source_description == null ? "" : String(v.source_description);
    const sev = v.severity && typeof v.severity === "object" ? v.severity : {};
    out.severity = {};
    SEVERITY_KEYS.forEach((k) => {
      out.severity[k] = selected.has(SEVERITY_TYPE[k]) ? toSeverity(sev[k]) : 0;
    });
    // Canonical key order (matches SPEC2 §2 sample).
    return {
      data_type: out.data_type,
      data_structure: out.data_structure,
      attack_type: out.attack_type,
      attack_subcategory: out.attack_subcategory,
      domain: out.domain,
      role: out.role,
      verified: out.verified,
      language: out.language,
      source_description: out.source_description,
      document_edited: out.document_edited,
      severity: out.severity,
      intention: out.intention,
      source: out.source,
    };
  }

  /** validateValue(value, tax) → [{field, message}] mirroring SPEC2 §2 validate_annotation. */
  function validateValue(value, tax) {
    const v = value || {};
    const errors = [];
    const push = (field, message) => errors.push({ field, message });

    SINGLE_FIELDS.forEach((f) => {
      const val = v[f] == null ? "" : String(v[f]);
      if (!val) push(f, FIELD_LABELS[f] + " is required.");
      else if (tax._order[f][val] == null) push(f, FIELD_LABELS[f] + ' has an unknown value "' + val + '".');
    });

    const types = toList(v.attack_type);
    const knownTypes = tax._order.attack_type;
    if (!types.length) push("attack_type", "Select at least one attack type.");
    else {
      const bad = types.filter((t) => knownTypes[t] == null);
      if (bad.length) push("attack_type", 'Unknown attack type "' + bad[0] + '".');
      if (types.includes(BENIGN) && types.length > 1) push("attack_type", "Benign cannot be combined with other attack types.");
    }

    if (types.length && !isBenignOnly(types)) {
      const subs = toList(v.attack_subcategory);
      const selected = new Set(types);
      if (!subs.length) push("attack_subcategory", "Select at least one attack subcategory.");
      else {
        const stray = subs.find((s) => tax._subGroup[s] == null || !selected.has(tax._subGroup[s]));
        if (stray != null) push("attack_subcategory", '"' + stray + '" does not belong to a selected attack type.');
      }
    }

    if (typeof v.verified !== "boolean") push("verified", "Verification status must be true or false.");
    if (typeof v.document_edited !== "boolean") push("document_edited", "Document edited must be true or false.");
    if (v.source_description != null && typeof v.source_description !== "string") push("source_description", "Source description must be text.");

    const sev = v.severity && typeof v.severity === "object" ? v.severity : {};
    const selectedTypes = new Set(types);
    SEVERITY_KEYS.forEach((k) => {
      const field = "severity_" + k;
      const n = sev[k];
      const on = selectedTypes.has(SEVERITY_TYPE[k]);
      if (n != null && (!Number.isInteger(n) || n < 0 || n > 5)) push(field, FIELD_LABELS[field] + " must be an integer between 0 and 5.");
      else if (on && (n == null || n === 0)) push(field, FIELD_LABELS[field] + " must be 1–5 when " + SEVERITY_TITLE[k] + " is selected.");
    });
    return errors;
  }

  /* ── Styles ────────────────────────────────────────────────────────────── */
  const CHIP_BASE =
    "display:inline-flex;align-items:center;gap:6px;height:30px;padding:0 12px;border-radius:999px;font-size:13px;font-weight:500;" +
    "font-family:inherit;line-height:1;white-space:nowrap;transition:background .15s, color .15s, border-color .15s;user-select:none;";
  const CHIP_OFF = "border:1px solid #e2e8f0;background:#fff;color:#475569;";
  const CHIP_ON = "border:1px solid #bfdbfe;background:#eff6ff;color:#1d4ed8;";
  const LABEL_STYLE = "display:flex;align-items:center;gap:6px;font-size:12px;font-weight:600;color:#475569;margin-bottom:6px;line-height:1.3;";
  const ERR_STYLE = "display:none;font-size:12px;color:#dc2626;margin-top:4px;line-height:1.35;";
  const HINT_STYLE = "font-size:12px;color:#94a3b8;";
  const GROUP_HEAD = "font-size:11px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:#64748b;margin-bottom:6px;";
  const BOX_STYLE = "border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px;background:rgba(255,255,255,0.6);";

  function fieldWrap(key, labelHtml, control, hintHtml) {
    const wrap = h('<div data-field="' + esc(key) + '" style="min-width:0"></div>');
    if (labelHtml != null) wrap.appendChild(h('<div data-role="label" style="' + LABEL_STYLE + '">' + labelHtml + "</div>"));
    if (control) wrap.appendChild(control);
    if (hintHtml) wrap.appendChild(h('<div style="' + HINT_STYLE + 'margin-top:4px">' + hintHtml + "</div>"));
    wrap.appendChild(h('<div data-err="' + esc(key) + '" role="alert" style="' + ERR_STYLE + '"></div>'));
    return wrap;
  }

  function outputChip(key, on) {
    const App = A();
    const t = App.TONES[on ? "emerald" : "slate"];
    return (
      '<span data-output="' + key + '" style="display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;font-size:12px;font-weight:600;' +
      "border:1px solid " + t.border + ";background:" + t.bg + ";color:" + t.text + ';white-space:nowrap">' +
      '<span style="width:7px;height:7px;border-radius:9999px;background:' + t.dot + ';flex-shrink:0"></span>' +
      esc(OUTPUT_TITLE[key]) + '<span style="font-family:' + App.tokens.MONO + ';font-weight:700">' + (on ? "true" : "false") + "</span></span>"
    );
  }

  /* ── mount() ───────────────────────────────────────────────────────────── */
  function mount(container, opts) {
    const App = A();
    if (!container) throw new Error("AnnotationForm.mount: container is required.");
    const o = opts || {};
    const tax = normTaxonomy(o.taxonomy);
    let state = normalise(o.value, tax);
    let readOnly = !!o.readOnly;
    let destroyed = false;
    let errors = {}; // field -> message (first)
    const refs = {}; // live element references for partial repaints

    const emit = () => {
      if (destroyed || typeof o.onChange !== "function") return;
      try { o.onChange(getValue()); } catch (e) { console.error("[AnnotationForm] onChange handler failed", e); }
    };
    const getValue = () => JSON.parse(JSON.stringify(normalise(state, tax)));

    /* ---- error painting ---- */
    function paintErrors() {
      Object.keys(refs.errEls || {}).forEach((key) => {
        const node = refs.errEls[key];
        const msg = errors[key];
        node.textContent = msg || "";
        node.style.display = msg ? "block" : "none";
      });
      Object.keys(refs.controls || {}).forEach((key) => {
        const ctl = refs.controls[key];
        if (!ctl || !ctl.style) return;
        if (errors[key]) { ctl.dataset.errBorder = "1"; ctl.style.borderColor = "#f87171"; }
        else if (ctl.dataset.errBorder === "1") { delete ctl.dataset.errBorder; ctl.style.borderColor = ctl.dataset.baseBorder || "#cbd5e1"; }
      });
    }
    function clearError(key) {
      if (!errors[key]) return;
      delete errors[key];
      paintErrors();
    }

    /* ---- control styling for read-only / disabled ---- */
    function styleSelect(sel, disabled) {
      sel.disabled = !!disabled;
      if (disabled) {
        sel.style.background = sel.dataset.baseBg ? sel.dataset.baseBg.replace("#fff", "#f8fafc") : "#f8fafc";
        sel.style.color = "#64748b";
        sel.style.cursor = "not-allowed";
      } else {
        sel.style.background = sel.dataset.baseBg || "";
        sel.style.color = "#0f172a";
        sel.style.cursor = "pointer";
      }
    }
    function mkSelect(key, options, value, cfg) {
      const c = cfg || {};
      const sel = App.select({
        options,
        value,
        placeholder: c.placeholder,
        width: "100%",
        onChange: (v) => { if (readOnly) return; c.onChange(v); },
      });
      sel.setAttribute("aria-label", c.ariaLabel || FIELD_LABELS[key] || key);
      sel.dataset.baseBg = sel.style.background;
      sel.dataset.baseBorder = "#cbd5e1";
      refs.controls[key] = sel;
      return sel;
    }

    /* ---- attack type chips ---- */
    function paintChips() {
      const selected = new Set(state.attack_type);
      App.qsa("[data-chip]", refs.chips).forEach((btn) => {
        const on = selected.has(btn.dataset.chip);
        btn.setAttribute("style", CHIP_BASE + (on ? CHIP_ON : CHIP_OFF) + (readOnly ? "cursor:default;" : "cursor:pointer;"));
        btn.setAttribute("aria-pressed", on ? "true" : "false");
        const check = btn.querySelector("[data-check]");
        if (check) check.style.display = on ? "inline-flex" : "none";
      });
    }
    function toggleType(t) {
      if (readOnly) return;
      const has = state.attack_type.includes(t);
      let next;
      if (has) next = state.attack_type.filter((x) => x !== t);
      else if (t === BENIGN) next = [BENIGN];
      else next = state.attack_type.filter((x) => x !== BENIGN).concat([t]);
      state = normalise(Object.assign({}, state, { attack_type: next }), tax);
      // Newly-selected attack types default their severity to 0 → the annotator must pick 1–5.
      clearError("attack_type");
      clearError("attack_subcategory");
      SEVERITY_KEYS.forEach((k) => { if (!state.attack_type.includes(SEVERITY_TYPE[k])) clearError("severity_" + k); });
      paintChips();
      paintSubcats();
      paintSeverity();
      paintOutput();
      emit();
    }
    function buildChips() {
      const wrap = h('<div role="group" aria-label="Attack type" style="display:flex;flex-wrap:wrap;gap:8px"></div>');
      tax.attack_type.forEach((opt) => {
        const btn = h(
          '<button type="button" data-chip="' + esc(opt.value) + '" data-hover="chiptoggle" style="' + CHIP_BASE + CHIP_OFF + '">' +
            '<span data-check style="display:none;line-height:0">' + App.icon("AiOutlineCheck", { size: 12 }) + "</span>" +
            esc(opt.label) + "</button>",
        );
        btn.addEventListener("click", () => toggleType(opt.value));
        wrap.appendChild(btn);
      });
      refs.chips = wrap;
      return wrap;
    }

    /* ---- subcategories ---- */
    function toggleSub(value, checked) {
      if (readOnly) return;
      const set = new Set(state.attack_subcategory);
      if (checked) set.add(value); else set.delete(value);
      state = normalise(Object.assign({}, state, { attack_subcategory: Array.from(set) }), tax);
      clearError("attack_subcategory");
      emit();
    }
    function paintSubcats() {
      const field = refs.subField;
      const box = refs.subBox;
      box.innerHTML = "";
      const types = state.attack_type.filter((t) => t !== BENIGN && (tax.attack_subcategory[t] || []).length);
      const benignOnly = isBenignOnly(state.attack_type);
      field.style.display = benignOnly ? "none" : "";
      if (benignOnly) return;
      if (!types.length) {
        box.appendChild(h('<div style="' + HINT_STYLE + 'padding:2px 0">Select an attack type above to choose its subcategories.</div>'));
        return;
      }
      const selected = new Set(state.attack_subcategory);
      types.forEach((t, gi) => {
        const group = h('<div style="' + (gi ? "margin-top:10px;padding-top:10px;border-top:1px dashed #e2e8f0;" : "") + '"></div>');
        group.appendChild(h('<div style="' + GROUP_HEAD + '">' + esc(tax._labels.attack_type[t] || t) + "</div>"));
        const list = h('<div style="display:grid;grid-template-columns:1fr;gap:6px"></div>');
        (tax.attack_subcategory[t] || []).forEach((opt) => {
          const cb = App.checkbox({
            checked: selected.has(opt.value),
            label: opt.label,
            value: opt.value,
            disabled: readOnly,
            onChange: (checked) => toggleSub(opt.value, checked),
          });
          cb.style.fontSize = "13.5px";
          cb.style.alignItems = "flex-start";
          cb.style.lineHeight = "1.35";
          cb.input.style.marginTop = "1px";
          list.appendChild(cb);
        });
        group.appendChild(list);
        box.appendChild(group);
      });
    }

    /* ---- severity ---- */
    function paintSeverity() {
      SEVERITY_KEYS.forEach((k) => {
        const on = state.attack_type.includes(SEVERITY_TYPE[k]);
        const sel = refs.controls["severity_" + k];
        const label = refs.sevLabels[k];
        sel.value = String(state.severity[k]);
        if (sel.value !== String(state.severity[k])) sel.value = "0";
        styleSelect(sel, readOnly || !on);
        // Single line at the 440px workspace column width: short type word, never wraps.
        label.style.whiteSpace = "nowrap";
        label.innerHTML =
          esc("Severity " + k) +
          '<span style="font-weight:500;color:#94a3b8;overflow:hidden;text-overflow:ellipsis;min-width:0">' +
          esc(on ? SEVERITY_SHORT[k] : "(n/a)") + "</span>";
        label.title = SEVERITY_TITLE[k] + (on ? "" : " is not a selected attack type");
      });
    }

    /* ---- derived output ---- */
    function paintOutput() {
      const out = deriveOutput(state);
      refs.output.innerHTML = OUTPUT_KEYS.map((k) => outputChip(k, out[k])).join("");
    }

    /* ---- read-only ---- */
    function applyReadOnly() {
      SINGLE_FIELDS.concat(["verified"]).forEach((k) => { const sel = refs.controls[k]; if (sel) styleSelect(sel, readOnly); });
      paintChips();
      paintSubcats();
      paintSeverity();
      const ta = refs.controls.source_description;
      if (ta) {
        ta.readOnly = readOnly;
        ta.style.background = readOnly ? "#f8fafc" : "#fff";
        ta.style.color = readOnly ? "#334155" : "#0f172a";
        ta.style.cursor = readOnly ? "default" : "";
      }
      if (refs.docSwitch) {
        refs.docSwitch.disabled = readOnly;
        refs.docSwitch.setAttribute("aria-disabled", readOnly ? "true" : "false");
      }
    }

    /* ---- full render ---- */
    function render() {
      refs.controls = {};
      refs.errEls = {};
      refs.sevLabels = {};
      const root = h(
        '<div data-annotation-form style="display:flex;flex-direction:column;gap:20px;font-family:' + App.tokens.FONT + ';color:#0f172a;min-width:0"></div>',
      );
      const section = (title) => {
        const s = h('<section style="display:flex;flex-direction:column;gap:12px;min-width:0"></section>');
        s.appendChild(h(App.sectionLabel(title)));
        root.appendChild(s);
        return s;
      };
      const grid2 = () => h('<div style="display:grid;grid-template-columns:repeat(2, minmax(0,1fr));gap:12px"></div>');
      const singleField = (key, placeholder) =>
        fieldWrap(
          key,
          esc(FIELD_LABELS[key]),
          mkSelect(key, tax[key], state[key], {
            placeholder,
            onChange: (v) => { state[key] = v; clearError(key); emit(); },
          }),
        );

      /* Classification */
      const cls = section("Classification");
      const g1 = grid2();
      g1.appendChild(singleField("data_type", "Select data type"));
      g1.appendChild(singleField("data_structure", "Select data structure"));
      cls.appendChild(g1);
      cls.appendChild(fieldWrap("attack_type", esc("Attack type") + '<span style="font-weight:500;color:#94a3b8">multi-select · Benign is exclusive</span>', buildChips()));
      refs.subBox = h('<div style="' + BOX_STYLE + '"></div>');
      refs.subField = fieldWrap("attack_subcategory", esc("Attack subcategory"), refs.subBox);
      cls.appendChild(refs.subField);

      /* Context */
      const ctx = section("Context");
      const g2 = grid2();
      g2.appendChild(singleField("domain", "Select domain"));
      g2.appendChild(singleField("role", "Select role"));
      g2.appendChild(singleField("language"));
      g2.appendChild(singleField("source"));
      ctx.appendChild(g2);
      const g3 = grid2();
      g3.appendChild(
        fieldWrap(
          "verified",
          esc("Verification status"),
          mkSelect(
            "verified",
            [{ value: "false", label: "Unverified" }, { value: "true", label: "Verified" }],
            state.verified ? "true" : "false",
            { onChange: (v) => { state.verified = v === "true"; clearError("verified"); emit(); } },
          ),
        ),
      );
      refs.docSwitch = App.switchEl({
        checked: state.document_edited,
        onChange: (next) => {
          if (readOnly) return false;
          state.document_edited = !!next;
          clearError("document_edited");
          emit();
          return true;
        },
      });
      refs.docSwitch.setAttribute("aria-label", "Document edited");
      const docRow = h('<div style="display:flex;align-items:center;gap:10px;height:36px"></div>');
      docRow.appendChild(refs.docSwitch);
      docRow.appendChild(h('<span style="font-size:13.5px;color:#0f172a">Document edited</span>'));
      g3.appendChild(fieldWrap("document_edited", esc("Document edited"), docRow));
      ctx.appendChild(g3);
      const ta = h(
        '<textarea rows="3" data-hover="fieldfocus" placeholder="Where does this prompt come from? Any context worth recording…" style="' +
          App.tokens.INPUT_STYLE.replace("height:36px;", "height:auto;min-height:78px;") +
          'padding:6px 11px;line-height:1.5;resize:vertical"></textarea>',
      );
      ta.value = state.source_description;
      ta.setAttribute("aria-label", "Source description");
      ta.dataset.baseBorder = "#cbd5e1";
      ta.addEventListener("input", () => {
        if (readOnly) return;
        state.source_description = ta.value;
        clearError("source_description");
        emit();
      });
      refs.controls.source_description = ta;
      ctx.appendChild(fieldWrap("source_description", esc("Source description") + '<span style="font-weight:500;color:#94a3b8">optional</span>', ta));

      /* Assessment */
      const asm = section("Assessment");
      const sevGrid = h('<div style="display:grid;grid-template-columns:repeat(3, minmax(0,1fr));gap:12px"></div>');
      const levelOpts = tax.severity_levels.map((n) => ({ value: String(n), label: String(n) }));
      SEVERITY_KEYS.forEach((k) => {
        const key = "severity_" + k;
        const sel = mkSelect(key, levelOpts, String(state.severity[k]), {
          onChange: (v) => {
            state.severity[k] = toSeverity(v);
            clearError(key);
            emit();
          },
        });
        const wrap = fieldWrap(key, esc("Severity " + k), sel);
        refs.sevLabels[k] = wrap.querySelector('[data-role="label"]');
        sevGrid.appendChild(wrap);
      });
      asm.appendChild(sevGrid);
      asm.appendChild(h('<div style="' + HINT_STYLE + 'margin-top:-6px">J = jailbreak · I = prompt injection · L = prompt leakage. 0 = not applicable, 1 = low, 5 = critical.</div>'));
      asm.appendChild(singleField("intention", "Select intention"));

      /* Output (derived) */
      const outSec = section("Output (derived)");
      refs.output = h('<div style="display:flex;flex-wrap:wrap;gap:8px"></div>');
      outSec.appendChild(refs.output);
      outSec.appendChild(h('<div style="' + HINT_STYLE + '">Computed from the selected attack types; stored server-side.</div>'));

      // Error slots.
      App.qsa("[data-err]", root).forEach((node) => { refs.errEls[node.dataset.err] = node; });

      container.innerHTML = "";
      container.appendChild(root);
      refs.root = root;
      applyReadOnly();
      paintOutput();
      paintErrors();
    }

    render();

    /* ---- handle ---- */
    const handle = {
      getValue,
      setValue(v) {
        if (destroyed) return;
        state = normalise(v, tax);
        errors = {};
        render();
      },
      validate(vopts) {
        if (destroyed) return [];
        const list = validateValue(normalise(state, tax), tax);
        errors = {};
        list.forEach((e) => { if (!errors[e.field]) errors[e.field] = e.message; });
        paintErrors();
        const messages = list.map((e) => e.message);
        const silent = vopts && vopts.silent;
        if (messages.length && !silent && App.toast) {
          App.toast.error(messages.length === 1 ? messages[0] : "Please fix " + messages.length + " issues in the annotation form.");
          const first = refs.root.querySelector('[data-field="' + list[0].field + '"]');
          if (first && typeof first.scrollIntoView === "function") {
            try { first.scrollIntoView({ block: "nearest", behavior: "smooth" }); } catch (e) { /* ignore */ }
          }
        }
        return messages;
      },
      setReadOnly(flag) {
        if (destroyed) return;
        readOnly = !!flag;
        applyReadOnly();
      },
      destroy() {
        if (destroyed) return;
        destroyed = true;
        if (refs.root && refs.root.parentNode === container) container.removeChild(refs.root);
        Object.keys(refs).forEach((k) => { refs[k] = null; });
      },
    };
    Object.defineProperty(handle, "readOnly", { get: () => readOnly });
    return handle;
  }

  /* ── Hover preset for the toggle chips (app.js has no chip-toggle state) ── */
  (function injectChipHover() {
    if (document.getElementById("pa-annotation-form")) return;
    const style = document.createElement("style");
    style.id = "pa-annotation-form";
    style.textContent =
      "[data-hover=chiptoggle]:not([aria-pressed=true]):not([disabled]):hover{border-color:#93c5fd!important;color:#1d4ed8!important;background:#f8fafc!important}" +
      "[data-hover=chiptoggle]:focus-visible{outline:none;box-shadow:0 0 0 2px rgba(29,78,216,.25)}";
    (document.head || document.documentElement).appendChild(style);
  })();

  window.AnnotationForm = { mount, deriveOutput, emptyValue };
})();
