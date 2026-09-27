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
  log=Mock();record={'turn_id':'44444444-4444-4444-8444-444444444444','status':'interrupted','error':None}
  with patch('nx.desktop_resume.continuation_guard',return_value=('mock-hash','')),patch('nx.desktop_resume.latest_turn',return_value=record),patch('nx.desktop_resume.title_prefix',return_value='synthetic title'),patch('nx.desktop_resume._desktop_command',return_value=['mock']),patch('nx.desktop_resume._invoke',return_value=Mock(stdout=stdout,returncode=2 if stdout.startswith('skip:') else 0)):
   result=attempt_continuation(Path('synthetic'),Path('helper.ps1'),{'thread_id':'67cc833f-6330-5bae-a638-9232b5ddfa21','turn_id':'44444444-4444-4444-8444-444444444444'},threading.Event(),log)
  return result,log
 def test_missing_native_button_is_a_visible_failure(self):
  result,_=self.attempt('skip:native_continue_unavailable\n');self.assertEqual(result,('failed','native_continue_unavailable'))
 def test_unrecognized_stdout_cannot_leak_into_logs(self):
  result,log=self.attempt('secret draft content');self.assertEqual(result,('failed','action_outcome_unknown'));self.assertNotIn('secret draft content',str(log.mock_calls))
 def test_native_helper_has_no_message_or_editor_write_path(self):
  s=(ROOT/'src/continue_in_desktop.ps1').read_text(encoding='utf-8-sig')
  self.assertNotIn('SendInput',s)
  self.assertNotIn('Send-ResumeMessage',s)
  self.assertNotIn('Find-Composer',s)
  self.assertIn("if (-not $NavigateOnly -and $Action -ne 'interrupted') { Skip 'bridge_required' }",s)

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
 def test_native_helper_parses_without_editor_input_code(self):
  shell=shutil.which('pwsh') or shutil.which('powershell')
  r=subprocess.run([shell,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(ROOT/'tools/test_automatic_resume.ps1')],capture_output=True,text=True,timeout=30)
  self.assertEqual(r.returncode,0,r.stderr);self.assertIn('parsed and compiled',r.stdout)
