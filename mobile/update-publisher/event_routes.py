"""Minimal dispatcher for the EXISTING TLS Handler; no listener, token store or pairing code."""
from event_outbox import AuthenticatedPeer, EventError, keys, parse, require


class EventRoutes:
    def __init__(self, outbox):
        self.outbox = outbox

    def dispatch(self, path, raw_body, authenticated_peer):
        require(isinstance(authenticated_peer, AuthenticatedPeer), 'authentication_failed')
        body = parse(raw_body, 4096)
        if path == '/v1/events/fetch':
            keys(body, ('schema', 'cursor', 'limit', 'stream_id'))
            require(type(body['schema']) is int and body['schema'] == 1)
            return self.outbox.fetch(authenticated_peer, body['cursor'], body['limit'], stream_id=body['stream_id'])
        if path == '/v1/events/ack':
            keys(body, ('schema', 'event_ids'))
            require(type(body['schema']) is int and body['schema'] == 1)
            return self.outbox.ack(authenticated_peer, body['event_ids'])
        raise EventError('invalid_input')
