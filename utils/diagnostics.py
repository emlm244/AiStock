# utils/diagnostics.py

"""
Pre-Flight System Diagnostics

Performs comprehensive system checks before bot startup to ensure
all prerequisites are met and provides beginner-friendly guidance.
"""

import os
import platform
import socket
import sys
from datetime import datetime
from pathlib import Path


class DiagnosticCheck:
    """Represents a single diagnostic check result"""

    def __init__(self, name: str, passed: bool, message: str, suggestion: str = ''):
        self.name = name
        self.passed = passed
        self.message = message
        self.suggestion = suggestion
        self.timestamp = datetime.now()

    def __repr__(self):
        status = '✓ PASS' if self.passed else '✗ FAIL'
        return f'{status}: {self.name} - {self.message}'


class SystemDiagnostics:
    """Performs comprehensive pre-flight system checks"""

    def __init__(self, logger=None):
        self.logger = logger
        self.checks: list[DiagnosticCheck] = []

    def run_all_checks(self, settings=None) -> tuple[bool, list[DiagnosticCheck]]:
        """
        Run all diagnostic checks

        Returns:
            (all_passed, list_of_checks)
        """
        self.checks = []

        # System checks
        self.checks.append(self._check_python_version())
        self.checks.append(self._check_operating_system())
        self.checks.append(self._check_disk_space())
        self.checks.append(self._check_memory())

        # Dependency checks
        self.checks.append(self._check_required_packages())

        # File system checks
        self.checks.append(self._check_required_files())
        self.checks.append(self._check_directory_permissions())

        # Network checks
        if settings:
            self.checks.append(self._check_tws_connection(settings))
            self.checks.append(self._check_internet_connection())

        # Configuration checks
        if settings:
            self.checks.append(self._check_credentials())
            self.checks.append(self._check_critical_settings(settings))

        all_passed = all(check.passed for check in self.checks)
        return all_passed, self.checks

    def _check_python_version(self) -> DiagnosticCheck:
        """Check if Python version is compatible"""
        version = sys.version_info
        min_major, min_minor = 3, 9

        if version.major >= min_major and version.minor >= min_minor:
            return DiagnosticCheck(
                'Python Version', True, f'Python {version.major}.{version.minor}.{version.micro} is compatible'
            )
        else:
            return DiagnosticCheck(
                'Python Version',
                False,
                f'Python {version.major}.{version.minor} is too old (minimum: {min_major}.{min_minor})',
                f'Install Python {min_major}.{min_minor} or newer from python.org',
            )

    def _check_operating_system(self) -> DiagnosticCheck:
        """Check operating system compatibility"""
        os_name = platform.system()
        os_version = platform.release()

        supported_os = ['Windows', 'Linux', 'Darwin']  # Darwin = macOS

        if os_name in supported_os:
            return DiagnosticCheck('Operating System', True, f'{os_name} {os_version} is supported')
        else:
            return DiagnosticCheck(
                'Operating System',
                False,
                f'{os_name} may not be fully supported',
                'Tested on Windows, Linux, and macOS. Other systems may have issues.',
            )

    def _check_disk_space(self) -> DiagnosticCheck:
        """Check available disk space"""
        try:
            if platform.system() == 'Windows':
                import ctypes

                free_bytes = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                    ctypes.c_wchar_p(os.getcwd()), None, None, ctypes.pointer(free_bytes)
                )
                free_gb = free_bytes.value / (1024**3)
            else:
                stat = os.statvfs(os.getcwd())
                free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)

            min_required_gb = 1.0  # Minimum 1GB free

            if free_gb >= min_required_gb:
                return DiagnosticCheck('Disk Space', True, f'{free_gb:.2f} GB available (sufficient)')
            else:
                return DiagnosticCheck(
                    'Disk Space',
                    False,
                    f'Only {free_gb:.2f} GB available (minimum: {min_required_gb} GB)',
                    'Free up disk space before running the bot',
                )

        except Exception as e:
            return DiagnosticCheck(
                'Disk Space',
                True,  # Don't fail on check error
                f'Could not check disk space: {e}',
            )

    def _check_memory(self) -> DiagnosticCheck:
        """Check available memory"""
        try:
            if platform.system() == 'Windows':
                import ctypes

                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ('dwLength', ctypes.c_ulong),
                        ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', ctypes.c_ulonglong),
                        ('ullAvailPhys', ctypes.c_ulonglong),
                        ('ullTotalPageFile', ctypes.c_ulonglong),
                        ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong),
                        ('ullAvailVirtual', ctypes.c_ulonglong),
                        ('sullAvailExtendedVirtual', ctypes.c_ulonglong),
                    ]

                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
                available_mb = stat.ullAvailPhys / (1024**2)
            else:
                # Linux/macOS - try psutil
                try:
                    import psutil

                    available_mb = psutil.virtual_memory().available / (1024**2)
                except ImportError:
                    return DiagnosticCheck('Memory', True, 'Could not check memory (psutil not installed)')

            min_required_mb = 512  # Minimum 512MB

            if available_mb >= min_required_mb:
                return DiagnosticCheck('Memory', True, f'{available_mb:.0f} MB available (sufficient)')
            else:
                return DiagnosticCheck(
                    'Memory',
                    False,
                    f'Only {available_mb:.0f} MB available (minimum: {min_required_mb} MB)',
                    'Close other applications to free up memory',
                )

        except Exception as e:
            return DiagnosticCheck(
                'Memory',
                True,  # Don't fail on check error
                f'Could not check memory: {e}',
            )

    def _check_required_packages(self) -> DiagnosticCheck:
        """Check if required Python packages are installed"""
        required_packages = [
            'pandas',
            'numpy',
            'pytz',
            'ibapi',
            'tenacity',
            'scikit-learn',
            'flask',
            'prometheus_client',
        ]

        missing = []
        for package in required_packages:
            try:
                __import__(package)
            except ImportError:
                missing.append(package)

        if not missing:
            return DiagnosticCheck('Required Packages', True, 'All required packages are installed')
        else:
            return DiagnosticCheck(
                'Required Packages',
                False,
                f'Missing packages: {", ".join(missing)}',
                f'Install missing packages: pip install {" ".join(missing)}',
            )

    def _check_required_files(self) -> DiagnosticCheck:
        """Check if required configuration files exist"""
        required_files = [
            'config/settings.py',
            'config/credentials.py',
        ]

        missing = []
        for file_path in required_files:
            if not Path(file_path).exists():
                missing.append(file_path)

        if not missing:
            return DiagnosticCheck('Required Files', True, 'All required configuration files exist')
        else:
            return DiagnosticCheck(
                'Required Files',
                False,
                f'Missing files: {", ".join(missing)}',
                'Create missing configuration files. Check CLAUDE.md for guidance.',
            )

    def _check_directory_permissions(self) -> DiagnosticCheck:
        """Check if required directories have proper permissions"""
        critical_dirs = ['logs', 'logs/error_logs', 'logs/trade_logs', 'data', 'models']

        permission_errors = []

        for dir_path in critical_dirs:
            path = Path(dir_path)

            # Create if doesn't exist
            if not path.exists():
                try:
                    path.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    permission_errors.append(f'{dir_path}: Cannot create - {e}')
                    continue

            # Test write permission
            test_file = path / '.write_test'
            try:
                test_file.touch()
                test_file.unlink()
            except Exception as e:
                permission_errors.append(f'{dir_path}: Not writable - {e}')

        if not permission_errors:
            return DiagnosticCheck('Directory Permissions', True, 'All directories have proper write permissions')
        else:
            return DiagnosticCheck(
                'Directory Permissions',
                False,
                'Some directories have permission issues',
                'Fix permissions: ' + '; '.join(permission_errors),
            )

    def _check_tws_connection(self, settings) -> DiagnosticCheck:
        """Check if TWS/Gateway is accessible"""
        try:
            from config.credentials import IBKR
        except ImportError:
            return DiagnosticCheck(
                'TWS Connection',
                False,
                'Cannot import IBKR credentials',
                'Create config/credentials.py with IBKR configuration',
            )

        host = IBKR.get('TWS_HOST', '127.0.0.1')
        port = IBKR.get('TWS_PORT', 7497)

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            result = sock.connect_ex((host, port))
            sock.close()

            if result == 0:
                port_type = 'Paper Trading' if port in [7497, 4002] else 'Live Trading'
                return DiagnosticCheck(
                    'TWS Connection', True, f'TWS/Gateway is accessible at {host}:{port} ({port_type})'
                )
            else:
                return DiagnosticCheck(
                    'TWS Connection',
                    False,
                    f'Cannot connect to TWS/Gateway at {host}:{port}',
                    '1. Start TWS or IB Gateway\n'
                    '   2. Enable API: File > Global Configuration > API > Settings\n'
                    "   3. Check 'Enable ActiveX and Socket Clients'\n"
                    f'   4. Verify port {port} is correct for your setup',
                )

        except Exception as e:
            return DiagnosticCheck(
                'TWS Connection',
                False,
                f'Error checking TWS connection: {e}',
                'Verify TWS/Gateway is running and network settings are correct',
            )

    def _check_internet_connection(self) -> DiagnosticCheck:
        """Check if internet connection is available"""
        test_hosts = [
            ('8.8.8.8', 53),  # Google DNS
            ('1.1.1.1', 53),  # Cloudflare DNS
        ]

        for host, port in test_hosts:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex((host, port))
                sock.close()

                if result == 0:
                    return DiagnosticCheck('Internet Connection', True, 'Internet connection is available')
            except Exception:
                continue

        return DiagnosticCheck(
            'Internet Connection',
            False,
            'No internet connection detected',
            'Check your network connection. Internet access is required for market data.',
        )

    def _check_credentials(self) -> DiagnosticCheck:
        """Check if credentials are properly configured"""
        try:
            from config.credentials import IBKR
        except ImportError:
            return DiagnosticCheck(
                'Credentials',
                False,
                'Cannot import IBKR credentials',
                'Create config/credentials.py with IBKR configuration',
            )

        account_id = IBKR.get('ACCOUNT_ID')

        if not account_id or account_id == 'YOUR_ACCOUNT_ID':
            return DiagnosticCheck(
                'Credentials',
                False,
                'IBKR Account ID is not configured',
                'Set your Interactive Brokers account ID in config/credentials.py\n'
                '   Find it in TWS: Account > Account Info',
            )

        return DiagnosticCheck('Credentials', True, f'Account ID configured: {account_id[:3]}...{account_id[-3:]}')

    def _check_critical_settings(self, settings) -> DiagnosticCheck:
        """Check critical trading settings"""
        issues = []

        # Check risk per trade
        risk_per_trade = getattr(settings, 'RISK_PER_TRADE', None)
        if risk_per_trade is None or risk_per_trade <= 0:
            issues.append('RISK_PER_TRADE not set or invalid')
        elif risk_per_trade > 0.05:
            issues.append(f'RISK_PER_TRADE ({risk_per_trade:.1%}) is very high')

        # Check max daily loss
        max_daily_loss = getattr(settings, 'MAX_DAILY_LOSS', None)
        if max_daily_loss is None or max_daily_loss <= 0:
            issues.append('MAX_DAILY_LOSS not set or invalid')

        # Check instruments
        instruments = getattr(settings, 'TRADE_INSTRUMENTS', [])
        if not instruments:
            issues.append('No trading instruments configured')

        if issues:
            return DiagnosticCheck(
                'Critical Settings',
                False,
                f'Configuration issues: {"; ".join(issues)}',
                'Review and fix settings in config/settings.py',
            )

        return DiagnosticCheck('Critical Settings', True, 'All critical settings are configured')

    def print_report(self, checks: list[DiagnosticCheck] = None):
        """Print a formatted diagnostic report"""
        if checks is None:
            checks = self.checks

        print('\n' + '=' * 70)
        print(' SYSTEM DIAGNOSTICS REPORT')
        print('=' * 70 + '\n')

        passed_count = sum(1 for c in checks if c.passed)
        total_count = len(checks)

        for check in checks:
            status_icon = '✓' if check.passed else '✗'
            status_color = '\033[92m' if check.passed else '\033[91m'
            reset_color = '\033[0m'

            print(f'{status_color}{status_icon}{reset_color} {check.name:.<40} {check.message}')

            if not check.passed and check.suggestion:
                print(f'  💡 {check.suggestion}\n')

        print('\n' + '-' * 70)
        print(f'Result: {passed_count}/{total_count} checks passed')

        if passed_count == total_count:
            print('\n✓ All checks passed! System is ready to run.')
        else:
            print(f'\n✗ {total_count - passed_count} check(s) failed. Please fix the issues above before running.')

        print('=' * 70 + '\n')

        return passed_count == total_count


def run_diagnostics(settings=None, logger=None) -> bool:
    """
    Convenience function to run all diagnostics and print report

    Returns:
        True if all checks passed
    """
    diagnostics = SystemDiagnostics(logger)
    all_passed, checks = diagnostics.run_all_checks(settings)
    return diagnostics.print_report(checks)
