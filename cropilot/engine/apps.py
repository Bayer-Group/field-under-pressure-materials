from django.apps import AppConfig


class EngineConfig(AppConfig):
    """
    No signals: when the demo date moves, the platform calls engine.clock_moved(old, new) explicitly
    (docs/archive/engine-predict-review.md, point 4).
    """

    name = "engine"
    verbose_name = "Decision engine"
