"""Open Chrome and read the current page."""

from task_metrics_ import time_step

import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from weakref import WeakKeyDictionary

from playwright.sync_api import Error, sync_playwright

from observations_ import control_details, validate_action_group, validate_wait

# Remember which Chrome nodes belong to the latest page observation.
_observations = WeakKeyDictionary()
_CONTROL_ROLES = {
    "button",
    "link",
    "textbox",
    "searchbox",
    "combobox",
    "checkbox",
    "radio",
    "switch",
    "spinbutton",
    "slider",
    "tab",
    "menuitem",
    "menuitemcheckbox",
    "menuitemradio",
    "option",
    "treeitem",
}


# Connect to Chrome, or open it with Chexsa's saved browser profile.
def open_browser():
    playwright = sync_playwright().start()

    try:
        try:
            # Chrome must allow remote control for this connection to work.
            browser = playwright.chromium.connect_over_cdp(
                "http://127.0.0.1:9222", timeout=2000
            )
            context = browser.contexts[0] if browser.contexts else browser.new_context()
        except Error:
            # Reuse this folder so logins survive when Chexsa opens Chrome again.
            profile = (
                Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
                / "Chexsa"
                / "chrome"
            )
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                channel="chrome",
                headless=False,
                args=["--no-first-run", "--no-default-browser-check"],
            )

        # context.pages means the open tabs. Keep tabs that are not closed
        # and show a website, a local file, or a blank page; skip Chrome settings.
        pages = [
            page
            for page in context.pages
            if not page.is_closed()
            and page.url.startswith(("http://", "https://", "file://", "about:blank"))
        ]
        page = pages[-1] if pages else context.new_page()

        return playwright, page
    except Exception:
        # Stop the connection if startup fails partway through.
        playwright.stop()
        raise


def list_tabs(current):
    """Return a bounded list of open web tabs and keep their objects separate."""
    targets, descriptions = {}, []
    for tab in current.context.pages:
        if tab.is_closed():
            continue

        url = tab.url
        address = urlsplit(url)
        if address.scheme not in ("http", "https") and url != "about:blank":
            continue
        if len(targets) >= 20:
            continue

        number = len(targets) + 1
        targets[number] = (tab, url)
        # Keep URL credentials, query values, and fragments off the model request.
        short_url = url
        if address.hostname:
            host = address.hostname
            if ":" in host:
                host = f"[{host}]"
            if address.port is not None:
                host += f":{address.port}"
            short_url = f"{address.scheme}://{host}{address.path}"
        descriptions.append({
            "tab": number,
            "url": short_url[:240],
            "current": tab is current,
        })
    return descriptions, targets


def select_tab(listed, number):
    """Select the same still-open tab that was listed, even if tabs were reordered."""
    entry = listed.get(number)
    if entry is None:
        raise RuntimeError("List current tabs before choosing one.")
    tab, url = entry
    if tab.is_closed() or tab.url != url:
        raise RuntimeError("The listed tab closed or changed. List tabs again.")
    return tab


