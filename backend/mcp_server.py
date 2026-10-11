"""Standard MCP over stdio; all work runs in the existing desktop service."""
from typing import Any
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from mcp.server.mcpserver.exceptions import ToolError, ResourceError
from agent_client import AgentClient

server = MCPServer('FX Studio', version='0.1.0', instructions=
    'Create local sound effects in FX Studio with Stable Audio 3 Medium. First get_status and get_prompt_guide. '
    'Use concrete English prompts: source, action/event count, texture/decay, recording distance and room. '
    'For a game or named project, list/create the project and pass its project_id to generation or a pack. '
    'The user reviews its sounds in Projects. Start at 8 steps, CFG 1. Create separate assets in a pack. Poll get_job/get_pack, '
    'cancel on request, then export the saved crop. Only one generation runs at a time. Never claim audio quality without auditioning. '
    'App access must be enabled in Setup > Local agents.')
class MCPClient(AgentClient):
    def request(self, route, data=None):
        try:
            return super().request(route, data)
        except (ValueError, KeyError, OSError) as error:
            raise ToolError(str(error)) from None


client = MCPClient()
READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
RETRY = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


@server.tool(annotations=READ, structured_output=True)
def get_status() -> dict[str, Any]:
    """Start FX Studio if needed; check model readiness, queue, local access and export folder."""
    return client.request('/status')


@server.tool(annotations=READ, structured_output=True)
def get_prompt_guide() -> dict[str, Any]:
    """Read the English operating/prompt guide and twelve concrete sound-effect examples."""
    return client.request('/guide')


@server.resource('fxstudio://guide', mime_type='text/markdown')
def prompt_guide() -> str:
    try:
        return get_prompt_guide()['guide']
    except ToolError as error:
        raise ResourceError(str(error)) from None


@server.tool(annotations=RETRY, structured_output=True)
def generate_sound(request_id: str, prompt: str, asset_name: str = 'sound', seconds: float = 3,
                   variants: int = 1, steps: int = 8, cfg: float = 1, seed: int | None = None,
                   negative_prompt: str = '', mode: str = 'text', reference_id: str | None = None,
                   strength: float = .65, start: float = 0, end: float | None = None,
                   project_id: str | None = None) -> dict[str, Any]:
    """Queue one asset and return its job id immediately. Duration .5–30s, variants 1–4, steps 1–16, CFG 0–10.
    Supply a unique request_id; reuse the same id/settings after a transport error to avoid duplicate jobs.
    mode text, variation or inpaint; reference modes require reference_id and the reference duration.
    Negative prompt has no effect at CFG 1. Inspect errors before retrying; poll get_job until completed.
    Pass project_id returned by list_projects/create_project to file every variant in that project.
    """
    settings = dict(prompt=prompt, asset_name=asset_name, seconds=seconds, variants=variants, steps=steps,
                    cfg=cfg, seed=seed, negative_prompt=negative_prompt, mode=mode)
    if mode != 'text':
        settings.update(reference_id=reference_id, strength=strength, start=start, end=seconds if end is None else end)
    if project_id is not None:
        settings['project_id'] = project_id
    return client.request('/generate', {'request_id': request_id, 'settings': settings})


@server.tool(annotations=RETRY, structured_output=True)
def create_sound_pack(request_id: str, name: str, assets: list[dict[str, Any]], project_id: str | None = None) -> dict[str, Any]:
    """Atomically queue 1–8 separate assets. Each needs a distinct asset_name and English prompt.
    Optional per-asset fields: seconds, variants, steps, cfg, seed, negative_prompt, mode, reference_id,
    strength, start, end. Names use letters/numbers/underscores/hyphens. Reuse request_id after transport errors.
    Returns pack and job ids immediately. Poll get_pack; larger packs need batches after jobs finish.
    Pass project_id to group every asset/variant in the same persistent project for desktop review.
    """
    data = dict(request_id=request_id, name=name, assets=assets)
    if project_id is not None:
        data['project_id'] = project_id
    return client.request('/packs', data)


@server.tool(annotations=READ, structured_output=True)
def list_projects(query: str = '') -> dict[str, Any]:
    """Find existing projects by name/description, with sound counts and active jobs."""
    return client.request(client.query('/projects', q=query))


@server.tool(annotations=RETRY, structured_output=True)
def create_project(name: str, description: str = '') -> dict[str, Any]:
    """Create a persistent project (name 1–80 chars, description up to 1000). Reuses a matching name,
    ignoring case, without changing its description. Pass the returned id as project_id for every asset/pack.
    """
    return client.request('/projects', dict(name=name, description=description))


