"""Consensus + final-record builder for prompt-attack annotations.

Pure functions over plain dicts (and, where a ``task`` / ``annotation`` is
taken, either an ORM object or a dict with the same attribute names). No DB
access, so everything here is directly unit-testable.

Annotation data shape (``TaskAnnotation.data`` / ``Task.final_data``)::

    { "data_type": "general_text", "data_structure": "general_text",
      "attack_type": ["jailbreak", "prompt_injection"],
      "attack_subcategory": ["role_playing_jailbreaks", "direct_instruction_override"],
      "domain": "other", "role": "general", "verified": true, "language": "en",
      "source_description": "...", "document_edited": false,
      "severity": {"J": 5, "I": 4, "L": 0}, "intention": "adversarial", "source": "real_user" }
"""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import Any

from app.core import taxonomy as tx

# Scalar dropdown fields that must hold one valid taxonomy value.
# (``role`` is a multi-select list, handled separately.)
SCALAR_FIELDS: tuple[str, ...] = ("data_type", "data_structure", "domain", "language", "intention", "source")
BOOL_FIELDS: tuple[str, ...] = ("verified", "document_edited")
SEVERITY_ORDER: tuple[str, ...] = ("J", "I", "L")
OUTPUT_TYPES: tuple[str, ...] = ("jailbreak", "prompt_injection", "prompt_leakage")

# The ten agreement keys the customer record carries.
CUSTOMER_AGREEMENT_KEYS: tuple[str, ...] = (
    "attack_type",
    "attack_subcategory",
    "output_jailbreak",
    "output_prompt_injection",
    "output_prompt_leakage",
    "severity_J",
    "severity_I",
    "severity_L",
    "intention",
    "verified",
)
# Extra (harmless) agreement keys exposed to the QA UI.
EXTRA_AGREEMENT_KEYS: tuple[str, ...] = (
    "data_type",
    "data_structure",
    "domain",
    "role",
    "language",
    "document_edited",
    "source",
)

_BOOL_TRUE = ("true", "1", "yes", "y", "verified", "on")
_BOOL_FALSE = ("false", "0", "no", "n", "unverified", "off", "")

_MISSING = object()


# ─── Small accessors ─────────────────────────────────────────────────────────

