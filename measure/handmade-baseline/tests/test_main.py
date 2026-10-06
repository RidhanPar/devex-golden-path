from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_hello() -> None:
    assert client.get("/hello", params={"name": "Ada"}).json() == {"message": "Hello, Ada!"}