# Read controls using the exact node IDs Chrome already gives us.
# Readable return fields (extra local fields keep identities, controls, and text nodes):
# {
#     "url": "https://example.com/mail",
#     "title": "Inbox",
#     "elements": (
#         '[10] button "Compose" | context: main "Inbox"\n'
#         '[12] textbox "Recipients" | context: dialog "New Message"\n'
#         '[14] textbox "Subject" | context: dialog "New Message"\n'
#         '[16] textbox "Message Body" | context: dialog "New Message"\n'
#         '[18] button "Send" | context: dialog "New Message"'
#     ),
#     "content": "Inbox\nCompose\nRecipients\nSubject\nMessage Body\nSend"
# }
@time_step("observation")
def read_page(page):
    previous = _observations.pop(page, None)
    if previous:
        try:
            previous["session"].detach()
        except Error:
            pass  # A closed tab may have already ended its connection.

    # CDP is Chrome's remote-control connection. It exposes exact node IDs.
    session = page.context.new_cdp_session(page)

    try:
        document = session.send("DOM.getDocument", {"depth": 0})["root"][
            "backendNodeId"
        ]
        nodes = session.send("Accessibility.getFullAXTree")["nodes"]
        by_id = {node["nodeId"]: node for node in nodes}
        targets, lines, text_lines = set(), [], []
        controls, text_nodes = {}, {}
        headings = []

        for node in nodes:
            if node.get("ignored"):
                continue

            role = node.get("role", {}).get("value", "").lower()
            name = node.get("name", {}).get("value", "")

            # Read ordinary text from this same tree. InlineTextBox repeats it.
            if role == "statictext" and name.strip():
                # Chrome also puts field values in text children; keep those values local.
                ancestor = by_id.get(node.get("parentId"))
                while ancestor and ancestor.get("role", {}).get(
                    "value", ""
                ).lower() not in (
                    "textbox",
                    "searchbox",
                    "combobox",
                    "spinbutton",
                ):
                    ancestor = by_id.get(ancestor.get("parentId"))
                if ancestor is None:
                    text_lines.append(name)
                    text_id = node.get("backendDOMNodeId", "ax:" + node["nodeId"])
                    text_nodes[text_id] = name

            if role == "heading" and name.strip():
                level = next(
                    (prop.get("value", {}).get("value") for prop in node.get("properties", [])
                     if prop["name"] == "level"),
                    None,
                )
                headings.append({"level": level, "title": name[:240]})

            target = node.get("backendDOMNodeId")
            if role not in _CONTROL_ROLES or not target:
                continue

            targets.add(target)
            line = f"[{target}] {role} {json.dumps(name, ensure_ascii=False)}"

            # Walk up the page structure to show where duplicate controls belong.
            context = []
            region_id = None
            # Track real parents locally; identical names can belong to different forms.
            ancestors = []
            parent = by_id.get(node.get("parentId"))
            while parent:
                if parent.get("backendDOMNodeId"):
                    ancestors.append(parent["backendDOMNodeId"])
                parent_role = parent.get("role", {}).get("value", "").lower()
                if parent_role in (
                    "dialog",
                    "alertdialog",
                    "main",
                    "form",
                    "navigation",
                    "region",
                ):
                    if region_id is None:
                        region_id = parent.get("backendDOMNodeId", parent["nodeId"])
                    parent_name = parent.get("name", {}).get("value", "")
                    context.append(
                        f"{parent_role} {json.dumps(parent_name, ensure_ascii=False)}"
                    )
                parent = by_id.get(parent.get("parentId"))

            if context:
                line += " | context: " + " > ".join(reversed(context))
            lines.append(line)

            # Keep values and states locally so changes include more than renamed buttons.
            states = {
                prop["name"]: prop.get("value", {}).get("value")
                for prop in node.get("properties", [])
                if prop["name"]
                in (
                    "disabled",
                    "readonly",
                    "checked",
                    "selected",
                    "expanded",
                    "pressed",
                    "focused",
                )
            }
            # Chrome represents some checkbox states as a tri-state string.
            if states.get("checked") in ("true", "false"):
                states["checked"] = states["checked"] == "true"
            controls[target] = {
                "line": line,
                "role": role,
                "name": name,
                "context": context,
                "region_id": region_id,
                "ancestors": ancestors,
                "value": node.get("value", {}).get("value", ""),
                "states": states,
            }

        result = {
            "url": page.url,
            "title": page.title(),
            # These local fields let us compare the same nodes on the same document.
            "page_id": id(page),
            "document_id": document,
            "controls": controls,
            "text_nodes": text_nodes,
            "headings": headings,
            "elements": "\n".join(lines),
            # Plain accessible text, rather than a second formatted tree snapshot.
            "content": "\n".join(text_lines),
        }

        # Keep the full tree locally too. The AI payload does not include it.
        _observations[page] = {
            "session": session,
            "document": document,
            "nodes": targets,
            "tree": nodes,
            "observation": result,
        }
        return result

    except Exception:
        try:
            session.detach()
        except Error:
            pass  # The tab may have closed while we were reading it.
        raise


