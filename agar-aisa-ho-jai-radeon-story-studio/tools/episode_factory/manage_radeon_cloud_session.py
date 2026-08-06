#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from .radeon_cloud_execution import read_json, write_json
    from .radeon_cloud_session import ProviderRegistry, RadeonCloudSession, SharedDirectoryTransport, load_session, save_session
    from .radeon_cloud_ssh import AttachedRadeonCloudProvider, SshCommandExecutor, SshWorkspaceConnection, attached_session
except ImportError:
    from radeon_cloud_execution import read_json, write_json
    from radeon_cloud_session import ProviderRegistry, RadeonCloudSession, SharedDirectoryTransport, load_session, save_session
    from radeon_cloud_ssh import AttachedRadeonCloudProvider, SshCommandExecutor, SshWorkspaceConnection, attached_session


def dump(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Manage Radeon Cloud sessions and artifact transport')
    sub = parser.add_subparsers(dest='command', required=True)

    create = sub.add_parser('create-session')
    create.add_argument('--provider', required=True)
    create.add_argument('--workspace-root', required=True)
    create.add_argument('--remote-reference')
    create.add_argument('--output', type=Path, required=True)

    transition = sub.add_parser('transition')
    transition.add_argument('session', type=Path)
    transition.add_argument('state')

    build = sub.add_parser('build-job')
    build.add_argument('--provider', required=True)
    build.add_argument('--configuration', type=Path, required=True)
    build.add_argument('--output', type=Path, required=True)

    stage = sub.add_parser('stage-package')
    stage.add_argument('session', type=Path)
    stage.add_argument('package', type=Path)

    collect = sub.add_parser('collect-result')
    collect.add_argument('session', type=Path)
    collect.add_argument('--cloud-result-directory', type=Path, required=True)
    collect.add_argument('--destination', type=Path, required=True)

    attach = sub.add_parser('attach-ssh', help='validate and attach to an already-running workspace')
    attach.add_argument('--host', required=True)
    attach.add_argument('--port', type=int, default=22)
    attach.add_argument('--user', required=True)
    attach.add_argument('--identity-file', type=Path, required=True)
    attach.add_argument('--workspace-root', default='/workspace')
    attach.add_argument('--remote-repository', required=True)
    attach.add_argument('--no-strict-host-key-checking', action='store_true')
    attach.add_argument('--output', type=Path, required=True)

    probe = sub.add_parser('probe-ssh', help='probe an attached workspace and its Radeon runtime')
    probe.add_argument('session', type=Path)

    remote = sub.add_parser('run-remote', help='stage, run, retrieve, and verify one package')
    remote.add_argument('session', type=Path)
    remote.add_argument('package', type=Path)
    remote.add_argument('--destination', type=Path, required=True)
    remote.add_argument('--timeout', type=float)
    remote.add_argument('--evidence-directory', type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == 'create-session':
            session = RadeonCloudSession(args.provider, args.workspace_root, remote_reference=args.remote_reference)
            save_session(args.output, session)
            dump({'session_id': session.session_id, 'state': session.state})
        elif args.command == 'transition':
            session = load_session(args.session).transition(args.state)
            save_session(args.session, session)
            dump({'session_id': session.session_id, 'state': session.state})
        elif args.command == 'build-job':
            configuration = read_json(args.configuration)
            job = ProviderRegistry.defaults().resolve(args.provider).build_job(configuration)
            write_json(args.output, job.as_dict())
            dump({'provider': args.provider, 'job_id': job.job_id})
        elif args.command == 'stage-package':
            receipt = SharedDirectoryTransport().stage_package(load_session(args.session), args.package)
            dump({**receipt.as_dict(), 'receipt_id': receipt.receipt_id})
        elif args.command == 'collect-result':
            receipts = SharedDirectoryTransport().collect_result(load_session(args.session), args.cloud_result_directory, args.destination)
            dump({'files': len(receipts), 'receipts': [{**r.as_dict(), 'receipt_id': r.receipt_id} for r in receipts]})
        elif args.command == 'attach-ssh':
            connection = SshWorkspaceConnection(
                host=args.host,
                port=args.port,
                username=args.user,
                identity_file=args.identity_file,
                workspace_root=args.workspace_root,
                remote_repository=args.remote_repository,
                strict_host_key_checking=not args.no_strict_host_key_checking,
            )
            probe = SshCommandExecutor(connection).probe(include_runtime=False)
            if not probe['base_ready']:
                raise RuntimeError('SSH workspace validation failed')
            session = attached_session(connection).transition('ready')
            save_session(args.output, session)
            dump({
                'connection_id': connection.connection_id,
                'session_id': session.session_id,
                'state': session.state,
                'session': str(args.output.resolve()),
                'workspace_ready': True,
            })
        elif args.command == 'probe-ssh':
            session = load_session(args.session)
            provider = AttachedRadeonCloudProvider.from_session(session)
            assert provider.executor is not None
            probe = provider.executor.probe(include_runtime=True)
            dump(probe)
            return 0 if probe['base_ready'] else 2
        elif args.command == 'run-remote':
            session = load_session(args.session)
            provider = AttachedRadeonCloudProvider.from_session(session)
            result = provider.run_remote(
                args.session,
                args.package,
                args.destination,
                timeout=args.timeout,
                evidence_directory=args.evidence_directory,
            )
            dump(result)
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
