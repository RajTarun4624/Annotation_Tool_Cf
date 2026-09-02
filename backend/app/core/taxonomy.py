"""Annotation taxonomy — the single source of truth for every dropdown.

Edit THIS file to change what annotators can pick. Values (``value``) are
what gets stored in ``TaskAnnotation.data`` / ``Task.final_data`` and what
the exports emit; labels are what the UI shows. The frontend never hardcodes
options: it reads ``GET /api/v1/annotation/taxonomy`` (see
:func:`taxonomy_payload`).

NOTE: the customer's attack_subcategory taxonomy document was not provided,
so ``SUBCATEGORIES`` is a sensible placeholder grouped by attack type.
"""

from __future__ import annotations

from typing import Any


def _opts(*pairs: tuple[Any, str]) -> list[dict[str, Any]]:
    return [{"value": value, "label": label} for value, label in pairs]


# ─── Flat option lists ───────────────────────────────────────────────────────

OPTIONS: dict[str, list[dict[str, Any]]] = {
    "data_type": _opts(
        ("single_turn", "Single-turn"),
        ("multi_turn", "Multi-turn"),
        ("agentic", "Agentic"),
        ("general_text", "General Text"),
    ),
    "data_structure": _opts(
        ("general_text", "General text"),
        ("json", "JSON"),
        ("xml", "XML"),
        ("list_table", "List/Table"),
        ("code", "Code"),
        ("markdown_html", "Markdown/HTML"),
        ("mixed", "Mixed"),
    ),
    # Multi-select. "benign" is exclusive (cannot be combined with the others).
    "attack_type": _opts(
        ("jailbreak", "Jailbreak"),
        ("prompt_injection", "Prompt Injection"),
        ("prompt_leakage", "Prompt Leakage"),
        ("benign", "Benign"),
    ),
    "domain": _opts(
        ("medical", "Medical"),
        ("accounting", "Accounting"),
        ("it_support", "IT Support"),
        ("education", "Education"),
        ("legal", "Legal"),
        ("finance", "Finance"),
        ("e_commerce", "E-commerce"),
        ("customer_service", "Customer Service"),
        ("software_development", "Software Development"),
        ("creative_writing", "Creative Writing"),
        ("other", "Other"),
    ),
    "role": _opts(
        ("system_prompt", "System prompt"),
        ("user", "User"),
        ("assistant", "Assistant"),
        ("memory", "Memory"),
        ("tool_input", "Tool input"),
        ("tool_output", "Tool output"),
        ("environmental_feedback", "Environmental feedback"),
        ("general", "General"),
    ),
    # Boolean field, exposed as two options for the dropdown.
    "verified": _opts(
        (False, "Unverified"),
        (True, "Verified"),
    ),
    "language": _opts(
        ("en", "English"),
        ("hi", "Hindi"),
        ("es", "Spanish"),
        ("fr", "French"),
        ("de", "German"),
        ("zh", "Chinese"),
        ("ar", "Arabic"),
        ("other", "Other"),
    ),
    "intention": _opts(
        ("benign", "Benign"),
        ("adversarial", "Adversarial"),
        ("hard_to_say", "Hard to say"),
    ),
    "source": _opts(
        ("real_user", "Real user"),
        ("synthetic", "Synthetic"),
        ("red_team", "Red team"),
        ("other", "Other"),
    ),
}

# ─── Attack subcategories, grouped by attack type (multi-select) ─────────────

SUBCATEGORIES: dict[str, list[dict[str, Any]]] = {
    "jailbreak": _opts(
        ("role_playing_jailbreaks", "Role-playing jailbreaks (DAN / persona)"),
        ("hypothetical_framing", "Hypothetical / fictional framing"),
        ("encoding_obfuscation", "Encoding & obfuscation"),
        ("multi_step_escalation", "Multi-step escalation"),
        ("authority_impersonation", "Authority impersonation"),
        ("emotional_manipulation", "Emotional manipulation"),
        ("refusal_suppression", "Refusal suppression"),
        ("few_shot_priming", "Few-shot priming"),
        ("competing_objectives", "Competing objectives"),
        ("other_jailbreak", "Other jailbreak"),
    ),
    "prompt_injection": _opts(
        ("direct_instruction_override", "Direct instruction override"),
        ("indirect_injection", "Indirect injection (documents / tools / web)"),
        ("delimiter_escape", "Delimiter / format escape"),
        ("payload_splitting", "Payload splitting"),
        ("context_manipulation", "Context manipulation"),
        ("tool_call_hijacking", "Tool-call hijacking"),
        ("goal_hijacking", "Goal hijacking"),
        ("other_injection", "Other injection"),
    ),
    "prompt_leakage": _opts(
        ("system_prompt_extraction", "System prompt extraction"),
        ("instruction_repetition_request", "Instruction repetition request"),
        ("conversation_history_extraction", "Conversation history extraction"),
        ("memory_extraction", "Memory extraction"),
        ("tool_config_extraction", "Tool / config extraction"),
        ("other_leakage", "Other leakage"),
    ),
    "benign": [],
}

# Canonical ordering of attack types (used to sort multi-select values).
ATTACK_TYPE_ORDER: list[str] = [o["value"] for o in OPTIONS["attack_type"]]

# Attack type -> severity key. "benign" has no severity.
SEVERITY_KEYS: dict[str, str] = {
    "jailbreak": "J",
    "prompt_injection": "I",
    "prompt_leakage": "L",
}
SEVERITY_LEVELS: list[int] = [0, 1, 2, 3, 4, 5]

DEFAULTS: dict[str, Any] = {
    "language": "en",
    "source": "real_user",
    "verified": False,
    "document_edited": False,
}

