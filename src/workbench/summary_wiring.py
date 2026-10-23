"""Explicit summary wiring; importing or constructing an adapter performs no I/O."""
if __package__:
    from .summary_adapter import SummaryAdapter, Limits
else:
    from summary_adapter import SummaryAdapter, Limits


def adapter_for_chat(chat, *, observer=None, http=None, io_timeout=2.0):
    """Build while idle; caller explicitly enables it on the existing context.

    Reuse the current application's budget/counter, never an old core default.
    This factory does not assert the configured provider's real token window.
    """
    with chat.guard:
        if chat.sending.locked():
            raise ValueError('等待当前请求结束再接入摘要。')
        context = chat.context
        budget = context.budget

    def settings():
        with chat.guard:
            config = chat._config()
            return {k: config[k] for k in ('enabled', 'endpoint', 'model')}

    def key(config):
        with chat.guard:
            current = chat._config()
            if {k: current[k] for k in ('enabled', 'endpoint', 'model')} != config:
                return ''
            return chat.keys.get(chat._target(config))

    return SummaryAdapter(settings_getter=settings, key_getter=key, http=http,
                          limits=Limits(context_window=budget.context_window,
                                        margin=budget.margin, io_timeout=io_timeout),
                          token_counter=context.token_counter, counter_is_exact=context.exact,
                          observer=observer)
