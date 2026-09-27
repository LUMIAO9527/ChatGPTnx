"""One inventory feeds the live explorer, screenshot capture and route-coverage tests.

Cases cover maintained routes and explicit decision/feedback states, not the
Cartesian product of all possible values. Native Windows surfaces are separate.
"""
from urllib.parse import urlencode

CASES = []
def add(group, key, label, *, route=None, scenario=None, steps=None, note='', **params):
    query={}
    if route:query['open']=route
    if scenario:query['scenario']=scenario
    query.update(params)
    CASES.append(dict(id=key,group=group,label=label,route=route or 'home',query=urlencode(query),steps=steps or [],note=note))

def click(action, **extra):return {'click':f'[data-action="{action}"]',**extra}
def selector(value, **extra):return {'click':value,**extra}

G='01 · 首次使用与连接'
add(G,'first-run','首次引导 · 桌面未启动',scenario='first-run',note='全屏流程；不显示空账号列表。')
add(G,'first-waiting','首次引导 · 等待登录',scenario='first-waiting')
add(G,'first-account','首次引导 · 检测到账号',scenario='empty')
add(G,'first-saving','首次引导 · 保存中',scenario='first-saving')
add(G,'first-failed','首次引导 · 保存失败',scenario='first-failed')
add(G,'connection-error','本地服务未连接',scenario='connection-error')

G='02 · 首页'
for key,label,sc in [('home','首页 · 常规',None),('home-single','首页 · 一个账号','single-account'),('home-many','首页 · 14 个账号','many'),('home-long-names','首页 · 长名称','long-names'),('home-error','首页 · 操作失败','error-home'),('home-stale','首页 · 缓存过期','stale'),('home-expired','首页 · 到点待核验','expired'),('home-no-relay','首页 · 无可用接力账号','no-relay'),('home-desktop-off','首页 · 桌面未运行','chatgpt-off'),('home-exhausted','首页 · 已耗尽且自动接力关闭','week-exhausted-auto-off'),('home-refreshing','首页 · 正在刷新','refreshing'),('home-resuming','首页 · 接续进行中','resume-progress'),('home-waiting','首页 · 等待账号恢复','resume-waiting'),('home-failed','首页 · 接续失败','resume-failed')]:add(G,key,label,scenario=sc)

G='03 · 账号详情'
for key,label,sc,params in [
 ('detail','详情 · 当前账号',None,{}),('detail-other','详情 · 其他账号',None,{'email':'backup@example.com'}),
 ('detail-pro','详情 · Pro 单额度窗口',None,{'email':'studio@example.com'}),
 ('detail-credits','详情 · Credits 余额','detail-dense',{}),('detail-credits-zero','详情 · Credits 为零','credits-zero',{}),
 ('detail-credits-unlimited','详情 · Credits 不限额','credits-unlimited',{}),('detail-credits-invalid','详情 · Credits 数据异常','credits-invalid',{}),('detail-credits-precise','详情 · Credits 精度','credits-precise',{}),
 ('detail-expanded','详情 · 重置次数展开',None,{'expand':'reset'}),('detail-zero-resets','详情 · 无可用重置次数','banked-zero',{'expand':'reset'}),('detail-unknown-resets','详情 · 重置次数未提供','banked-unknown',{'expand':'reset'}),('detail-partial-resets','详情 · 部分重置详情','banked-partial',{'expand':'reset'}),('detail-many-resets','详情 · 八条重置详情','banked-many',{'expand':'reset'}),
 ('detail-manual-date','详情 · 手工记录到期日','membership-manual',{}),('detail-no-date','详情 · 到期日未提供','member-none',{}),
 ('detail-timeout','详情 · 查询超时','detail-timeout',{}),('detail-reauth','详情 · 需要重新登录','reauth',{'email':'remote@example.com'}),
 ('detail-missing','详情 · 登录快照缺失','detail-missing',{}),('detail-unsupported','详情 · 查询接口不支持','detail-schema',{})]:add(G,key,label,route='detail',scenario=sc,**params)
add(G,'detail-picked','详情 · 已指定为下一棒',route='detail',email='backup@example.com',steps=[click('pick')])

G='04 · 额度总览'
add(G,'quota-overview','额度总览 · 接力顺序',route='quota-overview')
for scope,label in [('five','5h'),('week','周')]:
 add(G,'quota-'+scope,'额度总览 · '+label+'额度排序',route='quota-overview',steps=[selector(f'[data-action="quota-scope"][data-value="{scope}"]')])
 add(G,'quota-time-'+scope,'额度总览 · '+label+'重置时间排序',route='quota-overview',steps=[selector('[data-action="quota-metric"][data-value="time"]'),selector(f'[data-action="quota-scope"][data-value="{scope}"]')])
