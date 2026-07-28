import pytest
from core.config import Config, MissingEnvError


def test_config_loads_all_required(env_stub):
    cfg = Config.load()
    assert cfg.anthropic_api_key == "sk-test-dummy"
    assert cfg.google_maps_api_key == "gmap-test-dummy"
    assert cfg.gmail_sender_address == "test@example.com"
    assert cfg.owner_name == "山田雄一"
    assert cfg.dry_run is True
    assert cfg.daily_send_limit == 100
    assert cfg.send_interval_sec == 0


def test_config_raises_when_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingEnvError) as exc:
        Config.load()
    assert "ANTHROPIC_API_KEY" in str(exc.value)


def test_dry_run_defaults_true_when_unset(env_stub):
    env_stub.delenv("SALES_OPS_DRY_RUN", raising=False)
    cfg = Config.load()
    assert cfg.dry_run is True  # 安全側デフォルト
