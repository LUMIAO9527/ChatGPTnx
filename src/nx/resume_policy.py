"""One classification and bounded retry policy for task continuation.

Unknown click/send outcomes are deliberately excluded. No editor state controls
continuation: message dispatch does not access the editor.
"""
ATTENTION_REASONS = frozenset()
AUTO_RETRY_DELAYS = (20, 60, 180, 300, 600)  # Five bounded retries.
AUTO_RETRY_PRE_DISPATCH = frozenset({
    'desktop_bridge_unavailable', 'history_unavailable',
    'account_changed',
    'target_not_visible', 'native_continue_not_ready',
    'desktop_not_running', 'desktop_task_not_idle',
    'task_identity_unavailable',
    'resume_source_unavailable',
})
AUTO_RETRY_TURN_FAILURES = frozenset({
    'resumed_turn_overloaded', 'resumed_turn_network',
})


def turn_failure_reason(error):
    """Classify a confirmed failed turn without recording its private message."""
    if not isinstance(error, dict):
        return 'resumed_turn_failed'
    code = str(error.get('codexErrorInfo') or '')
    message = str(error.get('message') or '').lower()
    if '401' in message or 'unauthorized' in message:
        return 'resume_auth_failed'
    if code == 'usageLimitExceeded':
        return 'resumed_turn_limit'
    if code == 'serverOverloaded' or 'at capacity' in message:
        return 'resumed_turn_overloaded'
    if code == 'other' and 'network' in message:
        return 'resumed_turn_network'
    return 'resumed_turn_failed'


def message_resume_eligible(error):
    """A failed turn can start a fresh message only for quota or transient errors."""
    if not isinstance(error, dict):
        return False
    reason = turn_failure_reason(error)
    if reason == 'resume_auth_failed':
        return False
    return (error.get('codexErrorInfo') == 'usageLimitExceeded' or
            reason in AUTO_RETRY_TURN_FAILURES)


def auto_retry_delay(reason, attempts):
    if (reason in AUTO_RETRY_PRE_DISPATCH | AUTO_RETRY_TURN_FAILURES and
            type(attempts) is int and 1 <= attempts <= len(AUTO_RETRY_DELAYS)):
        return AUTO_RETRY_DELAYS[attempts - 1]
    return None


RETRYABLE_REASONS = AUTO_RETRY_PRE_DISPATCH | AUTO_RETRY_TURN_FAILURES | frozenset({
    'target_changed',
    'desktop_window_ambiguous', 'desktop_location_unreadable',
    'desktop_bridge_ambiguous', 'resume_source_unconfigured',
    'title_unavailable_or_ambiguous',
    'task_navigation_unconfirmed', 'account_guard_unavailable',
    'native_continue_unavailable',
    'native_continue_ambiguous', 'invalid_resume_message',
})
