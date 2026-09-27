"""Only an explicit user action may recheck a proven pre-dispatch failure.

Unknown click/send outcomes are deliberately absent. No editor state controls
continuation: the quota path never accesses the editor.
"""
ATTENTION_REASONS = frozenset()
RETRYABLE_REASONS = frozenset({
    'target_not_visible', 'target_changed', 'desktop_not_running',
    'desktop_window_ambiguous', 'desktop_location_unreadable',
    'desktop_bridge_unavailable', 'desktop_bridge_ambiguous',
    'desktop_task_not_idle', 'history_unavailable',
    'resume_source_unconfigured', 'resume_source_unavailable',
    'title_unavailable_or_ambiguous', 'task_identity_unavailable',
    'task_navigation_unconfirmed', 'account_guard_unavailable',
    'native_continue_unavailable', 'native_continue_not_ready',
    'native_continue_ambiguous', 'invalid_resume_message',
})
