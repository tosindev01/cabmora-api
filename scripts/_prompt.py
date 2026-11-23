"""Shared password prompt for the bootstrap scripts.

Lives here rather than in either script so `create_admin` and `set_password`
cannot drift on the one rule that matters: the password is read from a prompt,
never taken as an argument. Anything on the command line lands in shell history
and in `ps` output for every user on the box.
"""

import getpass
import sys

MIN_PASSWORD_LENGTH = 8


def read_password() -> str:
    first = getpass.getpass("Password: ")
    if len(first) < MIN_PASSWORD_LENGTH:
        sys.exit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if first != getpass.getpass("Confirm password: "):
        sys.exit("Passwords do not match.")
    return first
