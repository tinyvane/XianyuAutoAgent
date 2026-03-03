import time
import os
import re
import sys
import random
from collections import deque

from curl_cffi import requests as curl_requests
from loguru import logger
from utils.xianyu_utils import generate_sign

# 请求节流配置
MIN_REQUEST_INTERVAL = float(os.getenv("MIN_REQUEST_INTERVAL", "2.0"))
MAX_REQUEST_INTERVAL = float(os.getenv("MAX_REQUEST_INTERVAL", "5.0"))


class XianyuApis:
    def __init__(self):
        self.url = 'https://h5api.m.goofish.com/h5/mtop.taobao.idlemessage.pc.login.token/1.0/'
        self.session = curl_requests.Session(impersonate="chrome133a")
        self.on_rgv587_callback = None  # 风控恢复回调
        self._request_timestamps = deque(maxlen=20)  # 滑动窗口请求记录
        self.session.headers.update({
            'accept': 'application/json',
            'accept-language': 'zh-CN,zh;q=0.9',
            'cache-control': 'no-cache',
            'origin': 'https://www.goofish.com',
            'pragma': 'no-cache',
            'priority': 'u=1, i',
            'referer': 'https://www.goofish.com/',
            'sec-ch-ua': '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
        })
        
    def clear_duplicate_cookies(self):
        """清理重复的cookies"""
        seen = {}
        for cookie in self.session.cookies.jar:
            seen[cookie.name] = cookie.value
        self.session.cookies.jar.clear()
        for name, value in seen.items():
            self.session.cookies.set(name, value, domain='.goofish.com')
        self.update_env_cookies()
        
    def update_env_cookies(self):
        """更新.env文件中的COOKIES_STR"""
        try:
            # 获取当前cookies的字符串形式
            # curl_cffi 的 Cookies 迭代时 yield 的是 cookie name (str)
            cookie_str = '; '.join([f"{name}={self.session.cookies.get(name)}" for name in self.session.cookies])
            
            # 读取.env文件
            env_path = os.path.join(os.getcwd(), '.env')
            if not os.path.exists(env_path):
                logger.warning(".env文件不存在，无法更新COOKIES_STR")
                return
                
            with open(env_path, 'r', encoding='utf-8') as f:
                env_content = f.read()
                
            # 使用正则表达式替换COOKIES_STR的值
            if 'COOKIES_STR=' in env_content:
                new_env_content = re.sub(
                    r'COOKIES_STR=.*', 
                    f'COOKIES_STR={cookie_str}',
                    env_content
                )
                
                # 写回.env文件
                with open(env_path, 'w', encoding='utf-8') as f:
                    f.write(new_env_content)
                    
                logger.debug("已更新.env文件中的COOKIES_STR")
            else:
                logger.warning(".env文件中未找到COOKIES_STR配置项")
        except Exception as e:
            logger.warning(f"更新.env文件失败: {str(e)}")
        
    def set_rgv587_handler(self, callback):
        """
        注册风控恢复回调。

        callback(self) -> Optional[str]: 返回新 cookie 字符串或 None
        """
        self.on_rgv587_callback = callback

    def _apply_new_cookies(self, cookie_str):
        """
        应用新的 Cookie 字符串到 session 并持久化到 .env。

        Args:
            cookie_str: 完整的 cookie 字符串（格式: "name1=value1; name2=value2"）

        Returns:
            bool: 是否成功
        """
        try:
            from http.cookies import SimpleCookie
            cookie = SimpleCookie()
            cookie.load(cookie_str)

            self.session.cookies.clear()
            for key, morsel in cookie.items():
                self.session.cookies.set(key, morsel.value, domain='.goofish.com')

            self.update_env_cookies()
            logger.success("Cookie 已更新并持久化")
            return True
        except Exception as e:
            logger.error(f"Cookie 解析/应用失败: {e}")
            return False

    def _throttle(self):
        """
        请求节流：添加随机延迟，控制请求频率。
        使用滑动窗口避免短时间内发送过多请求。
        """
        now = time.time()

        # 检查滑动窗口内的请求密度
        if self._request_timestamps:
            # 清除 60 秒前的记录
            while self._request_timestamps and (now - self._request_timestamps[0]) > 60:
                self._request_timestamps.popleft()

            # 如果最近 60 秒内请求过多，增加额外延迟
            if len(self._request_timestamps) > 10:
                extra_delay = random.uniform(3.0, 8.0)
                logger.debug(f"请求频率过高，额外延迟 {extra_delay:.1f}s")
                time.sleep(extra_delay)

        # 基础随机延迟
        delay = random.uniform(MIN_REQUEST_INTERVAL, MAX_REQUEST_INTERVAL)
        time.sleep(delay)

        self._request_timestamps.append(time.time())

    def hasLogin(self, retry_count=0):
        """调用hasLogin.do接口进行登录状态检查"""
        if retry_count >= 2:
            logger.error("Login检查失败，重试次数过多")
            return False
            
        try:
            self._throttle()
            url = 'https://passport.goofish.com/newlogin/hasLogin.do'
            params = {
                'appName': 'xianyu',
                'fromSite': '77'
            }
            data = {
                'hid': self.session.cookies.get('unb', ''),
                'ltl': 'true',
                'appName': 'xianyu',
                'appEntrance': 'web',
                '_csrf_token': self.session.cookies.get('XSRF-TOKEN', ''),
                'umidToken': '',
                'hsiz': self.session.cookies.get('cookie2', ''),
                'bizParams': 'taobaoBizLoginFrom=web',
                'mainPage': 'false',
                'isMobile': 'false',
                'lang': 'zh_CN',
                'returnUrl': '',
                'fromSite': '77',
                'isIframe': 'true',
                'documentReferer': 'https://www.goofish.com/',
                'defaultView': 'hasLogin',
                'umidTag': 'SERVER',
                'deviceId': self.session.cookies.get('cna', '')
            }
            
            response = self.session.post(url, params=params, data=data)
            res_json = response.json()
            
            if res_json.get('content', {}).get('success'):
                logger.debug("Login成功")
                # 清理和更新cookies
                self.clear_duplicate_cookies()
                return True
            else:
                logger.warning(f"Login失败: {res_json}")
                time.sleep(0.5)
                return self.hasLogin(retry_count + 1)
                
        except Exception as e:
            logger.error(f"Login请求异常: {str(e)}")
            time.sleep(0.5)
            return self.hasLogin(retry_count + 1)

    def get_token(self, device_id, retry_count=0):
        if retry_count >= 2:  # 最多重试3次
            logger.warning("获取token失败，尝试重新登陆")
            # 尝试通过hasLogin重新登录
            if self.hasLogin():
                logger.info("重新登录成功，重新尝试获取token")
                return self.get_token(device_id, 0)  # 重置重试次数
            else:
                logger.error("重新登录失败，Cookie已失效")
                logger.error("程序即将退出，请更新.env文件中的COOKIES_STR后重新启动")
                sys.exit(1)  # 直接退出程序

        self._throttle()

        params = {
            'jsv': '2.7.2',
            'appKey': '34839810',
            't': str(int(time.time()) * 1000),
            'sign': '',
            'v': '1.0',
            'type': 'originaljson',
            'accountSite': 'xianyu',
            'dataType': 'json',
            'timeout': '20000',
            'api': 'mtop.taobao.idlemessage.pc.login.token',
            'sessionOption': 'AutoLoginOnly',
            'spm_cnt': 'a21ybx.im.0.0',
        }
        data_val = '{"appKey":"444e9908a51d1cb236a27862abc769c9","deviceId":"' + device_id + '"}'
        data = {
            'data': data_val,
        }

        # 简单获取token，信任cookies已清理干净
        token = self.session.cookies.get('_m_h5_tk', '').split('_')[0]

        sign = generate_sign(params['t'], token, data_val)
        params['sign'] = sign

        try:
            response = self.session.post('https://h5api.m.goofish.com/h5/mtop.taobao.idlemessage.pc.login.token/1.0/', params=params, data=data)
            res_json = response.json()

            if isinstance(res_json, dict):
                ret_value = res_json.get('ret', [])
                # 检查ret是否包含成功信息
                if not any('SUCCESS::调用成功' in ret for ret in ret_value):
                    # 检测风控/限流错误
                    error_msg = str(ret_value)
                    if 'RGV587_ERROR' in error_msg or '被挤爆啦' in error_msg:
                        logger.error(f"触发风控: {ret_value}")

                        # 层级1: 尝试自动恢复回调（浏览器自动化）
                        if self.on_rgv587_callback:
                            logger.info("正在尝试自动恢复...")
                            try:
                                new_cookie_str = self.on_rgv587_callback(self)
                                if new_cookie_str and self._apply_new_cookies(new_cookie_str):
                                    logger.success("自动恢复成功，正在重试...")
                                    return self.get_token(device_id, 0)
                            except Exception as e:
                                logger.error(f"自动恢复回调出错: {e}")
                            logger.warning("自动恢复失败，回退到手动输入")

                        # 层级2: 手动输入兜底
                        logger.error("请进入闲鱼网页版-点击消息-过滑块-复制最新的Cookie")
                        print("\n" + "="*50)
                        new_cookie_str = input("请输入新的Cookie字符串 (复制浏览器中的完整cookie，直接回车则退出程序): ").strip()
                        print("="*50 + "\n")

                        if new_cookie_str:
                            if self._apply_new_cookies(new_cookie_str):
                                logger.success("Cookie已更新，正在尝试重连...")
                                return self.get_token(device_id, 0)
                            else:
                                logger.error("Cookie解析失败")
                                sys.exit(1)
                        else:
                            logger.info("用户取消输入，程序退出")
                            sys.exit(1)

                    logger.warning(f"Token API调用失败，错误信息: {ret_value}")
                    # 处理响应中的Set-Cookie
                    if 'Set-Cookie' in response.headers:
                        logger.debug("检测到Set-Cookie，更新cookie")
                        self.clear_duplicate_cookies()
                    time.sleep(0.5)
                    return self.get_token(device_id, retry_count + 1)
                else:
                    logger.info("Token获取成功")
                    return res_json
            else:
                logger.error(f"Token API返回格式异常: {res_json}")
                return self.get_token(device_id, retry_count + 1)

        except Exception as e:
            logger.error(f"Token API请求异常: {str(e)}")
            time.sleep(0.5)
            return self.get_token(device_id, retry_count + 1)

    def get_item_info(self, item_id, retry_count=0):
        """获取商品信息，自动处理token失效的情况"""
        if retry_count >= 3:  # 最多重试3次
            logger.error("获取商品信息失败，重试次数过多")
            return {"error": "获取商品信息失败，重试次数过多"}

        self._throttle()

        params = {
            'jsv': '2.7.2',
            'appKey': '34839810',
            't': str(int(time.time()) * 1000),
            'sign': '',
            'v': '1.0',
            'type': 'originaljson',
            'accountSite': 'xianyu',
            'dataType': 'json',
            'timeout': '20000',
            'api': 'mtop.taobao.idle.pc.detail',
            'sessionOption': 'AutoLoginOnly',
            'spm_cnt': 'a21ybx.im.0.0',
        }
        
        data_val = '{"itemId":"' + item_id + '"}'
        data = {
            'data': data_val,
        }
        
        # 简单获取token，信任cookies已清理干净
        token = self.session.cookies.get('_m_h5_tk', '').split('_')[0]
        
        sign = generate_sign(params['t'], token, data_val)
        params['sign'] = sign
        
        try:
            response = self.session.post(
                'https://h5api.m.goofish.com/h5/mtop.taobao.idle.pc.detail/1.0/', 
                params=params, 
                data=data
            )
            
            res_json = response.json()
            # 检查返回状态
            if isinstance(res_json, dict):
                ret_value = res_json.get('ret', [])
                # 检查ret是否包含成功信息
                if not any('SUCCESS::调用成功' in ret for ret in ret_value):
                    logger.warning(f"商品信息API调用失败，错误信息: {ret_value}")
                    # 处理响应中的Set-Cookie
                    if 'Set-Cookie' in response.headers:
                        logger.debug("检测到Set-Cookie，更新cookie")
                        self.clear_duplicate_cookies()
                    time.sleep(0.5)
                    return self.get_item_info(item_id, retry_count + 1)
                else:
                    logger.debug(f"商品信息获取成功: {item_id}")
                    return res_json
            else:
                logger.error(f"商品信息API返回格式异常: {res_json}")
                return self.get_item_info(item_id, retry_count + 1)
                
        except Exception as e:
            logger.error(f"商品信息API请求异常: {str(e)}")
            time.sleep(0.5)
            return self.get_item_info(item_id, retry_count + 1)
