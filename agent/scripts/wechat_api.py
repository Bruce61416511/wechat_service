# -*- coding: utf-8 -*-
import os, sys, argparse, requests, re
from pathlib import Path

def load_env():
    # .env 放在 agent/ 目录下（scripts/ 的上一级）
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
    env = {}
    if os.path.exists(p):
        for line in open(p, encoding='utf-8-sig').read().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()
    return env

def get_access_token(aid, sec):
    r = requests.get('https://api.weixin.qq.com/cgi-bin/token',
        params={'grant_type':'client_credential','appid':aid,'secret':sec}, timeout=10)
    d = r.json()
    if 'access_token' not in d: raise RuntimeError('token failed: '+str(d))
    return d['access_token']

def upload_thumb(tok, path):
    url = 'https://api.weixin.qq.com/cgi-bin/material/add_material?access_token='+tok+'&type=thumb'
    with open(path,'rb') as f:
        r = requests.post(url, files={'media':(os.path.basename(path),f,'image/png')}, timeout=30)
    d = r.json()
    if 'media_id' not in d: raise RuntimeError('thumb failed: '+str(d))
    print('  [wechat-api] cover:', d['media_id'])
    return d['media_id']

def upload_img(tok, path):
    url = 'https://api.weixin.qq.com/cgi-bin/media/uploadimg?access_token='+tok
    with open(path,'rb') as f:
        r = requests.post(url, files={'media':(os.path.basename(path),f,'image/jpeg')}, timeout=30)
    d = r.json()
    if 'url' not in d: raise RuntimeError('img failed: '+str(d))
    return d['url']

def fix_images(tok, html, hdir):
    pat = re.compile(r'<img[^>]+src=["\x27]([^"\x27]+)["\x27]', re.I)
    def rep(m):
        tag, src = m.group(0), m.group(1)
        if 'mmbiz' in src: return tag
        if not os.path.isabs(src): src = os.path.join(hdir, src)
        if os.path.exists(src):
            try:
                u = upload_img(tok, src)
                print('  [wechat-api] img:', os.path.basename(src))
                return tag.replace(m.group(1), u)
            except Exception as e:
                print('  [wechat-api] img err:', e)
        return tag
    return pat.sub(rep, html)

def add_draft(tok, title, content, thumb, summary='', author=''):
    import json
    url = 'https://api.weixin.qq.com/cgi-bin/draft/add?access_token='+tok
    art = {'title':title,'author':author,'digest':summary,'content':content,
           'thumb_media_id':thumb,'need_open_comment':0,'only_fans_can_comment':0}
    body = json.dumps({'articles':[art]}, ensure_ascii=False)
    r = requests.post(url, data=body.encode('utf-8'),
                      headers={'Content-Type':'application/json; charset=utf-8'}, timeout=15)
    d = r.json()
    if 'media_id' not in d: raise RuntimeError('draft failed: '+str(d))
    return d

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('html_file')
    ap.add_argument('--title', required=True)
    ap.add_argument('--summary', default='')
    ap.add_argument('--cover', required=True)
    ap.add_argument('--author', default='')
    a = ap.parse_args()
    env = load_env()
    aid, sec = env.get('WECHAT_APP_ID',''), env.get('WECHAT_APP_SECRET','')
    if not aid or not sec: print('ERROR: no credentials'); sys.exit(1)
    hp = os.path.abspath(a.html_file)
    if not os.path.exists(hp): print('ERROR: file not found:', hp); sys.exit(1)
    with open(hp,'r',encoding='utf-8') as f: html = f.read()
    hd = os.path.dirname(hp)
    print('  [wechat-api] publishing:', a.title)
    tok = get_access_token(aid, sec)
    print('  [wechat-api] token ok')
    thumb = upload_thumb(tok, a.cover)
    html = fix_images(tok, html, hd)
    res = add_draft(tok, a.title, html, thumb, a.summary, a.author)
    print('  [wechat-api] draft:', res['media_id'])
    print('OK')

if __name__ == '__main__':
    main()