for key,label,sc in [('quota-many','额度总览 · 长名单','many'),('quota-plans','额度总览 · 多种会员类型','plan-types'),('quota-empty','额度总览 · 空名单','empty')]:add(G,key,label,route='quota-overview',scenario=sc)

G='05 · 个人用量'
for days in (7,30,180,'all'):add(G,'usage-'+str(days),'个人用量 · '+('全部时间' if days=='all' else f'{days} 天'),route='usage',days=days)
for key,label,sc in [('usage-empty','个人用量 · 数据未提供','usage-empty'),('usage-zero','个人用量 · 真实零值','usage-zero'),('usage-complete','个人用量 · 完整覆盖','complete'),('usage-refreshing','个人用量 · 正在更新','usage-refreshing')]:add(G,key,label,route='usage',scenario=sc)
for key,label,email in [('usage-account','分账号用量 · 正常','work-01@example.com'),('usage-account-failed','分账号用量 · 查询失败','remote@example.com')]:add(G,key,label,route='usage',email=email)
add(G,'usage-tooltip','个人用量 · 图表悬停提示',route='usage',steps=[{'hover':'.trend-bar:not(.missing)'}])

add(G,'usage-loading','个人用量 · 读取中',route='usage',scenario='usage-loading')
add(G,'usage-duplicate','个人用量 · 重复身份去重',route='usage',scenario='usage-duplicate')
add(G,'usage-identity-changed','个人用量 · 身份变化',route='usage',scenario='usage-identity-changed')

G='06 · 设置与参与账号'
add(G,'settings','设置 · 三个一级分组',route='settings')
add(G,'purchase-account','购买账号 · 微信联系',route='purchase')
add(G,'settings-automation','接力与接续 · 默认',route='automation')
add(G,'automation-on','接力与接续 · 已开启',route='automation',scenario='automation-on')
add(G,'automation-off','接力与接续 · 全关闭',route='automation',scenario='automation-off')
add(G,'settings-notifications','通知 · 默认',route='notifications')
add(G,'notifications-threshold','通知 · 低额度阈值',route='notifications',scenario='notify-low')
for key,label,sc in [('relay-accounts','参与账号 · 名称与会员等级',None),('relay-accounts-some','参与账号 · 部分参与','excluded-some'),('relay-accounts-none','参与账号 · 全部排除','excluded-all'),('relay-accounts-many','参与账号 · 长名单','many'),('relay-accounts-long','参与账号 · 长名称','long-names'),('relay-accounts-plans','参与账号 · 各会员类型','plan-types'),('relay-accounts-empty','参与账号 · 空名单','empty')]:add(G,key,label,route='relay-accounts',scenario=sc)
add(G,'resume-message','接续消息 · 编辑',route='resume-message')
add(G,'resume-message-validation','接续消息 · 无效输入反馈',route='resume-message',steps=[{'fill':'#resume-message','value':''},click('save-resume-message')])
add(G,'resume-message-saved','接续消息 · 原位保存',route='resume-message',steps=[{'fill':'#resume-message','value':'继续检查剩余内容'},click('save-resume-message')])
add(G,'scenarios','演示专用 · 场景选择',route='scenarios',note='此页只存在于演示；不编入真实产品入口。')

G='07 · 任务接续'
for key,label,sc in [('resume-empty','接续记录 · 无记录',None),('resume-progress','接续记录 · 正在接续','resume-progress'),('resume-switching','接续记录 · 正在切号','resume-switching'),('resume-waiting','接续记录 · 等待账号','resume-waiting'),('resume-failed','接续记录 · 失败','resume-failed'),('resume-success','接续记录 · 成功','resume-success'),('resume-unknown','接续记录 · 结果未确认','resume-unknown'),('resume-draft','接续记录 · 保留草稿','resume-draft'),('resume-editing','接续记录 · 正在输入','resume-editing'),('resume-no-window','接续记录 · 桌面未运行','resume-no-window'),('resume-ambiguous','接续记录 · 多窗口不明确','resume-ambiguous'),('resume-skipped','接续记录 · 已在运行而跳过','resume-skipped'),('resume-history','接续记录 · 时间分组','resume-history')]:add(G,key,label,route='resume',scenario=sc)
add(G,'resume-history-expanded','接续记录 · 历史展开',route='resume',scenario='resume-history',steps=[click('resume-toggle')])
add(G,'resume-collapsed','接续记录 · 折叠进行中',route='resume',scenario='resume-progress',steps=[click('resume-toggle')])
add(G,'resume-clear','清理已结束记录 · 确认',route='resume',scenario='resume-history',steps=[click('resume-clear')])

