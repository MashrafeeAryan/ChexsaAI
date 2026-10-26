"""Open Chrome and read the current page."""

import json
import os
from pathlib import Path
from weakref import WeakKeyDictionary

from playwright.sync_api import Error, sync_playwright

# Remember which Chrome nodes belong to the latest page observation.
_observations = WeakKeyDictionary()
_CONTROL_ROLES = {
    "button", "link", "textbox", "searchbox", "combobox", "checkbox", "radio",
    "switch", "spinbutton", "slider", "tab", "menuitem", "menuitemcheckbox",
    "menuitemradio", "option", "treeitem",
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
            profile = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Chexsa" / "chrome"
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                channel="chrome",
                headless=False,
                args=["--no-first-run", "--no-default-browser-check"],
            )

        # context.pages means the open tabs. Keep tabs that are not closed
        # and show a website, a local file, or a blank page; skip Chrome settings.
        pages = [
            page for page in context.pages
            if not page.is_closed()
            and page.url.startswith(("http://", "https://", "file://", "about:blank"))
        ]
        page = pages[-1] if pages else context.new_page()
        return playwright, page
    except Exception:
        # Stop the connection if startup fails partway through.
        playwright.stop()
        raise


# Read controls using the exact node IDs Chrome already gives us.
# Example return value (Chrome supplies the real node IDs):
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
        document = session.send("DOM.getDocument", {"depth": 0})["root"]["backendNodeId"]
        nodes = session.send("Accessibility.getFullAXTree")["nodes"]
        by_id = {node["nodeId"]: node for node in nodes}
        targets, lines, text_lines = set(), [], []
        for node in nodes:
            if node.get("ignored"):
                continue
            role = node.get("role", {}).get("value", "").lower()
            name = node.get("name", {}).get("value", "")
            # Read ordinary text from this same tree. InlineTextBox repeats it.
            if role == "statictext" and name.strip():
                text_lines.append(name)
            target = node.get("backendDOMNodeId")
            if role not in _CONTROL_ROLES or not target:
                continue
            targets.add(target)
            line = f"[{target}] {role} {json.dumps(name, ensure_ascii=False)}"

            # Walk up the page structure to show where duplicate controls belong.
            context = []
            parent = by_id.get(node.get("parentId"))
            while parent:
                parent_role = parent.get("role", {}).get("value", "").lower()
                if parent_role in ("dialog", "alertdialog", "main", "form", "navigation", "region"):
                    parent_name = parent.get("name", {}).get("value", "")
                    context.append(f"{parent_role} {json.dumps(parent_name, ensure_ascii=False)}")
                parent = by_id.get(parent.get("parentId"))
            if context:
                line += " | context: " + " > ".join(reversed(context))
            lines.append(line)

        result = {
            "url": page.url,
            "title": page.title(),
            "elements": "\n".join(lines),
            # Plain accessible text, rather than a second formatted tree snapshot.
            "content": "\n".join(text_lines),
        }
        # Keep the full tree locally too. The AI payload does not include it.
        _observations[page] = {
            "session": session, "document": document, "nodes": targets, "tree": nodes,
        }
        return result
    except Exception:
        try:
            session.detach()
        except Error:
            pass  # The tab may have closed while we were reading it.
        raise


# Check that a Chrome node was observed in this tab and is still on the page.
def resolve_node(page, backend_node_id):
    observation = _observations.get(page)
    if type(backend_node_id) is not int or not observation or backend_node_id not in observation["nodes"]:
        raise RuntimeError("This node was not observed in this tab. Read the page again.")
    if page.is_closed():
        raise RuntimeError("This tab is closed. Read an open tab again.")
    session = observation["session"]
    try:
        document = session.send("DOM.getDocument", {"depth": 0})["root"]["backendNodeId"]
        if document != observation["document"]:
            raise RuntimeError("The page changed. Read it again before using this node.")
        # A removed node can still have an ID, so check that it remains on the page.
        node = session.send("DOM.resolveNode", {"backendNodeId": backend_node_id})["object"]["objectId"]
        try:
            connected = session.send("Runtime.callFunctionOn", {
                "objectId": node,
                "functionDeclaration": "function() { return this.isConnected; }",
                "returnByValue": True,
            })["result"].get("value")
            if not connected:
                raise RuntimeError("The element was removed. Read the page again.")
        finally:
            session.send("Runtime.releaseObject", {"objectId": node})
        return session, backend_node_id
    except Error:
        raise RuntimeError("This element is no longer available. Read the page again.") from None


