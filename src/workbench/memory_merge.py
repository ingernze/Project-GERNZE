"""Offline manual-memory exchange. No network, database, prompt execution or clocks.

The caller must authenticate a pairing scope before invoking these functions.
Only current/conflicting leaf bodies exist; historical nodes contain no text.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import uuid

FORMAT = 'hebao-memory-exchange'
VERSION = 1
MAX_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 1024
MAX_REVISIONS = 8192
MAX_PARENTS = 256
NOTE_FIELDS = {'title', 'body', 'kind', 'event_date', 'chat_enabled', 'important'}
RECORD_FIELDS = NOTE_FIELDS | {'id', 'revision', 'parent_revision', 'device_id',
                            'created_at', 'updated_at', 'deleted'}
NODE_FIELDS = {'id', 'revision', 'parents', 'deleted', 'digest'}
KINDS = ('preference', 'agreement', 'event', 'other')
STAMP = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)\Z')
HEX = re.compile(r'[0-9a-f]{64}\Z')


class Rejected(ValueError):
    """A structured rejection that never includes personal input text."""
    def __init__(self, code, path='$'):
        self.code = code
        self.path = path
        super().__init__(code + ' at ' + path)

    def as_dict(self):
        return {'status': 'rejected', 'code': self.code, 'path': self.path}


def fail(code, path='$'):
    raise Rejected(code, path)


def canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, RecursionError):
        fail('not_json_data')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def identifier(value, path='$'):
    if type(value) is not str:
        fail('invalid_uuid', path)
    try:
        if str(uuid.UUID(value)) != value:
            fail('invalid_uuid', path)
    except (ValueError, AttributeError):
        fail('invalid_uuid', path)
    return value


def fields(value, expected, path):
    if type(value) is not dict or set(value) != expected:
        fail('unexpected_fields', path)


def text(value, maximum, path, *, nonempty=False):
    if (type(value) is not str or len(value) > maximum or '\x00' in value
            or any(0xD800 <= ord(c) <= 0xDFFF for c in value)
            or value != value.strip() or (nonempty and not value)):
        fail('invalid_text', path)


def stamp(value, path):
    if type(value) is not str or not STAMP.fullmatch(value):
        fail('invalid_timestamp', path)
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        fail('invalid_timestamp', path)


def validate_note(note, path='$'):
    fields(note, NOTE_FIELDS, path)
    text(note['title'], 60, path+'.title', nonempty=True)
    text(note['body'], 500, path+'.body', nonempty=True)
    if type(note['kind']) is not str or note['kind'] not in KINDS:
        fail('invalid_kind', path+'.kind')
    for k in ['chat_enabled', 'important']:
        if type(note[k]) is not bool:
            fail('invalid_boolean', path+'.'+k)
    text(note['event_date'], 10, path+'.event_date')
    if note['event_date']:
        try:
            if date.fromisoformat(note['event_date']).isoformat() != note['event_date']:
                fail('invalid_date', path+'.event_date')
        except ValueError:
            fail('invalid_date', path+'.event_date')


def validate_record(row, path='$'):
    fields(row, RECORD_FIELDS, path)
    for k in ['id', 'revision', 'device_id']:
        identifier(row[k], path+'.'+k)
    if row['parent_revision'] is not None:
        identifier(row['parent_revision'], path+'.parent_revision')
        if row['parent_revision'] == row['revision']:
            fail('cycle', path)
    for k in ['created_at', 'updated_at']:
        stamp(row[k], path+'.'+k)
    if type(row['deleted']) is not bool:
        fail('invalid_boolean', path+'.deleted')
    note = {k: row[k] for k in NOTE_FIELDS}
    if row['deleted']:
        empty = {'title': '', 'body': '', 'kind': 'other', 'event_date': '',
                 'chat_enabled': False, 'important': False}
        if note != empty or any(type(note[k]) is not bool for k in ['chat_enabled', 'important']):
            fail('tombstone_contains_data', path)
    else:
        validate_note(note, path)


def _limits(state):
    if len(state['records']) > MAX_RECORDS or len(state['revisions']) > MAX_REVISIONS:
        fail('input_too_large')
    if len(canonical(state)) > MAX_BYTES:
        fail('input_too_large')


def _graph(nodes):
    """Check UUID ownership and cycles even across dangling parent references."""
    owners = {}
    for n in nodes.values():
        for rev in [n['revision']] + n['parents']:
            if rev in owners and owners[rev] != n['id']:
                fail('revision_reused_across_records')
            owners[rev] = n['id']
    # Kahn's algorithm: edges child -> parent, never infer missing nodes.
    incoming = {r: 0 for r in nodes}
    for n in nodes.values():
        for p in n['parents']:
            if p in incoming:
                incoming[p] += 1
    queue = [r for r, n in incoming.items() if not n]
    visited = 0
    while queue:
        r = queue.pop()
        visited += 1
        for p in nodes[r]['parents']:
            if p in incoming:
                incoming[p] -= 1
                if not incoming[p]:
                    queue.append(p)
    if visited != len(nodes):
        fail('cycle')


def _leaves(nodes):
    parents = {p for n in nodes.values() for p in n['parents']}
    return set(nodes) - parents


def validate_snapshot(value, *, expected_scope):
    """Return a sorted deep copy or reject the entire snapshot."""
    identifier(expected_scope, '$expected_scope')
    fields(value, {'format', 'version', 'scope_id', 'records', 'revisions'}, '$')
    if value['format'] != FORMAT or type(value['version']) is not int or value['version'] != VERSION:
        fail('unsupported_format')
    identifier(value['scope_id'], '$.scope_id')
    if value['scope_id'] != expected_scope:
        fail('scope_mismatch')
    if type(value['records']) is not list or type(value['revisions']) is not list:
        fail('invalid_array')
    _limits(value)
    records, nodes = {}, {}
    for i, row in enumerate(value['records']):
        path = f'$.records[{i}]'
        validate_record(row, path)
        if row['revision'] in records:
            fail('duplicate_record_revision', path)
        records[row['revision']] = deepcopy(row)
    for i, n in enumerate(value['revisions']):
        path = f'$.revisions[{i}]'
        fields(n, NODE_FIELDS, path)
        identifier(n['id'], path+'.id')
        identifier(n['revision'], path+'.revision')
        if type(n['deleted']) is not bool:
            fail('invalid_boolean', path+'.deleted')
        if type(n['digest']) is not str or not HEX.fullmatch(n['digest']):
            fail('invalid_digest', path+'.digest')
        if type(n['parents']) is not list or len(n['parents']) > MAX_PARENTS:
            fail('invalid_parents', path+'.parents')
        for j, p in enumerate(n['parents']):
            identifier(p, path+f'.parents[{j}]')
        if len(set(n['parents'])) != len(n['parents']):
            fail('duplicate_parent', path)
        if n['revision'] in nodes:
            fail('duplicate_revision_node', path)
        nodes[n['revision']] = {**deepcopy(n), 'parents': sorted(n['parents'])}
    _graph(nodes)
    leaves = _leaves(nodes)
    deleted_ids = {n['id'] for n in nodes.values() if n['deleted']}
    created = {}
    for r, row in records.items():
        n = nodes.get(r)
        if not n or n['id'] != row['id'] or n['deleted'] != row['deleted']:
            fail('record_metadata_mismatch')
        if n['digest'] != digest(row):
            fail('revision_content_mismatch')
        if row['parent_revision'] != (n['parents'][0] if n['parents'] else None):
            fail('parent_metadata_mismatch')
        if row['id'] in created and created[row['id']] != row['created_at']:
            fail('record_identity_mismatch')
        created[row['id']] = row['created_at']
        if not row['deleted']:
            if row['id'] in deleted_ids:
                fail('live_body_after_deletion')
            if r not in leaves:
                fail('historical_body_forbidden')
    for r, n in nodes.items():
        if n['deleted'] and r not in records:
            fail('missing_tombstone')
        if r in leaves and n['id'] not in deleted_ids and r not in records:
            fail('missing_leaf_body')
    return {'format': FORMAT, 'version': VERSION, 'scope_id': expected_scope,
            'records': [records[r] for r in sorted(records)],
            'revisions': [nodes[r] for r in sorted(nodes)]}


def _pairs(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            fail('duplicate_json_key')
        result[k] = v
    return result


def load_snapshot(data, *, expected_scope):
    """Bounded UTF-8 JSON parser; disallows duplicate keys and NaN/Infinity."""
    if type(data) is str:
        try:
            data = data.encode('utf-8')
        except UnicodeError:
            fail('invalid_utf8')
    if type(data) is not bytes or len(data) > MAX_BYTES:
        fail('input_too_large')
    try:
        value = json.loads(data.decode('utf-8'), object_pairs_hook=_pairs,
                           parse_constant=lambda _: fail('invalid_json_number'))
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as e:
        if isinstance(e, Rejected):
            raise
        fail('invalid_json')
    return validate_snapshot(value, expected_scope=expected_scope)


def export_records(records, *, expected_scope):
    """Import complete baseline public rows (including content-free tombstones).

    Only current nodes and their actual immediate-parent reference are added.
    Use retained snapshots/commit_decision thereafter to preserve older edges.
    """
    if type(records) is not list or len(records) > MAX_RECORDS:
        fail('invalid_or_oversized_records')
    ids = set()
    nodes = []
    for i, row in enumerate(records):
        validate_record(row, f'$.records[{i}]')
        if row['id'] in ids:
            fail('duplicate_legacy_id')
        ids.add(row['id'])
        nodes.append({'id': row['id'], 'revision': row['revision'],
                      'parents': [] if row['parent_revision'] is None else [row['parent_revision']],
                      'deleted': row['deleted'], 'digest': digest(row)})
    return validate_snapshot({'format': FORMAT, 'version': VERSION, 'scope_id': expected_scope,
                              'records': deepcopy(records), 'revisions': nodes},
                             expected_scope=expected_scope)


def fingerprint(snapshot, *, expected_scope):
    return digest(validate_snapshot(snapshot, expected_scope=expected_scope))


def _assemble(scope, records, nodes):
    _graph(nodes)
    leaves = _leaves(nodes)
    deleted_ids = {n['id'] for n in nodes.values() if n['deleted']}
    kept = [row for r, row in records.items() if row['deleted'] or
            (r in leaves and row['id'] not in deleted_ids)]
    return validate_snapshot({'format': FORMAT, 'version': VERSION, 'scope_id': scope,
                              'records': kept, 'revisions': list(nodes.values())},
                             expected_scope=scope)


def merge(left, right, *, expected_scope):
    """Union causal evidence; never choose by wall time or device priority."""
    left = validate_snapshot(left, expected_scope=expected_scope)
    right = validate_snapshot(right, expected_scope=expected_scope)
    nodes, records, identities = {}, {}, {}
    for s in [left, right]:
        for n in s['revisions']:
            r = n['revision']
            if r in nodes and nodes[r] != n:
                fail('revision_collision')
            nodes[r] = n
        for row in s['records']:
            r = row['revision']
            if r in records and records[r] != row:
                fail('revision_collision')
            if row['id'] in identities and identities[row['id']] != row['created_at']:
                fail('record_identity_mismatch')
            identities[row['id']] = row['created_at']
            records[r] = row
    # Check full union before discarding stale bodies, including union-only cycles.
    if len(nodes) > MAX_REVISIONS or len(records) > MAX_RECORDS * 2:
        fail('input_too_large')
    return _assemble(expected_scope, records, nodes)


def _complete_lineage(rev, nodes):
    seen, todo = set(), [rev]
    while todo:
        r = todo.pop()
        if r in seen:
            continue
        seen.add(r)
        if r not in nodes:
            return False
        todo.extend(nodes[r]['parents'])
    return True


def inspect(snapshot, *, expected_scope):
    """Separate accepted records from quarantined branches; never run note text."""
    state = validate_snapshot(snapshot, expected_scope=expected_scope)
    nodes = {n['revision']: n for n in state['revisions']}
    rows = {r['revision']: r for r in state['records']}
    leaves = _leaves(nodes)
    ids = sorted({n['id'] for n in nodes.values()})
    active, conflicts, decisions, quarantine = [], [], [], []
    live_ids = 0
    for record_id in ids:
        tips = sorted(r for r in leaves if nodes[r]['id'] == record_id)
        tombs = sorted(r for r, n in nodes.items() if n['id'] == record_id and n['deleted'])
        live_tips = [r for r in tips if not nodes[r]['deleted']]
        d = {'id': record_id, 'tip_revisions': tips}
        if tombs:
            d['tombstone_revisions'] = tombs
            if live_tips:
                d['status'] = 'delete_edit'
                d['body_policy'] = 'all_live_bodies_discarded'
                conflicts.append(d)
            else:
                d['status'] = 'accepted_deleted'
        else:
            live_ids += 1
            if len(live_tips) == 1:
                d['status'] = 'accepted_live'
                active.append(rows[live_tips[0]])
            else:
                d['status'] = ('concurrent_edit' if all(_complete_lineage(r, nodes) for r in live_tips)
                               else 'ancestry_unknown')
                d['body_policy'] = 'quarantined_until_explicit_decision'
                conflicts.append(d)
                quarantine.extend(live_tips)
        decisions.append(d)
    chat = [r for r in active if r['chat_enabled']]
    limits = []
    if live_ids > 100:
        limits.append({'code': 'record_limit', 'actual': live_ids, 'maximum': 100})
    if len(chat) > 6:
        limits.append({'code': 'chat_limit', 'actual': len(chat), 'maximum': 6})
    # Match baseline display ordering; clocks here affect presentation only.
    active.sort(key=lambda r: r['id'])
    active.sort(key=lambda r: datetime.fromisoformat(r['created_at'].replace('Z', '+00:00')), reverse=True)
    active.sort(key=lambda r: r['important'], reverse=True)
    chat = [] if limits else [r for r in active if r['chat_enabled']]
    chat_fields = ['id', 'title', 'body', 'kind', 'event_date', 'important']
    return {'status': 'needs_decision' if conflicts or limits else 'ready',
            'decisions': decisions, 'conflicts': conflicts, 'limits': limits,
            'active_records': active, 'quarantine_revisions': sorted(quarantine),
            'chat_records': [{k: r[k] for k in chat_fields} for r in chat],
            'counts': {'live_ids': live_ids, 'accepted_live': len(active),
                       'chat_enabled_accepted': sum(r['chat_enabled'] for r in active)}}


def make_plan(local, remote, *, expected_scope):
    local = validate_snapshot(local, expected_scope=expected_scope)
    remote = validate_snapshot(remote, expected_scope=expected_scope)
    proposed = merge(local, remote, expected_scope=expected_scope)
    report = inspect(proposed, expected_scope=expected_scope)
    plan = {'format': 'hebao-memory-plan', 'version': VERSION, 'scope_id': expected_scope,
            'expected_local': digest(local), 'expected_remote': digest(remote),
            'status': report['status'], 'proposed': proposed, 'report': report}
    return {**plan, 'plan_digest': digest(plan)}


def apply_plan(current_local, current_remote, plan, *, expected_scope):
    """Pure in-memory CAS boundary. Caller must hold its own transaction/lock."""
    local = validate_snapshot(current_local, expected_scope=expected_scope)
    remote = validate_snapshot(current_remote, expected_scope=expected_scope)
    if type(plan) is not dict:
        fail('invalid_plan')
    if plan.get('scope_id') != expected_scope:
        fail('scope_mismatch')
    if plan.get('expected_local') != digest(local) or plan.get('expected_remote') != digest(remote):
        return {'status': 'needs_refresh', 'code': 'snapshot_changed', 'applied': False}
    recalculated = make_plan(local, remote, expected_scope=expected_scope)
    if plan != recalculated:
        fail('plan_modified')
    if plan['status'] != 'ready':
        return {'status': 'needs_decision', 'applied': False,
                'conflicts': deepcopy(plan['report']['conflicts']),
                'limits': deepcopy(plan['report']['limits'])}
    return {'status': 'applied', 'applied': True, 'snapshot': deepcopy(plan['proposed'])}


def commit_decision(snapshot, record_id, *, expected_scope, expected_fingerprint,
                    device_id, revision, timestamp, note=None, delete=False):
    """Explicit local correction/conflict decision, never an automatic merge.

    Consumes all known tips of this id. A delete is absorbing; restore requires
    an explicitly new record id outside this function.
    """
    state = validate_snapshot(snapshot, expected_scope=expected_scope)
    if digest(state) != expected_fingerprint:
        fail('decision_needs_refresh')
    for value in [record_id, device_id, revision]:
        identifier(value)
    stamp(timestamp, '$timestamp')
    if type(delete) is not bool:
        fail('invalid_boolean')
    if delete and note is not None:
        fail('delete_with_note')
    if not delete:
        validate_note(note)
    nodes = {n['revision']: n for n in state['revisions']}
    known = set(nodes) | {p for n in nodes.values() for p in n['parents']}
    if revision in known:
        fail('revision_already_used')
    selected = [n for n in nodes.values() if n['id'] == record_id]
    if not selected:
        fail('record_not_found')
    if not delete and any(n['deleted'] for n in selected):
        fail('deleted_id_cannot_restore')
    parents = sorted(r for r in _leaves(nodes) if nodes[r]['id'] == record_id)
    if len(parents) > MAX_PARENTS:
        fail('too_many_conflict_parents')
    current = [r for r in state['records'] if r['id'] == record_id]
    # Valid states require at least one body or tombstone for every note.
    created = current[0]['created_at']
    content = {'title': '', 'body': '', 'kind': 'other', 'event_date': '',
               'chat_enabled': False, 'important': False} if delete else deepcopy(note)
    row = {'id': record_id, 'revision': revision, 'parent_revision': parents[0],
           'device_id': device_id, **content, 'created_at': created,
           'updated_at': timestamp, 'deleted': delete}
    nodes[revision] = {'id': record_id, 'revision': revision, 'parents': parents,
                       'deleted': delete, 'digest': digest(row)}
    records = {r['revision']: r for r in state['records']}
    records[revision] = row
    return _assemble(expected_scope, records, nodes)


def _read(path, scope):
    with Path(path).open('rb') as f:
        return load_snapshot(f.read(MAX_BYTES+1), expected_scope=scope)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', required=True, help='already-authenticated expected scope UUID')
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('inspect'); check.add_argument('snapshot')
    plan = commands.add_parser('plan'); plan.add_argument('local'); plan.add_argument('remote')
    args = parser.parse_args(argv)
    try:
        if args.command == 'inspect':
            result = inspect(_read(args.snapshot, args.scope), expected_scope=args.scope)
        else:
            result = make_plan(_read(args.local, args.scope), _read(args.remote, args.scope), expected_scope=args.scope)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0 if result['status'] == 'ready' else 3
    except Rejected as error:
        print(json.dumps(error.as_dict(), ensure_ascii=False, sort_keys=True))
        return 2
    except OSError:
        print(json.dumps({'status': 'rejected', 'code': 'file_unavailable'}))
        return 2


if __name__ == '__main__':
    # The exchange CLI emits UTF-8 JSON independently of the Windows code page.
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
