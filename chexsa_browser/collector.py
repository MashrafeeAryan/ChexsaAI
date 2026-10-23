"""Join public CDP accessibility and DOM snapshots by backend node identity."""

from .models import Element


LANDMARKS = {"dialog", "alertdialog", "form", "main", "navigation", "region", "complementary", "search", "article"}
CLICK_ROLES = {"button", "link", "tab", "menuitem", "menuitemcheckbox", "menuitemradio", "option", "treeitem", "listitem"}
EDIT_ROLES = {"textbox", "searchbox", "spinbutton"}


def capabilities(role, tag, attributes, states, clickable=False):
    """Capabilities are independent of whether a node has a name or a ref."""
    result = []
    if role in CLICK_ROLES or clickable:
        result.append("click")
    if role in EDIT_ROLES or attributes.get("contenteditable") in ("", "true") and "contenteditable" in attributes:
        if not states.get("readonly"):
            result.append("type")
    if tag == "INPUT" and attributes.get("type", "text") not in ("checkbox", "radio", "file", "submit", "button", "hidden", "range", "color"):
        if not states.get("readonly"):
            result.append("type")
    if tag == "SELECT":
        result.append("select_option")
    if role in ("checkbox", "switch", "menuitemcheckbox"):
        result.extend(("check", "uncheck", "click"))
    if role in ("radio", "menuitemradio"):
        result.extend(("check", "click"))
    if tag == "INPUT" and attributes.get("type") == "file":
        result.append("upload_file")
    return tuple(dict.fromkeys(result))


def parse_document(target_id, frame_id, document_id, document, strings, ax_nodes):
    """Return complete local structures; formatting and budgets belong elsewhere."""
    nodes = document.get("nodes", {})
    backends = nodes.get("backendNodeId", [])
    indexes = {backend: i for i, backend in enumerate(backends)}
    ax_by_id = {node["nodeId"]: node for node in ax_nodes}
    ax_by_backend = {node["backendDOMNodeId"]: node for node in ax_nodes if node.get("backendDOMNodeId")}
    layout = document.get("layout", {})
    boxes = dict(zip(layout.get("nodeIndex", []), layout.get("bounds", [])))
    clickable = set(nodes.get("isClickable", {}).get("index", []))
    input_values = nodes.get("inputValue", {})
    values = dict(zip(input_values.get("index", []), input_values.get("value", [])))
    def string(index):
        return strings[index] if isinstance(index, int) and 0 <= index < len(strings) else ""
    def attributes(index):
        raw = nodes.get("attributes", [])[index] if index < len(nodes.get("attributes", [])) else []
        return {string(raw[i]): string(raw[i + 1]) for i in range(0, len(raw) - 1, 2)}
    def identity(backend):
        return f"{target_id}/{frame_id}/{document_id}/{backend}"
    def ancestry(ax):
        labels, regions, seen, live = [], [], set(), False
        parent = ax.get("parentId")
        while parent and parent not in seen:
            seen.add(parent)
            node = ax_by_id.get(parent, {})
            role, name = node.get("role", {}).get("value", ""), node.get("name", {}).get("value", "")
            live = live or role in ("status", "alert")
            if role in LANDMARKS:
                if name:
                    labels.append(f'{role} {name}')
                if node.get("backendDOMNodeId"):
                    regions.append(identity(node["backendDOMNodeId"]))
            parent = node.get("parentId")
        return tuple(reversed(labels)), tuple(reversed(regions)), live
    elements, text = [], {}
    for backend, index in indexes.items():
        ax = ax_by_backend.get(backend, {})
        attrs = attributes(index)
        tag = string(nodes.get("nodeName", [])[index]).upper()
        role = ax.get("role", {}).get("value", "").lower()
        props = {p["name"]: p.get("value", {}).get("value") for p in ax.get("properties", [])}
        props.update(disabled=bool(props.get("disabled") or "disabled" in attrs), readonly=bool(props.get("readonly") or "readonly" in attrs))
        name = str(ax.get("name", {}).get("value", ""))
        if ax and not ax.get("ignored"):
            props.update(_ax_role=role, _ax_name=name)
        context, region_path, live = ancestry(ax)
        caps = capabilities(role, tag, attrs, props, index in clickable)
        file_input = "upload_file" in caps
        if ax.get("ignored", not bool(ax)) and not file_input and not (index in clickable and index in boxes):
            continue
        if role in ("statictext", "inlinetextbox") and name.strip():
            # InlineTextBox repeats its StaticText parent's content.
            if role == "statictext":
                text[identity(backend)] = {"text": name, "region_path": region_path, "live": live}
            continue
        if not caps and role not in LANDMARKS | {"heading", "status", "alert"}:
            continue
        parent = ax_by_id.get(ax.get("parentId"), {}).get("backendDOMNodeId")
        value = str(ax.get("value", {}).get("value", string(values.get(index))))
        if attrs.get("type") == "password":
            value = "[redacted]" if value else ""
        elements.append(Element(target_id, frame_id, document_id, backend, role or tag.lower(), name or attrs.get("aria-label") or attrs.get("placeholder") or attrs.get("title") or ("File input" if file_input else ""), identity(parent) if parent else None, value, props, caps, context, tuple(boxes.get(index, ())), region_path=region_path))
    return elements, text


class Collector:
    def __init__(self, session):
        self.session = session

    def collect(self):
        elements, text, issues = [], {}, []
        for target_id, client in self.session.targets():
            try:
                snapshot = client.send("DOMSnapshot.captureSnapshot", {"computedStyles": [], "includeDOMRects": True})
                documents = snapshot.get("documents", [])
                for document in documents:
                    strings = snapshot["strings"]
                    frame_id = strings[document["frameId"]]
                    root_id = document["nodes"]["backendNodeId"][0]
                    document_id = str(root_id)
                    ax = client.send("Accessibility.getFullAXTree", {"frameId": frame_id})["nodes"]
                    batch, words = parse_document(target_id, frame_id, document_id, document, strings, ax)
                    elements.extend(batch)
                    text.update(words)
            except Exception as error:
                if target_id == self.session.page_id:
                    raise
                issues.append(f"Frame could not be observed: {type(error).__name__}")
        return elements, text, issues