G='08 · 账号操作与确认'
for key,label,sc in [('add-confirm','添加账号 · 重启确认',None),('add-opening','添加账号 · 正在打开','adding-opening'),('add-waiting','添加账号 · 等待登录','adding-home'),('add-ready','添加账号 · 登录就绪','adding-ready'),('add-unchanged','添加账号 · 仍是原账号','adding-unchanged'),('add-existing','添加账号 · 已在清单','adding-existing'),('add-saving','添加账号 · 保存中','adding-saving'),('add-cancelling','添加账号 · 恢复原账号','adding-cancelling')]:add(G,key,label,route='add',scenario=sc)
for key,label,sc in [('reauth','重新登录 · 重启确认','reauth'),('reauth-login','重新登录 · 等待验证','reauth-login'),('reauth-saving','重新登录 · 验证中','reauth-saving'),('reauth-cancelling','重新登录 · 恢复原账号','reauth-cancelling')]:add(G,key,label,route='reauth',scenario=sc,email='remote@example.com')
add(G,'switch-confirm','切换账号 · 确认',route='confirm')
add(G,'relay-confirm','账号接力 · 确认',route='confirm',kind='relay')
add(G,'switch-in-progress','切换账号 · 正在切换',route='confirm',scenario='switching')
add(G,'switch-error','切换账号 · 失败反馈',scenario='fail-switch',steps=[click('relay'),click('execute-switch',wait=1900)])
add(G,'edit','编辑账号 · 昵称',route='edit')
add(G,'edit-date','编辑账号 · 到期日期录入',route='edit',steps=[{'fill':'#manual-date','value':'2027-01-15'}])
add(G,'remove','归档账号 · 确认',route='remove',email='backup@example.com')
add(G,'archives-empty','归档账号 · 空名单',route='archives')
add(G,'archives','归档账号 · 待恢复',route='archives',scenario='archived')
add(G,'hotkeys','快捷键 · 列表',route='hotkeys')
add(G,'hotkeys-recording','快捷键 · 正在录制',route='hotkeys',steps=[click('record-hotkey')])
add(G,'hotkeys-conflict','快捷键 · 被占用',route='hotkeys',scenario='hotkey-conflict')
add(G,'hotkeys-empty','快捷键 · 无账号',route='hotkeys',scenario='empty')
add(G,'error-details','操作失败 · 详情',route='error',scenario='error-home')

G='10 · 状态一致性与固定布局'
add(G,'first-launch-pending','首次引导 · 单一悬浮进度',scenario='first-launch-pending',steps=[click('launch-chatgpt')],note='原按钮只保留操作标签，进度仅由底部悬浮条显示。')
add(G,'first-launch-failed','首次引导 · 打开失败可关闭',scenario='first-launch-failed',steps=[click('launch-chatgpt',wait=850)])
add(G,'first-launch-done','首次引导 · 请求已提交',scenario='first-waiting',steps=[click('launch-chatgpt',wait=850)])
add(G,'first-recheck','首次引导 · 原按钮检测反馈',scenario='first-waiting',steps=[click('refresh-state')])
add(G,'detail-date-entry','详情 · 昵称与会员期限展开',route='detail',scenario='member-none',steps=[selector('.account-editor summary')])
add(G,'detail-date-saved','详情 · 日期保存后收起',route='detail',scenario='member-none',steps=[selector('.account-editor summary'),{'fill':'#manual-date','value':'2027-01-15'},click('save-expiry'),selector('.account-editor summary')])
add(G,'edit-saving','账号编辑 · 原按钮保存中',route='edit',scenario='save-pending',steps=[{'fill':'#alias','value':'我的工作账号'},click('save-alias')])
add(G,'edit-save-failed','账号编辑 · 内联保存错误与草稿',route='edit',scenario='save-failed',steps=[{'fill':'#alias','value':'我的工作账号'},click('save-alias')])
add(G,'settings-saving','设置 · 即时切换且后台保存',route='settings',scenario='preference-pending',steps=[selector('[data-action="toggle"]')])
add(G,'settings-save-failed','设置 · 保存失败不假装成功',route='settings',scenario='preference-failed',steps=[selector('[data-action="toggle"]')])
add(G,'relay-account-saved','参与账号 · 即时改变参与状态',route='relay-accounts',steps=[click('auto-relay-account')])
add(G,'message-save-failed','接续消息 · 保存失败保留输入',route='resume-message',scenario='preference-failed',steps=[{'fill':'#resume-message','value':'继续检查剩余任务'},click('save-resume-message')])
add(G,'message-saving','接续消息 · 原按钮保存中',route='resume-message',scenario='preference-pending',steps=[click('save-resume-message')])

