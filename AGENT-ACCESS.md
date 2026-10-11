# FX Studio — local agent access

FX Studio supports local MCP clients and local agents that can run commands. Sound generation uses the running desktop service and its single queue. No payment activation, account, cloud gateway, public endpoint or additional model installation is required.

## Install

1. Install and open FX Studio. In **Setup → Local agents**, enable access and choose the export folder.
2. Choose **Install skill…**, then **Codex** for direct installation or **Choose skills folder…** for another local agent. The app installs `fx-studio/SKILL.md` and a small standard-library helper. Existing changed skill files are backed up in the app data's `skill-backups` folder. Alternatively, **Save agent kit…** creates a ZIP you can unpack there. Start a new agent conversation to discover the skill.
3. MCP is optional. **Copy MCP config** provides the standard `mcpServers` JSON recipe; **Copy Codex config** provides a TOML block. Add it to the client's MCP settings and reload that server. The adapter uses **stdio** and the app's bundled Python. It reads its local credential itself; no token belongs in a client configuration or prompt.

For Codex, the skill directory is `~/.codex/skills`. The server configuration is shared by Codex desktop and CLI in `~/.codex/config.toml`. For agents with different installation conventions, choose their documented skills folder; agents without a skill system can use the copied guide and command-line interface directly. The ZIP's MCP recipes are specific to the exporting computer's install paths.

On Apple Silicon macOS, the bundled CLI is:

```sh
"/Applications/FX Studio.app/Contents/Resources/app/python/bin/python3" -s -B \
  "/Applications/FX Studio.app/Contents/Resources/app/backend/agent_cli.py" status
```

On Windows x64, use `<install folder>\resources\app\python\python.exe` and `<install folder>\resources\app\backend\agent_cli.py`. A custom app location can be supplied as `FX_STUDIO_APP`. A valid enabled local credential is needed before the client can start a closed app. First-launch downloads remain visible in the desktop app; generation waits for model readiness.

## Tools and workflow

The MCP server exposes 20 tools: `get_status`, `get_prompt_guide`, `generate_sound`, `create_sound_pack`, `get_job`, `get_pack`, `cancel_job`, `cancel_pack`, `search_sounds`, `search_library`, `get_sound`, `trim_sound`, `set_favorite`, `export_sound`, `export_pack`, `list_projects`, `create_project`, `get_project`, `update_project`, `set_project_sound`. The English guide is also available as `fxstudio://guide`.

Creation returns job/pack ids immediately. Poll every 2–5 seconds rather than holding a tool call open for the full generation. States are `queued`, `running`, `cancelling`, `completed`, `failed`, `cancelled`, `interrupted`; a pack with terminal failures or cancellations is `incomplete`. Jobs appear in the desktop queue with **Agent** and their results are saved in its history. The serial worker releases model memory between variants. There is no generation timeout.

For a game or named edit, find it with `list_projects` or create it with `create_project(name, description)`. Creation is retry-safe by trimmed, case-insensitive name; it returns the existing project without overwriting its description. Pass the returned `project_id` to each sound or pack. The app’s current selection does not implicitly set the agent target. `get_project` returns metadata, paginated sounds and project jobs/errors. All finished variants are added automatically; project associations survive restarts and renaming. The desktop **Projects** view supports review with Play/Previous/Next, trim, favorite and export. `set_project_sound` adds/removes existing generated or library assets without copying or deleting audio. A sound can belong to multiple projects; trims and favorites are shared.

Create packs with 1–8 assets; each has a distinct filename-safe `asset_name` and a prompt. The whole pack is validated and stored atomically. The app has eight active queue slots, including desktop jobs; larger projects need batches. Every creation requires a unique `request_id`. Repeating it with identical input retrieves the same ids, including after app restart. Reusing it with different input returns a conflict.

