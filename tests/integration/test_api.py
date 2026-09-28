from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_empty_message():
    assert client.post("/chat", json={"message": "", "user_id": "cliente1988"}).status_code == 422
