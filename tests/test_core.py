"""Offline unit / transaction tests. All identities are synthetic."""
from pathlib import Path
import base64
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nx.storage import Paths, State, Accounts, atomic_bytes, identity, credential_metadata, safe_email, timestamp
from nx.core import Service, relay_candidate
from nx.quota import RPCError, Query, normalize_limits, normalize_usage
from nx.desktop import Desktop, launch_chatgpt, popup_position


_windll_patch = None

def setUpModule():
    global _windll_patch
    if not hasattr(ctypes, 'windll'):
        _windll_patch = patch.object(ctypes, 'windll', SimpleNamespace(user32=Mock()), create=True)
        _windll_patch.start()

def tearDownModule():
    if _windll_patch:
        _windll_patch.stop()

def auth(email, extra=None):
    payload={'email':email, 'exp':1900000000, 'https://api.openai.com/auth':extra or {}}
    middle=base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    return json.dumps({'tokens':{'id_token':'fixture.'+middle+'.not-signed','account_id':'fixture-'+email,
                                 'access_token':'synthetic-test-only',
                                 'refresh_token':'synthetic-test-only'}}).encode()

def limits():
    return {'rateLimits':{'planType':'plus','primary':{'usedPercent':74,'windowDurationMins':300,'resetsAt':1900000000},
             'secondary':{'usedPercent':92,'windowDurationMins':10080,'resetsAt':1900500000},'credits':{'balance':'12.50'}}}

class FakeQuery:
    def __init__(self): self.calls=[];self.fail=set();self.codes={};self.delay=0
    def run(self,email,current,usage=False,subscription=False,cancel=None):
        self.calls.append((email,current,usage))
        until=time.monotonic()+self.delay
        while time.monotonic()<until:
            if cancel and cancel.is_set():return {'email':email,'ok':False,'err':'paused','error_code':'cancelled'}
            time.sleep(.01)
        if email in self.fail or email in self.codes:return {'email':email,'ok':False,'err':'fixture failure','error_code':self.codes.get(email,'fixture')}
        if subscription:return {'ok':True,'status':'not_provided','date':None,'verified':False,'account_checked_online':True,'checked_at':int(time.time())}
        if usage:return normalize_usage({'summary':{'lifetimeTokens':42},'dailyUsageBuckets':None})
        return normalize_limits(limits(),email)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        self.paths=Paths(root,root/'codex')
        self.accounts=Accounts(self.paths)
        self.accounts.write(['a@example.com','b@example.com'])
        for email in self.accounts.all():atomic_bytes(self.paths.snapshot(email),auth(email))
        atomic_bytes(self.paths.auth,auth('a@example.com'))
        self.query=FakeQuery()
        self.service=Service(self.paths,self.query,self.runner)
    def test_early_anchor_selection_persists_only_plus_and_stays_optional(self):
        atomic_bytes(self.paths.snapshot('b@example.com'),
                     auth('b@example.com', {'chatgpt_plan_type': 'plus'}))
        before = self.paths.auth.read_bytes()
        self.assertFalse(self.service.state.get('settings')['early_anchor'])
        self.assertTrue(self.service.set_early_anchor_account('b@example.com', True)['ok'])
        self.assertFalse(self.service.set_early_anchor_account('a@example.com', True)['ok'])
        self.assertFalse(self.service.set_early_anchor_account('b@example.com', 'yes')['ok'])
        self.assertFalse(self.service._anchor_allowed('b@example.com'))
        self.assertTrue(self.service.set_preferences({'early_anchor': True})['ok'])
        self.assertTrue(self.service._anchor_allowed('b@example.com'))
        self.assertFalse(self.service._anchor_allowed('a@example.com'))
        self.assertEqual(State(self.paths).get('settings')['early_anchor_accounts'], ['b@example.com'])
        self.assertEqual(self.paths.auth.read_bytes(), before)

    def test_early_anchor_quota_update_preserves_other_accounts_and_reset_details(self):
        original = normalize_limits(limits(), 'a@example.com')
        original['banked_resets'] = {'available_count': 1, 'items': [{'title': 'fixture'}]}
        self.service.state.change('cache', lambda old: {'updated': 123, 'accounts': [
            original, {'email': 'b@example.com', 'ok': True}]})
        newer = normalize_limits(limits(), 'a@example.com')
        newer['windows'][0]['used'] = 0
        self.service._record_anchor_limits(newer)
        result = self.service.state.get('cache')
        self.assertEqual(result['updated'], 123)
        self.assertEqual(result['accounts'][0]['banked_resets'], original['banked_resets'])
        self.assertEqual(result['accounts'][0]['windows'][0]['used'], 0)
        self.assertEqual(result['accounts'][1], {'email': 'b@example.com', 'ok': True})

    def test_preheat_dispatch_yields_to_switch_and_resume_without_waiting(self):
        self.service.state.setting(early_anchor=True, early_anchor_accounts=['b@example.com'])
        with self.service._anchor_dispatch('b@example.com') as ready:
            self.assertTrue(ready)
            self.assertTrue(self.service.desktop_gate.locked())
        self.assertFalse(self.service.desktop_gate.locked())
        self.service.operation = {'kind': 'switch'}
        with self.service._anchor_dispatch('b@example.com') as ready:
            self.assertFalse(ready)
        self.service.operation = None
        self.service.desktop_gate.acquire()
        try:
            with self.service._anchor_dispatch('b@example.com') as ready:
                self.assertFalse(ready)
        finally:
            self.service.desktop_gate.release()

    def test_normal_refresh_updates_preheat_schedule(self):
        with patch.object(self.service.early_anchor, 'observe_limits') as observe:
            self.service._refresh(['b@example.com'])
        self.assertEqual(observe.call_count, 1)
        self.assertEqual(observe.call_args.args[0]['email'], 'b@example.com')
        self.assertTrue(observe.call_args.args[0]['ok'])

    def tearDown(self):
        self.service.stop.set()
        self.wait()
        for handler in list(self.service.log.handlers):
            self.service.log.removeHandler(handler)
            handler.close()
        self.tmp.cleanup()
    def wait(self,timeout=4):
        deadline=time.monotonic()+timeout
        while self.service.operation or self.service.gate.locked():
            if time.monotonic()>deadline:self.fail('operation did not finish')
            time.sleep(.015)
        time.sleep(.04)
        if self.service.operation:return self.wait(timeout)
    def runner(self,*args):
        if '-To' in args:atomic_bytes(self.paths.auth,self.paths.snapshot(args[-1]).read_bytes())
        elif '-Park' in args:
            email,_=identity(self.paths.auth)
            if email:atomic_bytes(self.paths.snapshot(email),self.paths.auth.read_bytes())
            self.paths.auth.unlink(missing_ok=True)
        elif '-Snapshot' in args:
            email,_=identity(self.paths.auth)
            atomic_bytes(self.paths.snapshot(email),self.paths.auth.read_bytes())
    def refresh(self):self.service.refresh();self.wait()

    def test_stale_relay_candidate_is_refreshed_and_selected(self):
        self.refresh()
        cache=self.service.state.get('cache')
        for a in cache['accounts']:
            a['fetched_at']=time.time()-601
        self.service.state.update(cache=cache)
        self.assertIsNone(self.service.get_data()['relay_email'])
        before=len(self.query.calls)
        self.assertTrue(self.service.refresh_stale_relay_accounts(self.service.get_data()))
        self.wait()
        self.assertEqual(len(self.query.calls)-before,2)
        self.assertEqual(self.service.get_data()['relay_email'],'b@example.com')
        self.assertFalse(self.service.refresh_stale_relay_accounts(self.service.get_data()))

    def test_failed_candidate_refresh_does_not_loop(self):
        self.refresh()
        cache=self.service.state.get('cache')
        for a in cache['accounts']:a['fetched_at']=time.time()-601
        self.service.state.update(cache=cache)
        self.query.fail=set(self.accounts.all())
        self.assertTrue(self.service.refresh_stale_relay_accounts(self.service.get_data()))
        self.wait()
        before=len(self.query.calls)
        self.assertFalse(self.service.refresh_stale_relay_accounts(self.service.get_data()))
        self.assertEqual(len(self.query.calls),before)

