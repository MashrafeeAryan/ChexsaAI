"""Deterministic evidence checks around independent model assessments."""

import re
import hashlib

from .models import BrowserError


EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def normalize(text):
    return str(text).replace("\r\n", "\n").strip()


def evidence_text(observation):
    return "\n".join([observation.url, observation.title] + [item["text"] for item in observation.text.values()] + [value for e in observation.elements for value in (e.name, e.value) if value])


def is_submission(request, observation):
    element = next((e for e in observation.elements if e.ref == request.arguments.get("ref")), None)
    # The model's effect is a hint. Opening UI and entering a search do not send
    # a message, even when the model incorrectly calls that a submission.
    if request.action in ("navigate", "go_back", "scroll", "switch_tab", "new_tab", "wait"):
        return False
    if request.action == "click" and element:
        name = re.sub(r"\s*\([^)]*\)\s*$", "", element.name).strip().casefold()
        if name in ("compose", "new message", "new email", "new draft", "reply", "reply all", "forward", "search"):
            return False
    if request.action == "type":
        if not request.arguments.get("press_enter"):
            return False
        if element and (element.role == "searchbox" or re.search(r"\bsearch\b", element.name, re.I)):
            return False
    if request.effect.get("kind") == "submission":
        return True
    if request.action == "click":
        return bool(element and re.match(r"^(send|submit|publish|purchase|place order|confirm payment)\b", element.name, re.I))
    if request.action == "press_key":
        return request.arguments.get("key", "").lower() in ("control+enter", "controlormeta+enter", "meta+enter", "ctrl+enter")
    return False


def preflight_email(state, observation, backend, model, request=None):
    if not state.spec.inputs.get("recipient") or not state.spec.inputs.get("body"):
        raise BrowserError("missing_information", "The email plan needs an explicit recipient and message before sending.")
    report = model.preflight(state, observation)
    if not report["ready"]:
        raise BrowserError("verification_failed", report.get("reason") or "The draft is not ready to send.")
    fields = [report.get("subject_ref"), report.get("body_ref")]
    if not all(fields) or len(set(fields)) != 2 or report.get("recipient_ref") in fields:
        raise BrowserError("verification_failed", "Recipient, subject, and body must use different controls.")
    region = next((r for r in observation.regions if r.ref == report.get("region_ref")), None)
    if region is None:
        raise BrowserError("verification_failed", "The verifier did not identify a current compose region.")
    if request and request.arguments.get("ref"):
        submit = next((e for e in observation.elements if e.ref == request.arguments["ref"]), None)
        if submit is None or submit.region != region.key:
            raise BrowserError("verification_failed", "The submission control belongs to a different region.")
    elements = {e.ref: e for e in observation.elements}
    def read(ref):
        element = elements.get(ref)
        if element is None or element.region != region.key or "type" not in element.capabilities:
            raise BrowserError("verification_failed", "The verifier selected a field outside the draft.")
        target = backend.registry.resolve(ref)
        try:
            return normalize(target.details()["value"])
        finally:
            target.close()
    for field in ("subject", "body"):
        expected = state.spec.inputs.get(field, "")
        if read(report.get(field + "_ref")) != normalize(expected):
            raise BrowserError("verification_failed", f"The actual {field} does not match the requested {field}.")
    if report.get("recipient_ref"):
        recipient = read(report["recipient_ref"])
    else:
        recipient = report.get("recipient_text", "")
        current = [item["text"] for item in observation.text.values() if region.key in item["region_path"]]
        if not recipient or not any(recipient in text for text in current):
            raise BrowserError("verification_failed", "The committed recipient is not present in this compose region.")
    addresses = {address.rstrip(".,").casefold() for address in EMAIL.findall(recipient)}
    if addresses != {state.spec.inputs["recipient"].casefold()}:
        raise BrowserError("verification_failed", "The draft recipient does not exactly match the requested recipient.")
    state.email_checked = True


def completion_is_supported(state, observation, verdict):
    quotes = verdict.get("evidence", [])
    actual = evidence_text(observation)
    text_proof = bool(quotes) and all(quote.strip() and quote in actual for quote in quotes)
    visual_proof = bool(observation.screenshot) and verdict.get("visual_evidence") is True and verdict.get("screenshot_id") == observation.screenshot_id
    if not verdict.get("complete") or not (text_proof or visual_proof):
        return False
    if "recipient" in state.spec.inputs and state.spec.intent != "draft":
        return state.email_checked and state.submission != "none" and any(quote not in state.commit_baseline for quote in quotes)
    if state.submission != "none":
        return any(quote not in state.commit_baseline for quote in quotes) or visual_proof and bool(state.commit_image_hash) and state.commit_image_hash != hashlib.sha256(observation.screenshot).hexdigest()
    return True


def failure_is_supported(state, observation, verdict):
    quotes = verdict.get("evidence", [])
    actual = evidence_text(observation)
    return verdict.get("failed") is True and verdict.get("complete") is False and bool(quotes) and all(quote.strip() and quote in actual for quote in quotes) and any(quote not in state.commit_baseline for quote in quotes)


def submission_confirmation(state, observation):
    """Accept a fresh same-frame live receipt only after checked email dispatch."""
    if not state.email_checked or state.submission not in ("attempting", "uncertain") or not state.commit_frame_id or state.commit_page_id != observation.page_id:
        return ""
    messages = [item["text"] for key, item in observation.text.items() if item.get("live") and len(key.split("/")) == 4 and key.split("/")[1] == state.commit_frame_id]
    messages.extend(e.name for e in observation.elements if e.role in ("status", "alert") and e.frame_id == state.commit_frame_id and e.name)
    for text in messages:
        if text not in state.commit_baseline and re.fullmatch(r"(?:your\s+)?(?:message|e-?mail)\s+(?:(?:was|has been)\s+)?sent(?:\s+successfully)?[.!]?", normalize(text), re.I):
            return normalize(text)
    return ""
