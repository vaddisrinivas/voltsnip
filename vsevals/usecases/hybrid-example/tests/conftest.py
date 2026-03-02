from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service.app import create_app


@pytest.fixture()
def app(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'hybrid-example-test.db'}"
    app = create_app(database_url=database_url)
    yield app
    app.state.http_client.client.close()


@pytest.fixture()
def client(app):
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
