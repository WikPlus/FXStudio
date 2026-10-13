---
name: fx-studio
description: Create, organize by project, trim and export local sound effects or asset packs with FX Studio and Stable Audio 3 Medium. Use MCP or the bundled CLI for game projects, video editing, foley, transitions and ambience, with concrete English prompts.
---

# FX Studio sound effects

## Operate the app

The model is **Stable Audio 3 Medium**, using MLX on Apple Silicon macOS or the official LiteRT CPU runtime on Windows x64. All work is local. New sounds use **Generate → Format**: **OGG Vorbis (quality 5, initial default)**, **WAV (lossless)** or **MP3 (320 kbps)**, at 44.1 kHz stereo. The selection persists and is returned as `generation_format` by `get_status`. Compressed storage removes the engine’s temporary WAV after a successful save. **Regenerate** preserves the sound’s format. Existing sounds remain usable in their original format. Windows generation can take longer; do not impose a short generation timeout or promise matching seeds across runtimes.

## Connect and run an agent job

The user must enable **Setup → Local agents → Enable agent access** once. MCP and the CLI then start the installed app if necessary. Use the existing app queue; never launch another model worker or accept license terms on the user's behalf. A missing model downloads through the app's visible setup flow; check readiness before queuing.

Prefer the **FX Studio MCP tools** when available:

1. Call `get_status` and `get_prompt_guide`. Check model readiness and the configured export folder.
   For a game, video or other named project, follow the project workflow below before generating.
2. Call `generate_sound` for one asset, or `create_sound_pack` for **1–8 separate assets**, each with a distinct `asset_name`. Larger projects need batches after jobs finish. Asset names use letters, numbers, underscores and hyphens. Set `format="ogg"`, `"wav"` or `"mp3"` on `generate_sound` or each pack asset when the user requests a format; omit it to use the app’s saved Format selection. Choose WAV at generation time when lossless source audio is required.
3. Give each creation a unique `request_id`. Reuse the **same id and settings** after a transport error to avoid duplicate generation. Use a new id when revising a prompt or settings.
4. Creation returns immediately. Poll `get_job` / `get_pack` every **2–5 seconds** until `completed`, `failed`, `cancelled` or `interrupted`. Inspect real errors. `cancel_job` / `cancel_pack` stop requested work; finished variants remain saved. Never submit repeated creation calls while waiting.
5. Use `get_sound` for `audio_path`: this is the **saved crop**. Search results' `path` points to the original. Audition with your available audio tools; if you cannot hear the take, say so. Do not promise a perfect result.
6. Use `trim_sound` for seconds measured in the original clip; crops apply **5 ms fades**. `export_sound` delivers the current crop. `export_pack` delivers all variants of a completed pack with a prompt/settings/seed/license manifest. Both default to `format="ogg"` and also accept `"wav"` or `"mp3"`. OGG exports the saved crop without regenerating audio.
7. Exports stay inside the folder the user selects in **Setup**. `folder` is relative; existing files are preserved. Ask the user to change that folder in Setup when needed. Report the returned **actual paths**, retained provenance and whether you auditioned the result.

For agents with terminal access but no MCP, run the installed skill helper:

```sh
python3 <this-skill-directory>/scripts/fxstudio.py status
python3 <this-skill-directory>/scripts/fxstudio.py generate '{"request_id":"camera_take_01","settings":{"asset_name":"camera_shutter","prompt":"A DSLR camera shutter firing once. A crisp mechanical snap followed by a tiny spring click, with a compact midrange body and a very fast decay. Recorded close to the mechanism in an acoustically dead room.","seconds":1,"steps":8,"cfg":1,"variants":2}}'
python3 <this-skill-directory>/scripts/fxstudio.py job <returned-job-id>
python3 <this-skill-directory>/scripts/fxstudio.py export '{"sound_id":"<returned-sound-id>","name":"camera_shutter_01","format":"ogg"}'
```

Replace placeholders and use your shell's proper quoting. JSON may also be passed on stdin: `generate -`, `pack -`, `export -`. `pack` takes `request_id`, `name`, `assets` and optional `project_id`; `get-pack` takes its returned id. Other commands: `guide`, `sound`, `history`, `library`, `cancel`, `cancel-pack`, `trim`, `favorite`, `export-pack`, `projects`, `create-project`, `project`, `update-project`, `project-sound`, `project-deletion`, `delete-project`. Cancellation uses `{"job_id":"..."}` or `{"pack_id":"..."}`. All outputs are JSON; a nonzero exit indicates an error.

No separate Python install is required: on macOS use `/Applications/FX Studio.app/Contents/Resources/app/python/bin/python3` to run this helper, or run the adjacent `backend/agent_cli.py` directly. On Windows use `<FX Studio install folder>\resources\app\python\python.exe` and its adjacent `backend\agent_cli.py`. For custom installations set `FX_STUDIO_APP` to the `.app` path or Windows app executable. Never read, echo or copy `agent-access.json` into a prompt or repository; the client reads its private credential automatically.

## Delete a project

