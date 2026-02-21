from __future__ import annotations

from pathlib import Path

import typer

from tt_core.project.create_project import create_project, load_project_info

app = typer.Typer(help="t-tool local-first CLI")


def _parse_targets(default_target: str, targets_option: str | None) -> list[str]:
    targets: list[str] = [default_target]
    if targets_option:
        targets.extend(chunk.strip() for chunk in targets_option.split(","))

    deduped: list[str] = []
    seen: set[str] = set()
    for target in targets:
        if not target or target in seen:
            continue
        seen.add(target)
        deduped.append(target)
    return deduped


@app.command("create-project")
def create_project_command(
    name: str = typer.Argument(..., help="Human-readable project name."),
    slug: str | None = typer.Option(None, "--slug", help="Slug override."),
    source: str = typer.Option("en-US", "--source", help="Default source locale."),
    target: str = typer.Option("de-DE", "--target", help="Default target locale."),
    targets: str | None = typer.Option(
        None,
        "--targets",
        help="Comma-separated target locales. Default target is always included.",
    ),
    root: Path | None = typer.Option(
        None,
        "--root",
        help="Projects root path. Defaults to ./projects.",
        file_okay=False,
        resolve_path=False,
    ),
) -> None:
    """Create a local-first project folder + SQLite database."""

    parsed_targets = _parse_targets(target, targets)

    try:
        created = create_project(
            name,
            slug=slug,
            default_source_locale=source,
            default_target_locale=target,
            targets=parsed_targets,
            root=root,
        )
    except (FileExistsError, ValueError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Project created: {created.slug}")
    typer.echo(f"Path: {created.project_path}")
    typer.echo(f"Database: {created.db_path}")
    typer.echo("Next steps:")
    typer.echo(f"  tt project-info {created.slug} --root {created.root}")


@app.command("project-info")
def project_info_command(
    slug: str = typer.Argument(..., help="Project slug."),
    root: Path | None = typer.Option(
        None,
        "--root",
        help="Projects root path. Defaults to ./projects.",
        file_okay=False,
        resolve_path=False,
    ),
) -> None:
    """Show project configuration and DB schema details."""

    try:
        project = load_project_info(slug, root=root)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    locales_display = ", ".join(project.enabled_locales)

    typer.echo(f"Project: {project.name} ({project.slug})")
    typer.echo(f"Path: {project.project_path}")
    typer.echo(f"Source locale: {project.source_locale}")
    typer.echo(f"Default target locale: {project.target_locale}")
    typer.echo(f"Enabled locales: {locales_display}")
    typer.echo(f"Schema version: {project.schema_version}")


if __name__ == "__main__":
    app()
