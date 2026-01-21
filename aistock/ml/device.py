"""Device management for PyTorch operations."""

import logging
from typing import Literal

import torch

logger = logging.getLogger(__name__)

DeviceType = Literal['auto', 'cpu', 'cuda', 'mps']


def get_device(preference: DeviceType = 'auto') -> torch.device:
    """Get the best available PyTorch device.

    Args:
        preference: Device preference ('auto', 'cpu', 'cuda', 'mps')
            - 'auto': Automatically select best available device
            - 'cpu': Force CPU usage
            - 'cuda': Use NVIDIA GPU (falls back to CPU if unavailable)
            - 'mps': Use Apple Silicon GPU (falls back to CPU if unavailable)

    Returns:
        torch.device for tensor operations
    """
    if preference == 'cpu':
        logger.info('Using CPU device (explicit preference)')
        return torch.device('cpu')

    if preference == 'cuda':
        if torch.cuda.is_available():
            device = torch.device('cuda')
            logger.info(f'Using CUDA device: {torch.cuda.get_device_name(0)}')
            return device
        logger.warning('CUDA requested but not available, falling back to CPU')
        return torch.device('cpu')

    if preference == 'mps':
        if torch.backends.mps.is_available():
            logger.info('Using MPS device (Apple Silicon)')
            return torch.device('mps')
        logger.warning('MPS requested but not available, falling back to CPU')
        return torch.device('cpu')

    # Auto-detect best device
    if torch.cuda.is_available():
        device = torch.device('cuda')
        logger.info(f'Auto-selected CUDA device: {torch.cuda.get_device_name(0)}')
        return device

    if torch.backends.mps.is_available():
        logger.info('Auto-selected MPS device (Apple Silicon)')
        return torch.device('mps')

    logger.info('Auto-selected CPU device (no GPU available)')
    return torch.device('cpu')


def get_device_info() -> dict[str, object]:
    """Get information about available devices.

    Returns:
        Dictionary with device availability and properties
    """
    info: dict[str, object] = {
        'cpu': True,
        'cuda_available': torch.cuda.is_available(),
        'mps_available': torch.backends.mps.is_available(),
    }

    if torch.cuda.is_available():
        info['cuda_device_count'] = torch.cuda.device_count()
        info['cuda_device_name'] = torch.cuda.get_device_name(0)
        info['cuda_memory_total'] = torch.cuda.get_device_properties(0).total_memory
        info['cuda_memory_allocated'] = torch.cuda.memory_allocated(0)

    return info
