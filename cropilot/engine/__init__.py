"""
Decision engine (Bartek). Public entry points:

    from engine import predict, clock_moved, precompute_season, what_if
    predict(field_ids=None, start=None, end=None) -> PredictResult   # int (rows written) with .field_ids
    clock_moved(old, new) -> PredictResult                            # after the demo date moves
    precompute_season(season=None) -> PredictResult                   # once, in the demo seed
    precompute_dates(first=None, last=None) -> int                    # optional: date moves become copies

Imported lazily so that `engine.satellite` and the training scripts work without Django.
"""


def predict(*args, **kwargs):
    from engine.compute import predict as _predict

    return _predict(*args, **kwargs)


def clock_moved(*args, **kwargs):
    """Recompute the days a demo-date move changes: see engine.compute.clock_moved."""
    from engine.compute import clock_moved as _clock_moved

    return _clock_moved(*args, **kwargs)


def precompute_season(*args, **kwargs):
    """For the demo seed: previous season, then this one to its end. See engine.compute.precompute_season."""
    from engine.compute import precompute_season as _precompute

    return _precompute(*args, **kwargs)


def precompute_dates(*args, **kwargs):
    """Computes ahead what moving the demo date needs. See engine.compute.precompute_dates."""
    from engine.compute import precompute_dates as _precompute_dates

    return _precompute_dates(*args, **kwargs)


def what_if(*args, **kwargs):
    """Dry run for the assistant: see engine.compute.what_if."""
    from engine.compute import what_if as _what_if

    return _what_if(*args, **kwargs)