G='11 · 即时设置与原地展开'
add(G,'inline-relay','接力规则 · 参与账号展开',route='automation',steps=[selector('[data-disclosure="relay"] > summary')])
add(G,'inline-relay-many','接力规则 · 长名单全部展开',route='automation',scenario='many',steps=[selector('[data-disclosure="relay"] > summary'),selector('[data-action="collection-more"][data-value="relay"]')])
add(G,'inline-message','接力规则 · 消息原地编辑',route='automation',steps=[selector('[data-disclosure="message"] > summary')])
add(G,'inline-message-failed','接力规则 · 消息保存失败保留草稿',route='automation',scenario='preference-failed',steps=[selector('[data-disclosure="message"] > summary'),{'fill':'#resume-message','value':'继续核对剩余项目'},click('save-resume-message',wait=500)])
add(G,'inline-resume','一级设置 → 独立接续记录',route='settings',scenario='resume-history',steps=[click('resume-details')])
add(G,'inline-all','接力规则 · 展开消息并收起参与名单',route='automation',scenario='resume-history',steps=[selector('[data-disclosure="relay"] > summary'),selector('[data-disclosure="message"] > summary')])
add(G,'inline-hotkeys','设置 · 快捷键展开',route='settings',steps=[selector('[data-disclosure="hotkeys"] > summary')])
add(G,'inline-hotkeys-recording','设置 · 原地录制快捷键',route='settings',steps=[selector('[data-disclosure="hotkeys"] > summary'),click('record-hotkey')])
add(G,'inline-archives','设置 · 归档账号展开',route='settings',scenario='archived',steps=[selector('[data-disclosure="archives"] > summary')])
add(G,'inline-archives-empty','设置 · 归档空状态展开',route='settings',steps=[selector('[data-disclosure="archives"] > summary')])
add(G,'inline-collapse','接力规则 · 展开后收起',route='automation',steps=[selector('[data-disclosure="relay"] > summary'),selector('[data-disclosure="relay"] > summary')])
add(G,'resume-composer-unknown','接续记录 · 输入框识别不确定',route='resume',scenario='resume-composer-unknown')
add(G,'home-composer-unknown','首页 · 接续待确认非已知草稿',scenario='resume-composer-unknown')

G='12 · 同页设置与单行编辑'
add(G,'root-notifications','系统 · 通知原地展开',route='settings',steps=[selector('[data-disclosure="notifications"] > summary')])
add(G,'root-relay','一级设置 · 参与账号简洁名单',route='settings',steps=[selector('[data-disclosure="relay"] > summary')])
add(G,'root-message','一级设置 · 单行消息与保存勾',route='settings',steps=[selector('[data-disclosure="message"] > summary')])
add(G,'root-message-saved','一级设置 · 消息保存原位反馈',route='settings',steps=[selector('[data-disclosure="message"] > summary'),{'fill':'#resume-message','value':'继续核对未完成部分'},click('save-resume-message')])
add(G,'root-relay-many','一级设置 · 14个参与账号展开',route='relay-accounts',scenario='many',steps=[selector('[data-action="collection-more"][data-value="relay"]')])
add(G,'root-all-expanded','一级设置 · 连续切换仅保留最后一项',route='settings',scenario='resume-history',steps=[selector('[data-disclosure="notifications"] > summary'),selector('[data-disclosure="relay"] > summary'),selector('[data-disclosure="message"] > summary'),selector('[data-disclosure="hotkeys"] > summary'),selector('[data-disclosure="archives"] > summary')])
add(G,'detail-inline-alias','详情 · 昵称单行编辑',route='edit',steps=[{'fill':'#alias','value':'我的工作账号'}])
add(G,'detail-inline-expiry','详情 · 会员期限单行编辑',route='edit',steps=[{'fill':'#manual-date','value':'2027-01-15'}])
add(G,'detail-inline-saved','详情 · 昵称保存不跳页',route='edit',steps=[{'fill':'#alias','value':'我的工作账号'},click('save-alias')])
add(G,'detail-inline-error','详情 · 保存失败保留两个输入',route='edit',scenario='save-failed',steps=[{'fill':'#alias','value':'待保存昵称'},{'fill':'#manual-date','value':'2027-01-15'},click('save-alias')])
add(G,'detail-inline-both','详情 · 昵称与重置次数同时展开',route='edit',steps=[click('toggle-reset-credits')])
add(G,'home-empty-centered','首页 · 其他账号空状态居中',scenario='single-account')

