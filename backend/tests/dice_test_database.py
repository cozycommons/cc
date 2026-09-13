import re
from collections.abc import Mapping
from urllib.parse import urlparse


LOCAL_DATABASE = re.compile(r"^dummi_regression_\d+_\d+$")


def is_isolated_dice_test_database(environment: Mapping[str, str]) -> bool:
    try:
        parsed = urlparse(environment.get("DB_URL", ""))
        database = parsed.path.removeprefix("/")
        local_harness = (
            environment.get("DICE_TEST_DATABASE") == "1"
            and parsed.scheme == "postgresql"
            and not parsed.query
            and not parsed.fragment
            and parsed.hostname == "127.0.0.1"
            and parsed.port in {54322, 55432}
            and (LOCAL_DATABASE.fullmatch(database) is not None or (parsed.port == 55432 and database == "dummi_test"))
        )
        ci_database = (
            environment.get("GITHUB_ACTIONS") == "true"
            and parsed.scheme == "postgresql"
            and not parsed.query
            and not parsed.fragment
            and parsed.hostname == "localhost"
            and parsed.port == 5432
            and database == "dummi_test"
        )
    except ValueError:
        return False
    return local_harness or ci_database
