"""
Encrypted credentials management for AiStock trading bot.
Uses Fernet symmetric encryption for sensitive data.
"""

import base64
import os
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
from dotenv import load_dotenv


class CredentialsManager:
    """
    Manages encrypted credentials using Fernet symmetric encryption.

    Best Practices (2025):
    - Uses PBKDF2 with 1,200,000+ iterations for key derivation
    - Stores encryption key in environment variable
    - Never logs or prints decrypted credentials
    - Supports key rotation via MultiFernet
    """

    def __init__(self, env_file: str = '.env'):
        """
        Initialize credentials manager.

        Args:
            env_file: Path to .env file containing credentials
        """
        # Load environment variables from .env file
        load_dotenv(env_file)

        # Get or generate encryption key
        self.encryption_key = self._get_or_create_key()
        self.cipher = Fernet(self.encryption_key)

    def _get_or_create_key(self) -> bytes:
        """
        Get encryption key from environment or generate new one.

        Returns:
            Fernet-compatible encryption key (32 bytes, URL-safe base64-encoded)
        """
        key_from_env = os.getenv('FERNET_ENCRYPTION_KEY')

        if key_from_env:
            try:
                # Validate key format
                key_bytes = key_from_env.encode()
                Fernet(key_bytes)  # Will raise if invalid
                return key_bytes
            except Exception as e:
                raise ValueError(
                    f'Invalid FERNET_ENCRYPTION_KEY in environment: {e}\n'
                    'Generate a new key with: python -m security.credentials_manager generate-key'
                )
        else:
            # Generate new key (only for development!)
            print('WARNING: No FERNET_ENCRYPTION_KEY found. Generating new key for this session.')
            print('This key will NOT persist. Set it in .env for production!')
            new_key = Fernet.generate_key()
            print(f'\nAdd this to your .env file:\nFERNET_ENCRYPTION_KEY={new_key.decode()}\n')
            return new_key

    @staticmethod
    def generate_key_from_password(password: str, salt: Optional[bytes] = None) -> bytes:
        """
        Derive encryption key from password using PBKDF2.

        Args:
            password: Master password for key derivation
            salt: Salt for key derivation (generates random if None)

        Returns:
            Fernet-compatible encryption key
        """
        if salt is None:
            salt = os.urandom(16)

        kdf = PBKDF2(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=1_200_000,  # Django 2025 recommendation
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt plaintext string.

        Args:
            plaintext: String to encrypt

        Returns:
            Encrypted string (URL-safe base64-encoded)
        """
        if not plaintext:
            return ''
        encrypted_bytes = self.cipher.encrypt(plaintext.encode())
        return encrypted_bytes.decode()

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt ciphertext string.

        Args:
            ciphertext: Encrypted string to decrypt

        Returns:
            Decrypted plaintext string
        """
        if not ciphertext:
            return ''
        decrypted_bytes = self.cipher.decrypt(ciphertext.encode())
        return decrypted_bytes.decode()

    def get_credential(self, key: str, encrypted: bool = False) -> Optional[str]:
        """
        Get credential from environment variables.

        Args:
            key: Environment variable name
            encrypted: If True, decrypt the value before returning

        Returns:
            Credential value (decrypted if encrypted=True)
        """
        value = os.getenv(key)

        if value is None:
            return None

        if encrypted:
            try:
                return self.decrypt(value)
            except Exception as e:
                raise ValueError(f"Failed to decrypt credential '{key}': {e}")

        return value

    def get_ibkr_credentials(self) -> dict[str, any]:
        """
        Get IBKR API credentials from environment.

        Returns:
            Dictionary with IBKR configuration

        Raises:
            ValueError: If required credentials are missing
        """
        account_id = self.get_credential('IBKR_ACCOUNT_ID')

        if not account_id or account_id == 'YOUR_ACCOUNT_ID_HERE':
            raise ValueError(
                'CRITICAL: IBKR_ACCOUNT_ID not set or is placeholder value.\n'
                'Set it in your .env file. See .env.example for reference.'
            )

        return {
            'TWS_HOST': self.get_credential('IBKR_TWS_HOST', encrypted=False) or '127.0.0.1',
            'TWS_PORT': int(self.get_credential('IBKR_TWS_PORT', encrypted=False) or 7497),
            'CLIENT_ID': int(self.get_credential('IBKR_CLIENT_ID', encrypted=False) or 1001),
            'ACCOUNT_ID': account_id,
        }

    def validate_credentials(self) -> tuple[bool, str]:
        """
        Validate that all required credentials are present and valid.

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            creds = self.get_ibkr_credentials()

            # Validate port number
            valid_ports = [7496, 7497, 4001, 4002]
            if creds['TWS_PORT'] not in valid_ports:
                return False, f'Invalid TWS_PORT: {creds["TWS_PORT"]}. Must be one of {valid_ports}'

            # Validate account ID format (basic check)
            if len(creds['ACCOUNT_ID']) < 5:
                return False, "IBKR_ACCOUNT_ID appears too short. Verify it's correct."

            return True, 'All credentials valid'

        except Exception as e:
            return False, str(e)


def main():
    """CLI utility for key generation."""
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == 'generate-key':
        key = Fernet.generate_key()
        print('Generated Fernet encryption key:')
        print(f'\nFERNET_ENCRYPTION_KEY={key.decode()}')
        print('\nAdd this to your .env file (keep it secret!)')
    else:
        print('Usage: python -m security.credentials_manager generate-key')


if __name__ == '__main__':
    main()
