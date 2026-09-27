"""5.7.3 state semantics, safe logging and build separation. No live credentials."""
from pathlib import Path
import sys,json,shutil,subprocess,threading,unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tools'))
from nx.desktop_resume import attempt_continuation
from nx.resume_flow import ATTENTION_REASONS
from build import panel
from screen_catalog import CASES

class ContinuationEvidenceTests(unittest.TestCase):
 def attempt(self,stdout):
  log=Mock();record={'turn_id':'t','status':'failed','error':{'codexErrorInfo':'usageLimitExceeded'}}
  with patch('nx.desktop_resume.latest_turn',return_value=record),patch('nx.desktop_resume.title_prefix',return_value='synthetic title'),patch('nx.desktop_resume._desktop_command',return_value=['mock']),patch('nx.desktop_resume._invoke',return_value=Mock(stdout=stdout,returncode=0)):
   result=attempt_continuation(Path('synthetic'),Path('helper.ps1'),{'thread_id':'67cc833f-6330-5bae-a638-9232b5ddfa21','turn_id':'t'},threading.Event(),log)
  return result,log
 def test_unknown_is_terminal_and_not_a_draft_claim(self):
  result,_=self.attempt('skip:composer_state_unknown\n');self.assertEqual(result,('failed','composer_state_unknown'))
 def test_missing_composer_does_not_auto_retry(self):
  result,_=self.attempt('skip:composer_unavailable\n');self.assertEqual(result,('failed','composer_unavailable'))
 def test_unsupported_automatic_path_is_explicit(self):
  result,_=self.attempt('skip:automatic_send_unavailable\n');self.assertEqual(result,('failed','automatic_send_unavailable'))
 def test_structural_diagnostics_discard_content_and_hash(self):
  result,log=self.attempt('evidence:'+json.dumps({'state':'empty','patterns':2,'lengths':[0,1],'draft':'secret text','hash':'secret hash'})+'\nskip:composer_state_unknown')
  logged=str(log.mock_calls);self.assertIn('composer_evidence',logged);self.assertNotIn('secret',logged)
 def test_malformed_diagnostics_ignored(self):
  for value in [[],{}, {'state':'present','patterns':True,'lengths':[1]},{'state':'present','patterns':2,'lengths':['secret']}]:
   with self.subTest(value=value):
    _,log=self.attempt('evidence:'+json.dumps(value)+'\nskip:composer_state_unknown');self.assertNotIn('composer_evidence',str(log.mock_calls))
 def test_unrecognized_stdout_cannot_leak_into_logs(self):
  result,log=self.attempt('secret draft content');self.assertEqual(result,('failed','action_outcome_unknown'));self.assertNotIn('secret draft content',str(log.mock_calls))
 def test_attention_semantics_exclude_uncertain_effects(self):
  self.assertIn('composer_state_unknown',ATTENTION_REASONS);self.assertIn('automatic_send_unavailable',ATTENTION_REASONS);self.assertNotIn('action_outcome_unknown',ATTENTION_REASONS)
 def test_automatic_message_path_rechecks_empty_and_selection(self):
  s=(ROOT/'src/continue_in_desktop.ps1').read_text(encoding='utf-8-sig')
  body=s[s.index('function Send-ResumeMessage'):s.index('function Assert-Target')]
  self.assertNotIn('Assert-EmptyComposer $composer',body)
  self.assertNotIn('Assert-CollapsedCaret $composer',body)
  self.assertNotIn('Composer-EqualsMessage',body)
  self.assertLess(body.index('AppendUnicode'),body.index('Invoke()'))
  self.assertNotIn('SetValue(',body)

class ProductBuildSeparationTests(unittest.TestCase):
 def test_production_excludes_proposal_and_demo_implementations(self):
  html=panel();self.assertNotIn('window.NXDesign=',html);self.assertNotIn('demo-archive',html);self.assertNotIn('studio-sidebar',html);self.assertNotIn('work-01@example.com',html)
 def test_demo_uses_the_same_inline_editor_as_production(self):
  for demo in (False,True):
   html=panel(demo=demo);self.assertIn('window.NXEditors =',html);self.assertNotIn('window.NXDesign=',html)
 def test_production_rejects_experimental_geometry(self):
  with self.assertRaises(ValueError):panel(proposal='studio')
 def test_inline_catalog_covers_all_five_expansions(self):
  ids={c['id'] for c in CASES};self.assertTrue({'inline-relay','inline-message','inline-resume','inline-hotkeys','inline-archives'}<=ids)
 def test_expiry_note_is_not_clickable(self):
  text=(ROOT/'src/ui/app.js').read_text(encoding='utf-8');self.assertIn('<div class="detail-expiry-note"',text);self.assertNotIn('edit-expiry',text)
 @unittest.skipUnless(shutil.which('pwsh') or shutil.which('powershell'),'PowerShell not installed; pure classifier/native parser checked on Windows')
 def test_powershell_parser_and_exact_pure_classifier(self):
  shell=shutil.which('pwsh') or shutil.which('powershell');r=subprocess.run([shell,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(ROOT/'tools/test_composer_policy.ps1')],capture_output=True,text=True,timeout=30)
  self.assertEqual(r.returncode,0,r.stderr);self.assertIn('34 classifier cases passed',r.stdout)
  r=subprocess.run([shell,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(ROOT/'tools/test_automatic_resume.ps1')],capture_output=True,text=True,timeout=30)
  self.assertEqual(r.returncode,0,r.stderr);self.assertIn('18 message cases',r.stdout)