G='13 · 无卡片用量与固定悬浮状态'
add(G,'usage-flat','个人用量 · 无背景卡片的统计层次',route='usage')
add(G,'usage-account-flat','分账号用量 · 相同的无卡片结构',route='usage',email='work-01@example.com')
add(G,'usage-floating-status','个人用量 · 底部悬浮接续进度',route='usage',steps=[{'simulate':'start-resume'}])
add(G,'home-floating-status','首页 · 悬浮进度覆盖第三个账号',steps=[{'simulate':'start-resume'}])
add(G,'home-floating-dismissed','首页 · 悬浮状态关闭后内容原位',scenario='resume-progress',steps=[click('dismiss-status')])
add(G,'home-floating-empty','首页 · 空列表中心与底部悬浮状态',scenario='single-account',steps=[{'simulate':'start-resume'}])
add(G,'settings-floating-status','设置 · 底部悬浮条与一级分组',route='settings',steps=[{'simulate':'start-resume'}])
add(G,'settings-notify-floating','设置 · 展开通知并显示悬浮条',route='settings',steps=[selector('[data-disclosure="notifications"] > summary'),{'simulate':'start-resume'}])
add(G,'detail-floating-status','详情 · 悬浮条距面板底边 12px',route='detail',steps=[{'simulate':'start-resume'}])
add(G,'detail-editor-floating','详情 · 内联编辑不改变悬浮位置',route='edit',steps=[{'fill':'#alias','value':'待保存昵称'},{'simulate':'start-resume'}])
add(G,'brand-onboarding','首次引导 · 统一 n× 标识',scenario='first-run')

G='14 · 统一行高与单面板'
add(G,'appearance-folded','设置 · 外观收起',route='settings')
add(G,'appearance-expanded','设置 · 外观选项展开',route='settings',steps=[selector('[data-disclosure="appearance"] > summary')])
add(G,'appearance-selected','设置 · 系统外观跟随',route='settings',steps=[selector('[data-disclosure="appearance"] > summary'),selector('[data-action="pref"][data-key="appearance"][data-value="system"]')])
add(G,'settings-header-hover','设置 · 收起条悬停',route='settings',steps=[{'hover':'[data-disclosure="notifications"] > summary'}])
add(G,'settings-expanded-hover','设置 · 展开条悬停轮廓',route='settings',steps=[selector('[data-disclosure="notifications"] > summary'),{'hover':'[data-disclosure="notifications"] > summary'}])
add(G,'hotkeys-many-expanded','快捷键 · 同高长名单',route='hotkeys',scenario='many',steps=[selector('[data-action="collection-more"][data-value="hotkeys"]')])
add(G,'usage-account-statistics','分账号用量 · 统计明细展开',route='usage',email='work-01@example.com',steps=[selector('[data-disclosure="usage-metrics"] > summary')])
add(G,'resume-auto-blocked','接续记录 · 自动消息路径不可用',route='resume',scenario='resume-auto-blocked')
add(G,'home-auto-blocked','首页 · 自动接续异常提示',scenario='resume-auto-blocked')

add(G,'resume-draft-waiting','接续记录 · 自动等待草稿处理',route='resume',scenario='resume-draft-waiting')
add(G,'home-draft-waiting','首页 · 等待输入区就绪',scenario='resume-draft-waiting')
add(G,'resume-auto-sending','接续记录 · 自动发送进行中',route='resume',scenario='resume-auto-sending')
add(G,'resume-auto-confirmed','接续记录 · 自动发送后已确认新回合',route='resume',scenario='resume-auto-sending',steps=[{'simulate':'complete-resume'}])

