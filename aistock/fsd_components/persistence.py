"""FSD state persistence."""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from ..fsd import FSDConfig, RLAgent


class FSDStatePersistence:
    """Handles saving and loading FSD learned state.

    Responsibilities:
    - Serialize Q-values and statistics
    - Atomic writes with backup
    - Load state with corruption recovery
    """

    def __init__(self, rl_agent: RLAgent, config: FSDConfig, symbol_performance: dict[str, Any]):
        self.rl_agent = rl_agent
        self.config = config
        self.symbol_performance = symbol_performance

        self.logger = logging.getLogger(__name__)

    def save_state(self, filepath: str) -> None:
        """Save FSD state with atomic writes."""
        from ..persistence import _atomic_write_json

        state = {
            'q_values': self.rl_agent.q_values,
            'total_trades': self.rl_agent.total_trades,
            'winning_trades': self.rl_agent.winning_trades,
            'total_pnl': self.rl_agent.total_pnl,
            'exploration_rate': self.rl_agent.exploration_rate,
            'symbol_performance': self.symbol_performance,
        }

        _atomic_write_json(state, Path(filepath))
        self.logger.info(f'FSD state saved: {len(self.rl_agent.q_values)} Q-values')

    def load_state(self, filepath: str) -> bool:
        """Load FSD state with corruption recovery."""
        try:
            path = Path(filepath)
            backup_path = path.with_suffix('.backup')

            # Try primary file
            payload_obj: object = None
            if path.exists():
                try:
                    with open(path) as f:
                        payload_obj = json.load(f)
                except json.JSONDecodeError:
                    self.logger.warning('Primary state file corrupted, trying backup')

            # Try backup if primary failed
            if payload_obj is None and backup_path.exists():
                try:
                    with open(backup_path) as f:
                        payload_obj = json.load(f)
                    self.logger.info('Loaded from backup')
                except json.JSONDecodeError:
                    self.logger.error('Both files corrupted, starting fresh')
                    return False

            if payload_obj is None:
                return False

            payload: dict[str, object] = cast(dict[str, object], payload_obj) if isinstance(payload_obj, dict) else {}

            # Load Q-values
            q_values_obj: object = payload.get('q_values', {})
            if isinstance(q_values_obj, dict):
                self.rl_agent.q_values = OrderedDict(q_values_obj)  # type: ignore
            else:
                self.rl_agent.q_values = OrderedDict()

            # Load statistics
            self.rl_agent.total_trades = int(payload.get('total_trades', 0))
            self.rl_agent.winning_trades = int(payload.get('winning_trades', 0))
            self.rl_agent.total_pnl = float(payload.get('total_pnl', 0.0))
            self.rl_agent.exploration_rate = float(payload.get('exploration_rate', self.config.exploration_rate))

            # Load symbol performance
            sp_obj: object = payload.get('symbol_performance', {})
            if isinstance(sp_obj, dict):
                self.symbol_performance.clear()
                self.symbol_performance.update(sp_obj)

            self.logger.info(f'FSD state loaded: {len(self.rl_agent.q_values)} Q-values')
            return True

        except (FileNotFoundError, json.JSONDecodeError) as exc:
            self.logger.warning(f'Could not load state: {exc}')
            return False
