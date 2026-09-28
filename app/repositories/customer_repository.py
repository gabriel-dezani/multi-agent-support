import json
from pathlib import Path
class CustomerRepository:
 def __init__(self,path="data/mock_customers.json"): self.path=Path(path)
 def get_by_user_id(self,user_id): return json.loads(self.path.read_text(encoding="utf-8")).get(user_id)
