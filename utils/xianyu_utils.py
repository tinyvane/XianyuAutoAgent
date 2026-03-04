import json
import subprocess
from functools import partial
subprocess.Popen = partial(subprocess.Popen, encoding="utf-8")
import execjs

try:
    xianyu_js = execjs.compile(open(r'../static/xianyu_js_version_2.js', 'r', encoding='utf-8').read())
except:
    xianyu_js = execjs.compile(open(r'static/xianyu_js_version_2.js', 'r', encoding='utf-8').read())

def trans_cookies(cookies_str):
    cookies = dict()
    for i in cookies_str.split("; "):
        try:
            cookies[i.split('=')[0]] = '='.join(i.split('=')[1:])
        except:
            continue
    return cookies


def generate_mid():
    mid = xianyu_js.call('generate_mid')
    return mid

def generate_uuid():
    uuid = xianyu_js.call('generate_uuid')
    return uuid

def generate_device_id(user_id):
    device_id = xianyu_js.call('generate_device_id', user_id)
    return device_id

def generate_sign(t, token, data):
    sign = xianyu_js.call('generate_sign', t, token, data)
    return sign

def decrypt(data):
    res = xianyu_js.call('decrypt', data)
    return res


def mid2url(media_id: str) -> str:
    """将闲鱼图片 mediaId 转换为可访问的图片 URL"""
    if not media_id:
        return ""
    # 尝试通过 JS bridge 调用 mid2Url
    try:
        url = xianyu_js.call('mid2Url', media_id)
        if url:
            return url
    except Exception:
        pass
    # 降级：拼接 CDN URL
    return f"https://impaas-static.dingtalk.com/media/{media_id}"
