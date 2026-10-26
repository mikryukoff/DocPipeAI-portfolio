from backend.app.infrastructure.exporters.passport_builders.control_volume_lookup import (
    ControlVolumeLookup,
)


def test_control_volume_lookup_supports_mixed_alphabets():
    lookup = ControlVolumeLookup()

    assert lookup.get_percent("Аа(1)", "УЗК") == "100%"
    assert lookup.get_percent("Aa(1)", "УЗК") == "100%"
    assert lookup.get_percent("В(2)", "ПВК") == "не менее 10%"
    assert lookup.get_percent("V(2)", "ПВК") == "не менее 10%"
    assert lookup.get_percent("ВV", "УЗК") == "1%"