@time_step("observation")
def selected_page_text(page):
    """Return selected regular page text without reading a field or clipboard."""
    return page.evaluate("""() => {
        let focus = document.activeElement;
        while (focus?.shadowRoot?.activeElement) focus = focus.shadowRoot.activeElement;
        if (focus?.matches('input, textarea') || focus?.isContentEditable) return '';
        return window.getSelection()?.toString() || '';
    }""")


@time_step("action")
def scroll_page(page, direction):
    """Move about one screen in the active page and return whether it moved."""
    if direction not in ("up", "down"):
        raise ValueError("Choose up or down.")
    return page.evaluate(
        """direction => {
            const before = window.scrollY;
            const distance = Math.round(window.innerHeight * 0.8);
            window.scrollBy({top: direction === "down" ? distance : -distance, behavior: "instant"});
            return window.scrollY !== before;
        }""",
        direction,
    )


@time_step("action")
def press_navigation_key(page, key):
    """Move focus or dismiss a popup with a short list of supported keys."""
    if key not in ("Tab", "Shift+Tab", "Escape"):
        raise ValueError("Use Tab, Shift+Tab, or Escape for browser navigation.")
    page.keyboard.press(key)


@time_step("action")
def scroll_region(page, target, direction):
    """Scroll the nearest scrollable ancestor of a shown control."""
    if direction not in ("up", "down"):
        raise ValueError("Choose up or down.")
    return _node_call(page, target, """function(direction) {
        if (!this.isConnected) return false;
        for (let node = this; node; node = node.parentElement || node.getRootNode().host) {
            const style = getComputedStyle(node);
            if (!['auto', 'scroll'].includes(style.overflowY) ||
                node.scrollHeight <= node.clientHeight) continue;
            const before = node.scrollTop;
            const distance = Math.round(node.clientHeight * 0.8);
            node.scrollBy({top: direction === 'down' ? distance : -distance, behavior: 'instant'});
            return node.scrollTop !== before;
        }
        return false;
    }""", direction)


# Check that a Chrome node was observed in this tab and is still on the page.
def resolve_node(page, backend_node_id):
    observation = _observations.get(page)
    if (
        type(backend_node_id) is not int
        or not observation
        or backend_node_id not in observation["nodes"]
    ):
        raise RuntimeError(
            "This node was not observed in this tab. Read the page again."
        )

    if page.is_closed():
        raise RuntimeError("This tab is closed. Read an open tab again.")

    session = observation["session"]

    try:
        document = session.send("DOM.getDocument", {"depth": 0})["root"][
            "backendNodeId"
        ]
        if document != observation["document"]:
            raise RuntimeError(
                "The page changed. Read it again before using this node."
            )

        # A removed node can still have an ID, so check that it remains on the page.
        node = session.send("DOM.resolveNode", {"backendNodeId": backend_node_id})[
            "object"
        ]["objectId"]

        try:
            connected = session.send(
                "Runtime.callFunctionOn",
                {
                    "objectId": node,
                    "functionDeclaration": "function() { return this.isConnected; }",
                    "returnByValue": True,
                },
            )["result"].get("value")
            if not connected:
                raise RuntimeError("The element was removed. Read the page again.")
        finally:
            session.send("Runtime.releaseObject", {"objectId": node})

        return session, backend_node_id

    except Error:
        raise RuntimeError(
            "This element is no longer available. Read the page again."
        ) from None


