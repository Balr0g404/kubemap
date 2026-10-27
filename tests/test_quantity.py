from kubemap.quantity import format_bytes, parse_bytes, parse_cpu


def test_parse_bytes_binary_and_decimal_units():
    assert parse_bytes("2Ti") == 2 * 1024**4
    assert parse_bytes("500Gi") == 500 * 1024**3
    assert parse_bytes("37976Mi") == 37976 * 1024**2
    assert parse_bytes("1k") == 1000
    assert parse_bytes("123") == 123


def test_parse_cpu_returns_millicores():
    assert parse_cpu("4205m") == 4205
    assert parse_cpu("2") == 2000
    assert parse_cpu("250000000n") == 250


def test_format_bytes_is_human_readable():
    assert format_bytes(2 * 1024**4) == "2 Ti"
    assert format_bytes(256 * 1024**3) == "256 Gi"
    assert format_bytes(1536 * 1024**2) == "1.5 Gi"
    assert format_bytes(0) == "0 B"
