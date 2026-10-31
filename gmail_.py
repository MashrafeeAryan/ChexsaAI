"""Read Gmail through its API and keep results small enough for the model."""

import base64
from email.utils import parseaddr
from html import unescape
from html.parser import HTMLParser


def _execute(request):
    """Run one Google request without automatic retries or private error output."""
    try:
        return request.execute(num_retries=0)
    except Exception:
        raise RuntimeError("Gmail could not complete the request. Check the connection and account access.") from None


def _check_id(value):
    """Accept a nonempty Gmail ID, not an invented numeric UI target."""
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValueError("Choose a Gmail ID from the current results.")
    return value


def _headers(message):
    """Make email header lookup ignore capitalization."""
    return {item["name"].lower(): item["value"] for item in message.get("payload", {}).get("headers", [])}


def _body(payload):
    """Prefer plain text, then HTML. Do not repeat both copies of the same email."""
    kind = payload.get("mimeType", "")
    if payload.get("filename"):
        return ""  # An attachment is not the email body.

    if kind.startswith("multipart/"):
        children = payload.get("parts", [])
        if kind == "multipart/alternative":
            children = sorted(children, key=lambda part: part.get("mimeType") != "text/plain")
            return next((text for part in children if (text := _body(part))), "")
        return "\n".join(filter(None, (_body(part) for part in children)))

    data = payload.get("body", {}).get("data", "")
    if kind not in ("text/plain", "text/html") or not data:
        return ""
    raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    text = raw.decode("utf-8", errors="replace")
    if kind == "text/plain":
        return text

    # Parse markup as text. Never load links, images, styles, or scripts.
    parts, hidden = [], []
    parser = HTMLParser(convert_charrefs=True)

    def start(tag, attributes):
        if tag in ("script", "style"):
            hidden.append(tag)
        elif tag in ("br", "p", "div", "li"):
            parts.append("\n")

    def end(tag):
        if hidden and hidden[-1] == tag:
            hidden.pop()

    parser.handle_starttag = start
    parser.handle_endtag = end
    parser.handle_data = lambda value: parts.append(value) if not hidden else None
    parser.feed(text)
    return "".join(parts).strip()


def _summary(message):
    """Return small search results; fetch full bodies only for selected messages."""
    headers = _headers(message)
    return {
        "id": message["id"],
        "thread_id": message.get("threadId", ""),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", ""),
        "date": headers.get("date", ""),
        "snippet": unescape(message.get("snippet", ""))[:400],
    }


def search_mail(service, query="in:inbox newer_than:14d", page_token="", limit=10):
    """Search one page of mail.

    Input: 'is:unread newer_than:7d'. Output: message summaries and a next-page token.
    The result covers this page only, not the whole mailbox.
    """
    if not isinstance(query, str) or len(query) > 1000:
        raise ValueError("Give a Gmail search query shorter than 1,000 characters.")
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Read between 1 and 20 search results at a time.")

    listing = _execute(service.users().messages().list(
        userId="me", q=query, maxResults=limit, pageToken=page_token or None,
    ))
    messages = []
    for item in listing.get("messages", []):
        message = _execute(service.users().messages().get(
            userId="me", id=item["id"], format="metadata",
            metadataHeaders=["From", "To", "Subject", "Date"],
        ))
        messages.append(_summary(message))

    return {"query": query, "messages": messages, "next_page": listing.get("nextPageToken", "")}


def read_mail(service, message_id, offset=0):
    """Read up to 6,000 body characters. next_offset allows reading the rest."""
    if type(offset) is not int or offset < 0:
        raise ValueError("The body offset must be a nonnegative integer.")
    message = _execute(service.users().messages().get(
        userId="me", id=_check_id(message_id), format="full",
    ))
    result = _summary(message)
    text = _body(message.get("payload", {}))
    result.update(body=text[offset:offset + 6000], next_offset=offset + 6000 if len(text) > offset + 6000 else None)
    return result


def list_drafts(service, page_token=""):
    """List draft IDs in small pages; read_draft supplies editable contents."""
    result = _execute(service.users().drafts().list(userId="me", maxResults=10, pageToken=page_token or None))
    return {"drafts": result.get("drafts", []), "next_page": result.get("nextPageToken", "")}


def read_draft(service, draft_id):
    """Read the exact draft before editing or sending it."""
    draft = _execute(service.users().drafts().get(userId="me", id=_check_id(draft_id), format="full"))
    result = _summary(draft["message"])
    result.update(draft_id=draft["id"], body=_body(draft["message"]["payload"]))
    return result
