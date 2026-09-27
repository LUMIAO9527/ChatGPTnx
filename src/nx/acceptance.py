"""Explicit one-relay acceptance entry using the real Service and queue."""
import json
import time

from .desktop_resume import active_turns
from .storage import atomic_bytes


def relay_once(service, thread_id, report):
    # Exclusive journal prevents accidentally repeating the same acceptance run.
    with report.open('x', encoding='utf-8') as stream:
        json.dump({'state': 'started', 'switch_requested': False}, stream)

    def record(state, **fields):
        atomic_bytes(report, json.dumps({'state': state, **fields}).encode('utf-8'))

    try:
        active = active_turns(service.paths.home)
        if {i['thread_id'] for i in active} != {thread_id}:
            record('blocked', reason='active_tasks_changed', active_count=len(active))
            return
        if not service.state.get('settings').get('task_continuation'):
            record('blocked', reason='continuation_disabled')
            return
        previous = {s['id'] for s in service.resumer.sessions}
        # Use the same current candidate and account preflight as the Relay UI.
        if not service.get_data().get('relay_email'):
            refresh = service.refresh()
            deadline = time.monotonic() + 180
            while service.operation and time.monotonic() < deadline:
                time.sleep(.25)
            if service.operation:
                record('blocked', reason='refresh_timeout')
                return
        active = active_turns(service.paths.home)
        if {i['thread_id'] for i in active} != {thread_id}:
            record('blocked', reason='active_tasks_changed', active_count=len(active))
            return
        service.resumer.start()
        real_runner = service.runner
        def guarded_runner(*args):
            # Recheck after network preflight, immediately before stopping the
            # desktop. Abort if the user has started any other task meanwhile.
            if {i['thread_id'] for i in active_turns(service.paths.home)} != {thread_id}:
                raise RuntimeError('acceptance_active_tasks_changed')
            return real_runner(*args)
        service.runner = guarded_runner
        record('requesting_relay', switch_requested=True)
        result = service.relay()
        if not result.get('accepted'):
            record('blocked', reason='relay_not_accepted', switch_requested=False)
            return
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            with service.resumer.lock:
                sessions = [s for s in service.resumer.sessions if s['id'] not in previous]
                summary = [{'id': s['id'], 'phase': s['phase'],
                    'switched': bool(s.get('switched_at')), 'items': [
                        {k: i.get(k) for k in ('thread_id', 'turn_id', 'state', 'reason',
                                              'attempts', 'observed_turn_id')}
                        for i in s['items']]} for s in sessions]
            if summary and all(s['phase'] in ('done', 'failed', 'cancelled') for s in summary):
                record('finished', switch_requested=True, sessions=summary)
                return
            if not service.operation and not summary:
                record('failed', reason='no_switch_session', switch_requested=True)
                return
            record('waiting', switch_requested=True, sessions=summary)
            time.sleep(1)
        record('timeout', switch_requested=True, sessions=summary)
    except Exception as error:
        record('error', error_type=type(error).__name__)
        raise
    finally:
        # Queue outcomes stay durable. Never replay an uncertain desktop action.
        service.stop.set()

