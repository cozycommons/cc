import pytest

from app_runtime.core import Store, allowed, hostname, proxy_config, slug


@pytest.mark.parametrize(
    "name",
    [
        "admin",
        "api",
        "auth",
        "www",
        "default",
        "a--b",
        "../app",
        "x\n}",
        "with.dot",
        "-start",
        "end-",
        "UPPER",
        "a" * 31,
    ],
)
def test_reject_reserved_and_config_injection(name):
    with pytest.raises(ValueError):
        slug(name)


def test_hosts_cannot_collide():
    assert hostname("trip", "default") == "trip.localhost"
    assert hostname("trip", "map") == "trip--map.localhost"
    assert len(hostname("a" * 30, "b" * 30).split(".")[0]) <= 63


def test_permissions_and_app_capability():
    app = {
        "name": "trip",
        "members": {"alice": "owner", "bob": "contributor", "eve": "viewer"},
    }
    assert allowed(app, "bob", "contributor")
    assert not allowed(app, "bob", "owner")
    assert not allowed(app, "eve", "contributor")
    assert not allowed(app, "stranger")
    assert allowed(app, "app:trip", "contributor")
    assert not allowed(app, "app:trip", "owner")
    assert not allowed(app, "app:other")


def test_every_route_authorizes_and_strips_platform_credentials():
    config = proxy_config(
        [
            {
                "name": "trip",
                "routes": {
                    "default": {"port": 3000, "public": True},
                    "map": {"port": 8080, "public": False},
                },
            }
        ]
    )
    assert config.count("forward_auth manager:9000") == 2
    assert config.count("header_up -Authorization") == 2
    assert config.count("header_up -Upgrade") == 2
    assert config.count("header_up -Connection") == 2
    assert "cc-apps-local-trip:8080" in config
    assert "admin localhost:2019" in config


def test_registry_survives_reopen(tmp_path):
    path = tmp_path / "db.sqlite3"
    Store(path).put({"name": "trip", "members": {"alice": "owner"}})
    assert Store(path).get("trip")["members"] == {"alice": "owner"}