# Column / row order used by comparison tables and exports.
FIELD_ORDER: list[str] = [
    "data_type",
    "data_structure",
    "attack_type",
    "attack_subcategory",
    "domain",
    "role",
    "verified",
    "language",
    "document_edited",
    "source_description",
    "severity_J",
    "severity_I",
    "severity_L",
    "intention",
    "source",
]

# Human labels for FIELD_ORDER entries (comparison tables / export headers).
FIELD_LABELS: dict[str, str] = {
    "data_type": "Data type",
    "data_structure": "Data structure",
    "attack_type": "Attack type",
    "attack_subcategory": "Attack subcategory",
    "domain": "Domain",
    "role": "Role",
    "verified": "Verified",
    "language": "Language",
    "document_edited": "Document edited",
    "source_description": "Source description",
    "severity_J": "Severity J",
    "severity_I": "Severity I",
    "severity_L": "Severity L",
    "intention": "Intention",
    "source": "Source",
}


# ─── Lookup helpers ──────────────────────────────────────────────────────────

# value -> attack type group, and value -> position for stable sorting.
_SUBCATEGORY_GROUP: dict[str, str] = {}
_SUBCATEGORY_INDEX: dict[str, int] = {}
_SUBCATEGORY_LABEL: dict[str, str] = {}
for _group_index, _group in enumerate(ATTACK_TYPE_ORDER):
    for _i, _opt in enumerate(SUBCATEGORIES.get(_group, [])):
        _SUBCATEGORY_GROUP[_opt["value"]] = _group
        _SUBCATEGORY_INDEX[_opt["value"]] = _group_index * 1000 + _i
        _SUBCATEGORY_LABEL[_opt["value"]] = _opt["label"]

_OPTION_LABELS: dict[str, dict[Any, str]] = {
    field: {opt["value"]: opt["label"] for opt in options} for field, options in OPTIONS.items()
}
_OPTION_INDEX: dict[str, dict[Any, int]] = {
    field: {opt["value"]: i for i, opt in enumerate(options)} for field, options in OPTIONS.items()
}


def values_of(field: str) -> list[Any]:
    """All valid values of a flat option field, in taxonomy order."""
    return [opt["value"] for opt in OPTIONS.get(field, [])]


def valid_values(field: str) -> set[Any]:
    """Set of valid values of a flat option field (empty set for unknown fields)."""
    return set(values_of(field))


def is_valid(field: str, value: Any) -> bool:
    """True when ``value`` is one of the options of the flat field."""
    return value in _OPTION_LABELS.get(field, {})


def label_for(field: str, value: Any) -> str:
    """Human label for one value of a field. Unknown values are returned
    as-is (stringified) so exports never lose data."""
    if field == "attack_subcategory":
        return subcategory_label(value)
    labels = _OPTION_LABELS.get(field, {})
    if value in labels:
        return labels[value]
    return "" if value is None else str(value)


def labels_for(field: str, values: Any) -> list[str]:
    """Labels for a list of values (a scalar is treated as a one-element list)."""
    if values is None:
        return []
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    return [label_for(field, v) for v in values]


def option_index(field: str, value: Any) -> int:
    """Sort key: position of ``value`` in the field's option list (unknown -> end)."""
    return _OPTION_INDEX.get(field, {}).get(value, 10_000)


def subcategory_values(attack_types: Any = None) -> list[str]:
    """Valid subcategory values for the given attack types (all groups when
    ``attack_types`` is None), in taxonomy order."""
    if attack_types is None:
        groups = ATTACK_TYPE_ORDER
    else:
        selected = set(attack_types)
        groups = [t for t in ATTACK_TYPE_ORDER if t in selected]
    out: list[str] = []
    for group in groups:
        out.extend(opt["value"] for opt in SUBCATEGORIES.get(group, []))
    return out


def subcategory_group(value: Any) -> str | None:
    """Attack type a subcategory value belongs to (None when unknown)."""
    return _SUBCATEGORY_GROUP.get(value)


def subcategory_index(value: Any) -> int:
    """Sort key for subcategory values: grouped by attack type order, then
    by position inside the group (unknown -> end)."""
    return _SUBCATEGORY_INDEX.get(value, 10_000_000)


def subcategory_label(value: Any) -> str:
    """Human label of a subcategory value (unknown values returned as-is)."""
    if value in _SUBCATEGORY_LABEL:
        return _SUBCATEGORY_LABEL[value]
    return "" if value is None else str(value)


def length_bucket(n: int | None) -> str:
    """Bucket a character count the way the customer record expects."""
    n = int(n or 0)
    if n < 100:
        return "< 100 char"
    if n < 500:
        return "100 - 500 char"
    if n < 1000:
        return "500 - 1,000 char"
    if n < 5000:
        return "1,000 - 5,000 char"
    if n < 10000:
        return "5,000 - 10,000 char"
    return "10,000+ char"


def taxonomy_payload() -> dict[str, Any]:
    """JSON body of ``GET /api/v1/annotation/taxonomy``."""
    return {
        "data_type": list(OPTIONS["data_type"]),
        "data_structure": list(OPTIONS["data_structure"]),
        "attack_type": list(OPTIONS["attack_type"]),
        "attack_subcategory": {group: list(SUBCATEGORIES.get(group, [])) for group in ATTACK_TYPE_ORDER},
        "domain": list(OPTIONS["domain"]),
        "role": list(OPTIONS["role"]),
        "language": list(OPTIONS["language"]),
        "intention": list(OPTIONS["intention"]),
        "source": list(OPTIONS["source"]),
        "severity_levels": list(SEVERITY_LEVELS),
        "defaults": dict(DEFAULTS),
    }
