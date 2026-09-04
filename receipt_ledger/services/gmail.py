from __future__ import annotations

import base64
import hashlib
import html
from datetime import date, datetime, timedelta, timezone
from email.utils import parseaddr
from html.parser import HTMLParser
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import (
    GmailConnection,
    GmailMessageImport,
    GmailSenderRule,
    Ingestion,
    RecurringItem,
)
from ..schemas import GmailSenderRuleOut, GmailStatusOut
from .finance import materialize_occurrences, nearest_occurrence_for_sender
from .ingestion import (
    DuplicateReceiptDocument,
    append_ingestion_document,
    ingest_bytes,
    schedule_ingestion,
)
from .storage import ALLOWED_MIMES


GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"


class _SafeTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "svg"}:
            self.ignored_depth += 1
        elif tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg"} and self.ignored_depth:
            self.ignored_depth -= 1
        elif tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)

    def text(self) -> str:
        lines = [" ".join(line.split()) for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line).strip()


def _cipher(settings: Settings) -> Fernet:
    secret = settings.gmail_token_encryption_key
    if not secret:
        raise ValueError("GMAIL_TOKEN_ENCRYPTION_KEY is not configured")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_token(settings: Settings, token: str) -> str:
    return _cipher(settings).encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_token(settings: Settings, token: str) -> str:
    try:
        return _cipher(settings).decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Stored Gmail credential cannot be decrypted") from exc


def oauth_authorization_url(settings: Settings, state: str, redirect_uri: str) -> str:
    if not settings.gmail_configured:
        raise ValueError("Gmail OAuth is not configured on the server")
    parameters = {
        "client_id": settings.gmail_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GMAIL_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(parameters)}"