# Click an observed Chrome node through CDP; this does not move the Windows cursor.
@time_step("action")
def click_node(page, backend_node_id):
    session, target = resolve_node(page, backend_node_id)
    node = None
    pressed = False

    try:
        session.send("DOM.scrollIntoViewIfNeeded", {"backendNodeId": target})
        node = session.send("DOM.resolveNode", {"backendNodeId": target})["object"][
            "objectId"
        ]

        # Ask the actual element for a visible point, and check what covers that point.
        check_point = {
            "objectId": node,
            "returnByValue": True,
            "functionDeclaration": """function() {
                if (!this.isConnected) return {error: "The element was removed."};
                if (this.matches(':disabled') || this.closest('[aria-disabled="true"], [inert]'))
                    return {error: "The element is disabled."};
                const style = getComputedStyle(this);
                const r = this.getBoundingClientRect();
                const left = Math.max(0, r.left), right = Math.min(innerWidth, r.right);
                const top = Math.max(0, r.top), bottom = Math.min(innerHeight, r.bottom);
                if (style.visibility !== 'visible' || right <= left || bottom <= top)
                    return {error: "The element is not visible."};
                const x = (left + right) / 2, y = (top + bottom) / 2;
                let hit = this.ownerDocument.elementFromPoint(x, y);
                // Look inside open shadow roots too, such as custom web controls.
                while (hit && hit.shadowRoot) {
                    const inner = hit.shadowRoot.elementFromPoint(x, y);
                    if (!inner || inner === hit) break;
                    hit = inner;
                }
                for (let current = hit; current; current = current.parentNode || current.host) {
                    if (current === this) return {x, y};
                }
                return {error: "Another element is covering the target."};
            }""",
        }
        previous = None

        # Moving over a control can change the page. Check again before pressing.
        for event in ("mouseMoved", "mousePressed"):
            response = session.send("Runtime.callFunctionOn", check_point)
            point = response.get("result", {}).get("value")
            if response.get("exceptionDetails") or not isinstance(point, dict):
                raise RuntimeError("Could not check the target. Read the page again.")

            if "error" in point:
                raise RuntimeError(point["error"] + " Read the page again.")

            if previous and (
                abs(point["x"] - previous["x"]) > 1
                or abs(point["y"] - previous["y"]) > 1
            ):
                raise RuntimeError(
                    "The target moved. Read the page again before clicking."
                )

            arguments = {"type": event, "x": point["x"], "y": point["y"]}
            if event == "mousePressed":
                arguments.update(button="left", clickCount=1)
                pressed = True

            session.send("Input.dispatchMouseEvent", arguments)
            previous = point

        session.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": point["x"],
                "y": point["y"],
                "button": "left",
                "clickCount": 1,
            },
        )

    except Error:
        if pressed:
            raise RuntimeError(
                "The click outcome is uncertain. Read the page before retrying."
            ) from None
        raise RuntimeError(
            "Could not click this element. Read the page again."
        ) from None

    finally:
        if node is not None:
            try:
                session.send("Runtime.releaseObject", {"objectId": node})
            except Error:
                pass  # Clicking may have loaded a new page and removed the old node.

        if pressed:
            # Require a new reading before another click; never repeat an uncertain click.
            _observations.pop(page, None)
            try:
                session.detach()
            except Error:
                pass


def inspect_control(page, observation, target):
    """Describe the state and useful operations of an exact observed browser control."""
    if _observations.get(page, {}).get("observation") is not observation:
        raise RuntimeError("This reading is old or already used. Read the page again.")
    resolve_node(page, target)
    control = observation["controls"][target]
    role = control["role"]
    state = control["states"]
    actions = []
    if not state.get("disabled"):
        actions.append("click")
        if role in ("textbox", "searchbox") and not state.get("readonly"):
            actions.append("type")
        if role in ("checkbox", "switch") and type(state.get("checked")) is bool:
            actions.append("set_checked")
        if role == "combobox":
            actions.append("read_options")
    details = control_details(target, role, control["name"], state, actions)
    if control["context"]:
        details["context"] = [name[:120] for name in control["context"][:3]]
    return details


