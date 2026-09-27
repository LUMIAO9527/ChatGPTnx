"""The explicit live acceptance entry must never switch unrelated active work."""
import json
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nx.acceptance import relay_once


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]/'_wip'/'temp'
        root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root)
        self.report=Path(self.temp.name)/'report.json'
        self.service=Mock()
        self.service.state.get.return_value={'task_continuation':True}
        self.service.get_data.return_value={'relay_email':'synthetic-target'}
        self.service.resumer.sessions=[]

    def tearDown(self):
        self.temp.cleanup()

    def test_other_active_task_prevents_switch(self):
        with patch('nx.acceptance.active_turns', return_value=[{'thread_id':'self'},{'thread_id':'other'}]):
            relay_once(self.service,'self',self.report)
        self.service.relay.assert_not_called()
        self.assertEqual(json.loads(self.report.read_text())['reason'],'active_tasks_changed')

    def test_task_finished_before_preflight_prevents_switch(self):
        with patch('nx.acceptance.active_turns', side_effect=[[{'thread_id':'self'}],[]]):
            relay_once(self.service,'self',self.report)
        self.service.relay.assert_not_called()

    def test_existing_journal_prevents_second_acceptance_run(self):
        self.report.write_text('{"state":"finished"}')
        with self.assertRaises(FileExistsError):
            relay_once(self.service,'self',self.report)
        self.service.relay.assert_not_called()

    def test_disabled_continuation_prevents_switch(self):
        self.service.state.get.return_value={'task_continuation':False}
        with patch('nx.acceptance.active_turns', return_value=[{'thread_id':'self'}]):
            relay_once(self.service,'self',self.report)
        self.service.relay.assert_not_called()
        self.assertEqual(json.loads(self.report.read_text())['reason'],'continuation_disabled')
