from typer.testing import CliRunner

from dome_triage.cli import app

runner = CliRunner()


def test_top_level_help_lists_all_subcommand_groups():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for group in ("ingest", "dedupe", "fulltext", "keywords", "curate", "pipeline"):
        assert group in result.output


def test_ingest_help_lists_expected_commands():
    result = runner.invoke(app, ["ingest", "--help"])
    assert result.exit_code == 0
    assert "load-sources" in result.output
    assert "enrich-metadata" in result.output


def test_pipeline_run_rejects_unknown_step():
    result = runner.invoke(app, ["pipeline", "run", "--steps", "not-a-real-step"])
    assert result.exit_code != 0
