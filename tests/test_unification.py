"""Single-panel migration and automatic-resume results, using synthetic data only."""
from pathlib import Path
import json,sys,tempfile,threading,time,unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tools'))
from nx.storage import State,Paths,atomic_bytes
from nx.settings import normalize_settings,valid_setting
from nx.desktop_resume import attempt_continuation
from nx.resume_flow import ResumeCoordinator
from build import panel
from screen_catalog import CASES
THREAD='67cc833f-6330-5bae-a638-9232b5ddfa21';TURN='42d1e863-8084-556e-a03c-d7c800c7055b'

class SinglePresentationTests(unittest.TestCase):
 def test_no_compact_or_manual_routes_or_buttons_in_product(self):
  html=panel()
  for marker in ('compact-panel','compact-home','compact-confirm','tray-accounts','full-panel','resume-manual','copy-resume-message','panel_mode'):
   with self.subTest(marker=marker):self.assertNotIn(marker,html)
 def test_catalog_only_single_panel_states(self):
  for c in CASES:
   self.assertNotIn('compact',c['query']);self.assertNotIn('compact',c['expected']);self.assertNotIn('手动接续',c['label'])
 def test_normalizing_legacy_modes_preserves_other_preferences(self):
  for old in ('compact','full',None):
   actual=normalize_settings({'panel_mode':old,'appearance':'dark','resume_message':'继续核对','auto_relay':True})
   self.assertNotIn('panel_mode',actual);self.assertEqual(actual['appearance'],'dark');self.assertEqual(actual['resume_message'],'继续核对');self.assertTrue(actual['auto_relay'])
   self.assertFalse(valid_setting('panel_mode',old))
 def test_real_state_upgrade_and_save_drop_removed_key(self):
  with tempfile.TemporaryDirectory() as d:
   paths=Paths(Path(d),Path(d)/'home');paths.data.mkdir(parents=True,exist_ok=True)
   # Derive the current metadata filename from State rather than assume a legacy filename.
   st=State(paths);st.update(settings={'**':'ignored','panel_mode':'compact','appearance':'dark','notify_low':True})
   loaded=State(paths);self.assertNotIn('panel_mode',loaded.get('settings'));self.assertEqual(loaded.get('settings')['appearance'],'dark');self.assertTrue(loaded.get('settings')['notify_low'])
 def test_unicode_message_policy_keeps_valid_scalar_text(self):
  self.assertTrue(valid_setting('resume_message','继续 🙂'))
  for bad in ('x\ny','继续\x00','\ud800',' x', 'x'*201):self.assertFalse(valid_setting('resume_message',bad))

class AutomaticResultsTests(unittest.TestCase):
 def attempt(self,label,*,observed=False,code=0):
  before={'turn_id':TURN,'status':'failed','error':{'codexErrorInfo':'usageLimitExceeded'}}
  after={**before,'turn_id':'ea10a953-d3a4-53b9-b010-6361794c2a22'}
  stop=Mock();stop.is_set.return_value=False;stop.wait.return_value=False
  with patch('nx.desktop_resume.latest_turn',side_effect=[before,after] if observed else None,return_value=before),patch('nx.desktop_resume.title_prefix',return_value='Unique synthetic task'),patch('nx.desktop_resume._desktop_command',return_value=['synthetic']),patch('nx.desktop_resume._invoke',return_value=Mock(stdout=label,returncode=code)) as run:
   result=attempt_continuation(Path('none'),Path('none'),{'thread_id':THREAD,'turn_id':TURN},stop,Mock())
  self.assertEqual(run.call_count,1);return result
 def test_automatic_message_needs_new_turn_evidence(self):self.assertEqual(self.attempt('invoked:send_message',observed=True),('done','new_turn_observed'))
 def test_native_action_same_confirmation_contract(self):self.assertEqual(self.attempt('invoked:native_continue',observed=True),('done','new_turn_observed'))
 def test_message_invoked_but_not_observed_does_not_retry(self):self.assertEqual(self.attempt('invoked:send_message'),('failed','start_not_observed'))
 def test_uncertain_insert_or_send_is_never_retryable(self):
  for reason in ('input_guard_timeout','text_insertion_unconfirmed','composer_changed','send_unavailable','desktop_error'):
   with self.subTest(reason=reason):self.assertEqual(self.attempt('uncertain:'+reason,code=2),('failed','action_outcome_unknown'))
 def test_nonzero_invoked_is_not_success(self):self.assertEqual(self.attempt('invoked:send_message',code=2),('failed','action_outcome_unknown'))
 def test_draft_typing_and_attachment_wait_without_writing(self):
  for reason in ('user_draft_present','composer_in_use','user_attachment_present'):
   with self.subTest(reason=reason):self.assertEqual(self.attempt('skip:'+reason,code=2),('defer',reason))
 def test_guard_refusal_is_pre_effect_retry_only(self):self.assertEqual(self.attempt('skip:input_guard_unavailable',code=2),('retry','input_guard_unavailable'))
 def test_unknown_composer_is_not_relabelled_as_draft(self):self.assertEqual(self.attempt('skip:composer_state_unknown',code=2),('failed','composer_state_unknown'))
 def test_private_text_in_response_does_not_become_reason(self):self.assertEqual(self.attempt('my private draft'),('failed','action_outcome_unknown'))

class WaitingPersistenceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.paths=Paths(Path(self.tmp.name),Path(self.tmp.name)/'home');self.stop=threading.Event()
  self.c=ResumeCoordinator(self.paths,lambda:'b@example.com',self.stop,Mock(),Mock(),threading.Lock())
  self.id=self.c.prepare('a@example.com','b@example.com','auto',[{'thread_id':THREAD,'turn_id':TURN}]);self.c.switched(self.id)
  self.item=self.c.sessions[0]['items'][0]
 def tearDown(self):self.stop.set();self.tmp.cleanup()
 def test_wait_rechecks_without_counting_a_send_attempt(self):
  before=time.time();self.c._persist_outcome(self.id,self.item,'defer','composer_in_use');i=self.c.sessions[0]['items'][0]
  self.assertEqual(i['state'],'waiting');self.assertEqual(i['attempts'],0);self.assertGreaterEqual(i['next_try'],before+15);self.assertEqual(self.c.summary()['waiting_reason'],'composer_in_use')
 def test_wait_is_bounded_and_survives_reload(self):
  self.item['deferred_since']=time.time()-301;self.c._save();self.c._persist_outcome(self.id,self.item,'defer','user_draft_present')
  c=ResumeCoordinator(self.paths,lambda:'b@example.com',self.stop,Mock(),Mock(),threading.Lock())
  self.assertEqual(c.sessions[0]['items'][0]['state'],'failed');self.assertEqual(c.sessions[0]['items'][0]['attempts'],0)
 def test_invalid_saved_wait_timestamp_is_sanitized(self):
  for value in ('bad',True,-1,time.time()+86400):
   self.c.sessions[0]['items'][0]['deferred_since']=value;self.c._save()
   c=ResumeCoordinator(self.paths,lambda:'b@example.com',self.stop,Mock(),Mock(),threading.Lock());self.assertNotIn('deferred_since',c.sessions[0]['items'][0])
 def test_explicit_retry_resets_wait_deadline(self):
  self.item.update(state='failed',reason='user_draft_present',deferred_since=time.time()-301);self.c.sessions[0]['phase']='failed';self.c._save()
  self.assertTrue(self.c.retry_draft(self.id,THREAD)['ok']);self.assertNotIn('deferred_since',self.c.sessions[0]['items'][0])
 def test_legacy_manual_record_migrates_but_does_not_replay(self):
  self.item.update(state='failed',reason='manual_message_required');self.c.sessions[0]['phase']='failed';self.c._save()
  c=ResumeCoordinator(self.paths,lambda:'b@example.com',self.stop,Mock(),Mock(),threading.Lock())
  self.assertEqual(c.sessions[0]['items'][0]['reason'],'automatic_send_unavailable');self.assertIsNone(c._ready())
 def test_watchdog_uncertainty_not_retryable(self):
  self.item.update(state='failed',reason='action_outcome_unknown');self.c.sessions[0]['phase']='failed';self.c._save()
  self.assertFalse(self.c.retry_draft(self.id,THREAD)['ok'])

class NativeSourceBoundariesTests(unittest.TestCase):
 def test_unicode_batch_is_not_a_replacement_or_clipboard_path(self):
  s=(ROOT/'src/continue_in_desktop.ps1').read_text(encoding='utf-8-sig')
  for forbidden in ('.SetValue(', 'Set-Clipboard', 'Start-Process', 'SendKeys', 'codex://'):
   self.assertNotIn(forbidden,s)
  self.assertNotIn('Assert-EmptyComposer $composer',s);self.assertNotIn('Assert-CollapsedCaret $composer',s)
  self.assertIn('flags=4',s);self.assertIn('flags=6',s);self.assertNotIn('vk=13',s)
 def test_automatic_navigation_waits_for_idle_but_explicit_open_is_separate(self):
  s=(ROOT/'src/continue_in_desktop.ps1').read_text(encoding='utf-8-sig')
  start=s.index("# Select the unique sidebar entry")
  self.assertNotIn("-not $NavigateOnly -and -not [NXResumeWindow]::Idle()",s[start:])
 def test_unused_input_lock_is_removed(self):
  s=(ROOT/'src/continue_in_desktop.ps1').read_text(encoding='utf-8-sig')
  self.assertNotIn('class NXInputGuard',s)
  self.assertNotIn('Process.GetCurrentProcess().Kill()',s)
if __name__=='__main__':unittest.main()
