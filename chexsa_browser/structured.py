"""Small strict provider schemas; normal action and target guards still apply."""

from .actions import BATCHABLE, FIELDS


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


STRING = {"type": "string"}
BOOLEAN = {"type": "boolean"}
STRINGS = {"type": "array", "items": STRING}
PLAN = obj({"inputs": {"type": "array", "items": obj({"name": STRING, "value": STRING})}, "subgoals": STRINGS, "completion": STRINGS, "intent": {"type": "string", "enum": ["act", "draft"]}})
PREFLIGHT = obj({"ready": BOOLEAN, **{key: STRING for key in ("region_ref", "subject_ref", "body_ref", "recipient_ref", "recipient_text", "reason")}})
VERIFY = obj({"complete": BOOLEAN, "failed": BOOLEAN, "progress": STRING, "evidence": STRINGS, "reason": STRING, "visual_evidence": {"type": ["boolean", "null"]}, "screenshot_id": {"type": ["string", "null"]}})


def arguments(actions):
    types = {str: "string", bool: "boolean", int: "integer", (int, float): "number"}
    fields = {}
    for action in actions:
        required, optional = FIELDS[action]
        for name, kind in {**required, **optional}.items():
            if kind is not list:
                fields[name] = {"type": [types[kind], "null"]}
    return fields


def decision(actions):
    fields = arguments(actions)
    fields.update({"response": {"type": ["string", "null"]}, "question": {"type": ["string", "null"]}})
    if "batch" in actions:
        fields["actions"] = {"anyOf": [{"type": "array", "items": obj({"action": {"type": "string", "enum": sorted(BATCHABLE)}, "arguments": obj(arguments(BATCHABLE))})}, {"type": "null"}]}
    return obj({"action": {"type": "string", "enum": [*actions, "finish", "ask_user"]}, "arguments": obj(fields), "effect": obj({"kind": {"type": ["string", "null"], "enum": ["value", "checked", "selection", "change", "submission", None]}, "value": {"type": ["string", "null"]}, "text": {"type": ["string", "null"]}})})


def without_nulls(value):
    """Null means omitted; preserve meaningful false, zero, and empty strings."""
    if isinstance(value, dict):
        return {key: without_nulls(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [without_nulls(item) for item in value]
    return value
