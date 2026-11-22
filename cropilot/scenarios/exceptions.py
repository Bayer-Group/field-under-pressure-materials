"""
Hierarchia wyjątków modułu zarządzania scenariuszami (test-cases).
"""

from __future__ import annotations


class ScenarioError(Exception):
    """Bazowy wyjątek dla wszystkich błędów operacji na scenariuszach."""


class ScenarioNotFoundError(ScenarioError):
    """Wyjątek rzucany, gdy żądany plik definicji scenariusza nie istnieje."""


class ScenarioValidationError(ScenarioError):
    """Wyjątek rzucany przy błędnej strukturze JSON lub niespójnych parametrach CLI."""


class DataSourceError(ScenarioError):
    """Wyjątek rzucany przy braku wymaganych plików w DATA_DIR lub błędnym formacie źródła."""