def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Attribute-or-key read so ORM rows and plain dicts are interchangeable."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _annotation_data(annotation: Any) -> dict[str, Any]:
    """The ``data`` dict of an annotation (ORM row, dict with ``data``, or a
    bare data dict)."""
    if annotation is None:
        return {}
    if isinstance(annotation, dict):
        if isinstance(annotation.get("data"), dict):
            return annotation["data"]
        if "data" in annotation:
            return {}
        return annotation  # a bare data dict
    data = getattr(annotation, "data", None)
    return data if isinstance(data, dict) else {}


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in _BOOL_TRUE:
        return True
    if text in _BOOL_FALSE:
        return False
    return default


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _as_list(value: Any) -> list[Any]:
    """Lists pass through; a comma-separated string is split; None -> []."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        return [part.strip() for part in text.split(",") if part.strip()]
    return [value]


def _uniq(values: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    out: list[Any] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _sort_key_dt(value: Any) -> tuple[int, Any]:
    """Sort helper: None sorts last; datetimes compare by timestamp."""
    if value is None:
        return (1, 0.0)
    if isinstance(value, datetime):
        try:
            return (0, value.timestamp())
        except (OverflowError, OSError, ValueError):
            return (0, 0.0)
    return (0, str(value))


def ordered_annotations(annotations: Any) -> list[Any]:
    """Annotations ordered by ``submitted_at`` (NULLs last) then ``created_at``.
    Accepts ORM rows or dicts; stable, never mutates the input."""
    items = list(annotations or [])
    return sorted(
        items,
        key=lambda a: (_sort_key_dt(_get(a, "submitted_at")), _sort_key_dt(_get(a, "created_at"))),
    )


# ─── Normalisation / validation ──────────────────────────────────────────────

def empty_annotation() -> dict[str, Any]:
    """A data-shaped dict with defaults applied and nothing selected."""
    return {
        "data_type": "",
        "data_structure": "",
        "attack_type": [],
        "attack_subcategory": [],
        "domain": "",
        "role": [],
        "verified": bool(tx.DEFAULTS["verified"]),
        "language": tx.DEFAULTS["language"],
        "source_description": "",
        "document_edited": bool(tx.DEFAULTS["document_edited"]),
        "severity": {"J": 0, "I": 0, "L": 0},
        "intention": "",
        "source": tx.DEFAULTS["source"],
    }


def normalise_annotation(data: Any) -> dict[str, Any]:
    """Return a clean copy of an annotation dict.

    * strings are trimmed, unknown keys dropped, defaults applied
      (language -> en, source -> real_user, verified/document_edited -> False);
    * ``attack_type`` is de-duplicated and sorted by taxonomy order
      (unknown values dropped);
    * ``attack_subcategory`` is de-duplicated and sorted by (attack type
      group, position in group); unknown values dropped;
    * ``role`` is a list (multi-select), de-duplicated, taxonomy order;
    * ``severity`` J/I/L are coerced to ints (non-numeric -> 0); the severity
      of an attack type that is NOT selected is forced to 0. The flat
      ``severity_J`` / ``severity_I`` / ``severity_L`` keys are accepted too.

    Invalid choices (e.g. an empty ``data_type``) are NOT errors here — see
    :func:`validate_annotation`.
    """
    src = data if isinstance(data, dict) else {}
    out = empty_annotation()

    for field in SCALAR_FIELDS:
        raw = src.get(field, _MISSING)
        if raw is _MISSING or raw is None or _as_str(raw) == "":
            out[field] = tx.DEFAULTS.get(field, "")
        else:
            out[field] = _as_str(raw)

    for field in BOOL_FIELDS:
        out[field] = _as_bool(src.get(field), default=bool(tx.DEFAULTS.get(field, False)))

    out["source_description"] = _as_str(src.get("source_description"))

    attack_types = [_as_str(v) for v in _as_list(src.get("attack_type"))]
    attack_types = [v for v in _uniq(attack_types) if v in tx.ATTACK_TYPE_ORDER]
    attack_types.sort(key=tx.ATTACK_TYPE_ORDER.index)
    out["attack_type"] = attack_types

    # role — multi-select list, de-duplicated, unknown values dropped, taxonomy order.
    role_order = [str(o["value"]) for o in tx.OPTIONS["role"]]
    roles = [_as_str(v) for v in _as_list(src.get("role"))]
    roles = [v for v in _uniq(roles) if v in role_order]
    roles.sort(key=role_order.index)
    out["role"] = roles

    subs = [_as_str(v) for v in _as_list(src.get("attack_subcategory"))]
    subs = [v for v in _uniq(subs) if tx.subcategory_group(v) is not None]
    subs.sort(key=tx.subcategory_index)
    out["attack_subcategory"] = subs

    raw_sev = src.get("severity")
    raw_sev = raw_sev if isinstance(raw_sev, dict) else {}
    selected_keys = {tx.SEVERITY_KEYS[t] for t in attack_types if t in tx.SEVERITY_KEYS}
    severity: dict[str, int] = {}
    for key in SEVERITY_ORDER:
        if key in raw_sev:
            value = _as_int(raw_sev.get(key), default=0)
        else:
            value = _as_int(src.get(f"severity_{key}"), default=0)
        severity[key] = value if key in selected_keys else 0
    out["severity"] = severity

    return out


def validate_annotation(data: Any) -> list[str]:
    """Validate an annotation for submit / finalise. Returns a list of
    human-readable error messages (empty when valid). Drafts are not
    validated. Normalises first, so the same rules apply to raw client input.

    Rules: data_type, data_structure, domain, intention, language and source
    are required valid values; role is a non-empty list of valid values;
    attack_type is a non-empty list of valid values and "benign" is
    exclusive; attack_subcategory holds exactly ONE value per selected attack
    type (from that type's group) and is empty when attack_type == ["benign"];
    verified / document_edited must be booleans; severities are ints 0..5 and
    the severity of a selected attack type must be 1..5 (unselected -> 0);
    source_description is a (possibly empty) string.
    """
    raw = data if isinstance(data, dict) else {}
    clean = normalise_annotation(raw)
    errors: list[str] = []

    for field in SCALAR_FIELDS:
        value = clean.get(field)
        label = tx.FIELD_LABELS.get(field, field)
        if not value:
            errors.append(f"{label} is required.")
        elif not tx.is_valid(field, value):
            errors.append(f"{label}: '{value}' is not a valid option.")

    # role — non-empty list of valid values.
    raw_roles = _uniq([_as_str(v) for v in _as_list(raw.get("role"))])
    for v in raw_roles:
        if v and not tx.is_valid("role", v):
            errors.append(f"Role: '{v}' is not a valid option.")
    if not clean["role"]:
        errors.append("Role: select at least one value.")

    # attack_type — non-empty, valid, benign exclusive.
    raw_types = _uniq([_as_str(v) for v in _as_list(raw.get("attack_type"))])
    for v in raw_types:
        if v and v not in tx.ATTACK_TYPE_ORDER:
            errors.append(f"Attack type: '{v}' is not a valid option.")
    attack_types = clean["attack_type"]
    if not attack_types:
        errors.append("Attack type: select at least one value.")
    elif "benign" in attack_types and len(attack_types) > 1:
        errors.append("Attack type: 'Benign' cannot be combined with other attack types.")

    # attack_subcategory — required unless benign only; each in a selected group.
    raw_subs = _uniq([_as_str(v) for v in _as_list(raw.get("attack_subcategory"))])
    for v in raw_subs:
        if v and tx.subcategory_group(v) is None:
            errors.append(f"Attack subcategory: '{v}' is not a valid option.")
    subs = clean["attack_subcategory"]
    benign_only = attack_types == ["benign"]
    if benign_only:
        if subs:
            errors.append("Attack subcategory must be empty when the attack type is 'Benign'.")
    elif attack_types:
        selected = set(attack_types)
        stray = False
        for v in subs:
            group = tx.subcategory_group(v)
            if group not in selected:
                stray = True
                errors.append(
                    f"Attack subcategory: '{tx.subcategory_label(v)}' belongs to "
                    f"'{tx.label_for('attack_type', group)}', which is not selected."
                )
        if not stray:
            # Exactly one subcategory per selected attack type that has subcategories.
            groups = tx.taxonomy_payload().get("attack_subcategory") or {}
            for t in attack_types:
                if t == "benign" or not groups.get(t):
                    continue
                count = sum(1 for v in subs if tx.subcategory_group(v) == t)
                label = tx.label_for("attack_type", t)
                if count == 0:
                    errors.append(f"Attack subcategory: select one value for '{label}'.")
                elif count > 1:
                    errors.append(f"Attack subcategory: select only one value for '{label}'.")

    # booleans — anything that is not bool-like is rejected.
    for field in BOOL_FIELDS:
        value = raw.get(field, _MISSING)
        if value is _MISSING or value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value in (0, 1):
            continue
        text = str(value).strip().lower()
        if text not in _BOOL_TRUE and text not in _BOOL_FALSE:
            errors.append(f"{tx.FIELD_LABELS.get(field, field)} must be true or false.")

    # severity — ints 0..5; selected attack types need 1..5 (unselected are forced to 0).
    raw_sev = raw.get("severity")
    raw_sev = raw_sev if isinstance(raw_sev, dict) else {}
    for attack_type, key in tx.SEVERITY_KEYS.items():
        raw_value = raw_sev.get(key, raw.get(f"severity_{key}"))
        if raw_value is not None and not isinstance(raw_value, bool):
            try:
                int(float(str(raw_value).strip()))
            except (TypeError, ValueError):
                errors.append(f"Severity {key} must be an integer between 0 and 5.")
                continue
        value = clean["severity"][key]
        if attack_type in attack_types:
            if not 1 <= value <= 5:
                errors.append(
                    f"Severity {key} must be between 1 and 5 when "
                    f"'{tx.label_for('attack_type', attack_type)}' is selected."
                )
        elif not 0 <= value <= 5:
            errors.append(f"Severity {key} must be an integer between 0 and 5.")

    desc = raw.get("source_description")
    if desc is not None and not isinstance(desc, str):
        errors.append("Source description must be text.")

    return errors


# ─── Derived values ──────────────────────────────────────────────────────────

def derive_output(data: Any) -> dict[str, bool]:
    """``{"jailbreak": bool, "prompt_injection": bool, "prompt_leakage": bool}``
    derived from ``attack_type``."""
    raw = data.get("attack_type") if isinstance(data, dict) else None
    types = {_as_str(v) for v in _as_list(raw)}
    return {t: (t in types) for t in OUTPUT_TYPES}


def severity_block(data: Any) -> dict[str, int]:
    """``{"J": int, "I": int, "L": int}`` from a data dict (missing -> 0)."""
    sev = data.get("severity") if isinstance(data, dict) else None
    sev = sev if isinstance(sev, dict) else {}
    return {key: _as_int(sev.get(key), 0) for key in SEVERITY_ORDER}


def annotator_block(data: Any) -> dict[str, Any]:
    """One annotator's block in the customer record (lists joined with ", ")."""
    clean = normalise_annotation(data)
    return {
        "attack_type": ", ".join(clean["attack_type"]),
        "attack_subcategory": ", ".join(clean["attack_subcategory"]),
        "output": derive_output(clean),
        "severity": dict(clean["severity"]),
        "intention": clean["intention"],
        "verified": bool(clean["verified"]),
    }


# ─── Majority voting ─────────────────────────────────────────────────────────

def _normalise_value(value: Any, kind: str) -> Any:
    """Hashable, comparable form of a value for exact-mode voting."""
    if kind == "list":
        return tuple(sorted(_as_str(v) for v in _as_list(value)))
    if kind == "bool":
        return _as_bool(value)
    if kind == "int":
        return _as_int(value)
    return _as_str(value)


def _denormalise_value(value: Any, kind: str) -> Any:
    if kind == "list":
        return list(value)
    return value


def majority(values: list[Any], kind: str = "str") -> tuple[Any, str]:
    """Exact-mode vote over ``values``.

    ``kind`` is one of ``"list"`` (compared as sorted tuples), ``"bool"``,
    ``"int"`` or ``"str"``. Returns ``(value, level)`` where level is:

    * ``"full"`` — every annotator gave the same value;
    * ``"majority"`` — one value occurs more than N/2 times (>= 2 of 3);
    * ``"none"`` — no value has a strict majority. The returned value is then
      the median for ints (lower median, so it is always one of the inputs)
      and the FIRST annotator's value for everything else.

    With an empty ``values`` list the level is ``"none"`` and the value is a
    neutral default (``[]`` / ``False`` / ``0`` / ``""``); with at least one
    value the result is never ``None``.
    """
    if not values:
        return {"list": [], "bool": False, "int": 0}.get(kind, ""), "none"

    norm = [_normalise_value(v, kind) for v in values]
    n = len(norm)
    counts: dict[Any, int] = {}
    for v in norm:
        counts[v] = counts.get(v, 0) + 1

    if len(counts) == 1:
        return _denormalise_value(norm[0], kind), "full"

    best_value, best_count = max(counts.items(), key=lambda kv: kv[1])
    if best_count * 2 > n:
        return _denormalise_value(best_value, kind), "majority"

    if kind == "int":
        return int(statistics.median_low(norm)), "none"
    return _denormalise_value(norm[0], kind), "none"


# ─── Consensus ───────────────────────────────────────────────────────────────

def compute_consensus(task: Any, annotations: Any) -> dict[str, Any]:
    """Field-by-field majority over the given annotations.

    Returns ``{"majority": <data-shaped dict>, "agreement": {...},
    "consensus_reached": bool}``. ``agreement`` holds exactly the ten customer
    keys (attack_type, attack_subcategory, output_jailbreak,
    output_prompt_injection, output_prompt_leakage, severity_J, severity_I,
    severity_L, intention, verified) plus the extra keys data_type,
    data_structure, domain, role, language, document_edited, source, each
    valued "full" | "majority" | "none". ``consensus_reached`` is True only
    when at least one annotation exists and EVERY voted key (customer and
    extra) is "full", i.e. all annotators gave identical answers.

    ``annotations`` may be ORM ``TaskAnnotation`` rows, dicts with a ``data``
    key, or bare data dicts; they are ordered by submitted_at first so the
    "first annotator wins" tie-break is deterministic. ``task`` is accepted
    for signature symmetry with :func:`build_record` and is not read.
    """
    del task  # not needed for the vote itself
    ordered = ordered_annotations(annotations)
    datas = [normalise_annotation(_annotation_data(a)) for a in ordered]

    majority_data = empty_annotation()
    agreement: dict[str, str] = {}

    if not datas:
        for key in CUSTOMER_AGREEMENT_KEYS + EXTRA_AGREEMENT_KEYS:
            agreement[key] = "none"
        return {"majority": majority_data, "agreement": agreement, "consensus_reached": False}

    def vote(kind: str, values: list[Any], agreement_key: str) -> Any:
        value, level = majority(values, kind)
        agreement[agreement_key] = level
        return value

    majority_data["attack_type"] = vote("list", [d["attack_type"] for d in datas], "attack_type")
    majority_data["attack_subcategory"] = vote("list", [d["attack_subcategory"] for d in datas], "attack_subcategory")
    # Derived outputs are voted separately: they can agree even when the full
    # attack_type list differs.
    outputs = [derive_output(d) for d in datas]
    for t in OUTPUT_TYPES:
        vote("bool", [o[t] for o in outputs], f"output_{t}")

    severity: dict[str, int] = {}
    for key in SEVERITY_ORDER:
        severity[key] = vote("int", [d["severity"][key] for d in datas], f"severity_{key}")
    majority_data["severity"] = severity
    majority_data["intention"] = vote("str", [d["intention"] for d in datas], "intention")
    majority_data["verified"] = vote("bool", [d["verified"] for d in datas], "verified")

    for field in ("data_type", "data_structure", "domain", "language", "source"):
        majority_data[field] = vote("str", [d[field] for d in datas], field)
    majority_data["role"] = vote("list", [d["role"] for d in datas], "role")
    majority_data["document_edited"] = vote("bool", [d["document_edited"] for d in datas], "document_edited")

    # Free text: agreed value if annotators typed the same thing, otherwise the
    # first non-empty description (not part of the agreement summary).
    descriptions = [d["source_description"] for d in datas]
    desc_value, desc_level = majority(descriptions, "str")
    if desc_level == "none" or not desc_value:
        desc_value = next((d for d in descriptions if d), desc_value)
    majority_data["source_description"] = desc_value

    # Re-normalise so a voted severity of an attack type absent from the voted
    # attack_type list is forced back to 0 and the shape stays canonical.
    majority_data = normalise_annotation(majority_data)

    # Consensus only when EVERY annotator gave the same answer on EVERY voted
    # field (customer keys and the extra fields alike). A single mismatch,
    # even a 2-of-3 majority, means no consensus.
    consensus_reached = all(
        agreement.get(key) == "full" for key in CUSTOMER_AGREEMENT_KEYS + EXTRA_AGREEMENT_KEYS
    )
    return {"majority": majority_data, "agreement": agreement, "consensus_reached": consensus_reached}


# ─── Final record ────────────────────────────────────────────────────────────

def build_record(task: Any, annotations: Any, final_data: Any) -> dict[str, Any]:
    """Build the customer's per-task JSON record.

    Key order (matters for readability): dataset, input, meta_data,
    annotator_1..annotator_N (ordered by submitted_at), inter_annotator_agreement,
    output, annotation, source. ``meta_data`` / ``output`` / ``annotation`` /
    ``source`` come from ``final_data`` (normalised); the length fields are
    computed from ``task.input_text``. ``task`` may be an ORM row or a dict
    with ``dataset`` and ``input_text``.
    """
    final = normalise_annotation(final_data if isinstance(final_data, dict) else {})
    input_text = _get(task, "input_text") or ""
    if not isinstance(input_text, str):
        input_text = str(input_text)
    length = len(input_text)

    ordered = ordered_annotations(annotations)
    consensus = compute_consensus(task, ordered)
    agreement = consensus["agreement"]

    record: dict[str, Any] = {
        "dataset": _get(task, "dataset") or "",
        "input": input_text,
        "meta_data": {
            "data_type": final["data_type"],
            "data_length_chars": length,
            "data_length_bucket": tx.length_bucket(length),
            "data_structure": final["data_structure"],
            "attack_type": ", ".join(final["attack_type"]),
            "attack_subcategory": ", ".join(final["attack_subcategory"]),
            "domain": final["domain"],
            "role": final["role"],
            "verified": bool(final["verified"]),
            "language": final["language"],
            "source_description": final["source_description"],
            "document_edited": bool(final["document_edited"]),
        },
    }
    for index, annotation in enumerate(ordered, start=1):
        record[f"annotator_{index}"] = annotator_block(_annotation_data(annotation))

    record["inter_annotator_agreement"] = {
        **{key: agreement.get(key, "none") for key in CUSTOMER_AGREEMENT_KEYS},
        "consensus_reached": bool(consensus["consensus_reached"]),
    }
    record["output"] = derive_output(final)
    record["annotation"] = {"severity": dict(final["severity"]), "intention": final["intention"]}
    record["source"] = final["source"]
    return record