def _node_call(page, target, script, *values):
    """Run one built-in operation on an exact live Chrome node."""
    session, target = resolve_node(page, target)
    node = None
    try:
        node = session.send("DOM.resolveNode", {"backendNodeId": target})["object"]["objectId"]
        response = session.send("Runtime.callFunctionOn", {
            "objectId": node,
            "functionDeclaration": script,
            "arguments": [{"value": value} for value in values],
            "returnByValue": True,
        })
        if "exceptionDetails" not in response and "value" in response.get("result", {}):
            return response["result"]["value"]
    except Error:
        pass
    finally:
        if node is not None:
            try:
                session.send("Runtime.releaseObject", {"objectId": node})
            except Error:
                pass  # The page may have navigated during the operation.
    raise RuntimeError("Could not check the target result. Read the current page again.")


@time_step("action")
def upload_file(page, target, path):
    """Attach a checked local file to one exact native input and verify selection."""
    path = Path(path)
    file_info = path.stat()
    usable = _node_call(page, target, """function() {
        if (!this.isConnected || this.tagName !== 'INPUT' || this.type !== 'file') return false;
        if (this.matches(':disabled') || this.closest('[aria-disabled="true"], [inert]')) return false;
        const rect = this.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && getComputedStyle(this).visibility === 'visible';
    }""")
    if usable is not True:
        raise RuntimeError("The observed control is not an enabled, visible file input.")

    session, target = resolve_node(page, target)
    try:
        session.send("DOM.setFileInputFiles", {
            "files": [str(path)],
            "backendNodeId": target,
        })
        attached = _node_call(page, target, """function() {
            const file = this.files && this.files.length === 1 && this.files[0];
            return file ? {name: file.name, size: file.size} : null;
        }""")
        if attached == {"name": path.name, "size": file_info.st_size}:
            return {"filename": path.name, "attached": True}
    except (Error, RuntimeError):
        pass
    finally:
        reading = _observations.pop(page, None)
        if reading:
            try:
                reading["session"].detach()
            except Error:
                pass
    raise RuntimeError("The attachment outcome is uncertain. Read the page before trying again.")


@time_step("observation")
def read_options(page, target, offset=0):
    """Read a page of labels from a native single-choice select."""
    result = _node_call(page, target, """function(offset) {
        if (!this.isConnected || this.tagName !== 'SELECT' || this.multiple) return null;
        const options = Array.from(this.options);
        return {
            options: options.slice(offset, offset + 30).map(option => ({
                label: option.label.slice(0, 240),
                selected: option.selected,
                disabled: option.matches(':disabled')
            })),
            total: options.length
        };
    }""", offset)
    if result is None:
        return {"options": [], "note": "This is not a native single-choice select."}
    end = offset + len(result["options"])
    result["next_offset"] = end if end < result["total"] else None
    return result


@time_step("action")
def select_option(page, target, label):
    """Choose one exact native option and check what the select kept."""
    if not isinstance(label, str) or not label.strip() or len(label) > 240:
        raise ValueError("Provide one exact option label.")
    try:
        result = _node_call(page, target, """function(label) {
            if (!this.isConnected || this.tagName !== 'SELECT' || this.multiple)
                return "This is not a native single-choice select.";
            if (this.matches(':disabled') || this.closest('[aria-disabled="true"], [inert]'))
                return "This select is disabled.";
            const rect = this.getBoundingClientRect();
            if (!rect.width || !rect.height || getComputedStyle(this).visibility !== 'visible')
                return "This select is hidden.";
            const choices = Array.from(this.options).filter(option => option.label === label);
            if (choices.length !== 1 || choices[0].matches(':disabled'))
                return "The option is absent, disabled, or ambiguous.";
            const option = choices[0];
            if (option.selected) return true;
            this.selectedIndex = option.index;
            this.dispatchEvent(new Event('input', {bubbles: true}));
            this.dispatchEvent(new Event('change', {bubbles: true}));
            return this.isConnected && option.isConnected && option.selected
                ? true : "The selected option could not be verified.";
        }""", label)
    finally:
        reading = _observations.pop(page, None)
        if reading:
            try:
                reading["session"].detach()
            except Error:
                pass
    if result is not True:
        raise RuntimeError(str(result) + " Read the page before trying again.")


