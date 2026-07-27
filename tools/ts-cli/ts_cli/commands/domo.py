"""ts domo — Domo → ThoughtSpot offline file transforms.

All I/O lives here; the ts_cli.domo package is pure (dicts in/out).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(help="Domo → ThoughtSpot conversion (offline bundle / live).")


@app.command("parse")
def parse_cmd(
    input_dir: str = typer.Argument(..., help="Directory of exported Domo JSON"),
    output_file: str = typer.Option(..., "--output", "-o", help="Output inventory JSON path"),
    mode: str = typer.Option("offline", "--mode", help="offline | domo-cloud"),
) -> None:
    from ts_cli.domo.parsing import build_inventory, parse_app

    app_ir = parse_app(input_dir, mode=mode)
    inv = build_inventory(app_ir)
    out = Path(output_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(inv, indent=2))
    typer.echo(f"Parsed {inv['counts']} → {output_file}", err=True)
    print(json.dumps(inv["counts"], indent=2))


@app.command("build-model")
def build_model_cmd(
    input_dir: str = typer.Argument(..., help="Directory of exported Domo JSON"),
    connection_name: str = typer.Option(..., "--connection", "-c", help="TS connection name"),
    database: str = typer.Option(..., "--database", help="Warehouse database"),
    schema: str = typer.Option(..., "--schema", help="Warehouse schema"),
    model_name: Optional[str] = typer.Option(None, "--model-name", "-m"),
    output_dir: str = typer.Option("out", "--output-dir", "-o"),
    mode: str = typer.Option("offline", "--mode"),
) -> None:
    from ts_cli.domo.build_model import build_model_artifacts
    from ts_cli.domo.parsing import parse_app
    from ts_cli.tml_common import dump_tml_yaml

    app_ir = parse_app(input_dir, mode=mode)
    arts = build_model_artifacts(
        app_ir, connection_name=connection_name, db=database, schema=schema,
        model_name=model_name)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for fn, doc in arts["tables"].items():
        (out / fn).write_text(dump_tml_yaml(doc))
    (out / arts["model"]["filename"]).write_text(dump_tml_yaml(arts["model"]["tml"]))
    (out / "mapping.json").write_text(json.dumps(arts["mapping"], indent=2))
    typer.echo(f"Model artifacts → {output_dir}", err=True)
    print(json.dumps({"counts": arts["counts"], "model": arts["model"]["filename"]}, indent=2))


@app.command("build-liveboard")
def build_liveboard_cmd(
    input_dir: str = typer.Argument(..., help="Directory of exported Domo JSON"),
    model_name: str = typer.Option(..., "--model-name", "-m", help="TS Model name to bind to"),
    model_fqn: Optional[str] = typer.Option(None, "--model-fqn", help="TS Model GUID (optional)"),
    report_name: Optional[str] = typer.Option(None, "--report-name"),
    output_dir: str = typer.Option("out", "--output-dir", "-o"),
    mode: str = typer.Option("offline", "--mode"),
) -> None:
    from ts_cli.domo.answers import build_liveboard_artifacts
    from ts_cli.domo.parsing import parse_app
    from ts_cli.tml_common import dump_tml_yaml

    app_ir = parse_app(input_dir, mode=mode)
    arts = build_liveboard_artifacts(
        app_ir, model_name=model_name, model_fqn=model_fqn, report_name=report_name)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / arts["liveboard"]["filename"]).write_text(dump_tml_yaml(arts["liveboard"]["tml"]))
    (out / "liveboard_mapping.json").write_text(json.dumps(arts["mapping"], indent=2))
    typer.echo(f"Liveboard → {output_dir}", err=True)
    print(json.dumps({"counts": arts["counts"], "liveboard": arts["liveboard"]["filename"]}, indent=2))
