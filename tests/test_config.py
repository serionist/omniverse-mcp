"""The server's flags and environment: defaults, overrides, and what it refuses."""

import pytest

from omniverse_mcp.config import parse_args


def test_defaults():
    args = parse_args([], {})
    assert (args.host, args.port, args.output_dir) == ("127.0.0.1", 8211, "")


def test_environment_sets_the_defaults():
    env = {"OMNIVERSE_MCP_HOST": "kit-box", "OMNIVERSE_MCP_PORT": "9000", "OMNIVERSE_MCP_OUTPUT_DIR": "out"}
    args = parse_args([], env)
    assert (args.host, args.port, args.output_dir) == ("kit-box", 9000, "out")


def test_flags_win_over_the_environment():
    env = {"OMNIVERSE_MCP_HOST": "kit-box", "OMNIVERSE_MCP_PORT": "9000"}
    args = parse_args(["--host", "10.0.0.2", "--port=9100", "--output-dir", "o"], env)
    assert (args.host, args.port, args.output_dir) == ("10.0.0.2", 9100, "o")


def test_empty_variables_count_as_unset():
    # An MCP client expands an unset ${VAR} in its config to "".
    env = {"OMNIVERSE_MCP_HOST": "", "OMNIVERSE_MCP_PORT": "", "OMNIVERSE_MCP_OUTPUT_DIR": ""}
    args = parse_args([], env)
    assert (args.host, args.port, args.output_dir) == ("127.0.0.1", 8211, "")


def test_a_bad_port_in_the_environment_is_an_error(capsys):
    with pytest.raises(SystemExit) as exited:
        parse_args([], {"OMNIVERSE_MCP_PORT": "eighty"})
    assert exited.value.code == 2
    assert "OMNIVERSE_MCP_PORT must be a port number, not 'eighty'" in capsys.readouterr().err


def test_an_unknown_flag_is_an_error(capsys):
    with pytest.raises(SystemExit) as exited:
        parse_args(["--hots", "x"], {})
    assert exited.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--isaac-port", "9000"], "--isaac-port was renamed --port"),
        (["--isaac-host=10.0.0.2"], "--isaac-host was renamed --host"),
    ],
)
def test_a_flag_from_before_the_rename_says_what_replaced_it(argv, message, capsys):
    with pytest.raises(SystemExit) as exited:
        parse_args(argv, {})
    assert exited.value.code == 2
    assert message in capsys.readouterr().err


def test_the_extension_command_takes_install_or_path():
    assert (parse_args(["extension", "install"], {}).command, parse_args(["extension", "path"], {}).action) == (
        "extension",
        "path",
    )
    assert parse_args([], {}).command is None


def test_the_extension_command_refuses_another_action(capsys):
    with pytest.raises(SystemExit) as exited:
        parse_args(["extension", "remove"], {})
    assert exited.value.code == 2
    assert "invalid choice: 'remove'" in capsys.readouterr().err


def test_the_extension_command_does_not_read_the_port():
    # Only the server talks to Kit: a bad port in the environment doesn't stop an install.
    assert parse_args(["extension", "install"], {"OMNIVERSE_MCP_PORT": "eighty"}).action == "install"
