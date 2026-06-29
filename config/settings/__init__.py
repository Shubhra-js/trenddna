"""
Settings router — loads the correct settings module based on DJANGO_ENV.

WHY THIS FILE EXISTS:
    Python treats the settings/ directory as a package. When Django loads
    'config.settings', it runs this __init__.py. We read DJANGO_ENV from
    the environment and dynamically import the matching settings module.

INTERVIEW Q: "How do split settings work?"
    "The __init__.py acts as a router. It reads DJANGO_ENV and imports
    either development.py or production.py. Both files import * from
    base.py first, then override what's different. This follows the
    Open/Closed Principle — adding staging.py doesn't modify existing files."

COMMON MISTAKE:
    Importing from base.py here too. That would cause double-import issues.
    Only the environment-specific file should import from base.
"""
import importlib
from decouple import config

env = config("DJANGO_ENV", default="development")

# Dynamically import the environment-specific settings module
_module = importlib.import_module(f"config.settings.{env}")

# Pull all public names into this namespace so Django sees them
globals().update({
    name: getattr(_module, name)
    for name in dir(_module)
    if not name.startswith("_")
})
