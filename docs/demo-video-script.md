# Demo video script: MCP resume matching

**Target runtime:** about 5 minutes 30 seconds  
**Format:** screen recording with voiceover  
**Recording setup:** open a terminal at the repository root, use a readable
font size, and keep the resume folder path visible. Avoid recording `.env` or
other credentials; this demo does not need an API key.

## Timed walkthrough

### 0:00–0:35 — Introduce the goal

**Show:** repository root and the `data/resumes/` folder.

**Say:** “This demo shows a resume matching agent using a filesystem MCP server.
The server publishes resume resources and standardized tools through JSON-RPC
over stdio. The agent discovers those resources, batches resume reads, and uses
a LangGraph workflow to rank candidates.”

### 0:35–1:20 — Configure and launch the MCP demo client

**Type:**

```sh
source .venv/bin/activate
export RESUME_MCP_ROOT="$PWD/data/resumes"
python mcp_demo.py
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` and set
`$env:RESUME_MCP_ROOT = "$PWD/data/resumes"`.

**Show:** initialize response with protocol version and server capabilities.

**Say:** “The demo client starts `filesystem_mcp_server.py` as a subprocess.
Initialize negotiates the MCP session. The server communicates on stdin and
stdout, so there is no HTTP port to configure.”

### 1:20–2:15 — Discover resources and tools

**Show:** `mcp_demo.py` output for resource names and tool names.

**Say:** “The client calls `resources/list` to find resumes and `tools/list` to
discover operations. The server exposes the original read, list, write, and
search operations, plus batch processing and directory watching. File access
is limited to the configured resume root.”

Pause briefly on the listed `batch_process` and `watch_directory` tools.

### 2:15–2:55 — Batch process through MCP

**Show:** the summary from the `batch_process` call: processed, succeeded,
failed, and per-file word counts.

**Say:** “Here the client calls `batch_process` for three discovered resources.
The response includes structured data and preserves per-file errors, so one
bad document does not fail the whole batch.”

### 2:55–4:35 — Run the end-to-end agent workflow

**Type:**

```sh
python matching_agent.py
```

At the prompt, enter:

```text
Find Python candidates with at least 3 years experience
```

**Show:** ranked candidates, scores, evidence, gaps, and recommendations.

**Say:** “The agent's LangGraph begins by parsing the request. It discovers
MCP resources, batch-loads resume text, then ranks candidates against the
required skill and experience threshold. The output shows the evidence behind
each result.”

Then enter:

```text
Compare the top 3 matches side by side
```

And:

```text
Generate interview questions for Carlos Mendez SRE
```

**Say:** “Follow-up turns use the current shortlist to compare candidates and
generate targeted screening prompts.”

### 4:35–5:15 — Show the missing-folder behavior

This part is optional if recording time is tight. In a second terminal, point
the demo client at an empty temporary directory, or explain the behavior
without changing the current resume folder.

**Say:** “If the configured resume directory is missing or empty, discovery
returns no resources and the agent gives a setup message instead of crashing.
The server also rejects paths outside the configured root.”

### 5:15–5:35 — Wrap up

**Show:** `docs/mcp-workflow.md` briefly.

**Say:** “This completes the MCP flow: initialize, discover, call tools, and
return a ranked report through the agent. The workflow diagram and additional
manual protocol scenarios are in the project documentation.”

## Expected result

With the included 32-resume corpus, the MCP client should discover 32 resources
and successfully read the first three in its batch. The agent should return a
ranked report and answer the comparison and interview question follow-ups.
Exact ranking order follows the resume text and deterministic scoring logic.

## Files shown in the recording

- `filesystem_mcp_server.py` — JSON-RPC MCP server, resources, and tools.
- `mcp_demo.py` — small stdio client for visible protocol discovery and calls.
- `matching_agent.py` — LangGraph workflow using MCP.
- `docs/mcp-workflow.md` — workflow diagram and manual scenarios.
