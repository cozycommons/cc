"""Compatibility import for the shared Venmo preview."""
import sys
from venmo import profiles
sys.modules[__name__] = profiles
