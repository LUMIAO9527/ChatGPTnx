"""Password-encrypted portable backups and transactional, local re-encryption."""
from __future__ import annotations
import base64
import copy
from contextlib import contextmanager
import json
import math
from pathlib import Path
import re
import secrets
import time
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .credentials import assert_safe_path, credential_store_lock, encode_credential_bytes, read_credential_bytes
from .settings import valid_setting
from .storage import atomic_bytes, safe_email, account_identity_key, credential_identity_key
from .account_meta import validate as account_meta

MAGIC=b'NXBACK1\x00'
MAX_SIZE=32*1024*1024
PORTABLE_SETTINGS={'appearance','window_material','notify_low','notify_reset_expiry','notify_credential',
                   'auto_relay','auto_relay_excluded','early_anchor','early_anchor_accounts',
                   'task_continuation','resume_message','poll_minutes','query_timeout','query_workers'}
JOURNAL='transfer-transaction.json'

def dump(value):
    return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')

def load(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('备份内容存在重复字段')
            result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('备份数值不合法')))

def password_key(password,salt):
    if not isinstance(password,str) or not 8<=len(password)<=128:
        raise ValueError('备份密码需要 8 至 128 位')
    return PBKDF2HMAC(algorithm=SHA256(),length=32,salt=salt,iterations=600000).derive(password.encode('utf-8'))

def seal(document,password):
    salt,nonce=secrets.token_bytes(16),secrets.token_bytes(12)
    raw=dump(document)
    if len(raw)>MAX_SIZE-128:raise ValueError('所选备份内容过大')
    return MAGIC+salt+nonce+AESGCM(password_key(password,salt)).encrypt(nonce,raw,MAGIC)

def unseal(raw,password):
    if len(raw)>MAX_SIZE or len(raw)<len(MAGIC)+44 or not raw.startswith(MAGIC):
        raise ValueError('这个文件不是完整的 NX 备份，请重新选择')
    offset=len(MAGIC);salt=raw[offset:offset+16];nonce=raw[offset+16:offset+28]
    try:plain=AESGCM(password_key(password,salt)).decrypt(nonce,raw[offset+28:],MAGIC)
    except InvalidTag:raise ValueError('密码不正确或备份文件已损坏，请检查后重试') from None
    try:return validate(load(plain))
    except (UnicodeError,TypeError,KeyError,RecursionError):raise ValueError('备份内容不完整，请重新导出') from None

def credential(raw,email):
    if raw is None:return None
    if not isinstance(raw,str) or len(raw)>3*1024*1024:raise ValueError('备份账号资料不合法')
    try:
        decoded=base64.b64decode(raw,validate=True)
        if len(decoded)>2*1024*1024:raise ValueError()
        document=load(decoded)
        if not isinstance(document,dict) or not isinstance(document.get('tokens'),dict):raise ValueError()
        token=document['tokens'].get('id_token','')
        piece=token.split('.')[1]
        claims=load(base64.urlsafe_b64decode(piece+'='*(-len(piece)%4)))
        if not isinstance(claims,dict) or str(claims.get('email','')).casefold()!=email.casefold():raise ValueError()
        return decoded
    except (ValueError,TypeError,IndexError,AttributeError,KeyError,UnicodeError):
        raise ValueError('备份账号与登录资料不匹配') from None

def time_value(value):
    if value is None:
        return None
    if (type(value) not in (int, float) or not math.isfinite(value)
            or not 0 <= value < 253402300800):
        raise ValueError('备份采集时间不合法')
    return value


def identity_key(value):
    if value is not None and (not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value)):
        raise ValueError('备份账号身份不合法')
    return value


def observation(value):
    value = time_value(value)
    if value is not None and value > time.time() + 300:
        raise ValueError('备份采集时间晚于当前时间，请核对系统时间')
    return value


