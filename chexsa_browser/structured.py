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


def conforms(value, schema):
    """Check provider-error JSON; only missing nullable fields may be omitted."""
    if "anyOf" in schema:
        return any(conforms(value, alternative) for alternative in schema["anyOf"])
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    actual = {str: "string", bool: "boolean", int: "integer", float: "number", dict: "object", list: "array", type(None): "null"}.get(type(value))
    if actual not in types and not (actual == "integer" and "number" in types):
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if set(value) - set(properties):
            return False
        if any(key not in value and not conforms(None, properties[key]) for key in schema.get("required", [])):
            return False
        return all(conforms(item, properties[key]) for key, item in value.items())
    if isinstance(value, list):
        return all(conforms(item, schema["items"]) for item in value)
    return True
