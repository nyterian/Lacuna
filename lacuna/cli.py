from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import sqlite3
from pathlib import Path

from pydantic import ValidationError
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from . import APP_NAME, __version__
from .models import ResearchProfile, ResearchRequest, RunConfig
from .specification import parse_request, request_template, example_request, input_prompt, write_specification_files, field_gap_request
from .pipeline import run_research
from .export import build_package, save_assistant_document
from .branches import topic_branch_request, branch_report, branch_svg, branch_tree, tree_lines, rich_tree

console = Console(stderr=True, theme=Theme({"accent": "bright_cyan", "muted": "grey70"}), highlight=False)


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def banner():
    console.print(Panel(f"[bold]{APP_NAME}[/bold]\n[muted]v{__version__} / local research workbench / no LLM dependency[/muted]", border_style="bright_black", padding=(1, 2)))


def ask(label, default="", required=False):
    while True:
        prompt = Text(label, style="accent")
        if default:
            prompt.append(f" [{default}]", style="muted")
        console.print(prompt, end="\n> ")
        value = input().strip() or default
        if value or not required:
            return value
        console.print("[yellow]A value is required.[/yellow]")


def ask_integer(label, default, minimum, maximum):
    while True:
        raw = ask(label, str(default))
        try:
            value = int(raw)
            if minimum <= value <= maximum:
                return value
        except ValueError:
            pass
        console.print(f"[yellow]Enter an integer from {minimum} to {maximum}.[/yellow]")


def split_terms(text):
    return [part.strip() for part in text.split("|") if part.strip()]


def guided_request() -> ResearchRequest:
    banner()
    console.print("[bold]Research specification[/bold]\nOptional fields: Enter to skip. Separate list values with |.\n")
    while True:
        title = ask("title", required=True)
        if len(title) >= 3:
            break
        console.print("[yellow]Use at least 3 characters.[/yellow]")
    while True:
        description = ask("description / research scope", required=True)
        if len(description) >= 10:
            break
        console.print("[yellow]Use at least 10 characters.[/yellow]")
    console.print("\n[bold]Concept groups[/bold]\nOne concept per group; synonyms separated by |. Blank line ends the list.")
    groups = []
    for i in range(8):
        while True:
            group = split_terms(ask(f"concept_groups[{i}]", required=not groups))
            if len(group) <= 12 and all(len(term) <= 160 for term in group):
                break
            console.print("[yellow]Use at most 12 terms of at most 160 characters.[/yellow]")
        if not group:
            break
        groups.append(group)
    fields = {}
    for name in ("questions", "population", "methods", "geography", "excluded_terms", "languages", "seed_dois"):
        fields[name] = split_terms(ask(name))
    mechanism_groups = []
    console.print("Architectural mechanisms: one group per entry, synonyms separated by |; blank ends the list.")
    for i in range(12):
        group = split_terms(ask(f"mechanism_groups[{i}]"))
        if not group:break
        mechanism_groups.append(group)
    seed_titles = split_terms(ask("seed_titles / known comparator methods or paper titles"))
    targeted_queries = split_terms(ask("targeted_queries / explicit searches"))
    raw_from = ask("year_from (blank = no lower bound)")
    year_from = int(raw_from) if raw_from else None
    year_to = ask_integer("year_to", 2026, year_from or 1500, 2100)
    while True:
        types = split_terms(ask("types", "article | conference-paper | preprint | review | dissertation"))
        if types and set(types) <= {"article", "conference-paper", "preprint", "review", "dissertation", "other"}:
            break
        console.print("[yellow]Valid types: article | conference-paper | preprint | review | dissertation | other[/yellow]")
    while True:
        raw = ask("sources (use 'none' for offline)", "openalex | crossref")
        sources = [] if raw.lower() == "none" else split_terms(raw)
        if set(sources) <= {"openalex", "crossref", "core", "oai"}:
            break
        console.print("[yellow]Valid sources: openalex | crossref | core | oai | none[/yellow]")
    config = RunConfig(sources=sources)
    config.per_source = ask_integer("per_source record cap", 150, 1, 2000)
    config.max_queries = ask_integer("max_queries", 8, 1, 30)
    config.request_budget = ask_integer("request_budget", 60, 1, 500)
    if sources:
        config.citation_rounds = ask_integer("citation_rounds", 1, 0, 2)
        config.max_downloads = ask_integer("max_downloads", 5, 0, 50)
    else:
        config.citation_rounds, config.max_downloads = 0, 0
    if "oai" in sources:
        config.oai_url = ask("oai_url", required=True)
        config.oai_set = ask("oai_set")
    pdfs = split_terms(ask("Local PDF paths"))
    records = split_terms(ask("Local CSV/JSON record paths"))
    profile = ResearchProfile(mechanism_groups=mechanism_groups, seed_titles=seed_titles, targeted_queries=targeted_queries, title=title, description=description, concept_groups=groups, year_from=year_from, year_to=year_to, types=types, **fields)
    return ResearchRequest(profile=profile, config=config, inputs={"pdfs": pdfs, "records": records})