Only delete when the user explicitly requests deletion of that exact project. Call `preview_project_deletion(project_id)` first and inspect its counts and blocked jobs. `delete_project(project_id, confirm_name, revision)` requires the exact returned project name and revision. It permanently removes exclusive generated sounds, previous takes, crops, internal drag files and job logs. Finish or cancel affected jobs first. Sounds shared with other projects, the read-only library and files exported outside FX Studio are preserved. CLI equivalents: `project-deletion '{"project_id":"..."}'` and `delete-project '{"project_id":"...","confirm_name":"...","revision":"..."}'`. Never delete projects as routine cleanup.

## Keep a game's sounds in a project

When asked to make sounds for a game or named edit, organize them in one persistent FX Studio project:

1. Use `list_projects` to find the requested project. Match its name, not just the first search result. If it does not exist, call `create_project(name, description)`. Creation reuses a name ignoring case and does not overwrite an existing description. Keep the returned `id`; display names may be renamed with `update_project`.
2. Plan distinct assets from the game actions (for example `ui_select`, `wooden_door_close`, `player_land`). Give each asset one concrete English prompt and a suitable duration. Do not describe the entire game in one sound prompt.
3. Pass that exact **`project_id`** to every `generate_sound` and every `create_sound_pack`. A pack's top-level `project_id` applies to all assets and variants. The desktop's current selection does not set the agent's target automatically. Omitting it creates sounds in global History only.
4. Poll the returned job/pack ids. Use `get_project(project_id)` to check saved sounds and project jobs/errors, including partial results. Paginate with `offset`/`limit` when needed. Further batches use the same project id and new request ids.
5. Tell the user to open **Projects → their project** to audition every take, use **Previous sound / Next sound**, favorite good takes and trim/export them. A project is an organization group, not an export folder; use the configured export folder when delivering files.

`set_project_sound(project_id, sound_id, included=true)` adds an existing History or library sound. `included=false` removes only its association. Sounds may belong to multiple projects without copying audio; their trim and favorite state are shared. Preserve source/license data for library assets.

Example for a local game agent, using the CLI fallback (replace `<project-id>` with the returned id):

```sh
python3 <this-skill-directory>/scripts/fxstudio.py projects '{"q":"Forest game"}'
python3 <this-skill-directory>/scripts/fxstudio.py create-project '{"name":"Forest game","description":"Dry wooden foley and subtle interface sounds for the forest level."}'
python3 <this-skill-directory>/scripts/fxstudio.py pack '{"request_id":"forest_foley_01","name":"forest_foley","project_id":"<project-id>","assets":[{"asset_name":"ui_select","prompt":"A single soft synthesized UI tap. A rounded midrange tick with a delicate bright attack and a very short, smooth decay. Dry and isolated.","seconds":1,"variants":2},{"asset_name":"wooden_door_close","prompt":"A small wooden cabin door pushed shut once. A compact wooden knock followed by a short latch click, with a warm low-mid body and a quick natural decay. Recorded close in a quiet, dry room.","seconds":2,"variants":2}]}'
python3 <this-skill-directory>/scripts/fxstudio.py get-pack <returned-pack-id>
python3 <this-skill-directory>/scripts/fxstudio.py project <project-id>
```

## Operate the desktop interface

If desktop control is needed, open `/Applications/FX Studio.app` on Mac or the installed FX Studio shortcut on Windows. Agent jobs appear in the same queue and history as desktop jobs.

1. Check the model badge. Missing weights download automatically on first launch. Read the download notice; use **Pause download**, **Resume download** or **Retry download** as needed. Wait for ready before generating. Open **Setup** for missing runtime files, storage or licenses; never accept license terms for the user.
2. For a game or edit, open **Projects → New project**, enter its name and optional description, then use **Generate for this project**. Alternatively select an existing **Project** in **Generate sound**. Choose **New sound** in **Workflow** and enter one English prompt per asset. Generate a pack as separate assets rather than describing the whole edit in one prompt.
3. Set **Duration**, **Variants** and, when needed, **Advanced settings**:
   - Start with **8 sampling steps / CFG 1** unless the user chooses otherwise. More steps or higher CFG do not automatically improve quality. The **Negative prompt** has no effect at CFG 1.
   - Duration supports **0.5–30 s**, steps **1–16**. Start around **1 s for clicks**, **1–3 s for transitions**, **6–10 s for ambience**; crop the result to the actual event.
   - Try **2–4 variants** for selection. Leave **Seed** blank for new takes. Keep the same seed and change one detail at a time when comparing prompts or settings.
4. Click **Generate sound** and watch **Jobs**. Jobs run one at a time; use **Cancel** to stop. Read a failed job's error before retrying.
5. Find the result under **Your sounds**, **History** or its **Projects** entry. Use **Play sound** to audition, and favorites to retain good takes. Each sound's **Projects** menu adds/removes membership. **Generate again** restores the saved prompt/settings and original generation project; it does not start generation automatically.
   **Regenerate** starts immediately with a fresh seed and replaces that sound in the same row when ready. It keeps projects, favorites and the saved crop; failed or cancelled attempts keep the previous take. Use this desktop control when the user wants to audition another take without leaving the list.

