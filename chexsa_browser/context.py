"""Bounded complete records, local search, and explicit observation-scoped paging."""

import json
import hashlib

from .models import BrowserError


def short(value, limit):
    value = str(value)
    return value if len(value) <= limit else value[:limit] + "… [expand with inspect_region]"


def record(element):
    item = {"ref": element.ref, "role": element.role, "name": short(element.name, 180), "actions": element.capabilities}
    flags = {k: v for k, v in element.states.items() if k in ("disabled", "readonly", "checked", "expanded", "selected", "focused", "required", "invalid") and (v or k in ("checked", "selected", "expanded"))}
    if element.value:
        item["value"] = short(element.value, 300)
    if flags:
        item["state"] = flags
    if element.context:
        item["context"] = short(" > ".join(element.context), 240)
    return item


def changes(previous, current):
    if previous is None:
        return ["Initial page state."]
    result = []
    # Text has stable node keys; equal strings in different controls are not merged.
    for key, item in current.text.items():
        if previous.text.get(key) != item:
            result.append("Added/changed text: " + short(item["text"], 350))
    before = {e.identity: e for e in previous.elements}
    after = {e.identity: e for e in current.elements}
    for key, element in after.items():
        if key not in before or before[key].signature() != element.signature():
            result.append("Control: " + json.dumps(record(element), ensure_ascii=False))
    for key, element in before.items():
        if key not in after:
            result.append(f"Removed: {element.role} {short(element.name, 150)}")
    return result or ["No visible changes."]


