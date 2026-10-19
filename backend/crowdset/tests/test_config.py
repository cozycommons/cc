from crowdset.config import env
from crowdset.hosting import HostedAccess
from crowdset.limits import Limits


def test_legacy_deployment_settings_remain_hosted_and_capped(monkeypatch, tmp_path):
    values = {'ORIGIN': 'https://commons.example', 'AUTH_URL': 'https://example.supabase.co',
              'AUTH_KEY': 'sb_publishable_test', 'DATA_DIR': str(tmp_path),
              'STORAGE_PROVIDER': 'r2', 'MAX_RECORDINGS': '64'}
    for name, value in values.items():
        monkeypatch.delenv('CROWDSET_' + name, raising=False)
        monkeypatch.setenv('CROWD_SET_' + name, value)
    hosted = HostedAccess()
    assert hosted.origin == values['ORIGIN'] and hosted.root == str(tmp_path)
    assert hosted.url == values['AUTH_URL'] and hosted.key == values['AUTH_KEY']
    limits = Limits.environment()
    assert limits.free_tier and limits.original_bytes == 8_000_000_000
    assert limits.recordings == 64
    monkeypatch.setenv('CROWDSET_MAX_RECORDINGS', '100')
    assert Limits.environment().recordings == 100
    monkeypatch.setenv('CROWDSET_ORIGIN', 'https://new.example')
    assert HostedAccess().origin == 'https://new.example'


def test_explicit_new_setting_wins_even_when_empty(monkeypatch):
    monkeypatch.setenv('CROWD_SET_STORAGE_PROVIDER', 'r2')
    monkeypatch.setenv('CROWDSET_STORAGE_PROVIDER', '')
    assert env('CROWDSET_STORAGE_PROVIDER') == ''
