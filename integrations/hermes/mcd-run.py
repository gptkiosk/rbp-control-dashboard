"""Hermes CLI compatibility shim: per-process pins and final model reporting.

No native files or defaults are changed. Explicit -m/--model disables inherited
fallbacks for this process; unassigned runs retain the native free-first chain.
Fail before inference if the supported native APIs change.
"""
import sys
import runpy

def install(pinned):
    import hermes_cli.fallback_config as fallback
    from hermes_cli.stream_json import StreamJsonEmitter
    if not callable(getattr(fallback, 'get_fallback_chain', None)) or not callable(getattr(StreamJsonEmitter, 'attach', None)):
        raise RuntimeError('Unsupported Hermes runtime; assigned-model guard unavailable.')
    if pinned:
        fallback.get_fallback_chain = lambda config: []
    attach, emit = StreamJsonEmitter.attach, StreamJsonEmitter._emit
    def tracked_attach(self, agent):
        self._mcd_agent = agent
        return attach(self, agent)
    def tracked_emit(self, event):
        agent = getattr(self, '_mcd_agent', None)
        if event.get('type') == 'result' and agent is not None:
            event = {**event, 'model': getattr(agent, 'model', None), 'provider': getattr(agent, 'provider', None)}
        return emit(self, event)
    StreamJsonEmitter.attach, StreamJsonEmitter._emit = tracked_attach, tracked_emit

def main():
    pinned = any(arg in ('-m', '--model') or arg.startswith('--model=') for arg in sys.argv[1:])
    try: install(pinned)
    except (ImportError, AttributeError, RuntimeError):
        print('MCD could not enforce the Hermes model policy; no inference started.', file=sys.stderr)
        raise SystemExit(2)
    runpy.run_module('hermes_cli.main', run_name='__main__')

if __name__ == '__main__': main()