## Prompt for clean sounds

Write a concrete English paragraph:

**Source → action and event count → audible texture and decay → recording distance and room.**

For editing accents, specify one isolated event, a close recording and a brief decay in a dry/dead room. For ambience, describe a continuous sound and its environment. Name the actual material and mechanism instead of vague words such as “premium” or “cinematic.” Avoid unrelated sources and contradictory descriptions.

FX Studio adds `TrackType: SFX,` automatically; enter only your description. This structure follows the [official Stable Audio 3 guide](https://stability.ai/guides/stable-audio-3-prompt-guide). These are original examples, not tested guarantees of perfect takes.

## English examples

Adjust the source and character to the user's edit. Suggested duration is the generated clip length, not exact event timing.

| Asset | Starting duration | Prompt |
| --- | --- | --- |
| Camera shutter | 1 s | A DSLR camera shutter firing once. A crisp mechanical snap followed by a tiny spring click, with a compact midrange body and a very fast decay. Recorded close to the mechanism in an acoustically dead room. |
| Mouse click | 1 s | A computer mouse button pressed and released once. Two closely spaced plastic clicks, light and crisp, with a small midrange body and an immediate decay. Close-miked in a quiet, dry room. |
| Minimal UI tap | 1 s | A single soft synthesized UI tap. A rounded midrange tick with a delicate bright attack and a very short, smooth decay. Dry and isolated, suitable for a subtle interface selection. |
| Metal switch | 1 s | A small metal toggle switch flipped once. A precise metallic tick followed by a muted mechanical contact, with a tight body and almost immediate decay. Recorded close in a dead room. |
| Soft pop | 1 s | One small air bubble popping. A soft rounded plop with a tiny bright attack and a very short tail. Close-miked and dry against a quiet background. |
| Light air swish | 1 s | A thin strip of fabric flicked quickly past a microphone once. A light, smooth air swish that rises briefly and fades immediately, with a soft high-frequency texture. Recorded close in a dry room. |
| Short transition | 2 s | A single synthesized transition whoosh. A smooth, quick air sweep resolves into a compact soft impact, followed by a fast decay. An airy high end and a restrained low-mid finish, dry and isolated. |
| Wooden accent | 1 s | A small padded mallet striking a wooden block once. A compact warm knock with a crisp initial attack, a gentle low-mid body and a quick natural decay. Close-miked in an acoustically dead room. |
| Paper movement | 2 s | One page of a paper book being turned. A delicate papery rustle builds as the sheet bends, ending in a light flutter as it settles. Recorded close in a quiet, dry room, preserving the fine paper texture. |
| Low transition hit | 2 s | One short synthesized low-frequency impact. A firm rounded bass thump with a restrained midrange attack and a smooth, short tail. Dry, controlled and isolated, with a compact rather than booming low end. |
| Gentle riser | 3 s | A single smooth synthesized air riser that gradually brightens and increases in intensity, then stops cleanly. A fine airy texture with a light low-mid foundation, dry and isolated. |
| Light rain ambience | 8 s | Light rain falling steadily on broad leaves. Individual droplets patter gently over a soft continuous rain bed. Recorded outdoors at close range with a natural stereo perspective and an even level throughout. |


## Select, refine and deliver

Listen for the requested source, event count, clean attack and useful decay. Check for unwanted speech, music, ringing, background noise or extra events. If you cannot hear the audio through your tools, say that the take has not been auditioned.

Refine the problem you actually hear: room sound → close recording in a dead room; harsh click → softer attack/rounded body; weak impact → firmer low-mid body; repeated events → simpler single action and another seed. Select among variants and revise a miss rather than repeating an unchanged prompt indefinitely.

- **Trim:** drag the waveform's left/right handles. **+ / −** zooms up to **16×**; scroll horizontally and use **Fit** for the full view. Focused handles move by **10 ms** with arrows or **1 ms** with Shift.
- **Fades:** crops apply **5 ms fade-in/out**. Leave space before the attack and after the decay to avoid softening the transient; the minimum selection is **10 ms**.
- **Export:** wait for the trim to save. Playback, **Save WAV**, **Save OGG**, **Save MP3** and **Drag audio** all use the saved crop. **Reset trim** restores the original. Choose **Format** beside Duration and Variants before generating: OGG for smaller files, WAV for lossless storage, MP3 for 320 kbps compressed audio. The choice persists and also supplies the agent default. **Drag audio** delivers the stored format, including the saved crop. Save WAV for editors that require it; conversion to WAV does not recover details discarded by OGG compression.
- **Editor:** drag using **Drag audio** and check that the destination imported the file. If dropping is unsupported, save the WAV and import it through the editor.

For reference-based generation, choose **Use as reference** on a 0.5–30 s take, then **Reference variation** or **Edit a section**. Lower **Variation strength** stays closer to the source. Section editing may also change audio outside the selected section slightly.

For existing assets, use **Sound library** and retain the displayed origin/license status. Save to the user's destination with clear names such as `camera_shutter_01.ogg` and report the actual delivered paths.
