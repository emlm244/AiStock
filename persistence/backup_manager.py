# persistence/backup_manager.py

"""
Backup Manager - Versioned State Backups with Integrity Checks

Features:
- Keep last N backups with timestamps
- SHA256 checksums for integrity verification
- Automatic cleanup of old backups
- Restore capability
"""

import hashlib
import json
import logging
import os
import shutil
from datetime import datetime
from typing import Optional


class BackupManager:
    """
    Manages versioned backups of bot state files

    Keeps the last N backups with timestamps and checksums for integrity
    """

    def __init__(
        self,
        state_file_path: str,
        backup_dir: Optional[str] = None,
        max_backups: int = 10,
        logger: Optional[logging.Logger] = None,
    ):
        self.state_file_path = state_file_path
        self.max_backups = max_backups
        self.logger = logger or logging.getLogger(__name__)

        # Set backup directory
        if backup_dir is None:
            state_dir = os.path.dirname(state_file_path)
            self.backup_dir = os.path.join(state_dir, 'backups')
        else:
            self.backup_dir = backup_dir

        # Create backup directory if it doesn't exist
        os.makedirs(self.backup_dir, exist_ok=True)

        # Metadata file
        self.metadata_file = os.path.join(self.backup_dir, 'backup_metadata.json')
        self.metadata = self._load_metadata()

    def _load_metadata(self) -> dict:
        """Load backup metadata"""
        if os.path.exists(self.metadata_file):
            try:
                with open(self.metadata_file) as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f'Error loading backup metadata: {e}')

        return {'backups': []}

    def _save_metadata(self):
        """Save backup metadata"""
        try:
            with open(self.metadata_file, 'w') as f:
                json.dump(self.metadata, f, indent=2, default=str)
        except Exception as e:
            self.logger.error(f'Error saving backup metadata: {e}')

    def _calculate_checksum(self, file_path: str) -> str:
        """Calculate SHA256 checksum of a file"""
        sha256_hash = hashlib.sha256()

        try:
            with open(file_path, 'rb') as f:
                # Read file in chunks to handle large files
                for byte_block in iter(lambda: f.read(4096), b''):
                    sha256_hash.update(byte_block)

            return sha256_hash.hexdigest()

        except Exception as e:
            self.logger.error(f'Error calculating checksum: {e}')
            return ''

    def create_backup(self, reason: str = '') -> Optional[str]:
        """
        Create a new backup of the state file

        Args:
            reason: Optional reason for the backup

        Returns:
            Path to the backup file, or None if failed
        """
        if not os.path.exists(self.state_file_path):
            self.logger.warning(f'State file not found: {self.state_file_path}')
            return None

        try:
            # Generate backup filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_filename = f'state_backup_{timestamp}.json'
            backup_path = os.path.join(self.backup_dir, backup_filename)

            # Copy state file to backup
            shutil.copy2(self.state_file_path, backup_path)

            # Calculate checksum
            checksum = self._calculate_checksum(backup_path)

            # Get file size
            file_size = os.path.getsize(backup_path)

            # Add to metadata
            backup_info = {
                'filename': backup_filename,
                'path': backup_path,
                'timestamp': datetime.now().isoformat(),
                'checksum': checksum,
                'size_bytes': file_size,
                'reason': reason,
            }

            self.metadata['backups'].append(backup_info)
            self._save_metadata()

            # Cleanup old backups
            self._cleanup_old_backups()

            self.logger.info(
                f'Backup created: {backup_filename} (size: {file_size} bytes, checksum: {checksum[:16]}...)'
            )

            return backup_path

        except Exception as e:
            self.logger.error(f'Failed to create backup: {e}', exc_info=True)
            return None

    def _cleanup_old_backups(self):
        """Remove backups exceeding max_backups limit"""
        if len(self.metadata['backups']) <= self.max_backups:
            return

        # Sort by timestamp (oldest first)
        sorted_backups = sorted(self.metadata['backups'], key=lambda x: x['timestamp'])

        # Remove oldest backups
        to_remove = sorted_backups[: -self.max_backups]

        for backup in to_remove:
            try:
                # Remove file
                if os.path.exists(backup['path']):
                    os.remove(backup['path'])
                    self.logger.info(f'Removed old backup: {backup["filename"]}')

                # Remove from metadata
                self.metadata['backups'].remove(backup)

            except Exception as e:
                self.logger.error(f'Error removing old backup {backup["filename"]}: {e}')

        self._save_metadata()

    def list_backups(self) -> list[dict]:
        """
        List all available backups

        Returns:
            List of backup info dictionaries, sorted by timestamp (newest first)
        """
        return sorted(self.metadata['backups'], key=lambda x: x['timestamp'], reverse=True)

    def verify_backup(self, backup_path: str) -> tuple[bool, str]:
        """
        Verify backup integrity using checksum

        Args:
            backup_path: Path to backup file

        Returns:
            Tuple of (is_valid, message)
        """
        if not os.path.exists(backup_path):
            return False, f'Backup file not found: {backup_path}'

        # Find backup in metadata
        backup_info = None
        for backup in self.metadata['backups']:
            if backup['path'] == backup_path:
                backup_info = backup
                break

        if backup_info is None:
            return False, 'Backup not found in metadata'

        # Verify checksum
        current_checksum = self._calculate_checksum(backup_path)
        expected_checksum = backup_info['checksum']

        if current_checksum != expected_checksum:
            return False, f'Checksum mismatch. Expected: {expected_checksum}, Got: {current_checksum}'

        return True, 'Backup integrity verified'

    def restore_backup(self, backup_path: str, verify: bool = True) -> bool:
        """
        Restore state from a backup

        Args:
            backup_path: Path to backup file
            verify: Whether to verify checksum before restoring

        Returns:
            True if restore successful, False otherwise
        """
        if not os.path.exists(backup_path):
            self.logger.error(f'Backup file not found: {backup_path}')
            return False

        try:
            # Verify backup if requested
            if verify:
                is_valid, msg = self.verify_backup(backup_path)
                if not is_valid:
                    self.logger.error(f'Backup verification failed: {msg}')
                    return False

            # Create a backup of current state before restoring
            if os.path.exists(self.state_file_path):
                self.create_backup(reason='Pre-restore backup')

            # Restore from backup
            shutil.copy2(backup_path, self.state_file_path)

            self.logger.info(f'State restored from backup: {backup_path}')
            return True

        except Exception as e:
            self.logger.error(f'Failed to restore backup: {e}', exc_info=True)
            return False

    def get_latest_backup(self) -> Optional[dict]:
        """Get info about the most recent backup"""
        backups = self.list_backups()
        return backups[0] if backups else None

    def get_backup_by_timestamp(self, timestamp_str: str) -> Optional[dict]:
        """Find backup by timestamp string"""
        for backup in self.metadata['backups']:
            if timestamp_str in backup['timestamp']:
                return backup
        return None

    def auto_restore_latest(self) -> bool:
        """
        Automatically restore from the latest valid backup

        Returns:
            True if restore successful, False otherwise
        """
        latest_backup = self.get_latest_backup()

        if latest_backup is None:
            self.logger.error('No backups available for auto-restore')
            return False

        self.logger.info(f'Auto-restoring from latest backup: {latest_backup["filename"]}')
        return self.restore_backup(latest_backup['path'], verify=True)

    def get_total_backup_size(self) -> int:
        """Get total size of all backups in bytes"""
        return sum(backup.get('size_bytes', 0) for backup in self.metadata['backups'])

    def cleanup_all_backups(self):
        """Remove all backups (use with caution)"""
        for backup in self.metadata['backups'].copy():
            try:
                if os.path.exists(backup['path']):
                    os.remove(backup['path'])
                self.metadata['backups'].remove(backup)
            except Exception as e:
                self.logger.error(f'Error removing backup {backup["filename"]}: {e}')

        self._save_metadata()
        self.logger.warning('All backups removed')
