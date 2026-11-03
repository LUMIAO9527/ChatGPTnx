"""Untrusted backup data is canonical before any local transaction."""
import base64
import sys
import time
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
from nx.backup import validate,quota_record
from nx.account_meta import validate as metadata
from nx.storage import credential_identity_key
from nx.usage import SOURCE
from test_backup import auth


class BackupValidationTests(unittest.TestCase):
    def document(self,**row):
        return {'schema':1,'accounts':[{'email':'audit@example.com','credential':None,**row}]}

    def test_schema_and_dates_are_exact(self):
        doc=self.document();doc['schema']=True
        with self.assertRaises(ValueError):validate(doc)
        for value in ('20261103','2026-02-30','２０２６-１１-０３'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                validate(self.document(meta={'subscription_date':value}))
        self.assertEqual(metadata({'alias':'  昵称  '})['alias'],'昵称')

    def test_metadata_contract_rejects_formatting_controls_and_long_aliases(self):
        for value in ('x'*25,'name\u202efake','line\nfeed'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                validate(self.document(meta={'alias':value}))

    def test_usage_timestamps_are_required_bounded_and_not_fabricated(self):
        for value in (None,-10**20,float('inf'),True,int(time.time())+86400):
            usage={'ok':True,'source':SOURCE,'fetched_at':value,'summary':{},'dailyUsageBuckets':[]}
            with self.subTest(value=value),self.assertRaises(ValueError):validate(self.document(usage=usage))

    def test_unknown_quota_fields_never_cross_into_state_or_ui(self):
        raw={'ok':True,'fetched_at':int(time.time()),'tokens':{'private':'synthetic-only'},
             'windows':[{'used':10,'resets_at':2000000000,'duration_mins':300,'credential':'synthetic-only'}]}
        clean=validate(self.document(quota=raw))['accounts'][0]['quota']
        self.assertNotIn('tokens',clean);self.assertNotIn('credential',clean['windows'][0])
        self.assertEqual(clean['windows'][0]['label'],'5h')
        self.assertIn('tokens',raw)

    def test_membership_hints_cannot_claim_online_verification(self):
        with self.assertRaises(ValueError):validate(self.document(subscription={'verified':True,'date':2000000000}))
        row=validate(self.document(subscription={'verified':False,'date':2000000000,'source':'untrusted','account_checked_online':True}))['accounts'][0]
        self.assertFalse(row['subscription']['account_checked_online'])
        self.assertEqual(row['subscription']['source'],'credential_claim')

    def test_archived_accounts_require_restorable_credentials(self):
        with self.assertRaises(ValueError):validate(self.document(archived=True))

    def test_account_and_usage_identity_are_bound_to_credential(self):
        raw=auth('audit@example.com');key=credential_identity_key(raw,'audit@example.com')
        row={'credential':base64.b64encode(raw).decode(),'identity_key':'0'*64}
        with self.assertRaises(ValueError):validate(self.document(**row))
        row['identity_key']=key
        row['usage']={'ok':True,'source':SOURCE,'identity_key':'0'*64,'fetched_at':int(time.time()),'summary':{}}
        with self.assertRaises(ValueError):validate(self.document(**row))

    def test_missing_metadata_and_failed_optional_records_remain_safe(self):
        row=validate(self.document(meta=None,usage={'ok':False,'untrusted':'value'}))['accounts'][0]
        self.assertIsNone(row['usage']);self.assertIsNone(row['meta'])

if __name__=='__main__':unittest.main()
