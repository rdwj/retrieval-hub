"""Fetch Google Docs from Drive API using service account credentials."""

from __future__ import annotations

import logging

from retrieval_hub.ingestion.fetch import FetchedDocument, FetchError

logger = logging.getLogger(__name__)

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
GOOGLE_DOCS_MIMETYPE = "application/vnd.google-apps.document"


def fetch_google_docs(
    *,
    folder_id: str | None = None,
    doc_ids: list[str] | None = None,
    service_account_key_path: str,
) -> list[FetchedDocument]:
    """Fetch Google Docs as plain text using service account credentials.

    Args:
        folder_id: Google Drive folder ID to fetch all docs from (mutually
            exclusive with doc_ids)
        doc_ids: List of specific Google Doc IDs to fetch (mutually exclusive
            with folder_id)
        service_account_key_path: Path to service account JSON key file

    Returns:
        List of FetchedDocument objects with exported plain text content

    Raises:
        ValueError: If neither or both of folder_id/doc_ids are provided
        FetchError: If API calls fail or documents cannot be fetched
    """
    if (folder_id is None) == (doc_ids is None):
        raise ValueError(
            "Exactly one of folder_id or doc_ids must be provided, not both or neither"
        )

    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise FetchError(
            "Install google-api-python-client and google-auth: "
            "pip install 'retrieval-hub[gdocs]'"
        ) from exc

    credentials = Credentials.from_service_account_file(
        service_account_key_path, scopes=DRIVE_SCOPES
    )
    service = build("drive", "v3", credentials=credentials)

    if folder_id:
        logger.info("fetch.fetch_google_docs folder_id=%s", folder_id)
        file_items = _list_docs_in_folder(service, folder_id)
    else:
        logger.info("fetch.fetch_google_docs doc_ids=%s", doc_ids)
        file_items = [_get_doc_metadata(service, doc_id) for doc_id in doc_ids]

    docs: list[FetchedDocument] = []
    for file_id, title in file_items:
        content = _export_doc_as_text(service, file_id)
        docs.append(
            FetchedDocument(
                url=f"https://docs.google.com/document/d/{file_id}/edit",
                title=title,
                content=content,
                content_type="text/plain",
                raw_bytes=content.encode("utf-8"),
                metadata={"google_doc_id": file_id, "source": "google_docs"},
            )
        )

    logger.info("fetch.fetch_google_docs fetched=%d docs", len(docs))
    return docs


def _list_docs_in_folder(service, folder_id: str) -> list[tuple[str, str]]:
    """List all Google Docs in a folder with pagination.

    Args:
        service: Google Drive API v3 service instance
        folder_id: Google Drive folder ID

    Returns:
        List of (file_id, name) tuples

    Raises:
        FetchError: If API call fails
    """
    query = (
        f"'{folder_id}' in parents and "
        f"mimeType='{GOOGLE_DOCS_MIMETYPE}' and "
        f"trashed=false"
    )
    items: list[tuple[str, str]] = []
    page_token = None

    try:
        while True:
            response = (
                service.files()
                .list(
                    q=query,
                    fields="nextPageToken, files(id, name)",
                    pageToken=page_token,
                )
                .execute()
            )
            for file_data in response.get("files", []):
                items.append((file_data["id"], file_data["name"]))

            page_token = response.get("nextPageToken")
            if not page_token:
                break
    except Exception as exc:
        raise FetchError(
            f"Failed to list docs in folder {folder_id}: {exc}"
        ) from exc

    logger.info(
        "fetch._list_docs_in_folder folder_id=%s count=%d", folder_id, len(items)
    )
    return items


def _get_doc_metadata(service, file_id: str) -> tuple[str, str]:
    """Fetch metadata for a single Google Doc.

    Args:
        service: Google Drive API v3 service instance
        file_id: Google Doc file ID

    Returns:
        Tuple of (file_id, name)

    Raises:
        FetchError: If API call fails
    """
    try:
        file_data = (
            service.files().get(fileId=file_id, fields="id, name").execute()
        )
        return file_data["id"], file_data["name"]
    except Exception as exc:
        raise FetchError(f"Failed to fetch metadata for doc {file_id}: {exc}") from exc


def _export_doc_as_text(service, file_id: str) -> str:
    """Export a Google Doc as plain text.

    Args:
        service: Google Drive API v3 service instance
        file_id: Google Doc file ID

    Returns:
        Document content as UTF-8 string

    Raises:
        FetchError: If export fails
    """
    try:
        response = (
            service.files()
            .export(fileId=file_id, mimeType="text/plain")
            .execute()
        )
        return response.decode("utf-8")
    except Exception as exc:
        raise FetchError(f"Failed to export doc {file_id} as text: {exc}") from exc