@server.tool(annotations=READ, structured_output=True)
def get_project(project_id: str, query: str = '', offset: int = 0, limit: int = 30) -> dict[str, Any]:
    """Get project metadata, jobs/errors and its sounds (including all variants). Paginate limit 1–100.
    The user auditions these in the app's Projects view. Use get_sound for the current crop's audio_path.
    """
    return client.request(client.query('/projects/' + project_id, q=query, offset=offset, limit=limit))


@server.tool(annotations=RETRY, structured_output=True)
def update_project(project_id: str, name: str | None = None, description: str | None = None) -> dict[str, Any]:
    """Rename or update a project description; all sound associations and generation settings stay intact."""
    data = dict(project_id=project_id)
    if name is not None:
        data['name'] = name
    if description is not None:
        data['description'] = description
    return client.request('/project-update', data)


@server.tool(annotations=RETRY, structured_output=True)
def set_project_sound(project_id: str, sound_id: str, included: bool = True) -> dict[str, Any]:
    """Add an existing history/library sound to a project, or remove its association with included=false.
    Keeps the audio, favorites and trims. Sounds may belong to multiple projects; their trim is shared.
    """
    return client.request('/project-sound', dict(project_id=project_id, sound_id=sound_id, included=included))


@server.tool(annotations=READ, structured_output=True)
def get_job(job_id: str) -> dict[str, Any]:
    """Get progress, actual errors and completed sounds with saved-crop audio paths. Poll every 2–5 seconds."""
    return client.request('/jobs/' + job_id)


@server.tool(annotations=READ, structured_output=True)
def get_pack(pack_id: str) -> dict[str, Any]:
    """Get all pack jobs, progress/errors and completed sounds. Partial or failed packs are marked incomplete."""
    return client.request('/packs/' + pack_id)


@server.tool(annotations=RETRY, structured_output=True)
def cancel_job(job_id: str) -> dict[str, Any]:
    """Cancel this queued/running job. Completed variants remain saved. Cancellation may need a brief moment."""
    return client.request('/cancel', {'job_id': job_id})


@server.tool(annotations=RETRY, structured_output=True)
def cancel_pack(pack_id: str) -> dict[str, Any]:
    """Cancel every active job in this pack; keep completed variants."""
    return client.request('/cancel-pack', {'pack_id': pack_id})


@server.tool(annotations=READ, structured_output=True)
def search_sounds(query: str = '', favorites: bool = False, offset: int = 0, limit: int = 30) -> dict[str, Any]:
    """Search generated history, including desktop and agent results; paginate with offset and limit (1–100)."""
    return client.request(client.query('/history', q=query, favorites=int(favorites), offset=offset, limit=limit))


@server.tool(annotations=READ, structured_output=True)
def search_library(query: str = '', category: str = '', favorites: bool = False, offset: int = 0, limit: int = 30) -> dict[str, Any]:
    """Search the existing read-only sound library; retain source/license fields, including undocumented assets."""
    return client.request(client.query('/library', q=query, category=category, favorites=int(favorites), offset=offset, limit=limit))


@server.tool(annotations=READ, structured_output=True)
def get_sound(sound_id: str) -> dict[str, Any]:
    """Get the actual saved-crop audio_path, original_path, duration, trim, seed/settings and provenance."""
    return client.request('/sounds/' + sound_id)


@server.tool(annotations=RETRY, structured_output=True)
def trim_sound(sound_id: str, start: float = 0, end: float | None = None, reset: bool = False) -> dict[str, Any]:
    """Save a crop using seconds in the original sound. Minimum 10ms; automatic 5ms edge fades. Reset restores original."""
    data = dict(sound_id=sound_id, start=start, reset=reset)
    if end is not None:
        data['end'] = end
    return client.request('/trim', data)


@server.tool(annotations=RETRY, structured_output=True)
def set_favorite(sound_id: str, favorite: bool = True) -> dict[str, Any]:
    """Mark or unmark a saved sound as a favorite."""
    return client.request('/favorite', dict(sound_id=sound_id, favorite=favorite))


@server.tool(annotations=WRITE, structured_output=True)
def export_sound(sound_id: str, name: str = '', format: str = 'wav', folder: str = '') -> dict[str, Any]:
    """Export the saved crop as WAV or MP3 inside the folder selected in Setup. folder is relative.
    name uses letters/numbers/underscores/hyphens. Existing files are preserved; returns actual path and provenance.
    """
    return client.request('/export', dict(sound_id=sound_id, name=name, format=format, folder=folder))


@server.tool(annotations=WRITE, structured_output=True)
def export_pack(pack_id: str, format: str = 'wav', folder: str = '') -> dict[str, Any]:
    """Export a completed pack's saved crops and a JSON manifest of prompts/settings/seeds/licenses.
    Writes a new pack directory inside the configured export folder; existing exports are preserved.
    """
    return client.request('/export-pack', dict(pack_id=pack_id, format=format, folder=folder))


if __name__ == '__main__':
    server.run(transport='stdio')
