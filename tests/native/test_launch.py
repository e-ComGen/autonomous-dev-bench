from tools.launch import command_name
from tools.prepare_ab import selected_backend


def test_flag_only_launch_is_the_default_real_ab_path():
    assert command_name([]) == "ab"
    assert command_name(["--backend", "native"]) == "ab"
    assert command_name(["test", "--offline"]) == "test"
    assert selected_backend(["--backend=native"]) == "native"
