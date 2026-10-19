import os


def env(name, default=None):
    """Prefer Crowdset settings while accepting existing deployment names."""
    return os.environ.get(name, os.environ.get(name.replace('CROWDSET_', 'CROWD_SET_', 1), default))
