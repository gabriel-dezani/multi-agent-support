from app.orchestration.privacy import safe_public_search_query


def test_reconstructed_weather_query_preserves_explicit_city_and_day():
    assert safe_public_search_query('Como está o clima em Paris amanhã?') == 'weather forecast paris tomorrow'
    assert safe_public_search_query('weather in London tomorrow for CPF 12345678909') == 'weather forecast london tomorrow'
    assert safe_public_search_query('clima amanhã') == 'weather forecast Brazil tomorrow'
