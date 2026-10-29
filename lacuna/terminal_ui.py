"""Numbered terminal workbench. Command-line subcommands retain JSON stdout."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import uuid

from pydantic import ValidationError
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / 'data' / 'terminal-settings.json'


def choose(console, title, options, default='0'):
    console.print(Panel(Text(title,style='bold'),border_style='bright_black'))
    table=Table(box=None,show_header=False,padding=(0,2),expand=True)
    table.add_column(width=3,style='bright_cyan');table.add_column(style='bold');table.add_column(ratio=2)
    for key,label,description in options:table.add_row(key,Text(label),Text(description,style='grey70'))
    console.print(table)
    from .cli import ask
    valid={row[0] for row in options}
    while True:
        value=ask('Select a number',default)
        if value in valid:return value
        console.print('Choose one of the numbers shown above.',style='yellow')


def load_folder():
    try:
        settings=json.loads(SETTINGS.read_text(encoding='utf-8'))
        value=settings.get('save_folder','') if isinstance(settings,dict) else ''
        if isinstance(value,str) and value:return Path(value).expanduser().resolve()
    except (OSError,ValueError,TypeError):pass
    return ROOT/'data'/'packages'


def change_folder(console,current):
    from .cli import ask
    console.print('Paste a folder path, or press Enter to keep the current folder.',style='grey70')
    console.print('Example: ~/Downloads/Lacuna',style='grey70')
    while True:
        raw=ask('Save folder',str(current))
        if len(raw)>1 and raw[0]==raw[-1] and raw[0] in "\"'":raw=raw[1:-1]
        folder=Path(raw).expanduser().resolve()
        try:
            folder.mkdir(parents=True,exist_ok=True)
            SETTINGS.parent.mkdir(parents=True,exist_ok=True)
            temporary=SETTINGS.with_name(SETTINGS.name+'.'+uuid.uuid4().hex+'.tmp')
            temporary.write_text(json.dumps({'save_folder':str(folder)},indent=2)+'\n',encoding='utf-8')
            temporary.replace(SETTINGS)
            console.print(Text(f'Save folder remembered: {folder}'),style='green')
            return folder
        except OSError as exc:console.print(Text(f'Cannot use this folder: {exc}'),style='yellow')


def quick_request():
    from .cli import ask,split_terms
    from .models import ResearchProfile,ResearchRequest,RunConfig
    while True:
        title=ask('Research topic / title',required=True)
        scope=ask('What do you want to compare? (scope or research question)',required=True)
        raw=ask('Keywords (optional; separate terms with |)')
        groups=[[term] for term in split_terms(raw)] if raw else [[title[:160]]]
        try:return ResearchRequest(profile=ResearchProfile(title=title,description=scope,concept_groups=groups),config=RunConfig())
        except ValidationError:
            from .cli import console
            console.print('Use a title of at least 3 characters, a scope of at least 10 characters, and up to 8 keyword groups.',style='yellow')


def help_screen(console):
    from .cli import ask
    console.print(Panel('Choose a task, enter your topic, review the settings, then select Run.\nYour assistant needs only the .assistant.md file.\nAdvanced JSON, local files and source limits remain available.',title='How to use Lacuna',border_style='bright_black'))
    table=Table(title='Command guide',show_lines=True)
    table.add_column('If you run this command',style='bright_cyan');table.add_column('This happens')
    for command,meaning in [
        ('python -m lacuna','Open this numbered workbench.'),
        ('python -m lacuna web','Start the local web interface.'),
        ('python -m lacuna gaps "online clustering"','Find attributed limitations and future work in theses.'),
        ('python -m lacuna branches "online clustering"','Draw suggested research-field paths and neighboring topics.'),
        ('python -m lacuna run request.json --out "~/Downloads/Lacuna"','Run a saved JSON request and save its assistant brief in that folder.'),
        ('python -m lacuna template --prompt','Print the prompt your assistant can use to prepare request JSON.'),
        ('python -m lacuna --help','Show every command and option.')]:table.add_row(Text(command),meaning)
    console.print(table)
    console.print('Double-click Lacuna.command on macOS, or Lacuna.bat on Windows, to open this menu.',style='grey70')
    ask('Press Enter to return')


def advanced_request(console):
    from .cli import read_pasted_json,read_request,guided_request,ask
    from .specification import input_prompt
    choice=choose(console,'Advanced tools',[
        ('1','Paste assistant JSON','Paste the complete request your assistant prepared.'),
        ('2','Load saved JSON','Run a request file already on this computer.'),
        ('3','Detailed research wizard','Set methods, dates, mechanisms, sources and all research dimensions.'),
        ('4','Get the assistant input prompt','Save or copy instructions for preparing a research JSON request.'),
        ('0','Back','Return to the main menu.')])
    if choice=='1':return read_pasted_json(),Path.cwd()
    if choice=='2':return read_request(ask('Request JSON file',required=True))
    if choice=='3':return guided_request(),Path.cwd()
    if choice=='4':
        folder=ROOT/'data';folder.mkdir(parents=True,exist_ok=True)
        path=folder/'INPUT_PROMPT.md';path.write_text(input_prompt(),encoding='utf-8')
        console.print(Text(f'Prompt saved: {path}'),style='green')
        console.print(Text(input_prompt()))
        ask('Press Enter to return')
    return None


def adjust_settings(console,request):
    from .cli import ask_integer
    from .models import RunConfig
    if request.config.analysis_mode=='topic_branches':
        request.config.branch_max_matches=ask_integer('Alternative placements',request.config.branch_max_matches,1,5)
        request.config.branch_sibling_limit=ask_integer('Neighboring topics per placement',request.config.branch_sibling_limit,0,12)
        return
    source=choose(console,'Sources',[
        ('1','Online discovery','Search OpenAlex and Crossref; add local files if desired.'),
        ('2','Local files only','Use your supplied PDFs or records without online retrieval.'),
        ('0','Keep current settings','Preserve the sources already configured.')])
    values=request.config.model_dump()
    if source=='1':values['sources']=['openalex','crossref']
    if source=='2':values.update(sources=[],max_downloads=0,citation_rounds=0)
    values['request_budget']=ask_integer('Maximum online requests',values['request_budget'],1,500)
    if values['sources']:values['max_downloads']=ask_integer('Maximum PDF downloads',values['max_downloads'],0,50)
    request.config=RunConfig(**values)


def attach_files(console,request):
    from .cli import ask,split_terms
    if request.config.analysis_mode=='topic_branches':
        console.print('Topic mapping uses the OpenAlex taxonomy. Local files are not used for this task.',style='yellow');return
    console.print('Separate paths with |. Press Enter to keep existing files.',style='grey70')
    pdfs=split_terms(ask('Local PDF paths'))
    records=split_terms(ask('Local CSV/JSON record paths'))
    request.inputs.pdfs.extend(pdfs);request.inputs.records.extend(records)
    if pdfs and request.config.analysis_mode=='field_gaps':
        confirmed=choose(console,'Identify uploaded documents',[
            ('1','These PDFs are theses','Use these documents in thesis-only gap extraction.'),
            ('2','Type is unknown','Keep them unverified; unknown PDFs are excluded from thesis gap extraction.')],default='2')
        request.config.local_documents_are_theses=confirmed=='1'


def open_folder(path):
    if sys.platform=='darwin':subprocess.Popen(['open',str(path)])
    elif os.name=='nt':os.startfile(str(path))
    else:subprocess.Popen(['xdg-open',str(path)])


def review_and_run(console,request,base,folder):
    from .cli import execute,resolve_inputs,save_json
    while True:
        detail=Text(f'Topic: {request.profile.title}\nTask: {request.config.analysis_mode}\nSources: {", ".join(request.config.sources) or "local files only"}\nLocal files: {len(request.inputs.pdfs)} PDFs, {len(request.inputs.records)} record files\nSave folder: {folder}\nOutput: one .assistant.md file; optional technical files in a subfolder.')
        console.print(Panel(detail,title='Ready to run',border_style='bright_black'))
        choice=choose(console,'Next action',[
            ('1','Run','Start the search and create your assistant brief.'),
            ('2','Change save folder','Choose and remember another output folder.'),
            ('3','Source and limit settings','Adjust online sources or retrieval limits.'),
            ('4','Attach local files','Add PDF, CSV or JSON inputs.'),
            ('0','Back','Return without running.')],default='1')
        if choice=='0':return folder
        if choice=='2':folder=change_folder(console,folder);continue
        if choice=='3':adjust_settings(console,request);continue
        if choice=='4':attach_files(console,request);continue
        replay=folder/'technical'/'requests'/f'request_{uuid.uuid4().hex[:12]}.json'
        save_json(replay,resolve_inputs(request,base))
        arguments=[sys.executable,'-m','lacuna','run',str(replay),'--out',str(folder)]
        command=subprocess.list2cmdline(arguments) if os.name=='nt' else shlex.join(arguments)
        console.print(Panel(Text(command),title='Equivalent command · reruns this saved request',border_style='bright_black'))
        summary=execute(request,base=base,out=folder,simple_ui=True)
        console.print(Panel(Text(summary['artifacts']['assistant_document']),title='Send this ONE file to your assistant',border_style='green'))
        console.print('Upload the file, or paste its contents. Its prompt and supplied evidence are already included.',style='grey70')
        while True:
            action=choose(console,'Completed',[
                ('1','Open saved folder','Show the assistant brief in your file manager.'),
                ('2','Show rerun command','Print the command for repeating this exact request.'),
                ('0','Main menu','Start another task or exit.')])
            if action=='0':return folder
            if action=='1':open_folder(folder)
            if action=='2':console.print(Text(command))


def run_workbench():
    from .cli import console,banner,ask
    from .branches import topic_branch_request
    from .specification import field_gap_request
    import sqlite3
    folder=load_folder()
    while True:
        banner()
        console.print(Text(f'Save folder: {folder}'),style='grey70')
        console.print('Type a number and press Enter. Ctrl+C cancels the current action.',style='grey70')
        try:
            choice=choose(console,'Research workbench',[
                ('1','Compare research','Enter a topic and scope; retrieve related studies and evidence.'),
                ('2','Find field gaps','Enter a field; find limitations and future work reported in theses.'),
                ('3','Map topic branches','Enter a specific topic; see its field, hierarchy and neighboring topics.'),
                ('4','Open web interface','Start the same tools in your browser at localhost.'),
                ('5','Save folder','Choose where briefs are saved; remember it for next time.'),
                ('6','Help and command guide','See what each command does and how to share your output.'),
                ('7','Advanced tools','Paste JSON, load requests or use the detailed wizard.'),
                ('0','Exit','Close the workbench.')])
            if choice=='0':return 0
            if choice=='5':folder=change_folder(console,folder);continue
            if choice=='6':help_screen(console);continue
            if choice=='4':
                from .cli import web
                console.print('The web server stays open here. Press Ctrl+C to stop it and return.',style='grey70')
                try:web()
                except KeyboardInterrupt:pass
                continue
            if choice=='1':request,base=quick_request(),Path.cwd()
            elif choice in {'2','3'}:
                while True:
                    topic=ask('Research field / topic' if choice=='2' else 'Specific research topic',required=True)
                    try:
                        request=field_gap_request(topic) if choice=='2' else topic_branch_request(topic)
                        break
                    except ValidationError:console.print('Use a topic of at least 3 characters (maximum 500).',style='yellow')
                base=Path.cwd()
            else:
                prepared=advanced_request(console)
                if prepared is None:continue
                request,base=prepared
            folder=review_and_run(console,request,base,folder)
        except KeyboardInterrupt:
            folder=load_folder()
            console.print('\nCancelled. Returning to the main menu.',style='yellow')
        except EOFError:return 0
        except (OSError,ValueError,RuntimeError,sqlite3.Error) as exc:
            folder=load_folder()
            console.print(Text(f'Could not complete this action: {exc}'),style='red')
            console.print('Check the input, folder permissions, source credentials or connection, then try again.',style='grey70')
