"""Assemble actual UI screenshots; a local font is never included in the archive."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from build import APP_VERSION
ROOT=Path(__file__).resolve().parents[1]

def build(font_path):
    out=ROOT/'docs/review';out.mkdir(parents=True,exist_ok=True)
    font=lambda size:ImageFont.truetype(str(font_path),size)
    sheets={
      'overview':('同一套行与展开规则',[
        ('settings','设置 · 以详情行高为基准','light'),
        ('appearance-expanded','外观 · 圆端胶囊','dark'),
        ('root-relay','参与账号 · 会员紧随名称','light'),
        ('settings-exclusive-message-draft','互斥展开 · 保留未存输入','dark'),
        ('detail-inline-both','昵称与期限 · 独立保存','light'),
        ('settings-expanded-hover','通知展开 · 完整轮廓','dark')]),
      'surfaces':('固定额度列、无卡片用量和清晰异常',[
        ('home','首页 · 圆头像与固定额度列','light'),
        ('detail-timeout','查询超时 · 卡片不变高','light'),
        ('first-launch-pending','启动中 · 只有一个悬浮状态','dark'),
        ('usage-flat','全部用量 · 无卡片统计','light'),
        ('usage-account-flat','单账号用量 · 相同结构','dark'),
        ('detail-missing','快照缺失 · 可读反馈和操作','dark')]),
      'floating':('悬浮位置以面板为基准',[
        ('home-floating-status','首页 · 覆盖第三个账号','light'),
        ('detail-floating-status','详情 · 底边上方 12px','light'),
        ('settings-notify-floating','设置 · 相同底边位置','light'),
        ('home-floating-status','首页 · 深色浮条','dark'),
        ('detail-editor-floating','编辑 · 展开不推高浮条','dark'),
        ('settings-notify-floating','通知 · 深色固定浮条','dark')])}
    for name,(title,items) in sheets.items():
        canvas=Image.new('RGB',(1200,1232),'#eceef1');draw=ImageDraw.Draw(canvas)
        draw.text((20,15),f'ChatGPTnx {APP_VERSION} · {title}',font=font(25),fill='#252d3b')
        draw.text((20,51),'实际组件与合成数据 · 深浅色同尺寸 · 372 × 520',font=font(16),fill='#616d7d')
        for i,(key,label,theme) in enumerate(items):
            x=20+(i%3)*394;y=93+(i//3)*561
            draw.text((x,y),label,font=font(18),fill='#252d3b')
            image=Image.open(ROOT/f'docs/previews/{theme}/{key}.png').convert('RGB')
            if image.size!=(372,520):raise ValueError(f'Unexpected geometry: {key}')
            canvas.paste(image,(x,y+30))
        canvas.save(out/f'{name}.png')
    return out

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--font',required=True,type=Path)
    print(build(p.parse_args().font))