def quota_record(raw, email):
    """Rebuild the public quota shape; arbitrary imported fields never enter state."""
    from .quota import label, normalize_usage_credits, normalize_banked_resets
    from .diagnostics_http import safe_code, safe_fields, message
    if not isinstance(raw, dict) or type(raw.get('ok')) is not bool:
        raise ValueError('备份额度格式不合法')
    windows = raw.get('windows', [])
    if not isinstance(windows, list) or len(windows) > 2:
        raise ValueError('备份额度窗口不合法')
    clean = []
    for window in windows:
        if not isinstance(window, dict):
            raise ValueError('备份额度窗口不合法')
        used, reset = window.get('used'), time_value(window.get('resets_at'))
        duration = window.get('duration_mins', window.get('duration'))
        if (type(used) not in (int, float) or not math.isfinite(used) or not 0 <= used <= 100
                or reset is None or reset <= 0 or type(duration) not in (int, float)
                or not math.isfinite(duration) or not 1 <= duration <= 5256000):
            raise ValueError('备份额度窗口不合法')
        clean.append({'label': label(duration), 'duration_mins': duration, 'used': used, 'resets_at': reset})
    if raw['ok'] and not clean:
        raise ValueError('备份额度窗口不完整')
    plan = raw.get('plan', 'unknown')
    if not isinstance(plan, str) or len(plan) > 64 or not plan.isprintable():
        raise ValueError('备份会员类型不合法')
    credit = raw.get('credit_info') or {}
    if not isinstance(credit, dict):
        raise ValueError('备份 Credits 格式不合法')
    credits = normalize_usage_credits({'unlimited': credit.get('status') == 'unlimited',
                                      'balance': credit.get('balance', raw.get('credits'))})
    bank = raw.get('banked_resets')
    resets = None
    if bank is not None:
        if not isinstance(bank, dict) or not isinstance(bank.get('items'), (list, type(None))):
            raise ValueError('备份重置次数格式不合法')
        items = bank.get('items')
        if items is not None and (len(items) > 50 or any(not isinstance(item, dict) for item in items)):
            raise ValueError('备份重置次数格式不合法')
        resets = normalize_banked_resets({'availableCount': bank.get('available_count'), 'credits': None if items is None else [
            {'id': item.get('id'), 'title': item.get('title'), 'description': item.get('description'),
             'resetType': item.get('reset_type'), 'status': item.get('status'), 'grantedAt': item.get('granted_at'),
             **({'expiresAt': item.get('expires_at')} if item.get('expires_known') is True else {})}
            for item in items]})
        if resets is None:
            raise ValueError('备份重置次数格式不合法')
    result = {'email': email, 'ok': raw['ok'], 'windows': clean, 'plan': plan,
              'fetched_at': observation(raw.get('fetched_at')), 'credits': credits['balance'],
              'credit_info': credits, 'banked_resets': resets}
    if not raw['ok']:
        code = safe_code(raw.get('error_code'))
        result.update(error_code=code, err=message(code), **safe_fields(raw))
    if isinstance(raw.get('query_warning'), dict):
        warning = raw['query_warning'];code = safe_code(warning.get('error_code'))
        result['query_warning'] = {**safe_fields(warning), 'error_code': code, 'err': message(code)}
    return result


def subscription_record(raw, key):
    if not isinstance(raw, dict) or raw.get('verified', False) is not False:
        raise ValueError('备份会员资料格式不合法')
    until = time_value(raw.get('date'))
    return {'status': 'cached_hint' if until else 'not_provided', 'date': until,
            'date_kind': 'entitlement_hint' if until else None,
            'source': 'credential_claim' if until else 'not_available', 'verified': False,
            'observed_at': observation(raw.get('observed_at')), 'checked_at': observation(raw.get('checked_at')),
            'account_read_ok': raw.get('account_read_ok') is True, 'account_checked_online': False,
            'error': None, 'billing_date_supported': False, 'identity_key': key}