def read_pasted_json() -> ResearchRequest:
    if sys.stdin.isatty():
        return read_terminal_json()
    console.print("[bold]Paste request JSON[/bold]\nPaste the object returned by your assistant. Input is accepted as soon as valid JSON is complete.\nType END on its own line to validate incomplete input; Ctrl+C cancels.\n")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "END":
            break
        lines.append(line)
        candidate = "\n".join(lines).strip()
        if len(candidate.encode()) > 1_000_000:
            raise ValueError("Request JSON exceeds the 1 MB limit.")
        # If a Markdown fence was pasted, wait for the closing fence.
        if candidate.startswith("```") and (len(lines) < 3 or lines[-1].strip() != "```"):
            continue
        try:
            return parse_request(candidate)
        except json.JSONDecodeError:
            continue
        except ValidationError:
            # Syntactically complete input should show schema errors immediately.
            raise
    return parse_request("\n".join(lines))


def read_terminal_json() -> ResearchRequest:
    """Raw-mode, bracketed-paste editor; never uses the OS canonical line buffer."""
    from prompt_toolkit import prompt
    from prompt_toolkit.key_binding import KeyBindings

    console.print("[bold]Paste request JSON[/bold]\nPaste the entire JSON, then press Enter to submit. Long lines and multiline paste are supported.\nIncomplete JSON: Enter adds a line. Ctrl+D submits for validation; Ctrl+C cancels.\n")
    bindings = KeyBindings()

    @bindings.add("enter")
    def submit_or_newline(event):
        text = event.current_buffer.text
        candidate = text.strip()
        forced = candidate.endswith("\nEND") or candidate == "END"
        if forced:
            event.app.exit(result=candidate.rsplit("END", 1)[0].rstrip())
            return
        try:
            parse_request(candidate)
        except json.JSONDecodeError:
            event.current_buffer.insert_text("\n")
            return
        except (ValidationError, ValueError):
            # Submit complete-but-invalid input so the normal validator can explain it.
            pass
        event.app.exit(result=text)

    @bindings.add("c-d")
    def submit_for_validation(event):
        event.app.exit(result=event.current_buffer.text)

    text = prompt("json> ", multiline=True, prompt_continuation="...   ", key_bindings=bindings)
    return parse_request(text)


def read_request(path: str) -> tuple[ResearchRequest, Path]:
    if path == "-":
        return parse_request(sys.stdin.read()), Path.cwd()
    source = Path(path).expanduser().resolve()
    return parse_request(source.read_text(encoding="utf-8")), source.parent


def resolve_inputs(request: ResearchRequest, base: Path) -> ResearchRequest:
    data = request.model_dump()
    for kind in ("pdfs", "records"):
        data["inputs"][kind] = [str((Path(raw).expanduser() if Path(raw).expanduser().is_absolute() else base / Path(raw).expanduser()).resolve())
                                for raw in data["inputs"][kind]]
    return ResearchRequest.model_validate(data)