class ContextView:
    def __init__(self, budget=12000):
        if budget < 2000:
            raise ValueError("Page context budget must be at least 2000 characters.")
        self.budget = budget
        self.selected = None
        self._automatic = None

    def _cursor(self, observation, scope, offset):
        key = hashlib.sha256(scope.encode()).hexdigest()[:10]
        return f"{observation.id}:{key}:{offset}"

    def _offset(self, observation, cursor, scope):
        if not cursor:
            return 0
        try:
            generation, key, value = cursor.rsplit(":", 2)
            offset = int(value)
            if generation != observation.id or cursor != self._cursor(observation, scope, offset) or offset < 0:
                raise ValueError
            return offset
        except (ValueError, AttributeError):
            raise BrowserError("stale_cursor", "Use the next_cursor returned by the same query or region in this observation; this cursor does not belong to it.")

    def page(self, observation, elements, cursor=None, budget=None, scope="page"):
        start = self._offset(observation, cursor, scope)
        if start > len(elements):
            raise BrowserError("stale_cursor", "This cursor is beyond the available results.")
        records, used = [], 0
        for element in elements[start:]:
            item = record(element)
            size = len(json.dumps(item, ensure_ascii=False)) + 2
            maximum = budget or self.budget // 2
            if not records and size > maximum:
                # Even a huge accessible name must not create an endless :0 cursor.
                item = {"ref": element.ref, "role": element.role, "name": short(element.name, 80), "expand": True}
                size = len(json.dumps(item, ensure_ascii=False)) + 2
            if used + size > maximum:
                break
            records.append(item)
            used += size
        end = start + len(records)
        return {"observation_id": observation.id, "elements": records, "omitted": max(0, len(elements) - end), "next_cursor": self._cursor(observation, scope, end) if end < len(elements) else None}

    def find(self, observation, query, cursor=None):
        if not isinstance(query, str) or len(query) > 1000:
            raise BrowserError("invalid_arguments", "Search query must be a string of at most 1000 characters.")
        words = query.casefold().split()
        matches = [e for e in observation.elements if all(word in f"{e.role} {e.name} {' '.join(e.context)}".casefold() for word in words)]
        return self.page(observation, matches, cursor, scope="find:" + " ".join(words))

    def inspect(self, observation, ref="page", cursor=None):
        if ref == "page":
            return self.page(observation, [e for e in observation.elements if e.capabilities or e.role in ("heading", "status", "alert")], cursor)
        region = next((r for r in observation.regions if r.ref == ref or r.key == ref), None)
        if region:
            self.selected = region.key
            return self.page(observation, [e for e in region.elements if e.capabilities or e.role in ("heading", "status", "alert")], cursor, scope="region:" + region.key)
        element = next((e for e in observation.elements if e.ref == ref), None)
        if not element:
            raise BrowserError("stale_target", "Unknown region or element. Observe again.")
        scope = "field:" + element.identity
        offset = self._offset(observation, cursor, scope)
        raw = json.dumps({"name": element.name, "value": element.value, "context": element.context}, ensure_ascii=False)
        chunk = raw[offset:offset + self.budget // 4]
        end = offset + len(chunk)
        return {"ref": ref, "observation_id": observation.id, "text_chunk": chunk, "next_cursor": self._cursor(observation, scope, end) if end < len(raw) else None}

    def tabs(self, observation, cursor=None):
        offset = self._offset(observation, cursor, "tabs")
        items, size = [], 0
        for tab in observation.tabs[offset:]:
            item = {**tab, "title": short(tab["title"], 100), "url": short(tab["url"], 180)}
            length = len(json.dumps(item, ensure_ascii=False)) + 2
            if size + length > self.budget // 2:
                break
            items.append(item)
            size += length
        end = offset + len(items)
        return {"tabs": items, "omitted": len(observation.tabs) - end, "next_cursor": self._cursor(observation, "tabs", end) if end < len(observation.tabs) else None}

    def render(self, observation, discovery=None):
        region = next((r for r in observation.regions if r.key == self.selected), None)
        # A newly focused form/dialog takes precedence over a previously inspected inbox.
        if observation.regions and (region is None or observation.regions[0].key != self._automatic and observation.regions[0].priority >= 100):
            region = observation.regions[0]
        self._automatic = observation.regions[0].key if observation.regions else None
        self.selected = region.key if region else None
        overview = [{"ref": r.ref, "label": short(r.label, 160), "controls": sum(bool(e.capabilities) for e in r.elements), "examples": [short(e.name, 60) for e in r.elements if e.capabilities and e.name][:3]} for r in observation.regions[:12]]
        data = {"observation_id": observation.id, "page_id": observation.page_id, "url": short(observation.url, 500), "title": short(observation.title, 180), "tabs": [{**tab, "title": short(tab["title"], 100), "url": short(tab["url"], 180)} for tab in observation.tabs[:12]], "tabs_omitted": max(0, len(observation.tabs) - 12), "regions": overview, "regions_omitted": max(0, len(observation.regions) - 12), "focused_region": region.ref if region else "page", "issues": observation.issues[:5]}
        # Reserve space for changes and text; never cut serialized control records.
        source = region.elements if region and region.key != "page" else observation.elements
        controls = [e for e in source if e.capabilities or e.role in ("heading", "status", "alert")]
        control_scope = "region:" + region.key if region and region.key != "page" else "page"
        data["controls"] = self.page(observation, controls, budget=self.budget // 2, scope=control_scope)
        # A compact index avoids a discovery round-trip for a search/form field
        # outside the automatically selected landmark. Full records stay local.
        fields = [e for e in observation.elements if e.region != self.selected and "type" in e.capabilities]
        data["field_index"] = [{"ref": e.ref, "role": e.role, "name": short(e.name, 80), "actions": ["type"], "context": short(" > ".join(e.context), 80)} for e in fields[:6]]
        data["fields_omitted"] = max(0, len(fields) - len(data["field_index"]))
        data["changes"] = []
        data["text"] = []
        if discovery is not None:
            data["discovery"] = discovery
        for change in observation.changes:
            candidate = data["changes"] + [change]
            if len(json.dumps(candidate, ensure_ascii=False)) > self.budget // 5:
                break
            if len(json.dumps({**data, "changes": candidate}, ensure_ascii=False)) > self.budget - 700:
                break
            data["changes"] = candidate
        data["changes_omitted"] = max(0, len(observation.changes) - len(data["changes"]))
        for item in observation.text.values():
            if region and region.key != "page" and region.key not in item["region_path"]:
                continue
            candidate = data["text"] + [short(item["text"], 350)]
            if len(json.dumps({**data, "text": candidate}, ensure_ascii=False)) > self.budget:
                break
            data["text"] = candidate
        # Search results can use half a budget; shrink overview/controls to accommodate.
        while len(json.dumps(data, ensure_ascii=False)) > self.budget:
            if data["changes"]:
                data["changes"].pop()
                data["changes_omitted"] += 1
            elif data["text"]:
                data["text"].pop()
            elif data["regions"]:
                data["regions"].pop()
                data["regions_omitted"] += 1
            elif data["controls"]["elements"]:
                data["controls"]["elements"].pop()
                data["controls"]["omitted"] += 1
                data["controls"]["next_cursor"] = self._cursor(observation, control_scope, len(data["controls"]["elements"]))
            elif data["tabs"]:
                data["tabs"].pop()
                data["tabs_omitted"] += 1
            elif data["field_index"]:
                data["field_index"].pop()
                data["fields_omitted"] += 1
            else:
                break
        observation.context = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return observation.context