def validate(document):
    """Validate every row before returning a canonical, credential-separated document."""
    if (not isinstance(document, dict) or type(document.get('schema')) is not int
            or document['schema'] != 1 or not isinstance(document.get('accounts'), list)):
        raise ValueError('不支持的 NX 备份格式')
    if not 1 <= len(document['accounts']) <= 500:
        raise ValueError('备份账号数量不合法')
    result = {'schema': 1, 'accounts': []}
    if 'created_at' in document:
        result['created_at'] = observation(document['created_at'])
    seen = set()
    for raw in document['accounts']:
        if not isinstance(raw, dict):
            raise ValueError('备份账号格式不合法')
        email = safe_email(raw.get('email'));fold = email.casefold()
        if fold in seen:
            raise ValueError('备份中有重复账号')
        seen.add(fold)
        decoded = credential(raw.get('credential'), email)
        if type(raw.get('archived', False)) is not bool:
            raise ValueError('备份归档状态不合法')
        if raw.get('archived') and decoded is None:
            raise ValueError('归档账号缺少登录资料，请重新导出')
        item = {k: raw[k] for k in ('email', 'credential', 'archived') if k in raw}
        key = identity_key(raw.get('identity_key'))
        if decoded is not None:
            actual = credential_identity_key(decoded, email)
            if key is not None and key != actual:
                raise ValueError('备份账号与登录身份不匹配')
            key = actual
        if key is not None:
            item['identity_key'] = key
        for field in ('meta', 'quota', 'usage', 'subscription'):
            value = raw.get(field)
            if value is not None and not isinstance(value, dict):
                raise ValueError('备份资料格式不合法')
            if field in raw:
                item[field] = value
        if raw.get('meta'):
            item['meta'] = account_meta(raw['meta'])
        if raw.get('quota'):
            item['quota'] = quota_record(raw['quota'], email)
        usage = raw.get('usage')
        if usage:
            from .usage import normalized, SOURCE
            if type(usage.get('ok')) is not bool:
                raise ValueError('备份用量状态不合法')
            if usage['ok']:
                if usage.get('source') != SOURCE:
                    raise ValueError('备份用量来源不合法')
                observed = observation(usage.get('fetched_at'))
                if observed is None:
                    raise ValueError('备份用量缺少采集时间')
                usage_key = identity_key(usage.get('identity_key'))
                if key and usage_key != key:
                    raise ValueError('备份用量与账号身份不匹配')
                item['usage'] = {**normalized(usage, now=observed), 'fetched_at': observed, 'identity_key': usage_key}
            else:
                item['usage'] = None
        if raw.get('subscription'):
            subscription_key = identity_key(raw['subscription'].get('identity_key'))
            if key and subscription_key != key:
                raise ValueError('备份会员资料与账号身份不匹配')
            item['subscription'] = subscription_record(raw['subscription'], subscription_key)
        result['accounts'].append(item)
    settings = document.get('settings')
    if settings is not None:
        if (not isinstance(settings, dict) or any(k not in PORTABLE_SETTINGS or not valid_setting(k, v)
                                                for k, v in settings.items())):
            raise ValueError('备份设置不合法')
        for field in ('auto_relay_excluded', 'early_anchor_accounts'):
            if field in settings and (len(settings[field]) > 100 or any(safe_email(e) != e for e in settings[field])):
                raise ValueError('备份接力账号设置不合法')
        result['settings'] = copy.deepcopy(settings)
    return result

def transaction_path(paths,name):
    if not isinstance(name,str):raise ValueError('恢复记录路径不合法')
    relative=Path(name)
    if relative.is_absolute() or '..' in relative.parts or not (
        name in ('accounts.txt','_data/state.json') or
        len(relative.parts)==2 and relative.parts[0]=='snapshots' and relative.suffix=='.json' or
        len(relative.parts)==3 and relative.parts[:2]==('snapshots','removed') and relative.suffix=='.json'):
        raise ValueError('恢复记录路径不合法')
    if relative.parts[0]=='snapshots':safe_email(relative.name[:-5])
    return assert_safe_path(paths.root/relative)

def recover(paths):
    journal=paths.data/JOURNAL
    if not journal.exists():return
    document=load(assert_safe_path(journal).read_bytes())
    if (not isinstance(document,dict) or type(document.get('schema')) is not int or document['schema']!=1
            or not isinstance(document.get('entries'),list) or len(document['entries'])>502):
        raise ValueError('导入恢复记录不完整')
    entries=[(transaction_path(paths,e['path']),base64.b64decode(e['old'],validate=True) if e['old'] is not None else None) for e in document['entries']]
    if len({target for target,_ in entries})!=len(entries):raise ValueError('导入恢复记录存在重复路径')
    for target,old in entries:
        if old is None:target.unlink(missing_ok=True)
        else:atomic_bytes(target,old,private=True)
    journal.unlink()

def commit(paths,writes):
    entries=[]
    for target,data in writes.items():
        target=assert_safe_path(target)
        relative=target.relative_to(paths.root).as_posix();transaction_path(paths,relative)
        old=target.read_bytes() if target.exists() else None
        entries.append({'path':relative,'old':base64.b64encode(old).decode('ascii') if old is not None else None})
    atomic_bytes(paths.data/JOURNAL,dump({'schema':1,'entries':entries}),private=True)
    try:
        for target,data in writes.items():atomic_bytes(target,data,private=True)
        (paths.data/JOURNAL).unlink()
    except Exception:
        recover(paths)
        raise

def stamp(value):
    result=(value or {}).get('fetched_at',(value or {}).get('checked_at',0))
    return result if type(result) in (int,float) else 0

