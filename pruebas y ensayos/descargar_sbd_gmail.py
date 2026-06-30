import base64
import csv
import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

ACCOUNT_EMAIL = "piddef0322@gmail.com"
SUBJECT = "SBD Msg From Unit: 300534063350070"

# Si querés filtrar por remitente exacto, completar por ejemplo:
# FROM_EMAIL = "sbdservice@sbd.iridium.com"
FROM_EMAIL = None

OUTPUT_DIR = Path("descargas_sbd")
METADATA_CSV = OUTPUT_DIR / "metadata_sbd.csv"


def authenticate():
    """
    Autentica contra Gmail API usando OAuth local.
    La primera vez abre el navegador y crea token.json.
    """
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json",
                SCOPES,
            )
            creds = flow.run_local_server(port=0)

        with open("token.json", "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def build_gmail_query() -> str:
    """
    Arma la búsqueda de Gmail.

    Nota:
    - No hace falta usar to:piddef0322@gmail.com si la cuenta autenticada
      ya es esa cuenta.
    - filename:sbd ayuda, pero el filtrado definitivo por extensión se hace
      en Python.
    """
    parts = [
        f'subject:"{SUBJECT}"',
        "has:attachment",
        "filename:sbd",
    ]

    if FROM_EMAIL:
        parts.insert(0, f"from:{FROM_EMAIL}")

    return " ".join(parts)


def list_message_ids(service, query: str) -> Iterable[str]:
    """
    Lista todos los IDs de mensajes que cumplen la query, paginando resultados.
    """
    page_token = None

    while True:
        response = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=query,
                pageToken=page_token,
                includeSpamTrash=False,
            )
            .execute()
        )

        for msg in response.get("messages", []):
            yield msg["id"]

        page_token = response.get("nextPageToken")
        if not page_token:
            break


def get_header(headers: List[Dict], name: str) -> Optional[str]:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value")
    return None


def iter_parts(payload: Dict) -> Iterable[Dict]:
    """
    Recorre recursivamente las partes MIME del mensaje.
    """
    yield payload

    for part in payload.get("parts", []) or []:
        yield from iter_parts(part)


def decode_base64url(data: str) -> bytes:
    """
    Gmail usa base64 URL-safe, a veces sin padding.
    """
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def extract_text_body(payload: Dict) -> str:
    """
    Extrae texto plano y, si no hay, algo de HTML.
    Suficiente para parsear los metadatos de estos correos SBD.
    """
    chunks = []

    for part in iter_parts(payload):
        mime_type = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")

        if not data:
            continue

        if mime_type in ("text/plain", "text/html"):
            try:
                text = decode_base64url(data).decode("utf-8", errors="replace")
                chunks.append(text)
            except Exception:
                pass

    return "\n".join(chunks)


def extract_metadata(body_text: str) -> Dict[str, Optional[str]]:
    """
    Extrae metadatos típicos del cuerpo del correo Iridium SBD.
    """
    patterns = {
        "MOMSN": r"MOMSN:\s*(\d+)",
        "MTMSN": r"MTMSN:\s*(\d+)",
        "Time of Session UTC": r"Time of Session\s*\(UTC\):\s*(.+)",
        "Session Status": r"Session Status:\s*(.+)",
        "Message Size bytes": r"Message Size\s*\(bytes\):\s*(\d+)",
        "Latitude": r"Lat\s*=\s*(-?\d+(?:\.\d+)?)",
        "Longitude": r"Long\s*=\s*(-?\d+(?:\.\d+)?)",
        "CEPradius": r"CEPradius\s*=\s*(\d+)",
    }

    metadata = {}

    for key, pattern in patterns.items():
        match = re.search(pattern, body_text, flags=re.IGNORECASE)
        metadata[key] = match.group(1).strip() if match else None

    return metadata


def safe_filename(name: str) -> str:
    """
    Limpia caracteres problemáticos para nombres de archivo.
    """
    name = name.strip()
    name = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE)
    return name or "attachment.sbd"


def download_attachment(service, message_id: str, attachment_id: str) -> bytes:
    attachment = (
        service.users()
        .messages()
        .attachments()
        .get(
            userId="me",
            messageId=message_id,
            id=attachment_id,
        )
        .execute()
    )

    return decode_base64url(attachment["data"])


def save_sbd_attachments(service, message_id: str) -> List[Dict[str, Optional[str]]]:
    """
    Descarga los adjuntos .sbd de un mensaje y devuelve filas de metadata.
    """
    message = (
        service.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="full",
        )
        .execute()
    )

    payload = message.get("payload", {})
    headers = payload.get("headers", [])

    gmail_date = get_header(headers, "Date")
    gmail_from = get_header(headers, "From")
    gmail_to = get_header(headers, "To")
    gmail_subject = get_header(headers, "Subject")

    body_text = extract_text_body(payload)
    metadata = extract_metadata(body_text)

    rows = []

    for part in iter_parts(payload):
        filename = part.get("filename") or ""
        body = part.get("body", {})
        attachment_id = body.get("attachmentId")

        if not filename.lower().endswith(".sbd"):
            continue

        if not attachment_id:
            continue

        raw_data = download_attachment(service, message_id, attachment_id)

        momsn = metadata.get("MOMSN") or "sin_momsn"
        original_filename = safe_filename(filename)

        output_name = f"{momsn}_{message_id}_{original_filename}"
        output_path = OUTPUT_DIR / output_name

        with open(output_path, "wb") as f:
            f.write(raw_data)

        row = {
            "message_id": message_id,
            "gmail_date": gmail_date,
            "gmail_from": gmail_from,
            "gmail_to": gmail_to,
            "gmail_subject": gmail_subject,
            "saved_file": str(output_path),
            "original_filename": filename,
            "attachment_size_bytes": len(raw_data),
            **metadata,
        }

        rows.append(row)

    return rows


def write_metadata_csv(rows: List[Dict[str, Optional[str]]]):
    if not rows:
        return

    fieldnames = [
        "message_id",
        "gmail_date",
        "gmail_from",
        "gmail_to",
        "gmail_subject",
        "saved_file",
        "original_filename",
        "attachment_size_bytes",
        "MOMSN",
        "MTMSN",
        "Time of Session UTC",
        "Session Status",
        "Message Size bytes",
        "Latitude",
        "Longitude",
        "CEPradius",
    ]

    with open(METADATA_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    
    print("Iniciando descarga de adjuntos SBD...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    service = authenticate()
    query = build_gmail_query()

    print(f"Buscando mensajes con query:")
    print(query)
    print()

    all_rows = []
    message_count = 0
    attachment_count = 0

    for message_id in list_message_ids(service, query):
        message_count += 1

        rows = save_sbd_attachments(service, message_id)
        all_rows.extend(rows)
        attachment_count += len(rows)

        print(
            f"Mensaje {message_count}: {message_id} - "
            f"{len(rows)} adjunto(s) .sbd descargado(s)"
        )

    write_metadata_csv(all_rows)

    print()
    print(f"Mensajes encontrados: {message_count}")
    print(f"Adjuntos .sbd descargados: {attachment_count}")
    print(f"Carpeta de salida: {OUTPUT_DIR.resolve()}")

    if all_rows:
        print(f"CSV de metadatos: {METADATA_CSV.resolve()}")


if __name__ == "__main__":
    main()