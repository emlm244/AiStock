# Third-Party License Summary

This document summarizes the licenses of third-party dependencies used in AIStock Robot.

## Production Dependencies

### Permissive Open Source (BSD/MIT/Apache)
All production dependencies use permissive open-source licenses compatible with commercial use:

- **BSD-3-Clause**: pandas, numpy, scikit-learn, joblib, python-dotenv, circuitbreaker, scikit-optimize, colorama
- **MIT**: pytz, SQLAlchemy, flask
- **Apache-2.0**: cryptography, prometheus-client, tenacity

### Interactive Brokers API
- **ibapi**: Proprietary license from Interactive Brokers
  - Must be obtained separately from https://interactivebrokers.github.io/
  - Subject to IB's API license agreement
  - Free for use with IB accounts

### Optional Dependencies (Not included by default)
- **psycopg2-binary**: LGPL (PostgreSQL adapter)
  - Only required if using PostgreSQL backend
  - LGPL allows linking in proprietary software

## Development Dependencies

All development dependencies use permissive licenses (MIT/BSD/Apache/MPL-2.0).

## License Compatibility

All included dependencies are compatible with:
- ✅ Commercial use
- ✅ Modification
- ✅ Distribution
- ✅ Private use

## Full License Texts

Full license texts for each dependency can be found in their respective package distributions or at:
- PyPI package pages: https://pypi.org/project/{package-name}/
- GitHub repositories linked from PyPI

## Disclaimer

This summary is provided for convenience. Always verify license terms directly from the source.
The maintainers of AIStock Robot are not responsible for license compliance of dependencies.
