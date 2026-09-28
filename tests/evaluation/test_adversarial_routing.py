from app.agents.router import RouterAgent


def test_adversarial_routing_cases():
    router = RouterAgent()
    cases = [
        ("Tell me today's weather in Sao Paulo", "web_search"),
        ("Could you give me the current euro exchange rate?", "web_search"),
        ("The card machine refuses to connect", "customer_support"),
        ("I cannot see yesterday's payout", "customer_support"),
        ("I need help with a sale", "customer_support"),
        ("How does the Payment Link work?", "knowledge"),
        ("Can I speak to a human agent?", "human_escalation"),
        ("My terminal is offline and what is the dollar exchange rate today?", "human_escalation"),
        ("Today, explain what Get Smart does", "knowledge"),
    ]
    for message, expected in cases:
        assert router.route(message, "cliente1988")["route"] == expected