@time_step("action")
def set_checked(page, reading, target, checked):
    """Click a checkbox only if needed, then check the same node's new state."""
    if type(checked) is not bool:
        raise ValueError("Choose true or false for checked.")
    resolve_node(page, target)
    current = read_page(page)
    same_document = current["document_id"] == reading["document_id"]
    control = current["controls"].get(target)
    if not same_document or not control or control["role"] not in ("checkbox", "switch"):
        raise RuntimeError("The checkbox changed. Read it again.")

    before = control["states"].get("checked")
    if before is checked:
        return current
    if type(before) is not bool:
        raise RuntimeError("The checkbox does not expose a definite checked state.")

    click_node(page, target)
    after = read_page(page)
    same_document = current["document_id"] == after["document_id"]
    state = after["controls"].get(target, {}).get("states", {}).get("checked")
    if not same_document or state is not checked:
        raise RuntimeError("Checkbox change could not be verified. Read the page before trying again.")
    return after


# Replace a text field's contents, then check that the exact field kept the text.
@time_step("action")
def type_node(page, backend_node_id, text):
    if not isinstance(text, str):
        raise RuntimeError("Typing requires text.")

    session, target = resolve_node(page, backend_node_id)
    node = None
    attempted = False

    try:
        session.send("DOM.scrollIntoViewIfNeeded", {"backendNodeId": target})
        node = session.send("DOM.resolveNode", {"backendNodeId": target})["object"][
            "objectId"
        ]
        response = session.send(
            "Runtime.callFunctionOn",
            {
                "objectId": node,
                "returnByValue": True,
                "arguments": [
                    {"value": text.replace("\r\n", "\n").replace("\r", "\n")}
                ],
                "functionDeclaration": """function(text) {
                if (!this.isConnected) return "The text field was removed.";
                const plainInput = this.tagName === 'INPUT' &&
                    ['text', 'search', 'email', 'url', 'tel', 'password'].includes(this.type);
                if (!plainInput && this.tagName !== 'TEXTAREA' && !this.isContentEditable)
                    return "This element is not a supported text field.";
                if (this.readOnly || this.matches(':disabled') ||
                    this.closest('[aria-disabled="true"], [aria-readonly="true"], [inert]'))
                    return "This text field cannot be edited.";
                const r = this.getBoundingClientRect();
                if (!r.width || !r.height || getComputedStyle(this).visibility !== 'visible')
                    return "This text field is not visible.";
                // Accessibility values can be masked. Compare the real value locally.
                const current = this.isContentEditable
                    ? (this.childNodes.length === 1 && this.firstChild.nodeName === 'BR' ? '' : this.innerText)
                    : this.value;
                if (current === text) return true;
                this.focus({preventScroll: true});
                let active = this.ownerDocument.activeElement;
                while (active && active.shadowRoot && active.shadowRoot.activeElement)
                    active = active.shadowRoot.activeElement;
                if (!this.isConnected || active !== this) return "Could not focus this text field.";
                // Select the old text so the new text replaces it instead of being appended.
                if (this.isContentEditable) {
                    const range = this.ownerDocument.createRange();
                    range.selectNodeContents(this);
                    const selection = this.ownerDocument.getSelection();
                    selection.removeAllRanges();
                    selection.addRange(range);
                } else {
                    this.select();
                }
                return null;
            }""",
            },
        )
        if response.get("exceptionDetails") or "value" not in response.get(
            "result", {}
        ):
            raise RuntimeError(
                "Could not prepare this text field. Read the page again."
            )

        error = response["result"]["value"]
        if error is True:
            return  # The exact editable field already holds the requested text.
        if error:
            raise RuntimeError(error + " Read the page again.")

        attempted = True
        if text:
            session.send("Input.insertText", {"text": text})
        else:
            # Backspace clears selected text when the requested value is empty.
            for event in ("rawKeyDown", "keyUp"):
                session.send(
                    "Input.dispatchKeyEvent",
                    {
                        "type": event,
                        "key": "Backspace",
                        "code": "Backspace",
                        "windowsVirtualKeyCode": 8,
                    },
                )

        response = session.send(
            "Runtime.callFunctionOn",
            {
                "objectId": node,
                "returnByValue": True,
                "functionDeclaration": """function() {
                if (!this.isConnected) return null;
                if (!this.isContentEditable) return this.value;
                // Chrome leaves a placeholder line break in an emptied editable area.
                if (this.childNodes.length === 1 && this.firstChild.nodeName === 'BR') return '';
                return this.innerText;
            }""",
            },
        )

        # Read back this exact node. A changed or missing value is not success.
        expected = text.replace("\r\n", "\n").replace("\r", "\n")
        if (
            response.get("exceptionDetails")
            or response.get("result", {}).get("value") != expected
        ):
            raise RuntimeError(
                "Text entry could not be verified. Read the page before retrying."
            )

    except Error:
        if attempted:
            raise RuntimeError(
                "Text entry is uncertain. Read the page before retrying."
            ) from None
        raise RuntimeError(
            "Could not type into this field. Read the page again."
        ) from None
    finally:
        if node is not None:
            try:
                session.send("Runtime.releaseObject", {"objectId": node})
            except Error:
                pass  # The page may have removed the field during typing.

        if attempted:
            _observations.pop(page, None)
            try:
                session.detach()
            except Error:
                pass


