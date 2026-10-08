"""Account activity and subscription truthfulness regressions; offline fixtures only."""
from pathlib import Path
from datetime import date
import sys, json, time, unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from nx.usage import aggregate, normalized, count, SOURCE
from nx.subscription import from_credential
from nx.storage import atomic_bytes, account_identity_key, activity_identity_key, State
from nx.quota import Query
from test_core import Fixture, auth

NOW=1789948800  # 2026-09-21 UTC
ACCOUNTS=[{'email':'a@example.com','identity_key':'key-a','activity_key':'person-a'},
          {'email':'b@example.com','identity_key':'key-b','activity_key':'person-b'}]
def item(key,total=10,buckets=None,at=NOW):
    return {**normalized({'summary':{'lifetimeTokens':total,'currentStreakDays':4,'peakDailyTokens':8},
            'dailyUsageBuckets':buckets},now=at),'identity_key':key}
def cache():return {'a@example.com':item('key-a',10),'b@example.com':item('key-b',20)}
def result(c=None,a=None,**kw):return aggregate(a or ACCOUNTS,cache() if c is None else c,now=NOW,**kw)

class UsageMathTests(unittest.TestCase):
    def test_exact_sum(self):self.assertEqual(result()['total_tokens'],'30')
    def test_full_account_coverage(self):self.assertTrue(result()['total_complete'])
    def test_failed_is_not_zero(self):
        c=cache();c['b@example.com']={'ok':False,'err':'offline','identity_key':'key-b'}
        r=result(c);self.assertEqual(r['total_tokens'],'10');self.assertFalse(r['total_complete']);self.assertEqual(r['included_accounts'],1)
    def test_no_records_is_not_zero(self):self.assertIsNone(result({})['total_tokens'])
    def test_real_zero_is_known(self):
        c={x['email']:item(x['identity_key'],0) for x in ACCOUNTS};r=result(c);self.assertEqual(r['total_tokens'],'0');self.assertTrue(r['total_complete'])
    def test_null_total_is_not_zero(self):
        c=cache();c['a@example.com']['summary']['lifetimeTokens']=None;r=result(c);self.assertEqual(r['total_tokens'],'20');self.assertEqual(r['rows'][0]['status'],'missing_total')
    def test_old_success_remains_visible(self):
        c=cache();c['a@example.com']['fetched_at']=NOW-86400;self.assertEqual(result(c)['total_tokens'],'30')
    def test_clock_skew_does_not_blank_success(self):
        c=cache();c['a@example.com']['fetched_at']=NOW+1;self.assertEqual(result(c)['total_tokens'],'30')
    def test_wrong_source_not_added(self):
        c=cache();c['a@example.com']['source']='local-log';self.assertEqual(result(c)['total_tokens'],'20')
    def test_identity_change_not_added(self):
        c=cache();c['a@example.com']['identity_key']='other';self.assertEqual(result(c)['rows'][0]['status'],'identity_changed')
    def test_legacy_unbound_not_added(self):
        c=cache();del c['a@example.com']['identity_key'];self.assertEqual(result(c)['total_tokens'],'20')
    def test_duplicate_person_not_added_twice(self):
        a=[*ACCOUNTS,{'email':'alias@example.com','identity_key':'key-alias','activity_key':'person-a'}]
        c=cache();c['alias@example.com']=item('key-alias',10);r=result(c,a);self.assertEqual(r['total_tokens'],'30');self.assertEqual(r['unique_accounts'],2);self.assertEqual(r['rows'][2]['status'],'duplicate')
    def test_large_counter_lossless(self):
        c=cache();c['a@example.com']=item('key-a',9007199254740993123);self.assertEqual(result(c)['total_tokens'],'9007199254740993143')
    def test_invalid_counts(self):
        for v in [True,False,-1,1.5,'1e9','-1','１２',None]:self.assertIsNone(count(v))
    def test_daily_missing_not_filled(self):
        c=cache();c['a@example.com']=item('key-a',10,[{'startDate':'2026-09-21','tokens':3}]);r=result(c);self.assertEqual(len(r['daily']),1);self.assertFalse(r['period']['complete'])
    def test_partial_day_exposes_coverage(self):
        c=cache();c['a@example.com']=item('key-a',10,[{'startDate':'2026-09-21','tokens':3}]);r=result(c);self.assertEqual(r['daily'][0]['accounts'],1);self.assertFalse(r['daily'][0]['complete'])
    def test_daily_zero_differs_from_missing(self):
        c=cache();c['a@example.com']=item('key-a',10,[{'startDate':'2026-09-21','tokens':0}]);self.assertEqual(result(c)['daily'][0]['tokens'],'0')
    def test_conflicting_duplicate_omitted(self):
        v=item('a',1,[{'startDate':'2026-09-21','tokens':2},{'startDate':'2026-09-21','tokens':3}]);self.assertEqual(v['dailyUsageBuckets'],[]);self.assertEqual(v['conflicting_dates'],['2026-09-21'])
    def test_bad_dates_not_normalized_into_real_days(self):
        v=item('a',1,[{'startDate':'2026-09-99','tokens':2}]);self.assertEqual(v['dailyUsageBuckets'],[])
    def test_peak_streak_never_summed(self):self.assertNotIn('currentStreakDays',result());self.assertNotIn('peakDailyTokens',result())
    def test_period_does_not_change_lifetime(self):self.assertEqual(result(days=7)['total_tokens'],result(days=90)['total_tokens'])
    def test_selected_window_has_per_account_totals(self):
        c=cache();c['a@example.com']=item('key-a',100,[{'startDate':'2026-09-21','tokens':3}]);c['b@example.com']=item('key-b',200,[{'startDate':'2026-09-21','tokens':7}])
        r=result(c,days=7);self.assertEqual(r['total_tokens'],'300');self.assertEqual(r['period']['recorded_tokens'],'10');self.assertEqual([x['period_tokens'] for x in r['rows']],['3','7'])
    def test_all_uses_lifetime_but_exposes_available_daily_range(self):
        c=cache();c['a@example.com']=item('key-a',100,[{'startDate':'2026-01-01','tokens':3},{'startDate':'2026-09-21','tokens':7}])
        r=result(c,days='all');self.assertEqual(r['total_tokens'],'120');self.assertEqual(r['period']['days'],'all');self.assertEqual(r['period']['start'],'2026-01-01');self.assertEqual(r['period']['recorded_tokens'],'10');self.assertFalse(r['period']['complete'])
    def test_missing_daily_account_is_not_zero(self):
        c=cache();c['a@example.com']=item('key-a',100,[{'startDate':'2026-09-21','tokens':3}]);r=result(c,days=7)
        self.assertEqual(r['rows'][0]['period_tokens'],'3');self.assertIsNone(r['rows'][1]['period_tokens']);self.assertFalse(r['period']['complete'])
    def test_period_outside_bucket_ignored(self):
        c=cache();c['a@example.com']=item('key-a',10,[{'startDate':'2020-01-01','tokens':100}]);self.assertEqual(result(c,days=7)['daily'],[])
    def test_invalid_period_defaults(self):self.assertEqual(result(days=13)['period']['days'],30)
    def test_period_end_uses_viewer_local_calendar_day(self):
        with patch('nx.usage._local_date',return_value=date(2026,9,22)):
            self.assertEqual(result(days=7)['period']['end'],'2026-09-22')

