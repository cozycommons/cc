from pathlib import Path

from commons.contracts import SCENE_CONTRACT, contract_path


def test_backend_reads_the_checked_in_shared_contract():
    assert contract_path() == Path(__file__).resolve().parents[2] / "shared/commons/scene-contract-v1.json"
    assert SCENE_CONTRACT["world"]["columns"] == 16
    assert SCENE_CONTRACT["actor_views"]["-1,0"] == "back_left"
