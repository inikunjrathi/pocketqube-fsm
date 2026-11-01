from mcu.host_bridge.uart_bridge import Serviced, format_service_line, parse_response_line


def test_service_line_grammar():
    line = format_service_line(
        "S-05", 120.0, {"deployment_confirmed": True}, {"elevation": 12.5},
        [("E-11", 120.0), ("E-05", 100.0)],
    )
    assert line == (
        "SERVICE S-05 120.0 deployment_confirmed=true ; elevation=12.5 ; E-11@120.0 E-05@100.0"
    )


def test_serviced_line_parses_the_kept_queue():
    assert parse_response_line("SERVICED\r\n") == Serviced(remaining=())
    assert parse_response_line("SERVICED E-05 E-18") == Serviced(remaining=("E-05", "E-18"))
