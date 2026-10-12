import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class CustomerRepository:
    def __init__(self, path="data/mock_customers.json"):
        candidate = Path(path)
        self.path = candidate if candidate.is_absolute() else PROJECT_ROOT / candidate

    def get_by_user_id(self, user_id):
        return json.loads(self.path.read_text(encoding="utf-8")).get(user_id)