def run_action_group(page, actions, observation, check_cancel=None, on_progress=None):
    """Execute a checked group without asking the model between its actions.

    Input: observed type actions, with an optional click at the end.
    Output: completed actions, a stop/error reason, and a fresh local observation.
    A completed click means input was sent; the page must still prove its outcome.
    on_progress can save partial work before input and after each local check.
    """
    validate_action_group(actions, observation["controls"])
    if _observations.get(page, {}).get("observation") is not observation:
        raise RuntimeError("This reading is old or already used. Read the page again.")

    if check_cancel:
        check_cancel()
    expected = {
        action["backend_node_id"]: observation["controls"][action["backend_node_id"]]
        for action in actions
    }
    current = read_page(page)
    result = {
        "completed": [],
        "remaining": len(actions),
        "stopped": None,
        "error": None,
        "observation": current,
        "attempting": None,
    }
    if on_progress:
        on_progress(result)

    for action in actions:
        control = expected[action["backend_node_id"]]
        invalid_check = action["action"] == "set_checked" and (
            control["role"] not in ("checkbox", "switch")
            or type(control["states"].get("checked")) is not bool
        )
        if control["states"].get("disabled") or invalid_check or (
            action["action"] == "type"
            and (
                control["states"].get("readonly")
                or control["role"] not in ("textbox", "searchbox", "combobox")
            )
        ):
            result["stopped"] = (
                "A planned control cannot perform this action. No actions were sent."
            )
            return result

    def assumptions_hold():
        """Stop on navigation, new controls, or changes to any planned target."""
        if any(
            current[key] != observation[key]
            for key in ("page_id", "document_id", "url")
        ):
            return False
        if current["controls"].keys() != observation["controls"].keys():
            return False
        for node, before in expected.items():
            after = current["controls"].get(node)
            if after is None or before is None:
                return False
            for key in ("role", "name", "context", "ancestors", "value"):
                if before[key] != after[key]:
                    return False
            # Focus naturally moves while typing. Other state changes need a new decision.
            if {
                key: value
                for key, value in before["states"].items()
                if key != "focused"
            } != {
                key: value for key, value in after["states"].items() if key != "focused"
            }:
                return False
        return True

    for action in actions:
        if check_cancel:
            check_cancel()
        if not assumptions_hold():
            result["stopped"] = (
                "The page or planned controls changed. Choose again from the fresh reading."
            )
            break

        node = action["backend_node_id"]
        # Check every remaining target's state before the first write too.
        if any(
            control["states"].get("disabled")
            for control in expected.values()
            if control
        ):
            result["stopped"] = (
                "A planned control is disabled. No further actions were sent."
            )
            break
        # Save intent before input, so interruption cannot make a sent action disappear.
        result["attempting"] = action.copy()
        if on_progress:
            on_progress(result)
        try:
            checked_reading = None
            if action["action"] == "type":
                type_node(page, node, action["text"])
            elif action["action"] == "set_checked":
                checked_reading = set_checked(page, current, node, action["checked"])
            else:
                click_node(page, node)
            result["completed"].append(action.copy())
            result["remaining"] -= 1
            current = checked_reading if checked_reading is not None else read_page(page)
            result["observation"] = current
            if action["action"] == "type":
                entered = current["controls"].get(node)
                text = action["text"].replace("\r\n", "\n").replace("\r", "\n")
                if entered is None or entered["value"] != text:
                    result["stopped"] = (
                        "The entered value changed before the next action. Read the page again."
                    )
                    break
                expected[node] = entered
            elif action["action"] == "set_checked":
                expected[node] = current["controls"][node]
            result["attempting"] = None
        except (RuntimeError, Error) as error:
            # Do not retry or ask the model to repeat an action with an uncertain outcome.
            result["error"] = str(error)
            result["stopped"] = (
                "The action outcome is uncertain. Investigate before trying again."
            )
            break
        finally:
            # This also runs on Ctrl+C and Stop, without swallowing cancellation.
            if on_progress:
                on_progress(result)

    if on_progress:
        on_progress(result)
    return result


