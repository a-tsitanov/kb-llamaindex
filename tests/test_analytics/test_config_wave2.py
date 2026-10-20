"""Wave 2 config tests: EventsSettings (extraction) + MonitorSettings."""

from src.config import settings


def test_events_extraction_defaults_on():
    assert settings.events.extraction_enabled is True
    assert "deal" in settings.events.taxonomy or len(settings.events.taxonomy) >= 1


def test_monitor_settings_defaults():
    m = settings.monitor
    assert m.enabled is False and m.task_queue == "kb-monitor"
    assert m.sweep_interval_minutes >= 1 and 0.0 < m.risk_rise_delta <= 1.0


def test_monitor_delivery_defaults():
    """Настройки доставки остались, настройки выведенной дуги — нет.

    Burst-детектор и глобальный `MONITOR_WEBHOOK_URL` ушли вместе с дугой
    `:Alert` (P2): адресат теперь на подписке, а burst под nebula не был
    портирован вовсе.
    """
    m = settings.monitor
    assert m.webhook_timeout_s > 0 and m.deliver_batch >= 1
    retired = {"burst_enabled", "burst_window_days", "burst_baseline_windows",
               "burst_ratio", "burst_min_count", "webhook_url", "new_window_days"}
    assert retired & set(type(m).model_fields) == set()