def save_json(path: Path, request: ResearchRequest, force=False):
    if path.exists() and not force:
        raise ValueError(f"File already exists: {path}. Use --force to replace it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(request.model_dump_json(indent=2) + "\n", encoding="utf-8")


def load_inputs(paths, base: Path, extensions):
    result = []
    for raw in paths:
        path = Path(raw).expanduser()
        path = path if path.is_absolute() else base / path
        if path.suffix.lower() not in extensions:
            raise ValueError(f"Unsupported input extension: {path.name}")
        if not path.is_file():
            raise ValueError(f"Input file not found: {path}")
        if path.stat().st_size > 100 * 1024 * 1024:
            raise ValueError(f"Input file exceeds 100 MB: {path.name}")
        result.append((path.name, path.read_bytes()))
    return result


def execute(request: ResearchRequest, *, base=None, out=Path("data/packages"), db=Path("data/research.sqlite"), extra_pdfs=None, extra_records=None, offline=False, quiet=False, simple_ui=False):
    base = base or Path.cwd()
    out = Path(out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    request = resolve_inputs(request, base)
    request.inputs.pdfs.extend(str(Path(raw).expanduser().resolve()) for raw in (extra_pdfs or []))
    request.inputs.records.extend(str(Path(raw).expanduser().resolve()) for raw in (extra_records or []))
    config = request.config.model_copy(deep=True)
    if offline:
        config.sources, config.citation_rounds, config.max_downloads = [], 0, 0
    pdfs = load_inputs(request.inputs.pdfs, base, {".pdf"})
    records = load_inputs(request.inputs.records, base, {".csv", ".json"})
    if not config.sources and not pdfs and not records:
        raise ValueError("Offline discovery needs at least one PDF or record file.")
    if "core" in config.sources and not os.getenv("CORE_API_KEY"):
        raise ValueError("CORE_API_KEY is required when the core source is selected.")
    if "oai" in config.sources and not config.oai_url:
        raise ValueError("oai_url is required when the oai source is selected.")
    if not quiet:
        if not simple_ui:banner()
        console.print(request.profile.title, style="bold", markup=False)
    progress = Progress(SpinnerColumn(), TextColumn("{task.description}"), BarColumn(), TaskProgressColumn(), console=console, disable=quiet)
    with progress:
        task = progress.add_task("Preparing discovery", total=100)
        result = run_research(request.profile, config, pdfs=pdfs, imports=records, db_path=db,
                              openalex_key=os.getenv("OPENALEX_API_KEY", ""), core_key=os.getenv("CORE_API_KEY", ""),
                              progress=lambda fraction, message: progress.update(task, completed=fraction*100, description=message))
    assistant_path = save_assistant_document(result, out)
    save_folder = out
    out = out / "technical" / result.run_id
    out.mkdir(parents=True, exist_ok=True)
    full = out / f"lacuna_{result.run_id}.zip"
    compact = out / f"lacuna_{result.run_id}_compact.zip"
    result_path = out / f"lacuna_{result.run_id}.json"
    request_path = out / f"lacuna_{result.run_id}.request.json"
    full.write_bytes(build_package(result))
    compact.write_bytes(build_package(result, compact=True))
    result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    saved_request = request.model_copy(update={"config": config})
    save_json(request_path, saved_request)
    summary = {"status": "complete" if not result.warnings else "complete_with_notes", "run_id": result.run_id,
               "studies": len(result.studies), "coverage": result.coverage,
               "save_folder": str(save_folder),
               "artifacts": {"assistant_document": str(assistant_path), "package": str(full.resolve()), "compact_package": str(compact.resolve()),
                             "result_json": str(result_path.resolve()), "request_json": str(request_path.resolve())},
               "warnings": result.warnings}
    if config.analysis_mode == "field_gaps":
        from .export import build_gap_report
        gap_json=out/f"lacuna_{result.run_id}.field_gaps.json"
        gap_md=out/f"lacuna_{result.run_id}.field_gaps.md"
        gap_json.write_text(json.dumps([gap.model_dump() for gap in result.gap_candidates],ensure_ascii=False,indent=2),encoding="utf-8")
        gap_md.write_text(build_gap_report(result),encoding="utf-8")
        summary["gap_candidates"]=[{"id":gap.id,"category":gap.category,"statement":gap.statement,"status":gap.status,"verification_status":gap.verification_status} for gap in result.gap_candidates]
        summary["gap_analysis"]=result.gap_analysis
        summary["artifacts"].update(field_gaps_json=str(gap_json.resolve()),field_gaps_report=str(gap_md.resolve()))
    if config.analysis_mode == "topic_branches":
        branch_paths = {}
        for extension, content in {"json":json.dumps(result.topic_branches,ensure_ascii=False,indent=2), "md":branch_report(result.topic_branches), "svg":branch_svg(result.topic_branches), "txt":tree_lines(branch_tree(result.topic_branches))}.items():
            path=out/f"lacuna_{result.run_id}.topic_branches.{extension}"
            path.write_text(content,encoding="utf-8")
            branch_paths["topic_branches_"+extension]=str(path.resolve())
        summary["topic_branches"]=result.topic_branches
        summary["artifacts"].update(branch_paths)
    if not quiet:
        console.print(Text(f"\nSend this single file to your assistant:\n{assistant_path}"),style="bold green")
        console.print("Optional JSON and ZIP files are in the technical subfolder.",style="muted")
        if not simple_ui:
            table = Table(title="Discovery complete", box=None)
            table.add_column("artifact", style="accent")
            table.add_column("path")
            for name, path in summary["artifacts"].items():
                table.add_row(name, path)
            console.print(table)
        if config.analysis_mode != "topic_branches":
            console.print(f"[muted]{len(result.studies)} records. Proximity is not a novelty probability.[/muted]")
        if config.analysis_mode == "field_gaps":
            console.print(f"\n{len(result.gap_candidates)} author-reported field-gap candidates; current openness is unverified.",style="bold")
            for gap in result.gap_candidates[:8]:
                console.print(Text(f"{gap.id} / {gap.category}: {gap.statement}"))
        if config.analysis_mode == "topic_branches":
            for i, placement in enumerate(result.topic_branches.get("placements", [])):
                console.print(Text(f"\nPlacement {i+1} · {placement['supporting_work_count']} sampled publications"),style="bold")
                console.print(rich_tree(result.topic_branches,i))
            console.print(result.topic_branches.get("note", ""),style="muted",markup=False)
        for warning in result.warnings:
            console.print(warning, style="yellow", markup=False)
    return summary


def web(port=8501):
    app = Path(__file__).resolve().parents[1] / "app.py"
    if not app.is_file():
        raise ValueError("Web entry point is missing. Run from the source checkout or install this project in editable mode.")
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app), "--server.address", "127.0.0.1", "--server.port", str(port), "--browser.gatherUsageStats", "false"], cwd=str(app.parent))