G='15 · 最终统一与交互恢复'
add(G,'settings-exclusive-notify-appearance','设置 · 外观展开后通知收起',route='settings',steps=[selector('[data-disclosure="notifications"] > summary'),selector('[data-disclosure="appearance"] > summary')])
add(G,'settings-exclusive-message-draft','设置 · 切换展开后保留消息草稿',route='settings',steps=[selector('[data-disclosure="message"] > summary'),{'fill':'#resume-message','value':'这条消息尚未保存'},selector('[data-disclosure="notifications"] > summary'),selector('[data-disclosure="message"] > summary')])
add(G,'settings-exclusive-hotkey','设置 · 收起快捷键时结束录制',route='hotkeys',steps=[click('record-hotkey'),selector('[data-disclosure="appearance"] > summary')])
add(G,'settings-exclusive-many','设置 · 长参与名单与固定浮条',route='relay-accounts',scenario='many',steps=[{'simulate':'start-resume'}])
add(G,'home-quota-axes','首页 · 右侧固定双额度列',scenario='plan-types')
add(G,'home-quota-long-floating','首页 · 长名称与第三行浮条',scenario='long-names',steps=[{'simulate':'start-resume'}])
add(G,'usage-flat-empty','个人用量 · 未提供今日值不显示横杠',route='usage',scenario='usage-empty')
add(G,'usage-flat-zero','个人用量 · 真实零值仍然显示',route='usage',scenario='usage-zero')
add(G,'detail-timeout-floating','详情 · 查询超时与固定悬浮条',route='detail',scenario='detail-timeout',steps=[{'simulate':'start-resume'}])
add(G,'detail-reauth-floating','详情 · 登录待恢复与固定悬浮条',route='detail',scenario='reauth',email='remote@example.com',steps=[{'simulate':'start-resume'}])
add(G,'detail-missing-floating','详情 · 快照缺失与固定悬浮条',route='detail',scenario='detail-missing',steps=[{'simulate':'start-resume'}])
add(G,'detail-unsupported-floating','详情 · 暂不支持查询与固定悬浮条',route='detail',scenario='detail-schema',steps=[{'simulate':'start-resume'}])
add(G,'detail-other-floating','详情 · 其他账号底部功能仍可到达',route='detail',email='backup@example.com',steps=[{'simulate':'start-resume'}])
add(G,'detail-editor-floating-dismissed','详情 · 关闭浮条后编辑位置不变',route='edit',steps=[{'fill':'#alias','value':'尚未保存的昵称'},{'simulate':'start-resume'},click('dismiss-status')])

# Exact expected final destination; checked for every screenshot, not inferred from its name.
from urllib.parse import parse_qs
for case in CASES:
    query=parse_qs(case['query']);scenario=query.get('scenario',[''])[0]
    expected=case['route']
    if case['id'] in {'first-run','first-waiting','first-account','first-saving','first-failed','first-launch-pending','first-launch-failed','first-launch-done','first-recheck','brand-onboarding'}:expected='onboarding'
    overrides={'detail-date-entry':'detail','detail-date-saved':'detail','resume-clear':'resume-clear','switch-error':'confirm','resume-message-saved':'settings','inline-resume':'resume'}
    expected={'automation':'settings','notifications':'settings','relay-accounts':'settings','hotkeys':'settings','archives':'settings','resume-message':'settings','edit':'detail'}.get(expected,expected)
    case['expected']=overrides.get(case['id'],expected)
    if scenario in {'first-saving','switching','refreshing','usage-refreshing','usage-loading','adding-opening','adding-saving','adding-cancelling','reauth-saving','reauth-cancelling'}:
        case['note']='此场景固定在处理中，供检查禁用态和进度；完整流程可从对应的初始页操作。'

NATIVE_SURFACES = [
 {'surface':'托盘菜单与气泡通知','source':'src/nx/desktop.py / src/nx/trayicon.py','verification':'由 Windows 原生绘制，须在本机验收；不以 HTML 模型冒充真实截图。'},
 {'surface':'ChatGPT 登录、继续按钮和系统权限窗口','source':'src/switch_account.ps1 / src/continue_in_desktop.ps1','verification':'外部应用/系统窗口，不由本项目渲染。演示仅模拟外部事件，不操作真实桌面。'},
 {'surface':'热键冲突、自启和 WebView2/DPI','source':'src/nx/desktop.py','verification':'HTML 状态已覆盖；原生结果需 Windows 实测。'},
]

if __name__=='__main__':
    import json
    print(json.dumps({'cases':CASES,'native':NATIVE_SURFACES},ensure_ascii=False,indent=2))
