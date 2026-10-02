"""Hidden agent histories must never become desktop continuation requests."""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from nx.desktop import Bridge
from nx.desktop_resume import active_turns, attempt_continuation
from nx.limit_watch import UsageLimitWatcher
from nx.resume_flow import ResumeCoordinator
from nx.storage import Paths


class SubagentResumeTests(unittest.TestCase):
    PARENT = '00000000-0000-4000-8000-000000000001'
    CHILD = '00000000-0000-4000-8000-000000000002'
    TURN = '00000000-0000-4000-8000-000000000003'
    OTHER_TURN = '00000000-0000-4000-8000-000000000004'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.paths = Paths(Path(self.temp.name), Path(self.temp.name)/'codex')
        self.paths.home.mkdir()
        with sqlite3.connect(self.paths.home/'state_5.sqlite') as db:
            db.execute('CREATE TABLE threads (id TEXT,title TEXT,archived INTEGER,source TEXT,name TEXT,rollout_path TEXT,thread_source TEXT)')
            db.execute('INSERT INTO threads VALUES (?,?,0,?,NULL,NULL,?)',
                (self.PARENT,'有完整名称的主任务','cli','cli'))
            db.execute('INSERT INTO threads VALUES (?,?,0,?,NULL,NULL,?)',
                (self.CHILD,'',json.dumps({'subagent':{'thread_spawn':{
                    'parent_thread_id':self.PARENT,'agent_path':'/root/checker'}}}), 'subagent'))
        db.close()
        self.stop = threading.Event()
        self.c = ResumeCoordinator(self.paths,lambda:'a@example.com',self.stop,Mock(),lambda:None,
            threading.Lock(),settings=lambda:{'auto_relay':True,'task_continuation':True})

    def tearDown(self):
        self.stop.set()
        self.temp.cleanup()

    def event(self, child=True):
        return {'thread_id':self.CHILD if child else self.PARENT,
                'turn_id':self.TURN if child else self.OTHER_TURN,'was_active':True}

    def history(self):
        db = sqlite3.connect(self.paths.home/'thread_history_1.sqlite')
        db.execute('CREATE TABLE thread_turns (thread_id TEXT,turn_id TEXT,status TEXT,error_json TEXT,started_at INTEGER,completed_at INTEGER,rollout_ordinal INTEGER)')
        return db

    def test_active_capture_only_returns_visible_parent(self):
        with self.history() as db:
            for child in (True,False):
                e=self.event(child)
                db.execute('INSERT INTO thread_turns VALUES (?,?,?,?,?,?,?)',
                    (e['thread_id'],e['turn_id'],'inProgress',None,int(time.time()),None,1))
        db.close()
        self.assertEqual([e['thread_id'] for e in active_turns(self.paths.home)],[self.PARENT])

    def test_child_limit_does_not_trigger_desktop_relay(self):
        with self.history() as db:
            db.execute('INSERT INTO thread_turns VALUES (?,?,?,?,?,?,?)',
                (self.PARENT,self.OTHER_TURN,'completed',None,1,10,1))
        watcher=UsageLimitWatcher(self.paths.home)
        self.assertTrue(watcher.prime())
        with db:
            db.execute('INSERT INTO thread_turns VALUES (?,?,?,?,?,?,?)',
                (self.CHILD,self.TURN,'failed',json.dumps({'codexErrorInfo':'usageLimitExceeded'}),2,11,1))
        db.close()
        consumer=Mock()
        self.assertEqual(watcher.poll(consumer),[])
        consumer.assert_not_called()
        self.assertEqual(watcher.poll(),[])

    def test_prepare_and_pending_never_queue_subagents(self):
        self.c.note_limit_events([self.event()], 'a@example.com', True)
        self.assertEqual(self.c.pending,[])
        sid=self.c.prepare('a@example.com','a@example.com','relay',[self.event(),self.event(False)])
        self.assertEqual([i['thread_id'] for i in self.c._session(sid)['items']],[self.PARENT])

    def test_previous_version_waiting_child_is_retired_without_action(self):
        sid=self.c.prepare('a@example.com','a@example.com','relay',[self.event(False)])
        self.c._session(sid)['items'].append(self.c._item(self.event()))
        self.c.switched(sid)
        ready=self.c._ready()
        self.assertEqual(ready[1]['thread_id'],self.PARENT)
        child=self.c._session(sid)['items'][1]
        self.assertEqual((child['state'],child['reason'],child['attempts']),('skipped','subagent_task',0))

    def test_dispatch_guard_never_calls_bridge_for_subagent(self):
        with patch('nx.desktop_resume._invoke') as native, patch('nx.app_bridge.resume_existing') as bridge:
            result=attempt_continuation(self.paths.home,self.paths.desktop_resume_ps1,self.event(),self.stop,Mock())
        self.assertEqual(result,('skipped','subagent_task'))
        native.assert_not_called(); bridge.assert_not_called()

    def test_previous_failed_child_is_not_requeued_or_rewritten_on_recovery(self):
        sid=self.c.prepare('a@example.com','a@example.com','relay',[self.event(False)])
        session=self.c._session(sid)
        session.update(phase='failed')
        item={**self.c._item(self.event()),'state':'failed','reason':'resumed_turn_failed',
              'attempts':1,'observed_turn_id':self.OTHER_TURN}
        session['items']=[item]
        before=copy.deepcopy(item)
        with patch('nx.resume_flow.latest_turn',return_value={
            'turn_id':self.OTHER_TURN,'status':'failed','error':{'codexErrorInfo':'serverOverloaded'}}):
            self.c._recover()
            self.assertIsNone(self.c._ready())
        self.assertEqual(item,before)

    def test_historical_display_preserves_unknown_outcome_and_opens_parent(self):
        sid=self.c.prepare('a@example.com','a@example.com','relay',[self.event(False)])
        session=self.c._session(sid)
        session.update(phase='failed')
        session['items']=[{**self.c._item(self.event()),'state':'failed','reason':'action_outcome_unknown','attempts':1}]
        self.c._save()
        before=copy.deepcopy(session)
        details=self.c.details()
        item=details[0]['items'][0]
        self.assertTrue(item['is_subagent'])
        self.assertIn('checker',item['title'])
        self.assertEqual(item['parent_thread_id'],self.PARENT)
        self.assertEqual(item['parent_title'],'有完整名称的主任务')
        self.assertEqual(item['reason'],'action_outcome_unknown')
        self.assertEqual(session,before)
        self.assertFalse(self.c.retry_task(sid,self.CHILD)['ok'])
        service=Mock(paths=self.paths,desktop_gate=threading.Lock())
        service.get_resume_details.return_value=details
        with patch('nx.desktop_resume.navigate_existing_task',return_value={'ok':True}) as navigate:
            self.assertTrue(Bridge(service,None).open_resume_task(self.CHILD)['ok'])
        self.assertEqual(navigate.call_args.args[2],self.PARENT)