class StorageTests(Fixture):
    def test_identity(self):self.assertEqual(self.accounts.current(),'a@example.com')
    def test_no_chdir(self):
        before=os.getcwd();self.refresh();self.assertEqual(os.getcwd(),before)
    def test_atomic_state_settings_keep_cache(self):
        self.refresh();self.service.state.setting(notify_low=True);self.assertEqual(len(self.service.state.get('cache')['accounts']),2)
    def test_atomic_write_retries_transient_windows_reader_lock(self):
        target=self.paths.data/'retry.json';original=os.replace;attempts=[]
        def briefly_locked(source,destination):
            attempts.append(destination)
            if len(attempts)==1:raise PermissionError('fixture reader lock')
            return original(source,destination)
        with patch('nx.storage.os.replace',side_effect=briefly_locked):atomic_bytes(target,b'{"ok":true}')
        self.assertEqual(target.read_bytes(),b'{"ok":true}');self.assertEqual(len(attempts),2)
    def test_removed_settings_are_not_loaded(self):
        atomic_bytes(self.paths.data/'state.json',b'{"settings":{"obsolete":true,"theme":"orbit","relay_pick":"b@example.com","task_continuation":true,"auto_relay":true},"cache":{"updated":123,"accounts":[]}}')
        state=State(self.paths);self.assertNotIn('obsolete',state.get('settings'));self.assertNotIn('theme',state.get('settings'));self.assertNotIn('relay_pick',state.get('settings'));self.assertTrue(state.get('settings')['task_continuation']);self.assertTrue(state.get('settings')['auto_relay']);self.assertEqual(state.get('cache')['updated'],123)
        self.assertIn('task_continuation',json.loads((self.paths.data/'state.json').read_text(encoding='utf-8'))['settings'])
    def test_malformed_saved_continuation_settings_use_safe_defaults(self):
        atomic_bytes(self.paths.data/'state.json',
                     json.dumps({'settings':{'task_continuation':'false',
                                             'resume_message':'line one\nline two'}}).encode('utf-8'))
        settings=State(self.paths).get('settings')
        self.assertIs(settings['task_continuation'],False)
        self.assertEqual(settings['resume_message'],'继续')
    def test_email_path_traversal_rejected(self):
        for value in ('../../x','a/../b@example.com','a\\b@example.com','x:bad@example.com',None,'a@example.com\n'):
            with self.assertRaises(ValueError):safe_email(value)
    def test_order_and_comments_preserved(self):
        self.paths.order.write_text('# important\na@example.com\nb@example.com\n',encoding='utf-8')
        self.accounts.append('c@example.com');self.assertTrue(self.paths.order.read_text(encoding='utf-8').startswith('# important'))
    def test_duplicate_emails_removed(self):
        self.paths.order.write_text('a@example.com\nA@example.com\nb@example.com\n');self.assertEqual(len(self.accounts.all()),2)
    def test_archive_reversible(self):
        key=self.accounts.archive('b@example.com');self.assertNotIn('b@example.com',self.accounts.all())
        self.assertTrue((self.paths.snapshots/'removed'/key).exists())
        self.accounts.restore(key);self.assertIn('b@example.com',self.accounts.all())
    def test_readding_archived_identity_reactivates_without_duplicate_archive(self):
        key=self.accounts.archive('b@example.com');self.assertTrue((self.paths.snapshots/'removed'/key).exists())
        atomic_bytes(self.paths.snapshot('b@example.com'),auth('b@example.com'))
        self.accounts.activate('b@example.com')
        self.assertIn('b@example.com',self.accounts.all());self.assertFalse((self.paths.snapshots/'removed'/key).exists())
        self.assertFalse(any(item['email']=='b@example.com' for item in self.accounts.archived()))
    def test_archive_current_refused(self):
        with self.assertRaises(ValueError):self.accounts.archive('a@example.com')
    def test_archive_restore_no_overwrite(self):
        key=self.accounts.archive('b@example.com');atomic_bytes(self.paths.snapshot('b@example.com'),b'existing')
        with self.assertRaises(ValueError):self.accounts.restore(key)
        self.assertEqual(self.paths.snapshot('b@example.com').read_bytes(),b'existing')
    def test_restore_path_rejected(self):
        for key in ('../auth.json','..\\auth.json','/tmp/auth.json'):
            with self.assertRaises(ValueError):self.accounts.restore(key)
    def test_token_exp_not_subscription(self):
        meta=credential_metadata(self.paths.auth);self.assertIsNone(meta['subscription']['until']);self.assertEqual(meta['id_token_expires_at'],1900000000)
    def test_claim_subscription_explicit_unverified(self):
        atomic_bytes(self.paths.auth,auth('a@example.com',{'chatgpt_subscription_active_until':'2027-01-01T00:00:00Z'}))
        meta=credential_metadata(self.paths.auth);self.assertFalse(meta['subscription']['verified']);self.assertEqual(meta['subscription']['source'],'credential_hint')
    def test_bad_date_unknown(self):
        for v in (True,'tomorrow','2027-01-01T00:00:00',-3,None):self.assertIsNone(timestamp(v))
    def test_public_state_no_tokens(self):
        self.refresh();public=json.dumps(self.service.get_data());self.assertNotIn('synthetic-test-only',public);self.assertNotIn('fixture.',public)

