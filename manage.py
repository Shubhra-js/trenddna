#!/usr/bin/env python
"""
Django's command-line utility for administrative tasks.

WHY THIS FILE EXISTS:
    Entry point for all Django CLI commands (runserver, migrate, test, etc.).
    Sets DJANGO_SETTINGS_MODULE so Django knows which settings to load.

INTERVIEW Q: "What does manage.py do?"
    "It's a thin wrapper around django-admin that sets the settings module
    environment variable. Every Django command — migrations, runserver,
    shell — goes through this file."
"""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