# Click an observed Chrome node through CDP; this does not move the Windows cursor.
def click_node(page, backend_node_id):
    session, target = resolve_node(page, backend_node_id)
    node = None
    pressed = False
    try:
        session.send("DOM.scrollIntoViewIfNeeded", {"backendNodeId": target})
        node = session.send("DOM.resolveNode", {"backendNodeId": target})["object"]["objectId"]

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
            if previous and (abs(point["x"] - previous["x"]) > 1 or abs(point["y"] - previous["y"]) > 1):
                raise RuntimeError("The target moved. Read the page again before clicking.")
            arguments = {"type": event, "x": point["x"], "y": point["y"]}
            if event == "mousePressed":
                arguments.update(button="left", clickCount=1)
                pressed = True
            session.send("Input.dispatchMouseEvent", arguments)
            previous = point
        session.send("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": point["x"], "y": point["y"],
            "button": "left", "clickCount": 1,
        })
    except Error:
        if pressed:
            raise RuntimeError("The click outcome is uncertain. Read the page before retrying.") from None
        raise RuntimeError("Could not click this element. Read the page again.") from None
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


# Replace a text field's contents, then check that the exact field kept the text.
def type_node(page, backend_node_id, text):
    if not isinstance(text, str):
        raise RuntimeError("Typing requires text.")
    session, target = resolve_node(page, backend_node_id)
    node = None
    attempted = False
    try:
        session.send("DOM.scrollIntoViewIfNeeded", {"backendNodeId": target})
        node = session.send("DOM.resolveNode", {"backendNodeId": target})["object"]["objectId"]
        response = session.send("Runtime.callFunctionOn", {
            "objectId": node,
            "returnByValue": True,
            "functionDeclaration": """function() {
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
        })
        if response.get("exceptionDetails") or "value" not in response.get("result", {}):
            raise RuntimeError("Could not prepare this text field. Read the page again.")
        error = response["result"]["value"]
        if error:
            raise RuntimeError(error + " Read the page again.")

        attempted = True
        if text:
            session.send("Input.insertText", {"text": text})
        else:
            # Backspace clears selected text when the requested value is empty.
            for event in ("rawKeyDown", "keyUp"):
                session.send("Input.dispatchKeyEvent", {
                    "type": event, "key": "Backspace", "code": "Backspace",
                    "windowsVirtualKeyCode": 8,
                })
        response = session.send("Runtime.callFunctionOn", {
            "objectId": node,
            "returnByValue": True,
            "functionDeclaration": """function() {
                if (!this.isConnected) return null;
                if (!this.isContentEditable) return this.value;
                // Chrome leaves a placeholder line break in an emptied editable area.
                if (this.childNodes.length === 1 && this.firstChild.nodeName === 'BR') return '';
                return this.innerText;
            }""",
        })
        # Read back this exact node. A changed or missing value is not success.
        expected = text.replace("\r\n", "\n").replace("\r", "\n")
        if response.get("exceptionDetails") or response.get("result", {}).get("value") != expected:
            raise RuntimeError("Text entry could not be verified. Read the page before retrying.")
    except Error:
        if attempted:
            raise RuntimeError("Text entry is uncertain. Read the page before retrying.") from None
        raise RuntimeError("Could not type into this field. Read the page again.") from None
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


# Release Playwright; Chrome launched by this file closes too.
def close_browser(playwright):
    _observations.clear()
    playwright.stop()