Use concrete English prompts from the [bundled skill](ui/skills/fx-studio/SKILL.md). Start at eight steps / CFG 1; select from variants and audition rather than claiming guaranteed quality. `get_sound.audio_path` points to the saved crop. Search result `path` points to the original. Crop bounds are measured in the original audio and apply the same 5 ms fades as desktop trimming.

Exports write only inside the folder chosen in Setup, with relative subfolders and safe filenames. WAV/MP3 exports use the saved crop; existing files are preserved. A completed pack exports all variants plus `manifest.json`, with paths, prompts, settings, seeds, trims and source/license/reference metadata and project membership. An incomplete pack can export its finished sounds individually. Historical removed models retain their original model identity. The external library is read-only and retains documented or unknown license status.

## HTTP API and CLI

HTTP base: `http://127.0.0.1:3921/agent/v1`. Send `Authorization: Bearer <local key>` and JSON objects on POST. The advanced API controls in Setup can copy or reset the key. The desktop's session token/cookie cannot authenticate agent routes, and the agent key cannot change desktop access/export settings. Host and Origin restrictions remain active; no cross-origin browser API is enabled.

| Method | Route | Input |
| --- | --- | --- |
| GET | `/status`, `/guide` | None |
| GET | `/jobs/{id}`, `/packs/{id}`, `/sounds/{id}` | Saved id |
| GET | `/history`, `/library` | `q`, `favorites=1`, `offset`, `limit=1..100`; library also `category` |
| GET | `/projects` | `q` searches name/description |
| GET | `/projects/{id}` | `q`, `offset`, `limit=1..100`; metadata, sounds and project jobs |
| POST | `/projects` | `name`, optional `description`; reuse existing name on retry |
| POST | `/project-update` | `project_id`, optional `name`, `description` |
| POST | `/project-sound` | `project_id`, `sound_id`, `included: true/false` |
| GET | `/audio/{sound_id}` | Current crop; supports byte ranges |
| POST | `/generate` | `request_id`, `settings` (optional `project_id` inside settings) |
| POST | `/packs` | `request_id`, `name`, `assets`, optional `project_id` applying to all assets |
| POST | `/cancel`, `/cancel-pack` | `job_id` or `pack_id` |
| POST | `/trim` | `sound_id`, `start`, `end`, or `reset: true` |
| POST | `/favorite` | `sound_id`, `favorite: true/false` |
| POST | `/export` | `sound_id`, optional `name`, `format`, `folder` |
| POST | `/export-pack` | `pack_id`, optional `format`, `folder` |

The CLI commands are `status`, `guide`, `generate`, `pack`, `job`, `get-pack`, `sound`, `history`, `library`, `cancel`, `cancel-pack`, `trim`, `favorite`, `export`, `export-pack`, `projects`, `create-project`, `project`, `update-project`, `project-sound`. `project` takes the returned project id. Id commands take an id; other commands take a JSON object argument or `-` to read it from stdin. Results are JSON; errors return a nonzero process exit. See the skill for complete examples. There is no separate CLI or MCP process calculating audio.

The owner-private `agent-access.json` lives alongside the app's database in its own data directory. New installations start with access off. Disable access in Setup to reject subsequent agent calls; this does not cancel previously accepted jobs. Resetting the key invalidates manually copied keys; the bundled clients read the new key on every request. API credentials and generated sounds are excluded from Git and from the agent kit.

## Validation and platform limits

Automated tests exercise the actual stdio protocol with modern discovery and the legacy initialize handshake, the HTTP authentication boundary, async creation, atomic packs, persistent duplicate suppression, subprocess failure/cancellation/recovery, crop/export frame counts and fades, filename/path restrictions and original library provenance. Test fixtures write only temporary audio; they are not shipped as generation results.

The installed Mac runtime receives a real Medium/MCP acceptance check. Windows uses the same standard-library client/HTTP/queue code and a prepared native build; Windows runtime, installer and MCP launch still need a native Windows acceptance run. No Windows binary has been claimed as tested or released.
