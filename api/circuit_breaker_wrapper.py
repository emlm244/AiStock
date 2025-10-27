# api/circuit_breaker_wrapper.py

"""
Circuit Breaker Wrapper for API Calls

Implements circuit breaker pattern to prevent cascading failures:
- Opens after N consecutive failures
- Stays open for recovery timeout
- Half-open state for testing recovery
"""

import logging
from functools import wraps
from typing import Any, Callable

from circuitbreaker import circuit


def with_circuit_breaker(
    failure_threshold: int = 5, recovery_timeout: float = 60.0, expected_exception: type = Exception
):
    """
    Circuit breaker decorator for API calls

    Args:
        failure_threshold: Number of failures before opening circuit (default: 5)
        recovery_timeout: Seconds to wait before attempting recovery (default: 60)
        expected_exception: Exception type that triggers circuit breaker

    Usage:
        @with_circuit_breaker(failure_threshold=5, recovery_timeout=60)
        def api_call():
            # Your API call here
            pass
    """

    def decorator(func: Callable) -> Callable:
        # Create circuit breaker for this function
        breaker = circuit(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            expected_exception=expected_exception,
            name=f'CircuitBreaker_{func.__name__}',
        )

        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            try:
                # Apply circuit breaker
                protected_func = breaker(func)
                return protected_func(*args, **kwargs)

            except expected_exception as e:
                # Circuit is open, log and re-raise
                logger = logging.getLogger(__name__)
                logger.error(f'Circuit breaker open for {func.__name__}: {e}', exc_info=True)
                raise

        return wrapper

    return decorator


class CircuitBreakerManager:
    """
    Centralized circuit breaker manager for monitoring and control

    Tracks all circuit breakers and provides status reporting
    """

    def __init__(self, logger: logging.Logger = None):
        self.logger = logger or logging.getLogger(__name__)
        self.breakers = {}

    def register_breaker(self, name: str, breaker):
        """Register a circuit breaker for monitoring"""
        self.breakers[name] = breaker
        self.logger.info(f'Registered circuit breaker: {name}')

    def get_status(self, name: str = None) -> dict:
        """
        Get status of circuit breakers

        Args:
            name: Specific breaker name, or None for all breakers

        Returns:
            Dictionary with breaker status
        """
        if name:
            if name in self.breakers:
                return self._get_breaker_status(name, self.breakers[name])
            else:
                return {'error': f'Breaker {name} not found'}

        # Return all breakers
        return {name: self._get_breaker_status(name, breaker) for name, breaker in self.breakers.items()}

    def _get_breaker_status(self, name: str, breaker) -> dict:
        """Get status for a single breaker"""
        try:
            return {
                'name': name,
                'state': str(breaker.current_state),
                'failure_count': getattr(breaker, 'failure_count', 0),
                'last_failure_time': getattr(breaker, 'last_failure_time', None),
            }
        except Exception as e:
            return {'name': name, 'error': str(e)}

    def reset_breaker(self, name: str) -> bool:
        """
        Manually reset a circuit breaker

        Args:
            name: Breaker name

        Returns:
            True if reset successful
        """
        if name not in self.breakers:
            self.logger.error(f'Breaker {name} not found')
            return False

        try:
            breaker = self.breakers[name]
            if hasattr(breaker, 'close'):
                breaker.close()
                self.logger.info(f'Circuit breaker {name} manually reset')
                return True
            else:
                self.logger.warning(f'Breaker {name} does not support manual reset')
                return False

        except Exception as e:
            self.logger.error(f'Error resetting breaker {name}: {e}')
            return False

    def reset_all(self):
        """Reset all circuit breakers"""
        for name in self.breakers:
            self.reset_breaker(name)
