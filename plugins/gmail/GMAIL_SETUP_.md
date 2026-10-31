# Connect Gmail to Chexsa

Chexsa uses Google's Gmail API. It can search and read mail, summarize work to do,
create drafts, edit drafts, prepare replies, and send a reviewed draft.

Your model still uses the API settings already in `.env`. Google sign-in gives
Chexsa separate permission to access your Gmail account.

## 1. Install Gmail support

From the repository folder, with your virtual environment active:

```powershell
python -m pip install -e ".[gmail]"
```

For Gmail and microphone support together:

```powershell
python -m pip install -e ".[gmail,voice]"
```

## 2. Create the Google sign-in file

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create or select a project.
2. Enable the **Gmail API** for that project.
3. Open **Google Auth platform** and configure the app name and contact email.
4. For a personal Gmail account, choose an **External** audience. While the app is in testing, add your own Gmail address as a test user.
5. Add these Gmail permissions under **Data Access**: `gmail.readonly` and `gmail.compose`.
6. Under **Clients**, create an OAuth client with application type **Desktop app**.
7. Download its JSON file. Keep it on your computer; do not paste it into chat or GitHub.

These are OAuth credentials, not a Gmail password or a simple API key.
The Google account choosing to connect must have access to the test app.
Publishing the app to other users can require Google's verification for these permissions.

Google's references: [Python setup](https://developers.google.com/workspace/gmail/api/quickstart/python)
and [Gmail permissions](https://developers.google.com/workspace/gmail/api/auth/scopes).

## 3. Connect your account

```powershell
python cli_.py gmail
```

Then enter:

```text
You > /connect
```

A file picker asks for the downloaded JSON. Chexsa opens Google's normal sign-in
page in your browser. Select your account and grant access. Return to the terminal
after Google confirms the connection.

Windows encrypts the saved login token for your Windows user under
`%LOCALAPPDATA%\Chexsa\gmail`. Restarting Chexsa reuses this access when valid;
Google can require signing in again if access expires or is revoked.

Optional: set `GMAIL_CLIENT_FILE` to the credentials path if you prefer selecting
it without a file picker. The picker is the default; this setting is not required.

## 4. Ask about your emails

```text
What work do I need to do from my inbox this week?
Find unread messages from my professor.
Read the email about the project deadline.
Search older messages too.
```

Chexsa searches small pages and reads selected bodies. Summaries should state the
search scope, cite message IDs, and distinguish stated deadlines from guesses.
It does not send the whole inbox to the model at once. Search results contain
small summaries; longer bodies have a continuation offset.

## 5. Create, edit, reply, and send

```text
Draft an email to person@example.com saying hello and asking how they are.
Make that draft friendlier and change the subject to Checking in.
Show my existing drafts.
Reply to the project email saying I can send the report on Friday. Keep it as a draft.
Send the draft we just edited.
```

A send request shows the exact draft for review. To submit it:

```text
You > /send
```

You can ask for another edit instead. An intervening request clears the old send
review. If the draft changes in Gmail after review, Chexsa requires reviewing it
again. A successful send reports Google's accepted message ID, not a guarantee
that the recipient received or read it.

If a send times out, check **Sent** in Gmail. Chexsa records submission intent
before sending and does not automatically send that draft version again.

Editing applies to drafts; already-sent email cannot be rewritten in place.
This version creates plain-text drafts and single-sender replies. It does not add
attachments or implement reply-all. Existing drafts with attachments or Cc/Bcc
must be edited in Gmail so those details are preserved. Send reviews show all
recipients and attachment names.

## 6. Use voice

Connect once in the terminal first, then run:

```powershell
python voice_.py gmail
```

Say **Hey Chexsa, what work do I have from my emails?**
For a reviewed send, say **Hey Chexsa, confirm send**.
Voice uses the existing speech-recognition and Windows speech path.

## Disconnect

Enter `/disconnect` to remove this computer's saved login token. To revoke access
at Google too, remove Chexsa in your [Google account connections](https://myaccount.google.com/connections).

`/connect` lets you reconnect or choose another account. Account changes clear
old draft selections and message IDs. No Google tokens are sent to the AI model;
requested email contents do go to your configured model provider for analysis.
