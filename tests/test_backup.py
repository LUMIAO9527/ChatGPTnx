"""Synthetic portable backups, duplicate merges, rollback and credential isolation."""
import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from nx.backup import Backups,seal,unseal,commit,recover,dump,JOURNAL
from nx.credentials import write_credential_bytes,read_credential_bytes
from nx.storage import Paths,State,Accounts,account_identity_key,atomic_bytes
from nx.usage import SOURCE

def auth(email,workspace='test-workspace'):
    payload={'email':email,'sub':'test-user-'+email,'exp':2000000000}
    token='test.'+base64.urlsafe_b64encode(dump(payload)).decode().rstrip('=')+'.unsigned'
    return dump({'tokens':{'id_token':token,'account_id':workspace,'access_token':'synthetic-access','refresh_token':'synthetic-refresh'}})

def service(folder):
    paths=Paths(folder,folder/'desktop');state=State(paths)
    return SimpleNamespace(paths=paths,state=state,accounts=Accounts(paths),gate=threading.Lock(),desktop_gate=threading.Lock(),
                           stop=threading.Event(),updater=SimpleNamespace(snapshot=lambda:{'status':'idle'}),notify=Mock())

class BackupTests(unittest.TestCase):
    def setUp(self):
        autostart=patch('nx.storage.autostart_enabled_safe',return_value=False);autostart.start();self.addCleanup(autostart.stop)
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.first=service(self.root/'first');self.second=service(self.root/'second')
        self.backups=Backups(self.first);self.destination=Backups(self.second)
        self.email='portable@example.com';self.other='archived@example.com';self.password='synthetic-password-2026'
        self.first.accounts.write([self.email])
        write_credential_bytes(self.first.paths.snapshot(self.email),auth(self.email))
        write_credential_bytes(self.first.paths.snapshots/'removed'/f'{self.other}.test.json',auth(self.other))
        key=account_identity_key(self.first.paths.snapshot(self.email),self.email)
        self.observed=int(time.time())-200
        self.first.state.update(account_meta={self.email:{'alias':'工作','subscription_date':'2026-12-31'}},
          usage={self.email:{'ok':True,'source':SOURCE,'identity_key':key,'fetched_at':self.observed,
                  'summary':{'lifetimeTokens':123},'dailyUsageBuckets':[{'startDate':'2026-11-01','tokens':100}]}},
          cache={'updated':self.observed,'current':self.email,'accounts':[{'email':self.email,'ok':True,'fetched_at':self.observed,'plan':'plus',
             'windows':[{'label':'5h','duration':300,'used':12,'resets_at':2000000000}]}]})
        self.first.state.setting(appearance='dark',resume_message='继续测试',autostart=True)
        self.file=self.root/'test.nxbackup'
    def tearDown(self):self.tmp.cleanup()
    def export(self,**options):
        return self.backups.export(self.file,{'accounts':[self.email],'usage':True,'preferences':True,**options},self.password)
    def unlock(self):self.destination.select(self.file);return self.destination.unlock(self.password)
    def apply(self,**options):
        return self.destination.import_selected({'accounts':[self.email],'merge':'merge','usage':True,'preferences':True,**options})
    def test_encrypted_round_trip_preserves_selected_data_and_reencrypts_credentials(self):
        self.export();raw=self.file.read_bytes()
        for private in (self.email.encode(),b'synthetic-access',b'synthetic-refresh'):self.assertNotIn(private,raw)
        info=self.unlock();self.assertEqual(info['accounts'][0]['email'],self.email)
        self.assertNotIn('credential',json.dumps(info));self.assertNotIn('token',json.dumps(info))
        result=self.apply();self.assertEqual((result['added'],result['merged']),(1,0))
        self.assertEqual(read_credential_bytes(self.second.paths.snapshot(self.email)),auth(self.email))
        self.assertNotEqual(self.second.paths.snapshot(self.email).read_bytes(),auth(self.email))
        self.assertFalse(self.second.paths.auth.exists())
        self.assertEqual(self.second.state.get('account_meta')[self.email]['alias'],'工作')
        self.assertEqual(self.second.state.get('usage')[self.email]['fetched_at'],self.observed)
        self.assertEqual(self.second.state.get('settings')['resume_message'],'继续测试')
        self.assertFalse(self.second.state.get('settings')['autostart'])
        self.assertFalse((self.second.paths.data/JOURNAL).exists())
    def test_wrong_password_tampering_and_truncation_never_change_destination(self):
        self.export();raw=self.file.read_bytes();before=copy.deepcopy(self.second.state.value)
        for payload,password in ((raw,'wrong-password'),(raw[:-1],self.password),(raw[:-1]+bytes([raw[-1]^1]),self.password)):
            with self.assertRaises(ValueError):unseal(payload,password)
        self.assertEqual(before,self.second.state.value);self.assertFalse(self.second.paths.order.exists())
    def test_selected_accounts_and_optional_attachments(self):
        self.export(usage=False,preferences=False,archived=True)
        preview=self.unlock();self.assertEqual(len(preview['accounts']),2);self.assertFalse(preview['usage']);self.assertFalse(preview['preferences'])
        self.apply(usage=False,preferences=False)
        self.assertEqual(self.second.accounts.all(),[self.email]);self.assertEqual(self.second.state.get('usage'),{})
        self.assertEqual(self.second.state.get('settings')['appearance'],'system')
        self.assertEqual(self.second.accounts.archived(),[])
    def test_archived_account_keeps_archived_status(self):
        self.export(archived=True);self.unlock();self.apply(accounts=[self.other])
        self.assertEqual(self.second.accounts.all(),[])
        self.assertEqual([r['email'] for r in self.second.accounts.archived()],[self.other])
    def test_merge_preserves_credentials_alias_and_newest_day(self):
        self.second.accounts.write([self.email]);write_credential_bytes(self.second.paths.snapshot(self.email),auth(self.email))
        before=self.second.paths.snapshot(self.email).read_bytes();key=account_identity_key(self.second.paths.snapshot(self.email),self.email)
        self.second.state.update(account_meta={self.email:{'alias':'本机昵称'}},usage={self.email:{'ok':True,'source':SOURCE,'identity_key':key,
            'fetched_at':self.observed+100,'summary':{'lifetimeTokens':222},'dailyUsageBuckets':[{'startDate':'2026-11-01','tokens':200},{'startDate':'2026-11-02','tokens':22}]}})
        self.export();self.assertTrue(self.unlock()['accounts'][0]['duplicate']);result=self.apply()
        self.assertEqual(result['merged'],1);self.assertEqual(self.second.paths.snapshot(self.email).read_bytes(),before)
        self.assertEqual(self.second.state.get('account_meta')[self.email]['alias'],'本机昵称')
        self.assertEqual(self.second.state.get('usage')[self.email]['dailyUsageBuckets'][0]['tokens'],200)
    def test_duplicate_skip_does_not_write(self):
        self.second.accounts.write([self.email]);write_credential_bytes(self.second.paths.snapshot(self.email),auth(self.email))
        self.export();self.unlock();before=self.second.state.path.read_bytes()
        with self.assertRaises(ValueError):self.apply(merge='skip')
        self.assertEqual(self.second.state.path.read_bytes(),before)
    def test_different_workspace_keeps_its_existing_usage(self):
        self.second.accounts.write([self.email]);write_credential_bytes(self.second.paths.snapshot(self.email),auth(self.email,'another-workspace'))
        self.second.state.update(usage={self.email:{'fetched_at':1700000000,'identity_key':'local-workspace','ok':False}})
        before=self.second.state.get('usage');self.export();self.unlock();self.apply()
        self.assertEqual(before,self.second.state.get('usage'))
    def test_failed_commit_restores_order_state_and_snapshot(self):
        self.export();self.unlock();before=self.second.state.path.read_bytes();real=atomic_bytes
        def failing(path,data,**kwargs):
            if path==self.second.state.path and data!=before:raise OSError('synthetic disk failure')
            return real(path,data,**kwargs)
        with patch('nx.backup.atomic_bytes',side_effect=failing):
            with self.assertRaises(OSError):self.apply()
        self.assertEqual(self.second.state.path.read_bytes(),before)
        self.assertFalse(self.second.paths.order.exists());self.assertFalse(self.second.paths.snapshot(self.email).exists())
        self.assertEqual(self.second.state.value,State(self.second.paths).value)
    def test_crash_journal_recovers_before_next_import(self):
        state=self.second.state.path;old=state.read_bytes()
        atomic_bytes(self.second.paths.data/JOURNAL,dump({'schema':1,'entries':[{'path':'_data/state.json','old':base64.b64encode(old).decode()}]}))
        atomic_bytes(state,b'changed');recover(self.second.paths);self.assertEqual(state.read_bytes(),old)
    def test_recovery_rejects_external_path(self):
        outside=self.root/'outside';outside.write_bytes(b'user')
        atomic_bytes(self.second.paths.data/JOURNAL,dump({'schema':1,'entries':[{'path':'../../outside','old':None}]}))
        with self.assertRaises(ValueError):recover(self.second.paths)
        self.assertEqual(outside.read_bytes(),b'user')
    def test_busy_desktop_prevents_import_and_export(self):
        self.first.desktop_gate.acquire()
        with self.assertRaises(ValueError):self.export()
        self.assertFalse(self.file.exists());self.first.desktop_gate.release()
    def test_credential_identity_mismatch_is_rejected(self):
        doc={'schema':1,'accounts':[{'email':self.email,'credential':base64.b64encode(auth('someone@example.com')).decode()}]}
        with self.assertRaises(ValueError):unseal(seal(doc,self.password),self.password)

if __name__=='__main__':unittest.main()