class SubscriptionAndServiceTests(Fixture):
    def test_malformed_credential_does_not_crash_panel(self):
        atomic_bytes(self.paths.snapshot('b@example.com'),b'[1,2]')
        self.assertEqual(len(self.service.get_data()['accounts']),2)
    def test_nested_bad_credential_safe(self):
        atomic_bytes(self.paths.snapshot('b@example.com'),b'{"tokens":[1]}')
        self.assertIsNone(from_credential(self.paths.snapshot('b@example.com'))['date'])

    def test_token_exp_not_a_membership_date(self):self.assertIsNone(from_credential(self.paths.auth)['date'])
    def test_local_account_read_does_not_verify_billing(self):
        atomic_bytes(self.paths.auth,auth('a@example.com',{'chatgpt_subscription_active_until':'2027-01-01T00:00:00Z'}))
        v=from_credential(self.paths.auth,checked_at=NOW,account_read_ok=True)
        self.assertTrue(v['account_read_ok']);self.assertFalse(v['account_checked_online']);self.assertFalse(v['verified']);self.assertFalse(v['billing_date_supported'])
    def test_member_auto_read_cached(self):
        self.service.get_subscription('a@example.com');self.wait();n=len(self.query.calls)
        self.service.get_subscription('a@example.com');self.assertEqual(len(self.query.calls),n)
    def test_member_refresh_can_retry(self):
        self.service.get_subscription('a@example.com');self.wait();n=len(self.query.calls)
        self.service.get_subscription('a@example.com',True);self.wait();self.assertEqual(len(self.query.calls),n+1)
    def test_total_usage_fetches_all_accounts(self):
        self.service.get_usage_all();self.wait();r=self.service.read_usage_all();self.assertEqual(r['total_tokens'],'84');self.assertEqual(r['included_accounts'],2)
    def test_total_usage_success_cached(self):
        self.service.get_usage_all();self.wait();n=len(self.query.calls);self.service.get_usage_all();self.assertEqual(n,len(self.query.calls))
    def test_archived_account_keeps_history_without_refresh(self):
        atomic_bytes(self.paths.snapshot('b@example.com'), auth('b@example.com', {'chatgpt_plan_type': 'plus'}))
        self.service.get_usage_all();self.wait()
        before=len(self.query.calls)
        key=self.accounts.archive('b@example.com')
        archived=self.service.read_usage_all(days='all')
        row=next(r for r in archived['rows'] if r['email']=='b@example.com')
        self.assertTrue(row['archived'])
        self.assertEqual(row['plan'], 'plus')
        self.assertEqual(row['tokens'],'42')
        self.assertEqual(archived['total_tokens'],'84')
        self.service.get_usage_all(force=True);self.wait()
        self.assertEqual(len(self.query.calls),before+1)
        self.accounts.restore(key)
        restored=next(r for r in self.service.read_usage_all()['rows'] if r['email']=='b@example.com')
        self.assertFalse(restored['archived'])
        self.assertEqual(restored['tokens'],'42')
    def test_archived_history_survives_disk_reload_without_network(self):
        from nx.storage import Accounts
        atomic_bytes(self.paths.snapshot('b@example.com'), auth('b@example.com', {'chatgpt_plan_type': 'pro'}))
        self.service.get_usage_all();self.wait()
        archive_key = self.accounts.archive('b@example.com')
        archive_path = self.paths.snapshots / 'removed' / archive_key
        archive_bytes = archive_path.read_bytes()
        before=len(self.query.calls)
        self.service.state=State(self.paths)
        self.service.accounts=Accounts(self.paths)
        archived=self.service.read_usage_all(days='all')
        row=next(r for r in archived['rows'] if r['email']=='b@example.com')
        self.assertTrue(row['archived']);self.assertEqual(row['tokens'],'42')
        self.assertEqual(row['plan'], 'pro')
        self.assertEqual(archived['total_tokens'],'84')
        self.assertEqual(len(self.query.calls),before)
        self.assertEqual(archive_path.read_bytes(), archive_bytes)
        self.assertNotIn('synthetic-test-only', json.dumps(archived))

    def test_failed_account_kept_separate(self):
        self.query.fail.add('b@example.com');self.service.get_usage_all();self.wait();r=self.service.read_usage_all();self.assertEqual(r['total_tokens'],'42');self.assertEqual(r['included_accounts'],1)
    def test_switch_terminal_result_survives_followup_refresh(self):
        self.refresh();accepted=self.service.switch('b@example.com');self.wait();self.refresh()
        values=self.service.get_data()['recent_results'];self.assertTrue(any(v['id']==accepted['operation_id'] and v['ok'] for v in values))
    def test_removed_settings_do_not_survive_loading(self):
        atomic_bytes(self.paths.data/'state.json',b'{"settings":{"theme":"orbit","obsolete":true}}')
        s=State(self.paths);self.assertNotIn('theme',s.get('settings'));self.assertNotIn('obsolete',s.get('settings'))
    def test_public_identity_keys_not_raw_subject(self):
        key=account_identity_key(self.paths.auth,'a@example.com');self.assertEqual(len(key),64);self.assertNotIn('@',key)
    def test_usage_identity_mismatch_is_rejected(self):
        from unittest.mock import Mock
        data=json.loads(auth('a@example.com'));data['tokens']['access_token']='fixture-access'
        atomic_bytes(self.paths.auth,json.dumps(data).encode())
        client=Mock();client.get.return_value={'account_id':'other','email':'wrong@example.com'}
        q=Query(self.paths,lambda:{},client=client);r=q.run('a@example.com',True,usage=True)
        self.assertFalse(r['ok']);self.assertEqual(r['error_code'],'identity_mismatch')
        self.assertEqual(client.get.call_count,1)
    def test_billing_read_has_no_guessed_endpoint(self):
        from unittest.mock import Mock
        data=json.loads(auth('a@example.com'));data['tokens']['access_token']='fixture-access'
        atomic_bytes(self.paths.auth,json.dumps(data).encode())
        client=Mock();client.get.return_value={'account_id':'fixture-a@example.com','email':'a@example.com','plan_type':'plus'}
        q=Query(self.paths,lambda:{},client=client);r=q.run('a@example.com',True,subscription=True)
        self.assertEqual([c.args[0] for c in client.get.call_args_list],['/wham/usage'])
        self.assertFalse(r['verified']);self.assertFalse(r['account_checked_online'])

if __name__=='__main__':unittest.main(verbosity=2)
