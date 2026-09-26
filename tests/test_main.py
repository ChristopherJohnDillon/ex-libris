from exlibris import __main__ as main


def test_both_apps_by_default():
    servers = main.build_servers()
    assert [(s.config.port, s.config.app.title) for s in servers] == [(8080, "Ex Libris"), (8081, "Ex Libris (public)")]
    assert all(s.config.host == "0.0.0.0" for s in servers)


def test_public_view_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("EXLIBRIS_PUBLIC", "off")
    assert [s.config.port for s in main.build_servers()] == [8080]


def test_ports_can_be_changed(monkeypatch):
    monkeypatch.setenv("EXLIBRIS_PORT", "9000")
    monkeypatch.setenv("EXLIBRIS_PUBLIC_PORT", "9001")
    assert [s.config.port for s in main.build_servers()] == [9000, 9001]