def _token_request(settings: Settings, values: dict[str, str]) -> dict:
    response = httpx.post(
        TOKEN_URL,
        data={
            **values,
            "client_id": settings.gmail_client_id,
            "client_secret": settings.gmail_client_secret,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _access_token(settings: Settings, connection: GmailConnection) -> str:
    refresh_token = decrypt_token(settings, connection.encrypted_refresh_token)
    token = _token_request(
        settings,
        {
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    ).get("access_token")
    if not token:
        raise ValueError("Google did not return an access token")
    return str(token)


def _gmail_get(
    access_token: str,
    path: str,
    *,
    params: dict | list[tuple[str, str]] | None = None,
) -> dict:
    response = httpx.get(
        f"{API_ROOT}/{path}",
        params=params,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=45,
    )
    response.raise_for_status()
    return response.json()


def connect_from_code(
    db: Session,
    settings: Settings,
    *,
    code: str,
    redirect_uri: str,
) -> GmailConnection:
    token_data = _token_request(
        settings,
        {
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )
    refresh_token = token_data.get("refresh_token")
    access_token = token_data.get("access_token")
    if not refresh_token or not access_token:
        raise ValueError("Google did not return offline Gmail access")
    profile = _gmail_get(str(access_token), "profile")
    email_address = str(profile.get("emailAddress") or "").strip().lower()
    history_id = str(profile.get("historyId") or "") or None
    if not email_address:
        raise ValueError("Google did not return the connected Gmail address")
    existing = db.scalar(select(GmailConnection).limit(1))
    if existing:
        existing.email_address = email_address
        existing.encrypted_refresh_token = encrypt_token(settings, str(refresh_token))
        existing.history_id = history_id
        existing.status = "connected"
        existing.error_message = None
        existing.next_sync_at = datetime.now(timezone.utc)
        connection = existing
    else:
        connection = GmailConnection(
            email_address=email_address,
            encrypted_refresh_token=encrypt_token(settings, str(refresh_token)),
            history_id=history_id,
            status="connected",
            next_sync_at=datetime.now(timezone.utc),
        )
        db.add(connection)
    db.commit()
    db.refresh(connection)
    return connection


def gmail_status(db: Session, settings: Settings) -> GmailStatusOut:
    connection = db.scalar(select(GmailConnection).limit(1))
    rules: list[GmailSenderRuleOut] = []
    if connection:
        stored_rules = db.scalars(
            select(GmailSenderRule)
            .where(GmailSenderRule.connection_id == connection.id)
            .order_by(GmailSenderRule.sender_address)
        ).all()
        for rule in stored_rules:
            recurring_item = (
                db.get(RecurringItem, rule.recurring_item_id)
                if rule.recurring_item_id
                else None
            )
            rules.append(
                GmailSenderRuleOut(
                    id=rule.id,
                    sender_address=rule.sender_address,
                    recurring_item_id=rule.recurring_item_id,
                    recurring_item_name=recurring_item.name if recurring_item else None,
                    category_id=rule.category_id,
                    scope=rule.scope,
                    match_window_days=rule.match_window_days,
                    enabled=rule.enabled,
                )
            )
    return GmailStatusOut(
        configured=settings.gmail_configured,
        connected=bool(connection and connection.status != "disconnected"),
        email_address=connection.email_address if connection else None,
        status=connection.status if connection else "disconnected",
        last_synced_at=connection.last_synced_at if connection else None,
        error_message=connection.error_message if connection else None,
        sender_rules=rules,
    )


def _decode_body(data: str | None) -> str:
    if not data:
        return ""
    padding = "=" * (-len(data) % 4)
    decoded = base64.urlsafe_b64decode(data + padding)
    return decoded.decode("utf-8", errors="replace")


def _header(payload: dict, name: str) -> str:
    wanted = name.lower()
    for item in payload.get("headers") or []:
        if str(item.get("name") or "").lower() == wanted:
            return str(item.get("value") or "")
    return ""


def _sender_address(payload: dict) -> str:
    return parseaddr(_header(payload, "From"))[1].strip().lower()


def _walk_parts(part: dict) -> list[dict]:
    output = [part]
    for child in part.get("parts") or []:
        output.extend(_walk_parts(child))
    return output


def _safe_body_text(payload: dict) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    for part in _walk_parts(payload):
        mime_type = str(part.get("mimeType") or "").lower()
        body_data = (part.get("body") or {}).get("data")
        if mime_type == "text/plain" and body_data:
            plain_parts.append(_decode_body(body_data))
        elif mime_type == "text/html" and body_data:
            parser = _SafeTextParser()
            parser.feed(_decode_body(body_data))
            html_parts.append(parser.text())
    selected = "\n\n".join(plain_parts or html_parts)
    return html.unescape(selected).strip()[:100_000]


def _attachment_bytes(access_token: str, message_id: str, part: dict) -> bytes:
    body = part.get("body") or {}
    if body.get("data"):
        data = str(body["data"])
    else:
        attachment_id = body.get("attachmentId")
        if not attachment_id:
            return b""
        value = _gmail_get(
            access_token,
            f"messages/{message_id}/attachments/{attachment_id}",
        )
        data = str(value.get("data") or "")
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _import_message(
    db: Session,
    settings: Settings,
    connection: GmailConnection,
    access_token: str,
    message_id: str,
) -> GmailMessageImport | None:
    if db.scalar(
        select(GmailMessageImport.id).where(
            GmailMessageImport.connection_id == connection.id,
            GmailMessageImport.gmail_message_id == message_id,
        )
    ):
        return None
    metadata = _gmail_get(
        access_token,
        f"messages/{message_id}",
        params=[
            ("format", "metadata"),
            ("metadataHeaders", "From"),
            ("metadataHeaders", "Subject"),
        ],
    )
    metadata_payload = metadata.get("payload") or {}
    sender = _sender_address(metadata_payload)
    rule = db.scalar(
        select(GmailSenderRule).where(
            GmailSenderRule.connection_id == connection.id,
            GmailSenderRule.sender_address == sender,
            GmailSenderRule.enabled.is_(True),
        )
    )
    if not rule:
        return None
    message = _gmail_get(access_token, f"messages/{message_id}", params={"format": "full"})
    payload = message.get("payload") or {}
    if _sender_address(payload) != sender:
        return None
    subject = _header(payload, "Subject")[:500]
    received_at = datetime.fromtimestamp(
        int(message.get("internalDate") or 0) / 1000,
        tz=timezone.utc,
    )
    imported = GmailMessageImport(
        connection_id=connection.id,
        sender_rule_id=rule.id,
        gmail_message_id=message_id,
        gmail_thread_id=str(message.get("threadId") or "") or None,
        subject=subject,
        sender_address=sender,
        status="queued",
        received_at=received_at,
    )
    db.add(imported)
    db.flush()
    body_text = _safe_body_text(payload)
    context = f"Email subject: {subject}\nEmail sender: {sender}"
    if body_text:
        context = f"{context}\n\nEmail body:\n{body_text}"
    context = context[:20_000]
    attachment_parts = [
        part
        for part in _walk_parts(payload)
        if part.get("filename")
        and str(part.get("mimeType") or "").lower() in ALLOWED_MIMES
    ]
    ingestion: Ingestion | None = None
    group_external_id = f"gmail:{connection.id}:{message_id}"
    try:
        for index, part in enumerate(attachment_parts):
            data = _attachment_bytes(access_token, message_id, part)
            if not data:
                continue
            external_id = f"{group_external_id}:attachment:{index}"
            if ingestion is None:
                ingestion = ingest_bytes(
                    db,
                    settings,
                    data=data,
                    filename=str(part.get("filename")),
                    claimed_mime=str(part.get("mimeType")),
                    source="gmail",
                    external_id=external_id,
                    group_external_id=group_external_id,
                    caption=context,
                    ready_at=datetime.now(timezone.utc) + timedelta(seconds=3),
                )
            else:
                try:
                    ingestion, _added = append_ingestion_document(
                        db,
                        settings,
                        ingestion=ingestion,
                        data=data,
                        filename=str(part.get("filename")),
                        claimed_mime=str(part.get("mimeType")),
                        source="gmail",
                        external_id=external_id,
                        caption=f"Email attachment {index + 1}",
                    )
                except DuplicateReceiptDocument:
                    continue
        if context:
            text_data = context.encode("utf-8")
            if ingestion is None:
                ingestion = ingest_bytes(
                    db,
                    settings,
                    data=text_data,
                    filename=f"gmail-{message_id}.txt",
                    claimed_mime="text/plain",
                    trusted_mime="text/plain",
                    source="gmail",
                    external_id=f"{group_external_id}:body",
                    group_external_id=group_external_id,
                    caption=context[:500],
                    ready_at=datetime.now(timezone.utc) + timedelta(seconds=3),
                )
            else:
                try:
                    ingestion, _added = append_ingestion_document(
                        db,
                        settings,
                        ingestion=ingestion,
                        data=text_data,
                        filename=f"gmail-{message_id}.txt",
                        claimed_mime="text/plain",
                        trusted_mime="text/plain",
                        source="gmail",
                        external_id=f"{group_external_id}:body",
                        caption="Sanitized email subject and body",
                    )
                except DuplicateReceiptDocument:
                    pass
        if ingestion is None:
            imported.status = "ignored"
            db.commit()
            return imported
        materialize_occurrences(
            db,
            today=received_at.date(),
            backfill_days=rule.match_window_days,
        )
        occurrence = nearest_occurrence_for_sender(db, rule, received_at.date())
        ingestion.gmail_message_import_id = imported.id
        ingestion.recurring_occurrence_id = occurrence.id if occurrence else None
        imported.ingestion_id = ingestion.id
        imported.status = "imported"
        schedule_ingestion(
            db,
            ingestion,
            ready_at=datetime.now(timezone.utc) + timedelta(seconds=3),
        )
        db.commit()
        return imported
    except Exception as exc:
        db.rollback()
        failed = db.get(GmailMessageImport, imported.id)
        if failed:
            failed.status = "failed"
            failed.error_message = str(exc)[:500]
            db.commit()
        raise


def _history_message_ids(access_token: str, history_id: str) -> tuple[list[str], str]:
    message_ids: set[str] = set()
    page_token: str | None = None
    latest_history_id = history_id
    while True:
        parameters = {
            "startHistoryId": history_id,
            "historyTypes": "messageAdded",
        }
        if page_token:
            parameters["pageToken"] = page_token
        result = _gmail_get(access_token, "history", params=parameters)
        latest_history_id = str(result.get("historyId") or latest_history_id)
        for history in result.get("history") or []:
            for added in history.get("messagesAdded") or []:
                message_id = str((added.get("message") or {}).get("id") or "")
                if message_id:
                    message_ids.add(message_id)
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return list(message_ids), latest_history_id


def _recovery_message_ids(
    access_token: str,
    connection: GmailConnection,
) -> list[str]:
    since = connection.last_synced_at or datetime.now(timezone.utc)
    since -= timedelta(days=1)
    result = _gmail_get(
        access_token,
        "messages",
        params={"q": f"after:{since.strftime('%Y/%m/%d')}", "maxResults": 500},
    )
    return [str(item["id"]) for item in result.get("messages") or [] if item.get("id")]


def sync_connection(
    db: Session,
    settings: Settings,
    connection: GmailConnection,
) -> int:
    access_token = _access_token(settings, connection)
    if not connection.history_id:
        profile = _gmail_get(access_token, "profile")
        connection.history_id = str(profile.get("historyId") or "") or None
        connection.last_synced_at = datetime.now(timezone.utc)
        connection.next_sync_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.gmail_sync_minutes
        )
        db.commit()
        return 0
    try:
        message_ids, latest_history_id = _history_message_ids(
            access_token,
            connection.history_id,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
        message_ids = _recovery_message_ids(access_token, connection)
        profile = _gmail_get(access_token, "profile")
        latest_history_id = str(profile.get("historyId") or connection.history_id)
    imported_count = 0
    for message_id in message_ids:
        if _import_message(
            db,
            settings,
            connection,
            access_token,
            message_id,
        ):
            imported_count += 1
    connection.history_id = latest_history_id
    connection.status = "connected"
    connection.error_message = None
    connection.last_synced_at = datetime.now(timezone.utc)
    connection.next_sync_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.gmail_sync_minutes
    )
    db.commit()
    return imported_count


def sync_due_connection(db: Session, settings: Settings) -> int | None:
    if not settings.gmail_configured:
        return None
    now = datetime.now(timezone.utc)
    connection = db.scalar(
        select(GmailConnection)
        .where(
            GmailConnection.status != "disconnected",
            (
                GmailConnection.next_sync_at.is_(None)
                | (GmailConnection.next_sync_at <= now)
            ),
        )
        .order_by(GmailConnection.next_sync_at)
        .limit(1)
    )
    if not connection:
        return None
    try:
        return sync_connection(db, settings, connection)
    except Exception as exc:
        db.rollback()
        connection = db.get(GmailConnection, connection.id)
        if connection:
            connection.status = "error"
            connection.error_message = str(exc)[:500]
            connection.next_sync_at = now + timedelta(minutes=settings.gmail_sync_minutes)
            db.commit()
        return None


def disconnect_connection(
    db: Session,
    settings: Settings,
    connection: GmailConnection,
) -> None:
    try:
        refresh_token = decrypt_token(settings, connection.encrypted_refresh_token)
        httpx.post(
            "https://oauth2.googleapis.com/revoke",
            params={"token": refresh_token},
            timeout=15,
        )
    except Exception:
        pass
    connection.encrypted_refresh_token = encrypt_token(settings, "disconnected")
    connection.status = "disconnected"
    connection.history_id = None
    connection.next_sync_at = None
    connection.error_message = None
    db.commit()
