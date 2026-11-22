# MCP Resume Matching Agent

This workspace now has an MCP-based filesystem workflow. The matching agent
starts the filesystem MCP server as a child process and communicates with it
over MCP's JSON-RPC stdio transport. You normally start only the agent; the MCP
server starts automatically.

## Setup

Use Python 3.10 or newer. Create and activate a virtual environment, then
install the dependencies used by the agent and supported resume formats:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install langgraph pypdf python-docx
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

The resume corpus should be in `data/resumes/` by default. To use a different
folder, set `RESUME_MCP_ROOT` to its absolute path. The server confines all
filesystem access to this configured root.

```sh
export RESUME_MCP_ROOT="$PWD/data/resumes"
```

PowerShell equivalent:

```powershell
$env:RESUME_MCP_ROOT = "$PWD/data/resumes"
```

PDF and DOCX files are supported when their optional libraries are installed;
plain text resumes work without them. The agent uses deterministic local
matching and does not require an API key.

## Run the agent

```sh
python matching_agent.py
```

Enter a role request, for example:

```text
Find Python candidates with at least 3 years experience
```

The agent discovers resume resources from the MCP server, batch-loads their
contents, ranks candidates, and prints a report. Follow-up prompts can compare
the current leaders, explain the ranking, suggest interview questions, or
refine requirements. Type `quit` or `exit` to stop.

**The run process is different from the previous unified CLI:** `python app.py`
and its `files`, `match`, and `assistant` subcommands are not part of this
MCP-backed entry point. Start `matching_agent.py`; it launches
`filesystem_mcp_server.py` itself. Do not start a second server in another
terminal for the agent, because the server uses a dedicated stdio connection.

## Run the MCP server directly

For protocol inspection or a custom MCP client, run:

```sh
RESUME_MCP_ROOT="$PWD/data/resumes" python filesystem_mcp_server.py
```

The server reads newline-delimited JSON-RPC messages from stdin and writes
responses to stdout. It is a stdio server, not an HTTP service. A compatible
client should send `initialize`, then `notifications/initialized`, and can
discover capabilities with `resources/list`, `resources/templates/list`, and
`tools/list`. The server exposes `read_file`, `list_files`, `write_file`,
`search_in_file`, `batch_process`, and `watch_directory`.

See [docs/mcp-workflow.md](docs/mcp-workflow.md) for the agent/server diagram
and manual protocol scenarios. For a timed 5–6 minute recording walkthrough,
see [docs/demo-video-script.md](docs/demo-video-script.md); run
`python mcp_demo.py` to show MCP discovery and tool calls on screen.
