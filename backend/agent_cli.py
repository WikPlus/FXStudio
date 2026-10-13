"""JSON CLI fallback for local agents without an MCP client."""
import argparse
import json
import sys
from agent_client import AgentClient


def main():
    parser = argparse.ArgumentParser(description='FX Studio local agent API. Generation returns a job id immediately.')
    parser.add_argument('command', choices=['status', 'guide', 'generate', 'pack', 'job', 'get-pack', 'sound',
                                           'history', 'library', 'cancel', 'cancel-pack', 'trim', 'favorite', 'export', 'export-pack',
                                           'projects', 'create-project', 'project', 'update-project', 'project-sound', 'project-deletion', 'delete-project'])
    parser.add_argument('value', nargs='?', help='Id for job/get-pack/sound; a JSON object for other commands. Use - for JSON on stdin.')
    args = parser.parse_args()
    client = AgentClient()
    routes = {'pack': '/packs', 'get-pack': '/packs/', 'job': '/jobs/', 'sound': '/sounds/',
              'create-project': '/projects', 'project': '/projects/', 'update-project': '/project-update', 'delete-project': '/project-delete'}
    if args.command in ('job', 'get-pack', 'sound', 'project'):
        if not args.value:
            parser.error('Supply an id.')
        import urllib.parse
        route, body = routes[args.command] + urllib.parse.quote(args.value, safe=''), None
    elif args.command in ('status', 'guide'):
        route, body = '/' + args.command, None
    else:
        body = json.loads(sys.stdin.read() if args.value == '-' else args.value or '{}')
        if not isinstance(body, dict):
            raise ValueError('Supply a JSON object.')
        route = routes.get(args.command, '/' + args.command)
        if args.command in ('history', 'library', 'projects', 'project-deletion'):
            route, body = client.query(route, **body), None
    print(json.dumps(client.request(route, body), ensure_ascii=False))


if __name__ == '__main__':
    # JSON exchanged with local agents uses UTF-8, including Windows pipes.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        sys.exit(1)
