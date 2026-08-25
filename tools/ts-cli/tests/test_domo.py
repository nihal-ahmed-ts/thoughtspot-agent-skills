"""Tests for the `ts domo` converter, run against tests/fixtures/domo/."""
import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from ts_cli.cli import app

try:
    runner = CliRunner(mix_stderr=False)
except TypeError:  # Click >= 8.2 removed mix_stderr
    runner = CliRunner()

FIXTURES = str(Path(__file__).parent / "fixtures" / "domo")


def test_parse_writes_inventory(tmp_path):
    out = tmp_path / "inv.json"
    result = runner.invoke(app, ["domo", "parse", FIXTURES, "--output", str(out)])
    assert result.exit_code == 0, result.stdout + getattr(result, "stderr", "")
    inv = json.loads(out.read_text())
    assert inv["counts"] == {"datasets": 2, "beast_modes": 3, "cards": 3, "pages": 1}
    assert inv["app_name"] == "Sales Overview"


def test_parse_missing_dir_is_graceful(tmp_path):
    out = tmp_path / "inv.json"
    result = runner.invoke(app, ["domo", "parse", str(tmp_path / "nope"), "--output", str(out)])
    # never crashes; emits an empty-but-valid inventory with a warning note
    assert result.exit_code == 0
    inv = json.loads(out.read_text())
    assert inv["counts"]["datasets"] == 0
    assert any(n["area"] == "parse" for n in inv["notes"])


def _build_model(tmp_path):
    result = runner.invoke(app, [
        "domo", "build-model", FIXTURES, "--connection", "Conn",
        "--database", "DB", "--schema", "SCH", "--model-name", "Sales Model",
        "--output-dir", str(tmp_path)])
    assert result.exit_code == 0, result.stdout + getattr(result, "stderr", "")
    return json.loads((tmp_path / "mapping.json").read_text())


def test_build_model_translates_beast_modes(tmp_path):
    mapping = _build_model(tmp_path)
    by_name = {f["name"]: f for f in mapping["beast_modes"]}
    assert by_name["Net Revenue"]["ts_formula"] == "sum([Revenue]) - sum([Discount])"
    assert by_name["Avg Order Value"]["ts_formula"] == \
        "sum([Revenue]) / unique count([Transaction ID])"
    assert all(f["status"] == "Migrated" for f in mapping["beast_modes"])


def test_build_model_flags_inferred_join(tmp_path):
    mapping = _build_model(tmp_path)
    assert len(mapping["joins"]) == 1
    j = mapping["joins"][0]
    assert j["on"] == "Customer ID" and j["inferred"] and j["status"] == "NEEDS REVIEW"


def test_build_model_tml_invariants(tmp_path):
    _build_model(tmp_path)
    # every table column carries db_column_name; connection uses name: only
    for tbl_file in tmp_path.glob("*.table.tml"):
        doc = yaml.safe_load(tbl_file.read_text())["table"]
        assert "fqn" not in doc["connection"]
        for col in doc["columns"]:
            assert col["db_column_name"], f"missing db_column_name in {tbl_file.name}"
    # model: formula columns pair to formulas[] by id
    model_doc = yaml.safe_load((tmp_path / "Sales_Model.model.tml").read_text())["model"]
    formula_ids = {f["id"] for f in model_doc["formulas"]}
    for col in model_doc["columns"]:
        if "formula_id" in col:
            assert col["formula_id"] in formula_ids


def test_build_liveboard_chart_types(tmp_path):
    result = runner.invoke(app, [
        "domo", "build-liveboard", FIXTURES, "--model-name", "Sales Model",
        "--report-name", "Sales Overview", "--output-dir", str(tmp_path)])
    assert result.exit_code == 0, result.stdout + getattr(result, "stderr", "")
    lb = yaml.safe_load((tmp_path / "Sales_Overview.liveboard.tml").read_text())["liveboard"]
    vizzes = {v["answer"]["name"]: v["answer"] for v in lb["visualizations"]}
    assert vizzes["Net Revenue"]["chart"]["type"] == "KPI"
    assert vizzes["Revenue by Region"]["chart"]["type"] == "BAR"
    # table card -> TABLE_MODE (no chart block)
    assert vizzes["Sales Rep Performance"]["display_mode"] == "TABLE_MODE"
    assert "chart" not in vizzes["Sales Rep Performance"]
    # page card order preserved, all three resolved
    assert len(lb["visualizations"]) == 3