def interactive_menu():
    from .terminal_ui import run_workbench
    return run_workbench()


def parser_for_cli():
    parser = argparse.ArgumentParser(prog="lacuna", description=APP_NAME)
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    commands = parser.add_subparsers(dest="command")
    template = commands.add_parser("template", help="Print JSON, its schema, or an AI input prompt")
    format_group = template.add_mutually_exclusive_group()
    format_group.add_argument("--prompt", action="store_true")
    format_group.add_argument("--schema", action="store_true")
    format_group.add_argument("--example", action="store_true")
    template.add_argument("--out", type=Path)
    template.add_argument("--force", action="store_true")
    init = commands.add_parser("init", help="Write template, example, schema, and AI input prompt")
    init.add_argument("--dir", type=Path, default=Path("specs"))
    init.add_argument("--force", action="store_true")
    validate = commands.add_parser("validate", help="Validate and normalize a request JSON file; use - for stdin")
    validate.add_argument("request")
    wizard = commands.add_parser("wizard", help="Collect fields interactively")
    wizard.add_argument("--out", type=Path)
    wizard.add_argument("--force", action="store_true")
    wizard.add_argument("--run", action="store_true")
    paste = commands.add_parser("paste", help="Paste a complete request JSON into the terminal")
    paste.add_argument("--out", type=Path)
    paste.add_argument("--force", action="store_true")
    paste.add_argument("--run", action="store_true")
    run = commands.add_parser("run", help="Run a request file or read JSON from stdin (-)")
    run.add_argument("request")
    run.add_argument("--config", type=Path, help="Optional config override; also accepts legacy profile-only JSON")
    run.add_argument("--pdf", action="append", default=[])
    run.add_argument("--records", action="append", default=[])
    run.add_argument("--offline", action="store_true")
    run.add_argument("--out", type=Path, default=Path("data/packages"))
    run.add_argument("--db", type=Path, default=Path("data/research.sqlite"))
    run.add_argument("--quiet", action="store_true", help="Suppress terminal progress; stdout remains JSON")
    browser = commands.add_parser("web", help="Run the local web interface")
    browser.add_argument("--port", type=int, default=8501)
    branches = commands.add_parser("branches", help="Map a specific topic into a source-backed research tree")
    branches.add_argument("topic")
    branches.add_argument("--matches", type=int, default=3, help="Maximum alternative placements (1–5)")
    branches.add_argument("--neighbors", type=int, default=4, help="Neighboring topics per placement (0–12)")
    branches.add_argument("--sample", type=int, default=20, help="Publication sample limit (1–100)")
    branches.add_argument("--out", type=Path, default=Path("data/packages"))
    branches.add_argument("--db", type=Path, default=Path("data/research.sqlite"))
    branches.add_argument("--quiet", action="store_true", help="Only emit JSON to stdout; omit terminal tree on stderr")
    gaps = commands.add_parser("gaps", help="Find author-reported limitations and future work in theses about a topic")
    gaps.add_argument("topic")
    gaps.add_argument("--concept", action="append", default=[], help="A concept group with synonyms separated by |; repeat for multiple groups")
    gaps.add_argument("--source", choices=["openalex","crossref","core","oai"], action="append")
    gaps.add_argument("--pdf", action="append", default=[], help="User-identified thesis PDF")
    gaps.add_argument("--records", action="append", default=[])
    gaps.add_argument("--offline", action="store_true")
    gaps.add_argument("--max-downloads", type=int, default=5)
    gaps.add_argument("--follow-up-queries", type=int, default=3)
    gaps.add_argument("--max-candidates", type=int, default=40)
    gaps.add_argument("--per-thesis", type=int, default=6)
    gaps.add_argument("--oai-url", default="")
    gaps.add_argument("--oai-set", default="")
    gaps.add_argument("--out", type=Path, default=Path("data/packages"))
    gaps.add_argument("--db", type=Path, default=Path("data/research.sqlite"))
    gaps.add_argument("--quiet", action="store_true")
    return parser


