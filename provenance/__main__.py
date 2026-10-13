import argparse
import json
from pathlib import Path
import sys

from provenance.record import AUTHOR, ROOT, create_proof, verify_proof
from v2.storage import BudgetExceeded


def main():
    parser = argparse.ArgumentParser(description='Dossiers de provenance au nom du createur, archives et horodatage RFC 3161.')
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create')
    create.add_argument('--author', default=AUTHOR)
    create.add_argument('--root', type=Path, default=ROOT)
    create.add_argument('--out', type=Path)
    create.add_argument('--max-output-bytes', type=int, default=10_000_000)
    create.add_argument('--timestamp', action='store_true', help='Send only the record hash to FreeTSA and verify its signature')
    verify = sub.add_parser('verify')
    verify.add_argument('--proof', type=Path, required=True)
    verify.add_argument('--project-root', type=Path)
    verify.add_argument('--require-timestamp', action='store_true')
    stamp = sub.add_parser('stamp')
    stamp.add_argument('--proof', type=Path, required=True)
    stamp.add_argument('--max-output-bytes', type=int, default=10_000_000)
    args = parser.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        if args.command == 'create':
            result = create_proof(args.root, args.author, args.out, args.max_output_bytes)
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
            if not args.timestamp:
                return
            from provenance.timestamp import stamp_proof
            result = stamp_proof(result['folder'], args.max_output_bytes)
        elif args.command == 'stamp':
            from provenance.timestamp import stamp_proof
            result = stamp_proof(args.proof, args.max_output_bytes)
        else:
            result = verify_proof(args.proof, args.project_root)
            if (args.proof/'timestamp.tsr').exists() or args.require_timestamp:
                from provenance.timestamp import verify_timestamp
                timestamp = verify_timestamp(args.proof)
                result.update({k: v for k, v in timestamp.items() if k.startswith('tsa_') or k in ('timestamp_status', 'trust_scope')})
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError, BudgetExceeded) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
