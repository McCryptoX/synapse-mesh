import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from synapse_cli.main import cmd_doctor


def test_cli_doctor_runs_cleanly(capsys):
    cmd_doctor(api_base="https://api.synapsemesh.dev")
    captured = capsys.readouterr()
    assert "SYNAPSE-MESH AGENT ENVIRONMENT DOCTOR" in captured.out
    assert "Platform:" in captured.out
    assert "Connecting to Synapse-Mesh Node" in captured.out
