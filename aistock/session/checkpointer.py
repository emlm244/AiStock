"""Checkpoint management for trading sessions."""

from __future__ import annotations

import logging
import queue
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..interfaces.persistence import StateManagerProtocol
    from ..interfaces.portfolio import PortfolioProtocol
    from ..interfaces.risk import RiskEngineProtocol


class CheckpointManager:
    """Manages async checkpointing with background worker thread.

    Responsibilities:
    - Non-blocking checkpoint saves via queue
    - Background worker thread for actual I/O
    - Graceful shutdown with queue drain
    """

    def __init__(
        self,
        portfolio: PortfolioProtocol,
        risk_engine: RiskEngineProtocol,
        state_manager: StateManagerProtocol,
        checkpoint_dir: str,
        enabled: bool = True,
    ):
        self.portfolio = portfolio
        self.risk_engine = risk_engine
        self.state_manager = state_manager
        self.checkpoint_dir = checkpoint_dir
        self.enabled = enabled

        self.logger = logging.getLogger(__name__)

        # Background worker
        self._checkpoint_queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=10)
        self._worker_running = True
        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name='CheckpointWorker')
        self._worker.start()
        self.logger.info('Checkpoint worker started')

    def save_async(self) -> None:
        """Request an async checkpoint save (non-blocking)."""
        if not self.enabled:
            return

        try:
            self._checkpoint_queue.put_nowait({})
        except queue.Full:
            self.logger.warning('Checkpoint queue full, skipping save')

    def _worker_loop(self) -> None:
        """Background worker that processes checkpoint saves."""
        while self._worker_running:
            try:
                # Wait for save request
                request = self._checkpoint_queue.get(timeout=1.0)

                if request is None:  # Shutdown signal
                    self._checkpoint_queue.task_done()  # Must mark sentinel as done
                    break

                # Perform save
                try:
                    self.state_manager.save_checkpoint(
                        self.portfolio,
                        self.risk_engine.state,  # type: ignore[attr-defined]
                        self.checkpoint_dir,
                    )
                    self.logger.debug('Checkpoint saved async')
                except Exception as exc:
                    self.logger.error(f'Checkpoint save failed: {exc}')

                self._checkpoint_queue.task_done()

            except queue.Empty:
                continue
            except Exception as exc:
                self.logger.error(f'Checkpoint worker error: {exc}')

        self.logger.info('Checkpoint worker stopped')

    def shutdown(self) -> None:
        """Gracefully shutdown with queue drain."""
        if not self.enabled:
            return

        self.logger.info('Stopping checkpoint worker')
        self._worker_running = False

        # Send shutdown signal
        try:
            self._checkpoint_queue.put(None, timeout=2.0)
        except queue.Full:
            self.logger.warning('Could not send shutdown signal')

        # Wait for pending saves
        queue_size = self._checkpoint_queue.qsize()
        if queue_size > 0:
            self.logger.info(f'Waiting for {queue_size} pending checkpoints')
            try:
                self._checkpoint_queue.join()
            except Exception as exc:
                self.logger.warning(f'Queue join failed: {exc}')

        # Wait for worker thread
        if self._worker.is_alive():
            self._worker.join(timeout=3.0)
            if self._worker.is_alive():
                self.logger.warning('Worker did not stop cleanly')

        # Final blocking save
        try:
            self.state_manager.save_checkpoint(
                self.portfolio,
                self.risk_engine.state,  # type: ignore[attr-defined]
                self.checkpoint_dir,
            )
            self.logger.info('Final checkpoint saved')
        except Exception as exc:
            self.logger.error(f'Final checkpoint failed: {exc}')
