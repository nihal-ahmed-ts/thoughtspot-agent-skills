"""Tests for the expanded Beast Mode translator and the migration report."""
from pathlib import Path

from typer.testing import CliRunner

from ts_cli.cli import app
from ts_cli.domo.functions import translate

try:
    runner = CliRunner(mix_stderr=False)
except TypeError:
    runner = CliRunner()

FIXTURES = str(Path(__file__).parent / "fixtures" / "domo")


def test_translate_deterministic_functions():
    assert translate("UPPER(`Name`)") == ("upper([Name])", False, "")
    assert translate("DATEDIFF(`delivered`, `purchased`)")[0] == "diff_days([delivered], [purchased])"
    assert translate("LENGTH(`Ticket`)")[0] == "strlen([Ticket])"


def test_translate_structural_flagged():
    # IFNULL / COALESCE need a structural rewrite -> NEEDS REVIEW, emitted verbatim
    expr, review, reason = translate("IFNULL(`a`, `b`)")
    assert review and "IFNULL" in expr
    # CASE WHEN -> flagged, unchanged
    expr2, review2, _ = translate("CASE WHEN `x` > 1 THEN 'hi' ELSE 'lo' END")
    assert review2 and "CASE" in expr2
    # window function -> flagged
    assert translate("RANK() OVER (PARTITION BY `region`)")[1] is True


def test_report_command_writes_markdown(tmp_path):
    common = ["--connection", "C", "--database", "DB", "--schema", "S"]
    r1 = runner.invoke(app, ["domo", "build-model", FIXTURES, *common,
                             "--model-name", "M", "--output-dir", str(tmp_path)])
    assert r1.exit_code == 0, r1.stdout + getattr(r1, "stderr", "")
    r2 = runner.invoke(app, ["domo", "build-liveboard", FIXTURES, "--model-name", "M",
                             "--output-dir", str(tmp_path)])
    assert r2.exit_code == 0, r2.stdout + getattr(r2, "stderr", "")
    r3 = runner.invoke(app, ["domo", "report", "--output-dir", str(tmp_path)])
    assert r3.exit_code == 0, r3.stdout + getattr(r3, "stderr", "")
    md = (tmp_path / "migration_report.md").read_text()
    assert "# Domo → ThoughtSpot Migration Report" in md
    assert "## Summary" in md
    assert "Needs review" in md
    assert "Beast Modes → Formulas" in md
    # the inferred join is flagged for review
    assert "inferred by shared column name" in md
