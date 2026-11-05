import pytest

from api_egress_entrypoint import load_runtime


def test_runtime_loader_preserves_raw_secret_values(tmp_path):
    path = tmp_path / 'runtime'
    path.write_text('# Comment\nKEY=synthetic-$literal=with spaces\nEMPTY=\n')
    assert load_runtime(path) == {'KEY': 'synthetic-$literal=with spaces', 'EMPTY': ''}


@pytest.mark.parametrize('content', ['export KEY=secret', 'KEY=one\nKEY=two', 'malformed-secret-line'])
def test_runtime_loader_rejects_ambiguous_input(tmp_path, content):
    path = tmp_path / 'runtime'
    path.write_text(content)
    with pytest.raises(ValueError):
        load_runtime(path)
