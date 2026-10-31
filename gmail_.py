"""Read Gmail through its API and keep results small enough for the model."""

import base64
import hashlib
import sqlite3
from contextlib import closing
from email.message import EmailMessage
from email.utils import parseaddr
from html import unescape
from html.parser import HTMLParser

from gmail_auth_ import account_folder


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
    headers = _headers(draft["message"])
    result.update(
        draft_id=draft["id"], body=_body(draft["message"]["payload"]),
        cc=headers.get("cc", ""), bcc=headers.get("bcc", ""),
        attachments=_attachment_names(draft["message"]["payload"]),
    )
    return result


def save_draft(service, to, subject, body, draft_id="", reply_to=""):
    """Create or replace an editable draft and read it back to verify the save.

    Input: recipient, subject, body, and optional draft or original-message ID.
    Output: the saved draft and verified text. This never sends an email.
    """
    for value in (to, subject, body, draft_id, reply_to):
        if not isinstance(value, str):
            raise ValueError("Email fields must be text.")
    if any("\n" in value or "\r" in value for value in (to, subject)):
        raise ValueError("Recipients and subjects cannot contain newlines.")
    if len(body) > 100000:
        raise ValueError("Draft text is limited to 100,000 characters.")

    headers, thread = {}, ""
    if draft_id:
        old = _execute(service.users().drafts().get(userId="me", id=_check_id(draft_id), format="full"))
        # Replacing an existing draft must not silently remove attachments or recipients.
        old_headers = _headers(old["message"])
        if old_headers.get("cc") or old_headers.get("bcc") or _has_attachment(old["message"]["payload"]):
            raise ValueError("This draft has attachments or extra recipients. Edit it in Gmail to preserve them.")
        headers = old_headers
        thread = old["message"].get("threadId", "")

    if reply_to:
        original = _execute(service.users().messages().get(userId="me", id=_check_id(reply_to), format="full"))
        original_headers = _headers(original)
        address = parseaddr(original_headers.get("reply-to") or original_headers.get("from", ""))[1]
        message_id = original_headers.get("message-id", "")
        if not address or not message_id:
            raise ValueError("The original email is missing a reply address or Message-ID.")
        to = address
        # Threading uses Google's thread ID plus the original RFC email headers.
        headers = {
            "in-reply-to": message_id,
            "references": (original_headers.get("references", "") + " " + message_id).strip(),
        }
        subject = original_headers.get("subject", "")
        if not subject.lower().startswith("re:"):
            subject = "Re: " + subject
        thread = original["threadId"]

    from email.utils import getaddresses

    addresses = getaddresses([to])
    if not addresses or any(not address or "@" not in address or " " in address for _, address in addresses):
        raise ValueError("Give full email addresses; Chexsa will not guess a person's address.")

    mail = EmailMessage()
    profile = _execute(service.users().getProfile(userId="me"))
    mail["From"] = profile["emailAddress"]
    mail["To"], mail["Subject"] = to, subject
    for header in ("in-reply-to", "references"):
        if headers.get(header):
            mail[header] = headers[header]
    mail.set_content(body.replace("\r\n", "\n").replace("\r", "\n"))
    message = {"raw": base64.urlsafe_b64encode(mail.as_bytes()).decode()}
    if thread:
        message["threadId"] = thread

    drafts = service.users().drafts()
    request = drafts.update(userId="me", id=draft_id, body={"message": message}) if draft_id else drafts.create(userId="me", body={"message": message})
    try:
        saved = _execute(request)
        verified = read_draft(service, saved["id"])
        expected = body.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
        if verified["to"] != str(mail["To"]) or verified["subject"] != subject or verified["body"].rstrip("\n") != expected:
            raise ValueError("Draft verification did not match.")
        return verified
    except Exception:
        raise RuntimeError("The draft save outcome is uncertain. List and read drafts before creating another copy.") from None


def _has_attachment(payload):
    """Check nested MIME parts before replacing a draft's contents."""
    return bool(payload.get("filename")) or any(_has_attachment(part) for part in payload.get("parts", []))


def _attachment_names(payload):
    """Include attachment names in send reviews without downloading their contents."""
    names = [payload["filename"]] if payload.get("filename") else []
    for part in payload.get("parts", []):
        names.extend(_attachment_names(part))
    return names


def draft_fingerprint(draft):
    """Identify exactly the reviewed message without storing its private body."""
    import json

    data = [draft.get(key, "") for key in ("draft_id", "id", "to", "cc", "bcc", "subject", "body", "attachments")]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()


def send_draft(service, draft_id, reviewed_fingerprint):
    """Send exactly the reviewed draft once, recording intent before the API call.

    Output: Google's accepted message ID. A timeout is uncertain, never a retry.
    """
    current = read_draft(service, draft_id)
    if draft_fingerprint(current) != reviewed_fingerprint:
        raise RuntimeError("The draft changed after review. Read and review it again before sending.")

    folder = account_folder()
    folder.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(folder / "submissions.sqlite3")) as journal:
        journal.execute("CREATE TABLE IF NOT EXISTS submissions (fingerprint TEXT PRIMARY KEY, status TEXT, message_id TEXT)")
        try:
            journal.execute("INSERT INTO submissions VALUES (?, 'pending', '')", (reviewed_fingerprint,))
            journal.commit()  # Commit intent before a network request can possibly send.
        except sqlite3.IntegrityError:
            raise RuntimeError("This draft version already has a submission record. Check Sent in Gmail; do not resend automatically.") from None

        try:
            result = _execute(service.users().drafts().send(userId="me", body={"id": draft_id}))
            if not result.get("id"):
                raise ValueError("No accepted message ID.")
            journal.execute("UPDATE submissions SET status='accepted', message_id=? WHERE fingerprint=?", (result["id"], reviewed_fingerprint))
            journal.commit()
            return {"status": "accepted", "message_id": result["id"], "thread_id": result.get("threadId", "")}
        except Exception:
            journal.execute("UPDATE submissions SET status='uncertain' WHERE fingerprint=?", (reviewed_fingerprint,))
            journal.commit()
            raise RuntimeError("The send outcome is uncertain. Check Sent in Gmail before taking further action. Chexsa will not send this version again.") from None
