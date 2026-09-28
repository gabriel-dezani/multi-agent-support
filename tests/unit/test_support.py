from app.agents.support import CustomerSupportAgent
from app.repositories.customer_repository import CustomerRepository


def test_support_sales_and_terminal():
    agent = CustomerSupportAgent(CustomerRepository())
    sales = agent.process("When will my sales be deposited?", "cliente1988")
    terminal = agent.process("My card machine will not connect to the internet", "cliente1988")
    assert sales["tools_used"] == ["get_sales_data"]
    assert terminal["tools_used"] == ["get_terminal_status"]
    assert sales["requires_human"] is False
    assert terminal["requires_human"] is False


def test_support_escalates_unknown_customer():
    agent = CustomerSupportAgent(CustomerRepository())
    result = agent.process("Check my sales", "missing")
    assert result["requires_human"] is True
    assert result["confidence"] == 0.2


def test_support_escalates_mixed_support_intents():
    agent = CustomerSupportAgent(CustomerRepository())
    result = agent.process("My terminal is offline and I need to know yesterday's payout", "cliente1988")
    assert result["requires_human"] is True
    assert result["tools_used"] == []


def test_generic_support_does_not_guess_a_tool():
    result = CustomerSupportAgent().process("I need support", "cliente1988")
    assert result["requires_human"] is True
    assert result["tools_used"] == []
