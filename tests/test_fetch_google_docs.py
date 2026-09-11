"""Tests for Google Docs fetch adapter and pipeline integration."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from retrieval_hub.ingestion.chunking.token_fixed import chunk_document
from retrieval_hub.ingestion.fetch import FetchedDocument, FetchError
from retrieval_hub.ingestion.fetch_google_docs import GOOGLE_DOCS_MIMETYPE, fetch_google_docs
from retrieval_hub.ingestion.normalize import normalize_document
from retrieval_hub.ingestion.parse import parse_document


@pytest.fixture
def mock_google_modules():
    mock_creds_class = MagicMock()
    mock_creds_instance = MagicMock()
    mock_creds_class.from_service_account_file.return_value = mock_creds_instance

    mock_service_account = MagicMock()
    mock_service_account.Credentials = mock_creds_class

    mock_oauth2 = MagicMock()
    mock_oauth2.service_account = mock_service_account

    mock_google = MagicMock()
    mock_google.oauth2 = mock_oauth2

    mock_build = MagicMock()
    mock_discovery = MagicMock()
    mock_discovery.build = mock_build

    mock_googleapiclient = MagicMock()
    mock_googleapiclient.discovery = mock_discovery

    sys.modules["google"] = mock_google
    sys.modules["google.oauth2"] = mock_oauth2
    sys.modules["google.oauth2.service_account"] = mock_service_account
    sys.modules["googleapiclient"] = mock_googleapiclient
    sys.modules["googleapiclient.discovery"] = mock_discovery

    yield mock_build, mock_creds_class

    for mod in [
        "google",
        "google.oauth2",
        "google.oauth2.service_account",
        "googleapiclient",
        "googleapiclient.discovery",
    ]:
        sys.modules.pop(mod, None)


@pytest.fixture
def mock_drive_service():
    service = MagicMock()
    files_api = MagicMock()
    service.files.return_value = files_api
    return service, files_api


def test_fetch_google_docs_with_folder_id(mock_google_modules, mock_drive_service):
    mock_build, mock_creds_class = mock_google_modules
    service, files_api = mock_drive_service

    files_api.list.return_value.execute.return_value = {
        "files": [
            {"id": "doc1", "name": "Document One"},
            {"id": "doc2", "name": "Document Two"},
        ],
    }

    files_api.export.return_value.execute.side_effect = [
        b"Content of document one",
        b"Content of document two",
    ]

    mock_build.return_value = service

    docs = fetch_google_docs(
        folder_id="folder123",
        service_account_key_path="/fake/path/to/key.json",
    )

    assert len(docs) == 2

    assert docs[0].url == "https://docs.google.com/document/d/doc1/edit"
    assert docs[0].title == "Document One"
    assert docs[0].content == "Content of document one"
    assert docs[0].content_type == "text/plain"
    assert docs[0].raw_bytes == b"Content of document one"
    assert docs[0].metadata["google_doc_id"] == "doc1"
    assert docs[0].metadata["source"] == "google_docs"

    assert docs[1].url == "https://docs.google.com/document/d/doc2/edit"
    assert docs[1].title == "Document Two"
    assert docs[1].content == "Content of document two"
    assert docs[1].content_type == "text/plain"
    assert docs[1].metadata["google_doc_id"] == "doc2"
    assert docs[1].metadata["source"] == "google_docs"

    files_api.list.assert_called_once()
    list_call_kwargs = files_api.list.call_args.kwargs
    assert "folder123" in list_call_kwargs["q"]
    assert GOOGLE_DOCS_MIMETYPE in list_call_kwargs["q"]


def test_fetch_google_docs_with_doc_ids(mock_google_modules, mock_drive_service):
    mock_build, mock_creds_class = mock_google_modules
    service, files_api = mock_drive_service

    files_api.get.return_value.execute.side_effect = [
        {"id": "doc1", "name": "First Doc"},
        {"id": "doc2", "name": "Second Doc"},
    ]

    files_api.export.return_value.execute.side_effect = [
        b"First doc content",
        b"Second doc content",
    ]

    mock_build.return_value = service

    docs = fetch_google_docs(
        doc_ids=["doc1", "doc2"],
        service_account_key_path="/fake/path/to/key.json",
    )

    assert len(docs) == 2
    assert docs[0].title == "First Doc"
    assert docs[0].content == "First doc content"
    assert docs[0].metadata["google_doc_id"] == "doc1"
    assert docs[1].title == "Second Doc"
    assert docs[1].content == "Second doc content"
    assert docs[1].metadata["google_doc_id"] == "doc2"

    assert files_api.get.call_count == 2
    assert files_api.export.call_count == 2


def test_fetch_google_docs_validation_error():
    with pytest.raises(
        ValueError,
        match="Exactly one of folder_id or doc_ids must be provided",
    ):
        fetch_google_docs(
            folder_id="folder123",
            doc_ids=["doc1"],
            service_account_key_path="/fake/path/to/key.json",
        )

    with pytest.raises(
        ValueError,
        match="Exactly one of folder_id or doc_ids must be provided",
    ):
        fetch_google_docs(
            service_account_key_path="/fake/path/to/key.json",
        )


def test_fetch_google_docs_missing_deps():
    import builtins

    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name.startswith("google"):
            raise ImportError("No module named 'google'")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        with pytest.raises(
            FetchError,
            match="Install google-api-python-client and google-auth",
        ):
            fetch_google_docs(
                folder_id="folder123",
                service_account_key_path="/fake/path/to/key.json",
            )


def test_fetch_google_docs_api_error(mock_google_modules, mock_drive_service):
    mock_build, mock_creds_class = mock_google_modules
    service, files_api = mock_drive_service

    files_api.list.return_value.execute.side_effect = Exception("Drive API failure")
    mock_build.return_value = service

    with pytest.raises(FetchError, match="Failed to list docs in folder"):
        fetch_google_docs(
            folder_id="folder123",
            service_account_key_path="/fake/path/to/key.json",
        )


def test_fetch_google_docs_folder_pagination(mock_google_modules, mock_drive_service):
    mock_build, mock_creds_class = mock_google_modules
    service, files_api = mock_drive_service

    files_api.list.return_value.execute.side_effect = [
        {
            "files": [{"id": "doc1", "name": "Page 1 Doc"}],
            "nextPageToken": "token123",
        },
        {
            "files": [{"id": "doc2", "name": "Page 2 Doc"}],
        },
    ]

    files_api.export.return_value.execute.side_effect = [
        b"Page 1 content",
        b"Page 2 content",
    ]

    mock_build.return_value = service

    docs = fetch_google_docs(
        folder_id="folder123",
        service_account_key_path="/fake/path/to/key.json",
    )

    assert len(docs) == 2
    assert docs[0].title == "Page 1 Doc"
    assert docs[1].title == "Page 2 Doc"

    assert files_api.list.call_count == 2
    first_call = files_api.list.call_args_list[0]
    second_call = files_api.list.call_args_list[1]
    assert first_call.kwargs.get("pageToken") is None
    assert second_call.kwargs.get("pageToken") == "token123"


def test_chunk_doc_id_propagation():
    doc = FetchedDocument(
        url="https://docs.google.com/document/d/testdoc123/edit",
        title="Test Document",
        content="This is a test document with some content. " * 50,
        content_type="text/plain",
        raw_bytes=b"",
        metadata={"google_doc_id": "testdoc123", "source": "google_docs"},
    )

    parsed = parse_document(doc)
    normalized = normalize_document(parsed)
    chunks = chunk_document(normalized, chunk_tokens=50, overlap_tokens=10)

    google_doc_id = doc.metadata.get("google_doc_id")
    for chunk in chunks:
        chunk.doc_id = google_doc_id

    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.doc_id == "testdoc123"
        assert chunk.doc_url == "https://docs.google.com/document/d/testdoc123/edit"
        assert chunk.doc_title == "Test Document"


def test_chunk_doc_id_default_none():
    doc = FetchedDocument(
        url="https://example.com/document",
        title="Regular Document",
        content="This is a regular document without google_doc_id metadata. " * 50,
        content_type="text/plain",
        raw_bytes=b"",
        metadata={"source": "web"},
    )

    parsed = parse_document(doc)
    normalized = normalize_document(parsed)
    chunks = chunk_document(normalized, chunk_tokens=50, overlap_tokens=10)

    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.doc_id is None
        assert chunk.doc_url == "https://example.com/document"
        assert chunk.doc_title == "Regular Document"