def main(argv=None):
    parser = parser_for_cli()
    argv = list(sys.argv[1:] if argv is None else argv)
    # Backward compatibility with the original positional profile invocation.
    if argv and not argv[0].startswith("-") and argv[0] not in {"template", "init", "validate", "wizard", "paste", "run", "web", "gaps", "branches"}:
        argv.insert(0, "run")
    args = parser.parse_args(argv)
    try:
        if args.command is None:
            if sys.stdin.isatty():
                return interactive_menu()
            parser.print_help()
            return 0
        if args.command == "template":
            value = input_prompt() if args.prompt else json.dumps(ResearchRequest.model_json_schema() if args.schema else example_request() if args.example else request_template(), indent=2) + "\n"
            if args.out:
                if args.out.exists() and not args.force:
                    raise ValueError("Output file exists; use --force to replace it.")
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_text(value, encoding="utf-8")
            else:
                print(value, end="")
        elif args.command == "init":
            names = ["request.template.json", "request.example.json", "request.schema.json", "INPUT_PROMPT.md"]
            if not args.force and any((args.dir/name).exists() for name in names):
                raise ValueError("Specification files already exist; use --force to replace them.")
            write_specification_files(args.dir)
            emit({"directory": str(args.dir.resolve()), "files": names})
        elif args.command == "validate":
            request, _ = read_request(args.request)
            emit(request.model_dump())
        elif args.command in {"wizard", "paste"}:
            request = guided_request() if args.command == "wizard" else read_pasted_json()
            if args.out:
                save_json(args.out, resolve_inputs(request, Path.cwd()), args.force)
            if args.run:
                emit(execute(request))
            else:
                emit(request.model_dump())
        elif args.command == "run":
            request, base = read_request(args.request)
            if args.config:
                request.config = RunConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
            emit(execute(request, base=base, out=args.out, db=args.db, extra_pdfs=args.pdf, extra_records=args.records, offline=args.offline, quiet=args.quiet))
        elif args.command == "branches":
            request=topic_branch_request(args.topic)
            request.config=RunConfig(**{**request.config.model_dump(),"branch_max_matches":args.matches,"branch_sibling_limit":args.neighbors,"branch_work_limit":args.sample})
            emit(execute(request,out=args.out,db=args.db,quiet=args.quiet))
        elif args.command == "gaps":
            request=field_gap_request(args.topic,concept_groups=[split_terms(term) for term in args.concept] or None,sources=args.source)
            request.config=RunConfig(**{**request.config.model_dump(),"max_downloads":args.max_downloads,"gap_follow_up_queries":args.follow_up_queries,"gap_max_candidates":args.max_candidates,"gap_per_study":args.per_thesis,"oai_url":args.oai_url,"oai_set":args.oai_set,"local_documents_are_theses":bool(args.pdf)})
            emit(execute(request,out=args.out,db=args.db,extra_pdfs=args.pdf,extra_records=args.records,offline=args.offline,quiet=args.quiet))
        elif args.command == "web":
            if not 1 <= args.port <= 65535:
                raise ValueError("Port must be between 1 and 65535.")
            return web(args.port)
        return 0
    except KeyboardInterrupt:
        console.print("\nCancelled.", style="yellow")
        return 130
    except (OSError, ValueError, ValidationError, EOFError) as exc:
        if isinstance(exc, ValidationError):
            detail = [{"field": ".".join(map(str, item["loc"])), "message": item["msg"]} for item in exc.errors()]
        else:
            detail = str(exc)
        emit({"status": "error", "error": detail})
        console.print("Request failed validation or could not be completed. Inspect the JSON error above.", style="red")
        return 2
    except (RuntimeError, sqlite3.Error) as exc:
        emit({"status": "error", "error": {"type": type(exc).__name__, "message": str(exc)}})
        console.print("Run failed. Inspect the JSON error and local storage.", style="red")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