def wait_for_page(page, action, observation, check_cancel=None):
    """Check a short-lived condition locally instead of asking the AI to keep checking.

    Return the latest reading and whether the condition matched. A timeout is not success.
    Polling stops after at most five seconds, apart from an in-flight Chrome response.
    """
    from time import monotonic

    validate_wait(action, observation["controls"])
    if _observations.get(page, {}).get("observation") is not observation:
        raise RuntimeError("This reading is old or already used. Read the page again.")
    deadline = monotonic() + action.get("timeout", 3)
    current = observation

    while True:
        if check_cancel:
            check_cancel()
        reason = None
        matched = False
        if any(
            current[key] != observation[key]
            for key in ("page_id", "document_id", "url")
        ):
            reason = "The page changed while waiting. Review the fresh reading."
        elif "text" in action:
            # Names and ordinary page text are enough; do not expose private field values.
            text = (
                current["content"]
                + "\n"
                + "\n".join(control["name"] for control in current["controls"].values())
            )
            matched = action["text"].casefold() in text.casefold()
        else:
            control = current["controls"].get(action["backend_node_id"])
            if control is None:
                reason = "The waiting target disappeared. Review the fresh reading."
            elif action["state"] in ("enabled", "disabled"):
                matched = bool(control["states"].get("disabled")) == (
                    action["state"] == "disabled"
                )
            else:
                checked = control["states"].get("checked")
                matched = (
                    checked in (True, "true")
                    if action["state"] == "checked"
                    else checked in (False, "false")
                )

        if matched or reason:
            return {"matched": matched, "reason": reason, "observation": current}
        remaining = deadline - monotonic()
        if remaining <= 0:
            return {
                "matched": False,
                "reason": "Timed out waiting for the condition.",
                "observation": current,
            }
        # Playwright's wait pumps browser events; a long time.sleep would not.
        page.wait_for_timeout(min(100, remaining * 1000))
        current = read_page(page)


# Release Playwright; Chrome launched by this file closes too.
def close_browser(playwright):
    _observations.clear()
    playwright.stop()