class TransactionTests(Fixture):
    def test_manual_switch_without_quota_never_queries_the_network(self):
        with patch.object(self.query, 'run', side_effect=AssertionError('manual switch queried HTTP')) as query:
            self.assertTrue(self.service.switch('b@example.com')['accepted'])
            self.wait()
            query.assert_not_called()
        self.assertTrue(self.service.last_result['ok'])
        self.assertEqual(self.accounts.current(), 'b@example.com')

    def test_manual_switch_ignores_stale_exhausted_quota_and_keeps_it_visible(self):
        target = normalize_limits(limits(), 'b@example.com')
        target.update(ok=False, error_code='network', fetched_at=time.time()-1800,
                      paused=False, retry_at=time.time()+900)
        target['windows'][1]['used'] = 100
        self.service._store_quota(target)
        before = self.service.state.get('cache')['accounts']
        with patch.object(self.query, 'run') as query:
            self.service.switch('b@example.com'); self.wait()
            query.assert_not_called()
        self.assertTrue(self.service.last_result['ok'])
        self.assertEqual(self.accounts.current(), 'b@example.com')
        self.assertEqual(self.service.state.get('cache')['accounts'], before)

    def test_manual_switch_does_not_depend_on_query_policy_or_server_status(self):
        real = Query(self.paths, lambda: self.service.state.get('settings'))
        self.service.query = real
        for code in ('network', 'timeout', 429, 403, 'reauth_required', 'query_policy_unavailable'):
            with self.subTest(code=code):
                atomic_bytes(self.paths.auth, auth('a@example.com'))
                with patch.object(real, 'run', side_effect=AssertionError('manual query')) as query, \
                        patch.object(real, 'status', return_value={
                            'ready':False, 'paused':True, 'error_code':code}) as status:
                    self.service.switch('b@example.com'); self.wait()
                    query.assert_not_called()
                    status.assert_not_called()
                self.assertTrue(self.service.last_result['ok'])
                self.assertEqual(self.accounts.current(), 'b@example.com')

    def test_manual_switch_rejects_missing_corrupt_or_wrong_local_identity(self):
        original = self.paths.auth.read_bytes()
        for saved in (None, b'not json', b'[]', auth('other@example.com'),
                      json.dumps({'tokens':{'access_token':'fixture'}}).encode()):
            with self.subTest(saved=saved):
                path = self.paths.snapshot('b@example.com')
                if saved is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_bytes(path, saved)
                with patch.object(self.service, 'runner') as switch, patch.object(self.query, 'run') as query:
                    self.service.switch('b@example.com'); self.wait()
                    switch.assert_not_called(); query.assert_not_called()
                self.assertFalse(self.service.last_result['ok'])
                self.assertEqual(self.paths.auth.read_bytes(), original)

    def test_manual_switch_rejects_incomplete_local_login(self):
        saved = json.loads(auth('b@example.com'))
        original = self.paths.auth.read_bytes()
        for token in (None, '', 1):
            with self.subTest(token=token):
                saved['tokens']['access_token'] = token
                atomic_bytes(self.paths.snapshot('b@example.com'), json.dumps(saved).encode())
                with patch.object(self.service, 'runner') as switch:
                    self.service.switch('b@example.com'); self.wait()
                    switch.assert_not_called()
                self.assertFalse(self.service.last_result['ok'])
                self.assertEqual(self.paths.auth.read_bytes(), original)

    def test_manual_switch_to_current_account_does_nothing(self):
        with patch.object(self.service, 'runner') as switch, patch.object(self.query, 'run') as query:
            result = self.service.switch('a@example.com')
            self.assertTrue(result['already_current'])
            switch.assert_not_called(); query.assert_not_called()

    def test_hotkey_switch_preempts_interruptible_refresh(self):
        self.query.delay = .2
        self.service.refresh(background=True); time.sleep(.03)
        host = SimpleNamespace(service=self.service, icon=Mock())
        Desktop.hotkey_switch(host, 'b@example.com')
        self.wait()
        self.assertEqual(self.accounts.current(), 'b@example.com')
        self.assertTrue(self.service.last_result['ok'])
        host.icon.notify.assert_not_called()

    def test_hotkey_switch_keeps_another_account_operation_intact(self):
        started, release = threading.Event(), threading.Event()
        def operation():
            started.set(); release.wait(2)
        self.service.begin('snapshot', None, operation)
        self.assertTrue(started.wait(1))
        try:
            host = SimpleNamespace(service=self.service, icon=Mock())
            Desktop.hotkey_switch(host, 'b@example.com')
            self.assertEqual(self.accounts.current(), 'a@example.com')
            host.icon.notify.assert_called_once()
        finally:
            release.set(); self.wait()

    def test_temporary_failure_keeps_zero_and_recovery_request(self):
        self.refresh()
        target = next(a for a in self.service.state.get('cache')['accounts'] if a['email']=='b@example.com')
        target['windows'][0]['used'] = 100
        self.service._record_anchor_limits(target)
        self.query.codes['b@example.com'] = 'network'
        self.service._refresh('b@example.com')
        shown = next(a for a in self.service.get_data()['accounts'] if a['email']=='b@example.com')
        self.assertEqual(shown['windows'][0]['used'], 100)
        self.assertEqual(shown['credits'], '12.50')
        self.assertEqual(self.service.set_relay_pick('b@example.com')['mode'], 'waiting')
        self.assertEqual(self.service.state.get('relay_wait')['origin'], 'a@example.com')
        self.assertIsNone(self.service.get_data()['relay_email'])

    def test_switch_with_known_quota_survives_temporary_preflight_failure(self):
        self.refresh()
        self.query.codes['b@example.com'] = 'network'
        self.assertTrue(self.service.switch('b@example.com')['accepted'])
        self.wait()
        self.assertTrue(self.service.last_result['ok'])
        self.assertEqual(self.accounts.current(), 'b@example.com')

    def test_relay_cached_quota_does_not_bypass_login_or_permission_failures(self):
        self.refresh()
        for code in (403, 'identity_mismatch', 'missing_snapshot', 'reauth_required'):
            with self.subTest(code=code):
                self.query.codes['b@example.com'] = code
                self.assertTrue(self.service._switch('b@example.com', 'relay')['accepted'])
                self.wait()
                self.assertFalse(self.service.last_result['ok'])
                self.assertEqual(self.accounts.current(), 'a@example.com')
                self.service.state.update(reauth=None)

    def test_all_failed_refresh_does_not_report_success_or_advance_updated(self):
        self.refresh()
        old = int(time.time())-120
        self.service.state.change('cache', lambda cache: {**cache, 'updated':old})
        self.query.codes = {email:'network' for email in self.accounts.all()}
        self.service.refresh(); self.wait()
        self.assertEqual(self.service.get_data()['updated'], old)
        self.assertFalse(self.service.last_result['ok'])

    def test_other_account_refresh_cannot_overwrite_preheat_result(self):
        self.refresh()
        started, release = threading.Event(), threading.Event()
        original = self.query.run
        def query(email, *args, **kwargs):
            result = original(email, *args, **kwargs)
            started.set(); release.wait(3)
            return result
        self.query.run = query
        worker = threading.Thread(target=self.service._refresh, args=('a@example.com',))
        worker.start()
        try:
            self.assertTrue(started.wait(2))
            value = normalize_limits(limits(), 'b@example.com')
            value['windows'][0]['used'] = 0
            value['fetched_at'] = time.time()
            self.service._record_anchor_limits(value)
        finally:
            release.set(); worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(next(a for a in self.service.get_data()['accounts'] if a['email']=='b@example.com')['windows'][0]['used'], 0)

    def test_late_older_read_of_same_account_cannot_overwrite_preheat(self):
        self.refresh()
        older = normalize_limits(limits(), 'b@example.com')
        newer = json.loads(json.dumps(older))
        newer['windows'][0]['used'] = 0
        newer['fetched_at'] = older['fetched_at'] + .5
        self.service._record_anchor_limits(newer)
        self.query.run = lambda *args, **kwargs: older
        self.service._refresh('b@example.com')
        self.assertEqual(next(a for a in self.service.get_data()['accounts'] if a['email']=='b@example.com')['windows'][0]['used'], 0)

    def test_refresh_progress_and_cache(self):
        self.refresh();data=self.service.get_data();self.assertTrue(all(a['ok'] for a in data['accounts']));self.assertEqual(data['current'],'a@example.com')
    def test_partial_failure_preserves_old_timestamp(self):
        self.refresh();old=self.service.get_data()['accounts'][1]['fetched_at'];self.query.fail.add('b@example.com');self.refresh()
        b=self.service.get_data()['accounts'][1];self.assertFalse(b['ok']);self.assertEqual(b['fetched_at'],old);self.assertEqual(len(b['windows']),2)
    def test_single_refresh_queries_one(self):
        self.refresh();self.query.calls=[];self.service.refresh('b@example.com');self.wait();self.assertEqual(len(self.query.calls),1)
    def test_default_refresh_updates_all_current_first(self):
        self.refresh();self.query.calls=[]
        self.service.refresh();self.wait()
        self.assertEqual([c[0] for c in self.query.calls], ['a@example.com','b@example.com'])
    def test_switch_verified_then_commit(self):
        self.refresh();self.query.calls=[];r=self.service.switch('b@example.com');self.assertTrue(r['ok']);self.wait();self.assertEqual(self.service.get_data()['current'],'b@example.com');self.assertEqual(self.query.calls,[])
    def test_relay_preflight_keeps_working_account_when_target_needs_login(self):
        self.query.codes['b@example.com']='reauth_required'
        self.service._switch('b@example.com', 'relay');self.wait()
        data=self.service.get_data();self.assertEqual(data['current'],'a@example.com')
        self.assertEqual(data['reauth']['email'],'b@example.com');self.assertEqual(data['reauth']['phase'],'ready')
        self.assertFalse(self.service.last_result['ok'])
    def test_no_false_switch_success(self):
        self.refresh();self.service.runner=lambda *a:None;self.service.switch('b@example.com');self.wait()
        self.assertEqual(self.service.get_data()['current'],'a@example.com');self.assertFalse(self.service.last_result['ok'])
    def test_switch_exception_retains_current(self):
        self.refresh()
        def failed(*a):raise RuntimeError('fixture failure')
        self.service.runner=failed;self.service.switch('b@example.com');self.wait()
        self.assertEqual(self.accounts.current(),'a@example.com');self.assertIsNotNone(self.service.last_error)
    def test_switch_preempts_running_refresh(self):
        self.query.delay=.2;self.service.refresh();time.sleep(.03);result=self.service.switch('b@example.com');self.assertTrue(result['accepted']);self.wait()
    def test_background_refresh_continues_while_panel_is_open(self):
        result=self.service.refresh(background=True);self.assertTrue(result['accepted']);self.wait();self.assertTrue(all(a['ok'] for a in self.service.get_data()['accounts']))
    def test_foreground_refresh_preempts_background_cleanup(self):
        self.query.delay=.25;self.service.refresh(background=True);time.sleep(.03)
        result=self.service.refresh();self.assertTrue(result['accepted']);self.wait()
    def test_add_cancel_restores_original(self):
        self.service.add_start();self.wait();self.assertFalse(self.paths.auth.exists());self.assertTrue(self.service.get_data()['adding'])
        self.service.add_cancel();self.wait();self.assertEqual(self.accounts.current(),'a@example.com');self.assertFalse(self.service.get_data()['adding'])
    def test_add_login_waits_for_inflight_desktop_continuation(self):
        original=self.service.runner;called=[]
        def runner(*args):
            called.append(args)
            return original(*args)
        self.service.runner=runner
        with self.service.desktop_gate:
            result=self.service.add_start();self.assertTrue(result['accepted'])
            time.sleep(.05)
            self.assertEqual(called,[])
        self.wait()
        self.assertEqual(called[0],('-Park',))
    def test_add_finish_snapshots_and_appends(self):
        self.service.add_start();self.wait();atomic_bytes(self.paths.auth,auth('new@example.com'));self.service.add_finish();self.wait()
        self.assertIn('new@example.com',self.accounts.all());self.assertTrue(self.paths.snapshot('new@example.com').exists());self.assertFalse(self.service.get_data()['adding'])
    def test_finish_without_login_is_recoverable(self):
        self.service.add_start();self.wait();result=self.service.add_finish();self.assertFalse(result['ok']);self.assertTrue(self.service.get_data()['adding'])
    def test_add_blocks_switch(self):
        self.service.add_start();self.wait();self.assertFalse(self.service.switch('b@example.com')['ok'])
    def test_add_state_survives_service_restart(self):
        self.service.add_start();self.wait();state=State(self.paths);self.assertEqual(state.get('adding')['previous'],'a@example.com')
    def test_reauth_cancel_before_login_does_not_switch(self):
        self.service.state.update(reauth={'email':'b@example.com','previous':'a@example.com','phase':'ready'})
        result=self.service.reauth_cancel();self.assertFalse(result['accepted'])
        self.assertIsNone(self.service.get_data()['reauth']);self.assertEqual(self.accounts.current(),'a@example.com')
    def test_reauth_flow_verifies_identity_and_saves_snapshot(self):
        self.service.reauth_start('b@example.com');self.wait();self.assertFalse(self.paths.auth.exists())
        atomic_bytes(self.paths.auth,auth('b@example.com'))
        self.service.reauth_finish();self.wait()
        self.assertIsNone(self.service.get_data()['reauth']);self.assertEqual(self.accounts.current(),'b@example.com')
    def test_reauth_wrong_account_never_overwrites_target(self):
        original=self.paths.snapshot('b@example.com').read_bytes()
        self.service.reauth_start('b@example.com');self.wait();atomic_bytes(self.paths.auth,auth('other@example.com'))
        self.service.reauth_finish();self.wait()
        self.assertIsNotNone(self.service.get_data()['reauth']);self.assertEqual(self.paths.snapshot('b@example.com').read_bytes(),original)
    def test_unknown_switch_rejected(self):self.assertFalse(self.service.switch('other@example.com')['ok'])
    def test_add_login_status_tracks_external_login(self):
        self.service.state.update(adding={'previous':'a@example.com','phase':'login'})
        self.paths.auth.unlink();self.assertEqual(self.service.get_data()['add_login_status'],'waiting')
        atomic_bytes(self.paths.auth,auth('a@example.com'));self.assertEqual(self.service.get_data()['add_login_status'],'unchanged')
        atomic_bytes(self.paths.auth,auth('b@example.com'));self.assertEqual(self.service.get_data()['add_login_status'],'existing')
        atomic_bytes(self.paths.auth,auth('new@example.com'));self.assertEqual(self.service.get_data()['add_login_status'],'ready')
    def test_add_finish_refuses_incomplete_or_existing_login(self):
        self.service.state.update(adding={'previous':'a@example.com','phase':'login'})
        self.paths.auth.unlink();self.assertIn('尚未检测到',self.service.add_finish()['error'])
        atomic_bytes(self.paths.auth,auth('b@example.com'));self.assertIn('已经在清单',self.service.add_finish()['error'])
    def test_settings_whitelist(self):
        self.assertFalse(self.service.set_preferences({'unknown':True})['ok']);self.assertFalse(self.service.set_preferences({'theme':'<script>'})['ok'])
        self.assertFalse(self.service.set_preferences({'theme':'orbit'})['ok'])
        self.assertFalse(self.service.set_preferences({'relay_pick':'b@example.com'})['ok'])
        self.assertFalse(self.service.set_preferences({'panel_mode':'compact'})['ok'])
        self.assertNotIn('panel_mode',self.service.state.get('settings'))
        self.assertFalse(self.service.set_preferences({'panel_mode':'tiny'})['ok'])
        self.assertTrue(self.service.set_preferences({'auto_relay':True})['ok'])
        self.assertTrue(self.service.state.get('settings')['auto_relay'])
        self.assertTrue(self.service.set_preferences({'task_continuation':False})['ok'])
        self.assertFalse(self.service.get_data()['settings']['task_continuation'])
        self.assertFalse(self.service.set_preferences({'resume_message':''})['ok'])
        self.assertFalse(self.service.set_preferences({'resume_message':'x\ny'})['ok'])
        self.assertFalse(self.service.set_preferences({'resume_message':'x'*201})['ok'])
        self.assertTrue(self.service.set_preferences({'resume_message':'请接着完成上个任务'})['ok'])
        self.assertEqual(self.service.get_data()['settings']['resume_message'],'请接着完成上个任务')
    def test_relay_pick_is_one_shot_and_never_persisted(self):
        self.assertTrue(self.service.set_relay_pick('b@example.com')['ok'])
        self.assertEqual(self.service.get_data()['settings']['relay_pick'],'b@example.com')
        self.assertNotIn('relay_pick',self.service.state.get('settings'))
        result=self.service.switch('b@example.com');self.assertTrue(result['accepted'])
        self.assertIsNone(self.service.get_data()['settings']['relay_pick']);self.wait()
    def test_relay_pick_rejects_current_account(self):
        self.assertFalse(self.service.set_relay_pick('a@example.com')['ok'])
    def exhaust_next(self, windows=(0,)):
        self.refresh()
        cache=self.service.state.get('cache')
        target=next(a for a in cache['accounts'] if a['email']=='b@example.com')
        for index in windows:target['windows'][index]['used']=100
        self.service.state.update(cache=cache)
    def recover_next(self):
        with patch('nx.desktop.chatgpt_running',return_value=True):
            return self.service.relay_when_recovered()
    def test_exhausted_next_creates_persisted_recovery_request(self):
        self.exhaust_next()
        result=self.service.set_relay_pick('b@example.com')
        self.assertEqual(result['mode'],'waiting')
        waiting=self.service.get_data()['relay_wait']
        self.assertEqual(waiting['origin'],'a@example.com')
        self.assertEqual(waiting,State(self.paths).get('relay_wait'))
        self.assertIsNone(self.service.get_data()['settings']['relay_pick'])
        self.assertEqual(self.accounts.current(),'a@example.com')
    def test_recovery_wait_can_be_cancelled_without_switching(self):
        self.exhaust_next()
        self.service.set_relay_pick('b@example.com')
        self.assertEqual(self.service.set_relay_pick()['mode'],'cancelled')
        self.refresh()
        self.assertEqual(self.recover_next()['reason'],'no_request')
        self.assertEqual(self.accounts.current(),'a@example.com')
        self.assertIsNone(State(self.paths).get('relay_wait'))
    def test_recovery_request_waits_for_both_quota_windows(self):
        self.exhaust_next((0,1))
        self.service.set_relay_pick('b@example.com')
        cache=self.service.state.get('cache')
        next(a for a in cache['accounts'] if a['email']=='b@example.com')['windows'][0]['used']=20
        self.service.state.update(cache=cache)
        self.assertEqual(self.recover_next()['reason'],'waiting')
        self.assertEqual(self.accounts.current(),'a@example.com')
        self.assertIsNotNone(self.service.state.get('relay_wait'))
    def test_verified_recovery_relays_once_even_when_automatic_rotation_is_off(self):
        self.exhaust_next()
        self.service.set_relay_pick('b@example.com')
        self.refresh()
        self.assertFalse(self.service.state.get('settings')['auto_relay'])
        with patch('nx.desktop.chatgpt_running',return_value=True):
            result=self.recover_next()
        self.assertTrue(result['accepted'])
        self.assertEqual(result['source'],'recovery')
        self.wait()
        self.assertEqual(self.accounts.current(),'b@example.com')
        self.assertIsNone(self.service.state.get('relay_wait'))
        self.assertEqual(self.recover_next()['reason'],'no_request')
    def test_reset_time_alone_refreshes_instead_of_switching(self):
        self.exhaust_next()
        self.service.set_relay_pick('b@example.com')
        cache=self.service.state.get('cache')
        target=next(a for a in cache['accounts'] if a['email']=='b@example.com')
        target['windows'][0]['resets_at']=time.time()-1
        self.service.state.update(cache=cache)
        with patch('nx.desktop.chatgpt_running',return_value=True):
            result=self.recover_next()
        self.assertEqual(result['reason'],'refreshing')
        self.wait()
        self.assertEqual(self.accounts.current(),'a@example.com')
        self.assertIsNotNone(self.service.state.get('relay_wait'))
    def test_paused_query_cannot_execute_recovery_request(self):
        self.exhaust_next()
        self.service.set_relay_pick('b@example.com')
        self.refresh()
        with patch('nx.desktop.chatgpt_running',return_value=True),patch.object(self.service,'_query_ready',return_value=False):
            self.assertEqual(self.recover_next()['reason'],'query_paused')
        self.assertEqual(self.accounts.current(),'a@example.com')
    def test_recovery_rechecks_online_quota_before_switching(self):
        self.exhaust_next()
        self.service.set_relay_pick('b@example.com')
        self.refresh()
        original=self.query.run
        def exhausted_online(*args,**kwargs):
            result=original(*args,**kwargs)
            result['windows'][1]['used']=100
            return result
        with patch('nx.desktop.chatgpt_running',return_value=True),patch.object(self.query,'run',side_effect=exhausted_online):
            self.assertTrue(self.recover_next()['accepted'])
            self.wait()
        self.assertFalse(self.service.last_result['ok'])
        self.assertEqual(self.accounts.current(),'a@example.com')
        self.assertIsNotNone(self.service.state.get('relay_wait'))
    def test_cancelling_during_recovery_preflight_prevents_switch(self):
        self.exhaust_next()
        self.service.set_relay_pick('b@example.com')
        self.refresh()
        entered,release=threading.Event(),threading.Event()
        original=self.query.run
        def preflight(*args,**kwargs):
            entered.set();release.wait(3)
            return original(*args,**kwargs)
        runner=Mock(side_effect=self.runner)
        self.service.runner=runner
        with patch('nx.desktop.chatgpt_running',return_value=True),patch.object(self.query,'run',side_effect=preflight):
            self.assertTrue(self.recover_next()['accepted'])
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(self.service.set_relay_pick()['mode'],'cancelled')
            finally:release.set()
            self.wait()
        runner.assert_not_called()
        self.assertEqual(self.accounts.current(),'a@example.com')
        self.assertIsNone(self.service.state.get('relay_wait'))
    def test_switching_manually_cancels_recovery_request(self):
        self.exhaust_next()
        self.service.set_relay_pick('b@example.com')
        self.assertTrue(self.service.switch('b@example.com')['accepted'])
        self.wait()
        self.assertIsNone(self.service.state.get('relay_wait'))
    def test_changed_current_account_invalidates_recovery_request(self):
        self.exhaust_next()
        self.service.set_relay_pick('b@example.com')
        self.runner('-To','b@example.com')
        self.assertEqual(self.recover_next()['reason'],'request_obsolete')
        self.assertIsNone(self.service.state.get('relay_wait'))
    def test_archiving_target_invalidates_recovery_request(self):
        self.exhaust_next()
        self.service.set_relay_pick('b@example.com')
        self.accounts.archive('b@example.com')
        self.assertEqual(self.recover_next()['reason'],'request_obsolete')
        self.assertIsNone(self.service.state.get('relay_wait'))
    def test_invalid_persisted_recovery_requests_are_dropped(self):
        for invalid in (True,{}, {'id':'bad','email':'b@example.com','origin':'a@example.com'},
                        {'id':'0'*32,'email':'a@example.com','origin':'a@example.com'}):
            self.service.state.update(relay_wait=invalid)
            self.assertIsNone(State(self.paths).get('relay_wait'))
    def test_relay_path_is_distinct_and_uses_canonical_candidate(self):
        self.refresh();self.wait()
        self.assertEqual(self.service.get_data()['relay_email'],'b@example.com')
        result=self.service.relay('b@example.com');self.assertTrue(result['accepted']);self.assertEqual(result['source'],'relay');self.wait()
        self.assertEqual(self.accounts.current(),'b@example.com')
    def test_next_baton_switch_queues_exact_task_after_preflight(self):
        self.refresh()
        candidate={'thread_id':'67cc833f-6330-5bae-a638-9232b5ddfa21',
                   'turn_id':'42d1e863-8084-556e-a03c-d7c800c7055b','was_active':True}
        with patch('nx.desktop_resume.active_turns',return_value=[candidate]) as snapshot:
            result=self.service.relay('b@example.com')
            self.assertTrue(result['accepted'])
            self.wait()
        snapshot.assert_called_once_with(self.paths.home)
        session=self.service.resumer.sessions[-1]
        self.assertEqual(self.service.last_result['resume_session_id'],session['id'])
        self.assertEqual(self.service.last_result['id'],result['operation_id'])
        self.assertEqual(session['phase'],'resuming')
        self.assertEqual(session['target'],'b@example.com')
        self.assertEqual(session['items'][0]['thread_id'],candidate['thread_id'])
        self.assertTrue((self.paths.data/'resume.json').exists())
    def test_direct_switch_queues_task_in_same_desktop_session(self):
        candidate={'thread_id':'ea10a953-d3a4-53b9-b010-6361794c2a22',
                   'turn_id':'db166421-27b4-561d-8583-670c674e9cad','was_active':True}
        with patch('nx.desktop_resume.active_turns',return_value=[candidate]) as snapshot:
            result=self.service.switch('b@example.com')
            self.assertTrue(result['accepted'])
            self.wait()
        snapshot.assert_called_once_with(self.paths.home)
        self.assertEqual(self.service.resumer.sessions[-1]['source'],'manual')
        self.assertEqual(self.service.resumer.sessions[-1]['items'][0]['thread_id'],candidate['thread_id'])
    def test_continuation_switch_off_skips_task_snapshot_but_keeps_relay(self):
        self.service.set_preferences({'task_continuation':False})
        with patch('nx.desktop_resume.active_turns') as snapshot:
            result=self.service.switch('b@example.com')
            self.assertTrue(result['accepted']);self.wait()
        snapshot.assert_not_called()
        self.assertEqual(self.accounts.current(),'b@example.com')
        self.assertEqual(self.service.resumer.sessions,[])
        self.assertIsNone(self.service.last_result['resume_session_id'])
    def test_auto_relay_still_switches_when_task_continuation_is_off(self):
        self.refresh();cache=self.service.state.get('cache');now=int(time.time())
        current=next(a for a in cache['accounts'] if a['email']=='a@example.com')
        current['fetched_at']=now;current['windows'][1]['used']=100
        self.service.state.update(cache=cache)
        self.service.set_preferences({'auto_relay':True,'task_continuation':False})
        with patch('nx.desktop_resume.active_turns') as snapshot:
            result=self.service.auto_relay_if_needed()
            self.assertTrue(result['accepted']);self.wait()
        snapshot.assert_not_called()
        self.assertEqual(self.accounts.current(),'b@example.com')
        self.assertEqual(self.service.resumer.sessions,[])
    def test_auto_relay_is_disabled_by_default(self):
        self.refresh();result=self.service.auto_relay_if_needed()
        self.assertFalse(result['accepted']);self.assertEqual(result['reason'],'disabled_or_busy')
    def test_auto_relay_retries_after_failed_switch(self):
        self.refresh();cache=self.service.state.get('cache');now=int(time.time())
        current=next(a for a in cache['accounts'] if a['email']=='a@example.com')
        current['fetched_at']=now;current['windows'][0]['used']=100;current['windows'][0]['resets_at']=now+3600
        self.service.state.update(cache=cache);self.service.set_preferences({'auto_relay':True})
        def failed(*args):raise RuntimeError('fixture launch failure')
        self.service.runner=failed
        first=self.service.auto_relay_if_needed();self.assertTrue(first['accepted']);self.assertEqual(first['source'],'auto');self.wait()
        self.assertIsNone(self.service.auto_relay_attempt)
        second=self.service.auto_relay_if_needed();self.assertFalse(second['accepted']);self.assertEqual(second['reason'],'cooldown')
        self.service.auto_relay_retry_after=0;self.service.runner=self.runner
        third=self.service.auto_relay_if_needed();self.assertTrue(third['accepted']);self.wait()
        self.assertEqual(self.accounts.current(),'b@example.com')
    def test_weekly_exhaustion_triggers_with_five_hour_quota_left(self):
        self.refresh();cache=self.service.state.get('cache');now=int(time.time())
        current=next(a for a in cache['accounts'] if a['email']=='a@example.com')
        current['fetched_at']=now;current['windows'][0]['used']=10;current['windows'][1]['used']=100
        self.service.state.update(cache=cache);self.service.set_preferences({'auto_relay':True})
        result=self.service.auto_relay_if_needed();self.assertTrue(result['accepted']);self.wait()
        self.assertEqual(self.accounts.current(),'b@example.com')
    def test_stale_exhaustion_does_not_switch_without_limit_event(self):
        self.refresh();cache=self.service.state.get('cache')
        current=next(a for a in cache['accounts'] if a['email']=='a@example.com')
        current['fetched_at']=int(time.time())-601;current['windows'][1]['used']=100
        self.service.state.update(cache=cache);self.service.set_preferences({'auto_relay':True})
        result=self.service.auto_relay_if_needed();self.assertEqual(result['reason'],'refreshing_candidates')
        self.wait();self.assertEqual(self.accounts.current(),'a@example.com')
    def test_limit_event_relay_bypasses_stale_current_quota(self):
        self.refresh();self.service.set_preferences({'auto_relay':True})
        result=self.service.auto_relay_on_usage_limit('a@example.com')
        self.assertTrue(result['accepted']);self.assertEqual(result['source'],'auto-limit');self.wait()
        self.assertEqual(self.accounts.current(),'b@example.com')
    def test_auto_relay_account_selection_does_not_change_manual_relay(self):
        self.refresh();self.service.set_preferences({'auto_relay':True})
        self.assertEqual(self.service.get_data()['auto_relay_email'],'b@example.com')
        self.assertTrue(self.service.set_auto_relay_account('b@example.com',False)['ok'])
        data=self.service.get_data()
        self.assertIsNone(data['auto_relay_email'])
        self.assertEqual(data['relay_email'],'b@example.com')
        self.assertTrue(self.service.set_auto_relay_account('b@example.com',True)['ok'])
        self.assertTrue(self.service.set_auto_relay_account('a@example.com',False)['ok'])
        self.assertEqual(self.service.auto_relay_if_needed()['reason'],'excluded')
        self.assertIsNone(self.service.get_data()['auto_relay_email'])
    def test_no_candidate_waits_then_relay_resumes_original_task(self):
        self.refresh();self.service.set_preferences({'auto_relay':True})
        cache=self.service.state.get('cache')
        next_account=next(a for a in cache['accounts'] if a['email']=='b@example.com')
        next_account['windows'][1]['used']=100
        self.service.state.update(cache=cache)
        event={'thread_id':'67cc833f-6330-5bae-a638-9232b5ddfa21',
               'turn_id':'42d1e863-8084-556e-a03c-d7c800c7055b'}
        self.service.resumer.note_limit_events([event],'a@example.com',True)
        pending=self.service.resumer.pending[0]
        self.assertIsNone(pending['expires_at'])
        self.assertEqual(self.service.auto_relay_on_usage_limit('a@example.com',
            self.service.resumer.limit_groups()['a@example.com']['events'])['reason'],'no_candidate')
        self.service.resumer.defer_limit('a@example.com',60,refreshed=False)
        self.assertNotIn('a@example.com',self.service.resumer.limit_groups())
        self.refresh()
        self.assertIn('a@example.com',self.service.resumer.limit_groups())
        with patch('nx.desktop_resume.active_turns',return_value=[]):
            result=self.service.auto_relay_on_usage_limit('a@example.com',
                self.service.resumer.limit_groups()['a@example.com']['events'])
            self.assertTrue(result['accepted']);self.wait()
        self.assertEqual(self.accounts.current(),'b@example.com')
        self.assertEqual(self.service.resumer.pending,[])
        self.assertEqual(self.service.resumer.sessions[-1]['items'][0]['thread_id'],event['thread_id'])
    def test_waiting_uses_earliest_eligible_reset_without_short_poll(self):
        now=time.time()
        accounts=[
            {'email':'a@example.com','fetched_at':now-60,'windows':[
                {'used':100,'resets_at':now+18000},{'used':30,'resets_at':now+600000}]},
            {'email':'b@example.com','fetched_at':now-60,'windows':[
                {'used':100,'resets_at':now+9000},{'used':100,'resets_at':now+70000}]},
            {'email':'c@example.com','fetched_at':now-60,'windows':[
                {'used':100,'resets_at':now+12000}]},
        ]
        self.assertEqual(Service._next_relay_reset_at(accounts, now=now),now+12000)
        self.assertEqual(Service._next_relay_reset_at(accounts,['c@example.com'],now),now+18000)
        accounts[2]['windows'][0]['resets_at']=now-1
        self.assertEqual(Service._next_relay_reset_at(accounts,now=now),now)
        accounts[2]['attempted_at']=now
        self.assertEqual(Service._next_relay_reset_at(accounts,now=now),now+18000)
        accounts[0]['attempted_at']='invalid'
        self.assertEqual(Service._next_relay_reset_at(accounts,now=now),now+18000)
    def test_unconfirmed_current_quota_does_not_steal_waiting_task(self):
        self.refresh();self.service.set_preferences({'auto_relay':True})
        cache=self.service.state.get('cache')
        next(a for a in cache['accounts'] if a['email']=='b@example.com')['windows'][1]['used']=100
        self.service.state.update(cache=cache)
        event={'thread_id':'67cc833f-6330-5bae-a638-9232b5ddfa21',
               'turn_id':'42d1e863-8084-556e-a03c-d7c800c7055b'}
        self.service.resumer.note_limit_events([event],'a@example.com',True)
        self.service.resumer.defer_limit('a@example.com',0,refreshed=True)
        result=self.service.auto_relay_on_usage_limit('a@example.com',
            self.service.resumer.limit_groups()['a@example.com']['events'])
        self.assertEqual(result['reason'],'no_candidate')
        self.assertEqual(len(self.service.resumer.pending),1)
    def test_limit_event_never_switches_a_different_current_account(self):
        self.refresh();self.service.set_preferences({'auto_relay':True})
        result=self.service.auto_relay_on_usage_limit('old@example.com')
        self.assertFalse(result['accepted']);self.assertEqual(result['reason'],'current_changed')
    def test_late_limit_event_is_attributed_to_original_switch_session(self):
        self.refresh();cache=self.service.state.get('cache');now=int(time.time())
        current=next(a for a in cache['accounts'] if a['email']=='a@example.com')
        current['fetched_at']=now;current['windows'][0]['used']=100
        current['windows'][0]['resets_at']=now+3600
        self.service.state.update(cache=cache)
        self.service.set_preferences({'auto_relay':True})
        result=self.service.auto_relay_if_needed();self.assertTrue(result['accepted']);self.wait()
        event={'thread_id':'67cc833f-6330-5bae-a638-9232b5ddfa21',
               'turn_id':'42d1e863-8084-556e-a03c-d7c800c7055b',
               'started_at':int(self.service.last_result['started_at'])-10,
               'completed_at':int(self.service.last_result['started_at'])}
        self.service.resumer.note_limit_events([event],'b@example.com',True)
        related=self.service.resumer.sessions[-1]
        self.assertEqual(related['source'],'auto')
        self.assertEqual(related['items'][0]['thread_id'],event['thread_id'])
        self.assertEqual(self.accounts.current(),'b@example.com')
        self.assertEqual(self.service.resumer.pending,[])
    def test_relay_ranking_uses_bottleneck_instead_of_week_alone(self):
        now=int(time.time())+3600
        accounts=[
            {'email':'full@example.com','ok':True,'fetched_at':int(time.time()),'windows':[{'label':'5h','duration_mins':300,'used':0,'resets_at':now},{'label':'周','duration_mins':10080,'used':88,'resets_at':now}]},
            {'email':'week@example.com','ok':True,'fetched_at':int(time.time()),'windows':[{'label':'5h','duration_mins':300,'used':54,'resets_at':now},{'label':'周','duration_mins':10080,'used':8,'resets_at':now}]},
        ]
        self.assertEqual(relay_candidate(accounts,None)['email'],'week@example.com')
    def test_relay_ranking_keeps_weekly_only_account_as_reserve(self):
        now=int(time.time())+3600
        weekly_only={'email':'pro@example.com','ok':True,'fetched_at':int(time.time()),'windows':[{'label':'周','duration_mins':10080,'used':1,'resets_at':now}]}
        plus={'email':'plus@example.com','ok':True,'fetched_at':int(time.time()),'windows':[{'label':'5h','duration_mins':300,'used':70,'resets_at':now},{'label':'周','duration_mins':10080,'used':90,'resets_at':now}]}
        self.assertEqual(relay_candidate([weekly_only,plus],None)['email'],'pro@example.com')
        plus['windows'][0]['used']=100
        self.assertEqual(relay_candidate([weekly_only,plus],None)['email'],'pro@example.com')
    def test_relay_ranking_puts_one_percent_plus_after_healthy_accounts(self):
        now=int(time.time())
        def plus(email,five,week):
            return {'email':email,'ok':True,'fetched_at':int(time.time()),'windows':[
                {'label':'5h','duration_mins':300,'used':100-five,'resets_at':now+18000},
                {'label':'周','duration_mins':10080,'used':100-week,'resets_at':now+500000}]}
        accounts=[plus('emergency@example.com',1,53),plus('ample@example.com',100,53),
                  plus('stable@example.com',100,49)]
        self.assertEqual(relay_candidate(accounts,None)['email'],'ample@example.com')
    def test_relay_ranking_healthy_pro_precedes_tight_plus(self):
        now=int(time.time())
        pro={'email':'pro@example.com','ok':True,'fetched_at':int(time.time()),'windows':[{'label':'周','duration_mins':10080,'used':53,'resets_at':now+400000}]}
        tight={'email':'tight@example.com','ok':True,'fetched_at':int(time.time()),'windows':[{'label':'5h','duration_mins':300,'used':81,'resets_at':now+1000},{'label':'周','duration_mins':10080,'used':20,'resets_at':now+500000}]}
        self.assertEqual(relay_candidate([tight,pro],None)['email'],'pro@example.com')
    def test_relay_rejects_expired_or_stale_candidate(self):
        now=int(time.time())
        def account(email,fetched,reset):
            return {'email':email,'ok':True,'fetched_at':fetched,
                    'windows':[{'label':'周','duration_mins':10080,'used':20,'resets_at':reset}]}
        accounts=[account('expired@example.com',now,now-1),
                  account('stale@example.com',now-601,now+3600),
                  account('fresh@example.com',now,now+3600)]
        self.assertEqual(relay_candidate(accounts,None)['email'],'fresh@example.com')

    def test_temporary_failure_can_use_recent_known_quota_but_old_cache_cannot(self):
        now = int(time.time())
        recent = {'email':'recent@example.com','ok':False,'error_code':'network','fetched_at':now-601,
                  'windows':[{'label':'5h','used':20,'resets_at':now+3600}]}
        old = {'email':'old@example.com','ok':False,'error_code':'network','fetched_at':now-901,
               'windows':[{'label':'5h','used':20,'resets_at':now+3600}]}
        self.assertEqual(relay_candidate([recent],None), recent)
        self.assertIsNone(relay_candidate([old],None))
    def test_meta_validated(self):
        self.assertFalse(self.service.set_account_meta('a@example.com','test','not-date')['ok'])
        self.assertTrue(self.service.set_account_meta('a@example.com','Work','2027-01-01')['ok'])
    def test_hotkey_assignment_validated_and_unique(self):
        self.assertFalse(self.service.set_account_hotkey('a@example.com','win+1')['ok'])
        self.assertTrue(self.service.set_account_hotkey('a@example.com','ctrl+shift+7')['ok'])
        self.assertFalse(self.service.set_account_hotkey('b@example.com','ctrl+shift+7')['ok'])
        self.assertEqual(self.service.resolved_hotkeys()['a@example.com'],'ctrl+shift+7')
    def test_usage_is_on_demand(self):
        self.refresh();self.assertFalse(any(c[2] for c in self.query.calls));self.service.get_usage('a@example.com');self.wait();self.assertEqual(self.service.read_usage('a@example.com')['summary']['lifetimeTokens'],42)
    def test_usage_cache_no_requery(self):
        self.service.get_usage('a@example.com');self.wait();count=len(self.query.calls);self.service.get_usage('a@example.com');self.assertEqual(len(self.query.calls),count)
    def test_powershell_exit_code_enforced(self):
        with patch('nx.core.subprocess.run',return_value=subprocess.CompletedProcess([],1,b'secret',b'secret')):
            with self.assertRaises(RuntimeError) as e:self.service._powershell('-To','b@example.com')
            self.assertNotIn('secret',str(e.exception))
    def test_powershell_receives_live_snapshot_directory(self):
        resources=self.paths.root/'embedded';resources.mkdir()
        self.service.paths.resources=resources;self.service.paths.ps1=resources/'switch_account.ps1'
        with patch('nx.core.subprocess.run',return_value=subprocess.CompletedProcess([],0,b'',b'')) as run:
            self.service._powershell('-To','b@example.com')
        command=run.call_args.args[0]
        self.assertEqual(command[command.index('-File')+1],str(resources/'switch_account.ps1'))
        self.assertEqual(command[command.index('-SnapshotDir')+1],str(self.paths.snapshots))
        self.assertEqual(run.call_args.kwargs['cwd'],os.environ.get('WINDIR') or os.environ.get('SystemRoot'))

