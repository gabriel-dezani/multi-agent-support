from app.repositories.customer_repository import CustomerRepository
from app.tools.sales import get_sales_data
from app.tools.terminal import get_terminal_status


def test_tools():
    repository = CustomerRepository()
    assert get_sales_data("cliente1988", repository).ok
    assert get_terminal_status("cliente1988", repository).ok
    assert get_sales_data("missing", repository).error == "customer_not_found"