def merge_usage(existing,incoming):
    if not incoming:return existing
    if not existing:return incoming
    if existing.get('identity_key')!=incoming.get('identity_key'):return existing
    older,newer=sorted((existing,incoming),key=stamp)
    result=copy.deepcopy(newer)
    days={b['startDate']:b for b in older.get('dailyUsageBuckets') or []}
    days.update({b['startDate']:b for b in newer.get('dailyUsageBuckets') or []})
    result['dailyUsageBuckets']=[days[k] for k in sorted(days)] if days else newer.get('dailyUsageBuckets')
    return result

class Backups:
    def __init__(self,service):
        self.service=service;self.encrypted=None;self.document=None;self.name=''

    @contextmanager
    def exclusive(self):
        service=self.service
        if not service.gate.acquire(blocking=False):raise ValueError('请先完成当前操作')
        try:
            if service.stop.is_set() or service.state.get('adding') or service.state.get('reauth') or service.updater.snapshot()['status'] in ('downloading','installing'):
                raise ValueError('请先完成当前的登录或更新')
            if getattr(service,'resumer',None) and (service.resumer.summary() or {}).get('phase') in ('switching','resuming'):
                raise ValueError('请先完成当前接续')
            if not service.desktop_gate.acquire(blocking=False):raise ValueError('请先完成当前接续')
            try:
                with credential_store_lock(service.paths.snapshots),service.state.lock:yield
            finally:service.desktop_gate.release()
        finally:service.gate.release()

    def info(self):
        return {'ok':True,'archived_count':len(self.service.accounts.archived())}

    def clear(self):
        self.encrypted=None;self.document=None;self.name=''
        return {'ok':True}

    def export(self,path,options,password):
        if not isinstance(options,dict):raise ValueError('导出选项不合法')
        if any(type(options.get(key,False)) is not bool for key in ('archived','usage','preferences')):
            raise ValueError('导出选项不合法')
        with self.exclusive():
            s=self.service;emails=s.accounts.all();selected=options.get('accounts',[])
            if not isinstance(selected,list) or any(e not in emails for e in selected):raise ValueError('所选账号已变化，请重新选择')
            sources=[(e,s.paths.snapshot(e),False) for e in emails if e in selected]
            if options.get('archived'):
                sources.extend((e['email'],s.paths.snapshots/'removed'/e['key'],True) for e in s.accounts.archived())
            rows=[];seen=set();cache={e['email']:e for e in s.state.get('cache').get('accounts',[])}
            for email,source,archived in sources:
                if email.casefold() in seen:continue
                seen.add(email.casefold())
                if not archived and s.accounts.current()==email and s.paths.auth.is_file():source=s.paths.auth
                raw=read_credential_bytes(source) if source.is_file() else None
                item={'email':email,'archived':archived,'credential':base64.b64encode(raw).decode('ascii') if raw else None,
                      'meta':s.state.get('account_meta').get(email,{}),
                      'identity_key':account_identity_key(source,email),
                      'subscription':s.state.get('subscriptions').get(email)}
                if options.get('usage'):
                    item.update(quota=cache.get(email),usage=s.state.get('usage').get(email))
                rows.append(item)
            document={'schema':1,'created_at':int(time.time()),'accounts':rows}
            if options.get('preferences'):document['settings']={k:v for k,v in s.state.get('settings').items() if k in PORTABLE_SETTINGS}
            document=validate(document);encrypted=seal(document,password)
            path=assert_safe_path(Path(path))
            if path.suffix.lower()!='.nxbackup':raise ValueError('请选择 .nxbackup 文件')
            atomic_bytes(path,encrypted,private=True)
            return {'ok':True,'filename':path.name,'count':len(rows)}

    def select(self,path):
        self.document=None;self.encrypted=None
        path=assert_safe_path(Path(path))
        if path.stat().st_size>MAX_SIZE:raise ValueError('备份文件过大')
        with path.open('rb') as stream:raw=stream.read(MAX_SIZE+1)
        if len(raw)>MAX_SIZE:raise ValueError('备份文件过大')
        if not raw.startswith(MAGIC):raise ValueError('这个文件不是 NX 备份，请重新选择')
        self.encrypted=raw;self.name=path.name
        return {'ok':True,'filename':self.name}

    def unlock(self,password):
        self.document=None
        if self.encrypted is None:raise ValueError('请先选择备份文件')
        document=unseal(self.encrypted,password)
        active={e.casefold() for e in self.service.accounts.all()}
        archived={e['email'].casefold() for e in self.service.accounts.archived()}
        self.document=document
        rows=[{'email':r['email'],'alias':(r.get('meta') or {}).get('alias',''),'archived':r.get('archived',False),
               'duplicate':r['email'].casefold() in active|archived,'needsLogin':r.get('credential') is None} for r in document['accounts']]
        return {'ok':True,'accounts':rows,'usage':any(r.get('quota') or r.get('usage') for r in document['accounts']),
                'preferences':document.get('settings') is not None}

    def import_selected(self,options):
        if self.document is None:raise ValueError('请先解锁备份')
        if not isinstance(options,dict) or options.get('merge') not in ('merge','skip'):raise ValueError('导入选项不合法')
        selected=options.get('accounts')
        if (not isinstance(selected,list) or not selected or any(not isinstance(e,str) for e in selected)
                or set(selected)-{r['email'] for r in self.document['accounts']}):
            raise ValueError('请选择备份中的账号')
        if any(type(options.get(key,False)) is not bool for key in ('usage','preferences')):
            raise ValueError('导入选项不合法')
        with self.exclusive():
            s=self.service;paths=s.paths;candidate=copy.deepcopy(s.state.value);emails=s.accounts.all()
            active={e.casefold():e for e in emails};archived={r['email'].casefold():r for r in s.accounts.archived()}
            writes={};added=merged=needs=0
            quotas={r['email']:r for r in candidate['cache'].get('accounts',[])}
            for row in self.document['accounts']:
                if row['email'] not in selected:continue
                folded=row['email'].casefold();duplicate=folded in active or folded in archived
                if duplicate and options['merge']=='skip':continue
                email=active.get(folded,archived.get(folded,{}).get('email',row['email']))
                if duplicate:merged+=1
                else:added+=1
                if folded in archived:target=paths.snapshots/'removed'/archived[folded]['key']
                elif row.get('archived') and folded not in active:target=paths.snapshots/'removed'/f'{email}.{int(time.time())}.{uuid.uuid4().hex[:8]}.json'
                else:
                    target=paths.snapshot(email)
                    if folded not in active:emails.append(email);active[folded]=email
                raw=credential(row.get('credential'),row['email'])
                bound=not target.exists() or row.get('identity_key')==account_identity_key(target,email)
                if raw is not None and not target.exists():writes[target]=encode_credential_bytes(raw)
                if raw is None and not target.exists():needs+=1
                old=candidate['account_meta'].get(email,{})
                incoming_meta=row.get('meta') or {}
                candidate['account_meta'][email]={k:old.get(k) or incoming_meta.get(k) for k in ('alias','subscription_date')
                                                 if old.get(k) or incoming_meta.get(k)}
                if bound and options.get('usage'):
                    incoming=row.get('quota')
                    if incoming and stamp(incoming)>stamp(quotas.get(email)):quotas[email]={**incoming,'email':email}
                    candidate['usage'][email]=merge_usage(candidate['usage'].get(email),row.get('usage')) or {}
                if bound and stamp(row.get('subscription'))>stamp(candidate['subscriptions'].get(email)):
                    candidate['subscriptions'][email]=copy.deepcopy(row['subscription'])
            if not added and not merged:raise ValueError('没有需要导入的账号')
            candidate['cache']['accounts']=list(quotas.values())
            candidate['usage_revision']=candidate.get('usage_revision',0)+1
            if options.get('preferences') and self.document.get('settings') is not None:
                portable=copy.deepcopy(self.document['settings'])
                for key in ('auto_relay_excluded','early_anchor_accounts'):
                    if key in portable:portable[key]=[e for e in portable[key] if e in emails]
                candidate['settings'].update(portable)
            comments=[]
            if paths.order.exists():comments=[l for l in paths.order.read_text(encoding='utf-8-sig').splitlines() if l.strip().startswith('#')]
            writes[paths.order]=('\n'.join(comments+emails)+'\n').encode('utf-8')
            writes[s.state.path]=dump(candidate)
            commit(paths,writes);s.state.value=candidate;s.accounts._order_signature=None
            self.clear()
            if getattr(s,'resumer',None):
                try:
                    settings=candidate['settings']
                    s.resumer.set_auto_enabled(settings['auto_relay'],settings.get('auto_relay_excluded') or [])
                    if settings['task_continuation']:s.resumer.wake.set()
                    else:s.resumer.cancel_active()
                except Exception:s.log.warning('import_resume_settings_sync_failed')
        s.notify()
        return {'ok':True,'added':added,'merged':merged,'needs_login':needs}