class ProtocolTests(unittest.TestCase):
    def test_auto_relay_blur_is_held_and_chatgpt_focus_is_reclaimed(self):
        panel=object.__new__(Desktop)
        panel.service=SimpleNamespace(operation={'id':'relay','kind':'switch','source':'auto'},log=Mock())
        panel.window=object();panel.visible=True;panel._relay_restore=None
        panel.closing=False;panel._shown_at=1;panel._relay_pinned=False
        panel.hide(reason='blur')
        self.assertTrue(panel.visible)
        panel.service.operation=None
        panel._relay_restore={'id':'relay','visible':True}
        with patch('nx.desktop.chatgpt_foreground',return_value=True), patch.object(panel,'show') as show:
            panel._restore_after_relay('relay')
        show.assert_called_once_with(relay_operation_id='relay')
        self.assertIsNotNone(panel._relay_restore)

    def test_relay_panel_uses_topmost_without_activating_other_apps(self):
        panel=object.__new__(Desktop)
        with patch('nx.desktop.os.name', 'nt'), patch('nx.desktop._find_hwnd',return_value=123), patch('nx.desktop.ctypes.windll.user32') as user32:
            user32.SetWindowPos.return_value=1
            user32.GetWindowLongPtrW.side_effect=[0x8,0]
            self.assertTrue(panel._set_panel_topmost(True))
            self.assertEqual(user32.SetWindowPos.call_args.args[1].value,ctypes.c_void_p(-1).value)
            self.assertEqual(user32.SetWindowPos.call_args.args[-1],0x0213)
            self.assertTrue(panel._set_panel_topmost(False))
            self.assertEqual(user32.SetWindowPos.call_args.args[1].value,ctypes.c_void_p(-2).value)

    def test_relay_panel_stays_over_chatgpt_and_unpins_on_other_app(self):
        panel=object.__new__(Desktop)
        panel.service=SimpleNamespace(operation=None,log=Mock())
        panel.window=object();panel.visible=True;panel._relay_restore={'id':'relay','pinned':True}
        panel._relay_pinned=True;panel._shown_at=1
        with patch('nx.desktop.chatgpt_foreground',side_effect=[True,False]), \
             patch.object(panel,'_dispatch_ui',side_effect=lambda action:action() or True), \
             patch.object(panel,'_set_panel_topmost',return_value=True) as topmost, \
             patch.object(panel,'_post_script'), patch.object(panel,'_form',return_value=Mock()) as form:
            panel.hide(reason='focus')
            self.assertTrue(panel.visible)
            panel.hide(reason='focus')
        self.assertFalse(panel.visible)
        self.assertIsNone(panel._relay_restore)
        self.assertFalse(panel._relay_pinned)
        topmost.assert_called_once_with(False)
        form.return_value.Hide.assert_called_once()

    def test_hide_removes_window_before_changing_z_order(self):
        panel=object.__new__(Desktop)
        panel.service=SimpleNamespace(operation=None,log=Mock())
        panel.window=object();panel.visible=True;panel._relay_restore=None
        panel._relay_pinned=False;panel._shown_at=1
        events=[]
        form=Mock();form.Hide.side_effect=lambda:events.append('hide')
        with patch.object(panel,'_dispatch_ui',side_effect=lambda action:action() or True), \
             patch.object(panel,'_set_panel_topmost',side_effect=lambda enabled:events.append('unpin') or True), \
             patch.object(panel,'_post_script'),patch.object(panel,'_form',return_value=form):
            panel.hide(reason='focus')
        self.assertEqual(events,['hide','unpin'])

    def test_relay_show_pins_visible_handle_and_records_verified_state(self):
        panel=object.__new__(Desktop)
        panel.window=object();panel.visible=True;panel._relay_restore={'id':'relay','visible':True}
        panel._relay_pinned=False;panel._hide_token=0;panel.last_layout=None
        panel.service=SimpleNamespace(log=Mock())
        with patch('nx.desktop.chatgpt_foreground',return_value=True), \
             patch('nx.desktop._find_hwnd',return_value=123), \
             patch('nx.desktop.ctypes.windll.user32') as user32, \
             patch.object(panel,'_dispatch_ui',side_effect=lambda action:action() or True), \
             patch.object(panel,'_style_window'), patch.object(panel,'_form',return_value=Mock()), \
             patch.object(panel,'_physical_size',return_value=(300,400)), \
             patch.object(panel,'_place_at_tray'), patch.object(panel,'_apply_native_shape'), \
             patch.object(panel,'_post_script'), \
             patch.object(panel,'_set_panel_topmost',return_value=True) as topmost:
            user32.GetForegroundWindow.return_value=123
            user32.IsWindowVisible.return_value=1
            panel._show_view('home','fixture',relay_operation_id='relay')
        self.assertTrue(panel._relay_pinned)
        self.assertTrue(panel._relay_restore['pinned'])
        topmost.assert_called_once_with(True,123)
        self.assertIn('visible=%s foreground=%s topmost=%s',
                      panel.service.log.info.call_args_list[0].args[0])

    def test_relay_show_cancels_if_user_switched_apps_while_queued(self):
        panel=object.__new__(Desktop)
        panel.window=object();panel.visible=True;panel._relay_restore={'id':'relay','visible':True}
        panel._relay_pinned=False;panel._hide_token=0;panel.service=SimpleNamespace(log=Mock())
        callbacks=[]
        with patch.object(panel,'_dispatch_ui',side_effect=lambda action:callbacks.append(action) or True), \
             patch('nx.desktop.chatgpt_foreground',return_value=False), \
             patch('nx.desktop._find_hwnd',return_value=123), \
             patch('nx.desktop.ctypes.windll.user32') as user32, \
             patch.object(panel,'hide') as hide, \
             patch.object(panel,'_set_panel_topmost') as topmost:
            user32.GetForegroundWindow.return_value=999
            panel._show_view('home','fixture',relay_operation_id='relay')
            callbacks[0]()
        self.assertIsNone(panel._relay_restore)
        hide.assert_called_once_with(reason='focus')
        topmost.assert_not_called()

    def test_relay_does_not_steal_focus_from_another_app(self):
        panel=object.__new__(Desktop)
        panel.service=SimpleNamespace(operation=None,log=Mock())
        panel._relay_restore={'id':'relay','visible':True};panel.closing=False;panel._relay_pinned=False;panel.visible=False
        with patch('nx.desktop.chatgpt_foreground',return_value=False), patch.object(panel,'show') as show:
            panel._restore_after_relay('relay')
        show.assert_not_called()
    def test_relay_waits_briefly_for_late_chatgpt_focus(self):
        panel=object.__new__(Desktop)
        panel.service=SimpleNamespace(operation=None,log=Mock())
        panel._relay_restore={'id':'relay','visible':True,'deadline':time.monotonic()+3}
        panel.closing=False;panel._relay_pinned=False
        with patch('nx.desktop.chatgpt_foreground',return_value=False), patch('nx.desktop.threading.Timer') as timer:
            panel._restore_after_relay('relay')
        self.assertIsNotNone(panel._relay_restore)
        timer.assert_called_once()
        timer.return_value.start.assert_called_once()
    def test_relay_restore_survives_immediate_followup_refresh(self):
        panel=object.__new__(Desktop)
        panel.visible=True;panel._relay_restore={'id':'switch','visible':True,'scheduled':False}
        panel.changed=__import__('threading').Event()
        panel.service=SimpleNamespace(operation={'id':'refresh','kind':'refresh'},last_result=None,log=Mock())
        with patch('nx.desktop.threading.Timer') as timer:
            panel._on_service_change()
        self.assertTrue(panel._relay_restore['scheduled'])
        timer.assert_called_once()
        timer.return_value.start.assert_called_once()

    def test_switch_panel_closes_only_after_its_resume_session_finishes(self):
        panel=object.__new__(Desktop)
        session={'id':'session','phase':'resuming'}
        panel.service=SimpleNamespace(
            operation={'id':'switch','kind':'switch'}, last_result=None,
            resumer=SimpleNamespace(lock=threading.RLock(),sessions=[session]),log=Mock())
        panel.visible=True;panel._relay_restore=None;panel.changed=threading.Event()
        with patch.object(panel,'hide') as hide, patch('nx.desktop.threading.Timer') as timer:
            panel._on_service_change()
            panel.service.operation=None
            panel.service.last_result={'id':'switch','ok':True,'resume_session_id':'session'}
            panel._on_service_change()
            hide.assert_not_called()
            self.assertTrue(panel._relay_restore['scheduled'])
            timer.assert_called_once()
            panel.service.last_result={'id':'refresh','ok':True}
            session['phase']='done'
            panel._on_service_change()
            hide.assert_called_once_with(reason='complete')

    def test_switch_panel_closes_without_tasks_but_keeps_failures_visible(self):
        panel=object.__new__(Desktop)
        panel.service=SimpleNamespace(operation=None,last_result={'id':'switch','ok':True,
            'resume_session_id':None},log=Mock())
        panel.visible=True;panel._relay_restore={'id':'switch','visible':True,'scheduled':False}
        panel.changed=threading.Event()
        with patch.object(panel,'hide') as hide:
            panel._on_service_change()
            hide.assert_called_once_with(reason='complete')
        panel.service.last_result={'id':'switch','ok':False}
        panel._relay_restore={'id':'switch','visible':True,'scheduled':False}
        with patch.object(panel,'hide') as hide, patch('nx.desktop.threading.Timer'):
            panel._on_service_change()
            hide.assert_not_called()

    def test_restore_timeout_keeps_long_continuation_protected_from_chatgpt_blur(self):
        panel=object.__new__(Desktop)
        panel.service=SimpleNamespace(operation=None,log=Mock())
        panel._relay_restore={'id':'switch','visible':True,'deadline':time.monotonic()-1}
        panel.closing=False;panel.visible=True;panel.window=object()
        with patch('nx.desktop.chatgpt_foreground',return_value=False), \
             patch.object(panel,'show') as show,patch('nx.desktop.threading.Timer') as timer:
            panel._restore_after_relay('switch')
            panel._retry_relay_restore('switch')
            show.assert_not_called();timer.assert_not_called()
        self.assertIsNotNone(panel._relay_restore)
        with patch('nx.desktop.chatgpt_foreground',return_value=True):
            panel.hide(reason='focus')
        self.assertTrue(panel.visible)

    def test_chatgpt_launch_is_brokered_from_neutral_directory(self):
        if hasattr(launch_chatgpt, '_aumid'):delattr(launch_chatgpt, '_aumid')
        found=subprocess.CompletedProcess([],0,b'OpenAI.Codex_test!App\r\n',b'')
        with patch('nx.desktop.subprocess.run',return_value=found) as run, patch('nx.desktop.subprocess.Popen') as popen:
            launch_chatgpt()
        neutral=os.environ.get('WINDIR') or os.environ.get('SystemRoot')
        self.assertEqual(run.call_args.kwargs['cwd'],neutral)
        self.assertEqual(popen.call_args.args[0],['explorer.exe','shell:AppsFolder\\OpenAI.Codex_test!App'])
        self.assertEqual(popen.call_args.kwargs['cwd'],neutral)
    def test_embedded_script_launches_from_neutral_directory(self):
        script=(Path(__file__).resolve().parents[1]/'src'/'switch_account.ps1').read_text(encoding='utf-8-sig')
        self.assertIn("Start-Process -FilePath explorer.exe", script)
        self.assertIn("-WorkingDirectory $neutralDir", script)
        self.assertIn('Wait-AppWindow', script)
        self.assertNotIn("Name LIKE 'codex%'", script)




    def test_query_orphan_cleanup_removes_only_old_private_query_home(self):
        temp_root=Path(__file__).resolve().parents[1]/'_wip'/'temp'
        temp_root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as folder:
            root=Path(folder);paths=Paths(root,root/'codex')
            old=paths.data/'query-old';old.mkdir();atomic_bytes(old/'auth.json',auth('a@example.com'))
            recent=paths.data/'query-recent';recent.mkdir();atomic_bytes(recent/'auth.json',auth('b@example.com'))
            past=time.time()-7200;os.utime(old,(past,past))
            removed,failed=Query(paths,lambda:{}).cleanup_orphans()
            self.assertEqual((removed,failed),(1,0))
            self.assertFalse(old.exists())
            self.assertTrue((recent/'auth.json').exists())


    @unittest.skipUnless(os.name == 'nt', 'PowerShell transaction is Windows-only')
    def test_embedded_script_dry_run_uses_explicit_snapshot_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);snapshots=root/'live-snapshots';snapshots.mkdir()
            atomic_bytes(snapshots/'b@example.com.json',auth('b@example.com'))
            atomic_bytes(root/'auth.json',auth('a@example.com'))
            script=Path(__file__).resolve().parents[1]/'src'/'switch_account.ps1'
            result=subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-NonInteractive',
                '-ExecutionPolicy','Bypass','-File',str(script),'-AuthFile',str(root/'auth.json'),
                '-SnapshotDir',str(snapshots),'-To','b@example.com','-DryRun'],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('Dry run',result.stdout)
            self.assertFalse((snapshots/'recovery').exists())
    def test_popup_tracks_all_taskbar_edges(self):
        monitor=(0,0,1920,1080);size=(372,520)
        self.assertEqual(popup_position((1800,1040,1824,1064),(0,0,1920,1040),monitor,size)[1],512)
        self.assertEqual(popup_position((1800,16,1824,40),(0,40,1920,1080),monitor,size)[1],48)
        self.assertEqual(popup_position((16,500,40,524),(40,0,1920,1080),monitor,size)[0],48)
        self.assertEqual(popup_position((1880,500,1904,524),(0,0,1880,1080),monitor,size)[0],1500)
    def test_plus_two_windows(self):
        a=normalize_limits(limits(),'a@example.com');self.assertEqual([w['label'] for w in a['windows']],['5h','周']);self.assertEqual(a['windows'][1]['used'],92)
    def test_banked_resets_count_expiry_and_partial_details(self):
        raw=limits();raw['rateLimitResetCredits']={'availableCount':2,'credits':[
            {'id':'opaque-1','resetType':'codexRateLimits','status':'available','grantedAt':1900000000,
             'expiresAt':1900500000,'title':'完整重置','description':'一次性额度重置'}]}
        a=normalize_limits(raw,'a@example.com')
        self.assertEqual(a['banked_resets']['available_count'],2)
        self.assertEqual(len(a['banked_resets']['items']),1)
        self.assertEqual(a['banked_resets']['items'][0]['expires_at'],1900500000)
        self.assertTrue(a['banked_resets']['items'][0]['expires_known'])
        self.assertNotIn('id',a['banked_resets']['items'][0])
        self.assertEqual(a['credits'],'12.50')
    def test_banked_resets_unknown_zero_and_no_expiry_are_distinct(self):
        raw=limits()
        self.assertIsNone(normalize_limits(raw,'a@example.com')['banked_resets'])
        raw['rateLimitResetCredits']={'availableCount':0,'credits':[]}
        self.assertEqual(normalize_limits(raw,'a@example.com')['banked_resets'],
                         {'available_count':0,'items':[]})
        raw['rateLimitResetCredits']={'availableCount':1,'credits':[
            {'resetType':'codexRateLimits','status':'available','grantedAt':1900000000,'expiresAt':None}]}
        self.assertIsNone(normalize_limits(raw,'a@example.com')['banked_resets']['items'][0]['expires_at'])
        self.assertTrue(normalize_limits(raw,'a@example.com')['banked_resets']['items'][0]['expires_known'])
        raw['rateLimitResetCredits']['credits'][0]['expiresAt']='invalid'
        self.assertFalse(normalize_limits(raw,'a@example.com')['banked_resets']['items'][0]['expires_known'])
        raw['rateLimitResetCredits']['credits']=None
        self.assertIsNone(normalize_limits(raw,'a@example.com')['banked_resets']['items'])
    def test_malformed_banked_resets_do_not_hide_valid_quota(self):
        for invalid in ({'availableCount':True,'credits':[]}, {'availableCount':-1,'credits':[]},
                        {'credits':[]}, 'invalid'):
            raw=limits();raw['rateLimitResetCredits']=invalid
            a=normalize_limits(raw,'a@example.com')
            self.assertIsNone(a['banked_resets'])
            self.assertEqual(len(a['windows']),2)
    def test_pro_single_window(self):
        raw=limits();raw['rateLimits']['primary']=raw['rateLimits'].pop('secondary');raw['rateLimits']['planType']='prolite'
        a=normalize_limits(raw,'a@example.com');self.assertEqual(len(a['windows']),1);self.assertEqual(a['windows'][0]['label'],'周')
    def test_never_clamp_invalid_percent(self):
        for value in (None,True,-1,101,float('nan'),'20'):
            raw=limits();raw['rateLimits']['primary']['usedPercent']=value
            with self.assertRaises(RPCError):normalize_limits(raw,'a@example.com')
    def test_missing_reset_invalid(self):
        raw=limits();raw['rateLimits']['primary'].pop('resetsAt')
        with self.assertRaises(RPCError):normalize_limits(raw,'a@example.com')
    def test_multibucket_not_added(self):
        raw=limits();raw['rateLimitsByLimitId']={'codex':raw['rateLimits'],'image':{'primary':{'usedPercent':99}}}
        a=normalize_limits(raw,'a@example.com');self.assertEqual(a['other_buckets'],['image']);self.assertEqual(len(a['windows']),2)
    def test_usage_nulls_remain_null(self):
        result=normalize_usage({'summary':{'lifetimeTokens':None},'dailyUsageBuckets':None});self.assertIsNone(result['summary']['lifetimeTokens']);self.assertIsNone(result['dailyUsageBuckets'])
    def test_usage_dates_not_zero_filled(self):
        result=normalize_usage({'summary':{},'dailyUsageBuckets':[{'startDate':'2026-09-01','tokens':10},{'startDate':'2026-09-03','tokens':20}]});self.assertEqual(len(result['dailyUsageBuckets']),2)
    def test_usage_duplicate_dates_not_added(self):
        result=normalize_usage({'summary':{},'dailyUsageBuckets':[{'startDate':'2026-09-01','tokens':10}]*2});self.assertEqual(len(result['dailyUsageBuckets']),1)
    def test_usage_malformed_rejected(self):
        with self.assertRaises(RPCError):normalize_usage({'usage':'unknown'})





if __name__=='__main__':unittest.main(verbosity=2)
