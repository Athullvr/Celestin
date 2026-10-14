from orbit.postgres.migrate_cli import main


def test_cli_requires_dsn_environment_variable_without_printing_secret(monkeypatch, capsys):
    monkeypatch.delenv("CELESTIN_POSTGRES_DSN", raising=False)

    assert main([]) == 2
    captured = capsys.readouterr()
    assert "CELESTIN_POSTGRES_DSN" in captured.err
    assert "password" not in captured.err.lower()

