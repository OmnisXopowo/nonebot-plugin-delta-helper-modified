from nonebot.log import logger

import httpx
import time
import base64
import json
import urllib.parse
from .util import Util

CONSTANTS = {
    'SIG':'https://xui.ptlogin2.qq.com/ssl/ptqrshow',
    'GETLOGINTICKET':'https://xui.ptlogin2.qq.com/cgi-bin/xlogin',
    'GETLOGINSTATUS':'https://ssl.ptlogin2.qq.com/ptqrlogin',
    'GAMEBASEURL':'https://comm.ams.game.qq.com/ide/',

    ''


    'REQUEST_HEADERS_BASE': {
        "platform": "android",
        'Content-Type': 'application/x-www-form-urlencoded'
    }
}

class DeltaApi:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=200)

    async def close(self):
        await self.client.aclose()

    def get_gtk(self, p_skey: str) -> int:
        """计算g_tk值"""
        h = 5381
        for c in p_skey:
            h += (h << 5) + ord(c)
        return h & 0x7fffffff

    def get_micro_time(self) -> int:
        """获取微秒时间戳"""
        return int(time.time() * 1000000)

    def create_cookie(self, openid: str, access_token: str, is_qq: bool = True) -> dict:
        cookies = {
            'openid': openid,
            'access_token': access_token,
            'acctype': 'qc' if is_qq else 'wx',
            'appid': str(101491592),
        }
        return cookies

    async def get_login_token(self) -> bool:
        headers = CONSTANTS['REQUEST_HEADERS_BASE']
        url = CONSTANTS['GETLOGINTICKET']
        params = {
            'appid': 716027609,
            'daid': 383,
            'style': 33,
            'login_text': '登录',
            'hide_title_bar': 1,
            'hide_border': 1,
            'target': 'self',
            's_url': 'https://graph.qq.com/oauth2.0/login_jump',
            'pt_3rd_aid': 101944512,
            'pt_feedback_link': 'https://support.qq.com/products/77942?customInfo=milo.qq.com.appid101491592',
            'theme': 2,
            'verify_theme': ''
        }

        try:
            response = await self.client.get(url, headers=headers, params=params)
            if response.status_code == 200:
                return True
            else:
                return False
        except Exception as e:
            logger.error(f"获取登录token失败: {e}")
            return False

    async def get_sig(self):
        if not await self.get_login_token():
            return {'status': False, 'message': '获取登录token失败'}
        
        headers = CONSTANTS['REQUEST_HEADERS_BASE']
        params = {
            'appid': 716027609,
            'e': 2,
            'l': 'M',
            's': 3,
            'd': 72,
            'v': 4,
            't': 0.6142752744667854,
            'daid': 383,
            'pt_3rd_aid': 101491592,
            'u1': 'https://graph.qq.com/oauth2.0/login_jump'
        }
        url = CONSTANTS['SIG']

        try:
            response = await self.client.get(url, headers=headers, params=params)

            if response.status_code == 200:
                qrSig = response.cookies.get('qrsig', '')
                if not qrSig:
                    return {'status': False, 'message': '获取二维码失败，请重试'}
                loginSig = response.cookies.get('pt_login_sig', '')
                iamgebase64 = base64.b64encode(response.content).decode('utf-8')
                qrToken = Util.get_qr_token(qrSig)

                data = {
                    'qrSig': qrSig,
                    'image': iamgebase64,
                    'token': qrToken,
                    'loginSig': loginSig,
                    'cookie': dict(response.cookies)
                }

                return {'status': True, 'message': data}
            else:
                logger.error(f"获取二维码失败")
                return {'status': False, 'message': "获取二维码失败"}
        except Exception as e:
            logger.exception(f"获取二维码失败: {e}")
            return {'status': False, 'message': '获取二维码失败，详情请查看日志'}

    async def get_login_status(self, cookie: str, qrSig: str, qrToken: str, loginSig: str):
        headers = CONSTANTS['REQUEST_HEADERS_BASE']
        url = CONSTANTS['GETLOGINSTATUS']
        
        try:
            # 解析cookie参数
            if not cookie:
                return {'code': -1, 'message': '缺少cookie参数', 'data': {}}
            
            cookies = json.loads(cookie)
            # 确保所有cookie值都是字符串类型
            for key in cookies:
                cookies[key] = str(cookies[key])
            cookies['qrsig'] = qrSig
            
            # 构建请求参数
            params = {
                'u1': 'https://graph.qq.com/oauth2.0/login_jump',
                'ptqrtoken': qrToken,
                'ptredirect': 0,
                'h': 1,
                't': 1,
                'g': 1,
                'from_ui': 1,
                'ptlang': 2052,
                'action': '0-0-1744807890273',
                'js_ver': 25040111,
                'js_type': 1,
                'login_sig': loginSig,
                'pt_uistyle': 40,
                'aid': 716027609,
                'daid': 383,
                'pt_3rd_aid': 101491592,
                'o1vId': '378b06c889d9113b39e814ca627809e3',
                'pt_js_version': '530c3f68',
            }
            
            # 发送请求，确保cookie格式正确
            # 将cookies转换为httpx兼容的格式
            httpx_cookies = {}
            for name, value in cookies.items():
                if value != '':
                    httpx_cookies[name] = str(value)
            
            response = await self.client.get(url, params=params, cookies=httpx_cookies, headers=headers)
            
            if response.status_code != 200:
                return {'code': -5, 'message': '响应错误', 'data': {}}
            
            result = response.text
            
            # 检查响应内容
            if result == '':
                return {'code': -1, 'message': 'qrSig参数不正确', 'data': {}}
            
            # 使用正则表达式解析ptuiCB响应
            import re
            pattern = r"ptuiCB\s*\(\s*'(.*?)'\s*,\s*'(.*?)'\s*,\s*'(.*?)'\s*,\s*'(.*?)'\s*,\s*'(.*?)'\s*,\s*'(.*?)'\s*\)"
            matches = re.search(pattern, result)
            
            if not matches:
                return {'code': -4, 'message': '响应格式错误', 'data': {}}
            
            code = matches.group(1)
            message = matches.group(5)
            
            # 处理不同的响应码
            if code == '65':
                return {'code': -2, 'message': message, 'data': {}}
            elif code == '66':
                return {'code': 1, 'message': message, 'data': {}}
            elif code == '67':
                return {'code': 2, 'message': message, 'data': {}}
            elif code == '86':
                return {'code': -3, 'message': message, 'data': {}}
            elif code != '0':
                return {'code': -4, 'message': message, 'data': {}}
            
            # 登录成功，解析QQ号
            q_url = matches.group(3)
            qq_match = re.search(r'uin=(.*?)&', q_url)
            if not qq_match:
                return {'code': -4, 'message': '无法解析QQ号', 'data': {}}
            
            qq = qq_match.group(1)
            
            # 访问重定向URL获取完整cookie
            redirect_response = await self.client.get(q_url, cookies=httpx_cookies, headers=headers)
            
            # 合并所有cookie，保持与PHP版本一致
            all_cookies = {}
            
            # 首先添加原始cookies
            for cookie_name, cookie_value in cookies.items():
                if cookie_value != '':
                    all_cookies[cookie_name] = str(cookie_value)
            
            # 然后添加重定向响应中的新cookies
            for cookie_name, cookie_value in redirect_response.cookies.items():
                if cookie_value != '':
                    all_cookies[cookie_name] = str(cookie_value)
            
            # 确保所有cookie值都是字符串类型
            for key in all_cookies:
                all_cookies[key] = str(all_cookies[key])
            
            return {
                'code': 0, 
                'message': '登录成功', 
                'data': {'cookie': all_cookies}
            }
            
        except json.JSONDecodeError:
            return {'code': -1, 'message': 'cookie格式错误', 'data': {}}
        except Exception as e:
            logger.exception(f"获取登录状态失败: {e}")
            return {'code': -4, 'message': '获取登录状态失败，详情请查看日志', 'data': {}}

    async def get_access_token(self, cookie: str):
        try:
            if '\\' in cookie:  # 判断cookie字符串中有转义字符
                cookie = cookie.replace('\\', '')  # 去除转义字符
            
            cookies = json.loads(cookie)
            
            # 第一步：发送授权请求
            headers = {
                'referer': 'https://xui.ptlogin2.qq.com/',
            }
            
            form_data = {
                'response_type': 'code',
                'client_id': '101491592',
                'redirect_uri': 'https://milo.qq.com/comm-htdocs/login/qc_redirect.html?parent_domain=https://df.qq.com&isMiloSDK=1&isPc=1',
                'scope': '',
                'state': 'STATE',
                'switch': '',
                'form_plogin': 1,
                'src': 1,
                'update_auth': 1,
                'openapi': 1010,
                'g_tk': self.get_gtk(cookies.get('p_skey', '')),
                'auth_time': int(time.time()),
                'ui': '979D48F3-6CE2-4E95-A789-3BD3187648B6',
            }
            
            url = 'https://graph.qq.com/oauth2.0/authorize'
            response = await self.client.post(url, data=form_data, headers=headers, cookies=cookies)
            
            # 从Location头中提取code
            import re
            location = response.headers.get('Location', '')
            code_match = re.search(r'code=(.*?)&', location)
            if not code_match:
                return {'status': False, 'message': 'Cookie过期，请重新扫码登录', 'data': {}}
            
            qc_code = code_match.group(1)
            
            # 访问重定向URL
            await self.client.get(location, cookies=cookies, headers=headers)
            
            # 第二步：获取openid和access_token
            headers = {
                'referer': 'https://df.qq.com/',
            }
            
            params = {
                'a': 'qcCodeToOpenId',
                'qc_code': qc_code,
                'appid': 101491592,
                'redirect_uri': 'https://milo.qq.com/comm-htdocs/login/qc_redirect.html',
                'callback': 'miloJsonpCb_86690',
                '_': self.get_micro_time(),
            }
            
            url = 'https://ams.game.qq.com/ams/userLoginSvr'
            response = await self.client.get(url, params=params, cookies=cookies, headers=headers)
            
            result = response.text
            # logger.debug(f"AccessToken获取结果: {result}")
            
            # 解析JSONP响应
            # 匹配 try{miloJsonpCb_86690({...});}catch(e){} 格式
            jsonp_match = re.search(r'try\{miloJsonpCb_86690\((\{.*?\})\);\}catch\(e\)\{\}', result)
            if not jsonp_match:
                # 尝试匹配不带try-catch的格式
                jsonp_match = re.search(r'miloJsonpCb_86690\((\{.*?\})\)', result)
                if not jsonp_match:
                    logger.error(f"无法解析JSONP响应: {result}")
                    return {'status': False, 'message': 'AccessToken获取失败', 'data': {}}
            
            json_data = json.loads(jsonp_match.group(1))
            # logger.debug(f"解析的JSON数据: {json_data}")
            
            if json_data['iRet'] != '0' and json_data['iRet'] != 0:
                logger.error(f"AccessToken获取失败，iRet: {json_data['iRet']}")
                return {'status': False, 'message': 'AccessToken获取失败', 'data': {}}
            
            return {
                'status': True, 
                'message': '获取成功', 
                'data': {
                    'access_token': json_data['access_token'],
                    'expires_in': json_data['expires_in'],
                    'openid': json_data['openid'],
                }
            }
            
        except json.JSONDecodeError:
            return {'status': False, 'message': 'cookie格式错误', 'data': {}}
        except Exception as e:
            logger.exception(f"获取access token失败: {e}")
            return {'status': False, 'message': 'AccessToken获取失败', 'data': {}}

    async def bind(self, access_token: str, openid: str, access_type: str = 'qc'):
        try:
            # 参数验证
            if not openid or not access_token:
                return {'status': False, 'message': '缺少参数', 'data': {}}
            
            # 创建cookie
            is_qq = access_type == 'qc'
            cookies = self.create_cookie(openid, access_token, is_qq)
            
            # 第一步：检查是否已绑定
            form_data = {
                'iChartId': 316964,
                'iSubChartId': 316964,
                'sIdeToken': '95ookO',
            }
            
            url = 'https://comm.ams.game.qq.com/ide/'
            response = await self.client.post(url, data=form_data, cookies=cookies)
            
            data = response.json()
            if data['ret'] != 0:
                return {'status': False, 'message': '获取失败,检查鉴权是否过期', 'data': {}}
            
            # 检查是否已绑定
            if not data['jData']['bindarea']:  # 未绑定游戏角色
                # 获取角色信息
                params = {
                    'needGopenid': 1,
                    'sAMSAcctype': 'qq' if access_type == 'qc' else 'wx',
                    'sAMSAccessToken': access_token,
                    'sAMSAppOpenId': openid,
                    'sAMSSourceAppId': '101491592',
                    'game': 'dfm',
                    'sCloudApiName': 'ams.gameattr.role',
                    'area': 36,
                    'platid': 1,
                    'partition': 36
                }
                
                headers = {
                    'referer': 'https://df.qq.com/',
                }
                
                url = 'https://comm.aci.game.qq.com/main'
                response = await self.client.get(url, params=params, headers=headers)
                result = response.text
                # logger.debug(f"获取角色信息结果: {result}")
                
                # 解析响应数据
                import re
                pattern = r"\{([^}]*)\}"
                matches = re.search(pattern, result)
                if not matches:
                    return {'status': False, 'message': '获取角色信息失败', 'data': {}}
                
                # 解析键值对
                pairs_pattern = r"(\w+):('[^']*'|-?\d+|[^,]*)"
                pairs = re.findall(pairs_pattern, matches.group(1))
                
                data = {}
                for key, value in pairs:
                    value = value.strip("'")  # 去除单引号
                    if key == 'msg':
                        # 处理GBK编码的消息
                        try:
                            data[key] = value.encode('latin1').decode('gbk')
                        except:
                            data[key] = value
                    else:
                        data[key] = value
                
                # 提取角色ID
                checkparam_parts = data['checkparam'].split('|')
                if len(checkparam_parts) < 3:
                    return {'status': False, 'message': '角色信息解析失败', 'data': {}}
                
                role_id = checkparam_parts[2]
                
                # 提交绑定
                form_data = {
                    'iChartId': 316965,
                    'iSubChartId': 316965,
                    'sIdeToken': 'sTzZS2',
                    'sArea': 36,
                    'sPlatId': 1,
                    'sPartition': 36,
                    'sCheckparam': data['checkparam'],
                    'sRoleId': role_id,
                    'md5str': data['md5str'],
                }
                
                url = 'https://comm.ams.game.qq.com/ide/'
                response = await self.client.post(url, data=form_data, cookies=cookies)
                result = response.json()
                
                if result['ret'] != 0:
                    return {'status': False, 'message': '绑定失败', 'data': {}}
                else:
                    return {'status': True, 'message': '获取成功', 'data': result['jData']['bindarea']}
            
            # 已绑定，直接返回
            return {'status': True, 'message': '获取成功', 'data': data['jData']['bindarea']}
            
        except Exception as e:
            logger.exception(f"绑定失败: {e}")
            return {'status': False, 'message': '绑定失败，详情请查看日志', 'data': {}}

    async def get_player_info(self, access_token: str, openid: str, season_id: int = 0, access_type: str = 'qc'):
        try:
            # 参数验证
            if not openid or not access_token:
                return {'status': False, 'message': '缺少参数', 'data': {}}
            
            # 创建cookie
            is_qq = access_type == 'qc'
            cookies = self.create_cookie(openid, access_token, is_qq)
            headers = CONSTANTS['REQUEST_HEADERS_BASE']
            
            # 初始化游戏数据
            game_data = {
                'player': [],
                'game': [],
                'coin': 0,
                'tickets': 0,
                'money': 0,
            }
            
            # 第一步：获取玩家基础信息
            form_params = {
                'iChartId': '317814',
                'iSubChartId': '317814',
                'sIdeToken': 'QIRBwm',
                'seasonid': str(season_id),
            }
            
            url = CONSTANTS['GAMEBASEURL']
            response = await self.client.post(url, params=form_params, cookies=cookies, headers=headers)
            
            data = response.json()
            # logger.debug(f"玩家基础信息：{data}")
            if data['ret'] == 0:
                # 处理玩家数据
                player_data = data['jData']['userData'].copy()
                player_data['charac_name'] = urllib.parse.unquote(player_data['charac_name'])
                game_data['player'] = player_data
                game_data['game'] = data['jData']['careerData']
            
            # 第二步：获取货币信息
            currency_items = {
                'coin': 17888808888,
                'tickets': 17888808889,
                'money': 17020000010,
            }
            
            for key, item_id in currency_items.items():
                form_data = {
                    'iChartId': 319386,
                    'iSubChartId': 319386,
                    'sIdeToken': 'zMemOt',
                    'type': 3,
                    'item': item_id,
                }
                
                response = await self.client.post(url, data=form_data, cookies=cookies)
                data = response.json()
                
                if data['ret'] == 0:
                    game_data[key] = int(data['jData']['data'][0].get('totalMoney', 0))
            
            return {'status': True, 'message': '获取成功', 'data': game_data}
            
        except Exception as e:
            logger.exception(f"获取玩家信息失败: {e}")
            return {'status': False, 'message': '获取玩家信息失败，详情请查看日志', 'data': {}}


    async def get_password(self, access_token: str, openid: str, access_type: str = 'qc'):
        try:
            # 参数验证
            if not openid or not access_token:
                return {'status': False, 'message': '缺少参数', 'data': {}}
            
            # 创建cookie
            is_qq = access_type == 'qc'
            cookies = self.create_cookie(openid, access_token, is_qq)
            
            # 发送请求获取密码信息
            form_data = {
                'iChartId': 316969,
                'iSubChartId': 316969,
                'sIdeToken': 'NoOapI',
                'method': 'dfm/center.day.secret',
                'source': 2
            }
            
            url = CONSTANTS['GAMEBASEURL']
            response = await self.client.post(url, data=form_data, cookies=cookies)
            
            data = response.json()
            if data['ret'] != 0:
                return {'status': False, 'message': '获取失败,检查鉴权是否过期', 'data': {}}
            
            return {'status': True, 'message': '获取成功', 'data': data['jData']['data']['data']}
            
        except Exception as e:
            logger.exception(f"获取密码失败: {e}")
            return {'status': False, 'message': '获取密码失败，详情请查看日志', 'data': {}}

    async def get_record(self, access_token: str, openid: str, access_type: str = 'qc'):
        """
        获取战绩记录
        :param openid: openid
        :param access_token: access_token
        :param access_type: 登录类型，默认为'qc'
        :return: 战绩记录
        """
        try:
            # 参数验证
            if not openid or not access_token:
                return {'status': False, 'message': '缺少参数', 'data': {}}
            
            # 创建cookie
            is_qq = access_type == 'qc'
            cookies = self.create_cookie(openid, access_token, is_qq)
            
            # 初始化游戏数据
            game_data = {
                'gun': [],
                'operator': [],
            }
            
            # 定义类型映射
            types = {4: 'gun', 5: 'operator'}
            
            # 遍历每种类型
            for type_id, key in types.items():
                # 遍历5页数据（长时间未游戏可能需要翻页获取）
                for page in range(1, 6):
                    form_data = {
                        'iChartId': 319386,
                        'iSubChartId': 319386,
                        'sIdeToken': 'zMemOt',
                        'type': type_id,
                        'page': page,
                    }
                    
                    url = CONSTANTS['GAMEBASEURL']
                    response = await self.client.post(url, data=form_data, cookies=cookies)
                    
                    data = response.json()
                    if data['ret'] == 0 and data['jData']['data']:
                        # 合并数据
                        game_data[key].extend(data['jData']['data'])
                    elif data['ret'] != 0:
                        logger.error(f"获取战绩失败: {data}")
                        return {'status': False, 'message': '获取失败', 'data': {}}
            
            return {'status': True, 'message': '获取成功', 'data': game_data}
            
        except Exception as e:
            logger.exception(f"获取战绩失败: {e}")
            return {'status': False, 'message': '获取战绩失败，详情请查看日志', 'data': {}}

    async def get_safehousedevice_status(self, access_token: str, openid: str, access_type: str = 'qc'):
        try:
            # 参数验证
            if not openid or not access_token:
                return {'status': False, 'message': '缺少参数', 'data': {}}
            
            # 创建cookie
            is_qq = access_type == 'qc'
            cookies = self.create_cookie(openid, access_token, is_qq)

            # 发送请求获取设备状态
            params = {
                'iChartId': 365589,
                'iSubChartId': 365589,
                'sIdeToken': 'bQaMCQ',
                'source': 2
            }

            url = CONSTANTS['GAMEBASEURL']
            response = await self.client.post(url, params=params, cookies=cookies)

            data = response.json()
            if data['ret'] == 0:
                return {'status': True, 'message': '获取成功', 'data': data['jData']['data']['data']}
            else:
                logger.error(f"获取特勤处状态失败: {data}")
                return {'status': False, 'message': '获取失败，可能需要重新登录', 'data': {}}
        except Exception as e:
            logger.exception(f"获取特勤处状态失败: {e}")
            return {'status': False, 'message': '获取特勤处状态失败，详情请查看日志', 'data': {}}

    async def get_object_info(self, access_token: str, openid: str, access_type: str = 'qc', object_id: str = ''):
        try:
            # 参数验证
            if not openid or not access_token or not object_id:
                return {'status': False, 'message': '缺少参数', 'data': {}}
            
            # 创建cookie
            is_qq = access_type == 'qc'
            cookies = self.create_cookie(openid, access_token, is_qq)

            # 发送请求获取物品信息
            params = {
                'iChartId': 316969,
                'iSubChartId': 316969,
                'sIdeToken': 'NoOapI',
                'method': 'dfm/object.list',
                'source': 2,
                'param': json.dumps({
                    'primary': 'props',
                    'objectID': object_id,
                }),
            }

            url = CONSTANTS['GAMEBASEURL']
            response = await self.client.post(url, params=params, cookies=cookies)

            data = response.json()
            if data['ret'] == 0:
                return {'status': True, 'message': '获取成功', 'data': data['jData']['data']['data']}
            else:
                logger.error(f"获取物品信息失败: {data}")
                return {'status': False, 'message': '获取失败', 'data': {}}
        except Exception as e:
            logger.exception(f"获取物品信息失败: {e}")
            return {'status': False, 'message': '获取物品信息失败，详情请查看日志', 'data': {}}

    async def get_daily_report(self, access_token: str, openid: str, access_type: str = 'qc'):
        try:
            # 参数验证
            if not openid or not access_token:
                return {'status': False, 'message': '缺少参数', 'data': {}}
            
            # 创建cookie
            is_qq = access_type == 'qc'
            cookies = self.create_cookie(openid, access_token, is_qq)

            # 发送请求获取每日报告
            params = {
                'iChartId': 316969,
                'iSubChartId': 316969,
                'sIdeToken': 'NoOapI',
                'method': 'dfm/center.recent.detail',
                'source': 2,
                'param': json.dumps({
                    'resourceType': 'sol',
                }),
            }

            url = CONSTANTS['GAMEBASEURL']

            response = await self.client.post(url, params=params, cookies=cookies)

            data = response.json()
            if data['ret'] == 0:
                return {'status': True, 'message': '获取成功', 'data': data['jData']['data']['data']}
            else:
                logger.error(f"获取每日报告失败: {data}")
                return {'status': False, 'message': '获取失败，可能需要重新登录', 'data': {}}
        except Exception as e:
            logger.exception(f"获取每日报告失败: {e}")
            return {'status': False, 'message': '获取每日报告失败，详情请查看日志', 'data': {}}

    async def get_weekly_report(self, access_token: str, openid: str, access_type: str = 'qc', statDate: str = ''):
        try:
            # 参数验证
            if not openid or not access_token or not statDate:
                return {'status': False, 'message': '缺少参数', 'data': {}}
            
            # 创建cookie
            is_qq = access_type == 'qc'
            cookies = self.create_cookie(openid, access_token, is_qq)
            
            # 发送请求获取每周报告
            params = {
                'iChartId': 316968,
                'iSubChartId': 316968,
                'sIdeToken': 'KfXJwH',
                'method': 'dfm/weekly.sol.record',
                'source': 5,
                'sArea': 36,
                'param': json.dumps({
                    "source":"5",
                    "method":"dfm/weekly.sol.record",
                    "statDate":statDate
                }),
            }

            url = CONSTANTS['GAMEBASEURL']
            response = await self.client.post(url, params=params, cookies=cookies)

            data = response.json()
            if data['ret'] == 0:
                return {'status': True, 'message': '获取成功', 'data': data['jData']['data']['data']}
            else:
                logger.error(f"获取每周报告失败: {data}")
                return {'status': False, 'message': '获取失败，可能需要重新登录', 'data': {}}
        except Exception as e:
            logger.exception(f"获取每周报告失败: {e}")
            return {'status': False, 'message': '获取每周报告失败，详情请查看日志', 'data': {}}

    async def get_weekly_friend_report(self, access_token: str, openid: str, access_type: str = 'qc', statDate: str = ''):
        try:
            # 参数验证
            if not openid or not access_token or not statDate:
                return {'status': False, 'message': '缺少参数', 'data': {}}
            
            # 创建cookie
            is_qq = access_type == 'qc'
            cookies = self.create_cookie(openid, access_token, is_qq)

            # 发送请求获取每周好友报告
            params = {
                'iChartId': 316968,
                'iSubChartId': 316968,
                'sIdeToken': 'KfXJwH',
                'method': 'dfm/weekly.sol.friend.record',
                'source': 5,
                'sArea': 36,
                'param': json.dumps({
                    "source":"5",
                    "method":"dfm/weekly.sol.friend.record",
                    "statDate":statDate
                }),
            }

            url = CONSTANTS['GAMEBASEURL']
            response = await self.client.post(url, params=params, cookies=cookies)

            data = response.json()
            if data['ret'] == 0:
                return {'status': True, 'message': '获取成功', 'data': data['jData']['data']['data']}
            else:
                logger.error(f"获取每周好友报告失败: {data}")
                return {'status': False, 'message': '获取失败，可能需要重新登录', 'data': {}}
        except Exception as e:
            logger.exception(f"获取每周好友报告失败: {e}")
            return {'status': False, 'message': '获取每周好友报告失败，详情请查看日志', 'data': {}}

    async def get_user_info(self, access_token: str, openid: str, access_type: str = 'qc', user_openid: str = ''):
        try:
            # 参数验证
            if not openid or not access_token or not user_openid:
                return {'status': False, 'message': '缺少参数', 'data': {}}
            
            # 创建cookie
            is_qq = access_type == 'qc'
            cookies = self.create_cookie(openid, access_token, is_qq)

            # 发送请求获取用户信息
            params = {
                'iChartId': 369172,
                'iSubChartId': 369172,
                'sIdeToken': 'FDNRsR',
                'method': 'dfm/center.user.info',
                'source': 5,
                'sArea': 36,
                'openid': user_openid
            }

            url = CONSTANTS['GAMEBASEURL']
            response = await self.client.post(url, params=params, cookies=cookies)

            data = response.json()
            if data['ret'] == 0:
                return {'status': True, 'message': '获取成功', 'data': data['jData']['data']}
            else:
                logger.error(f"获取用户信息失败: {data}")
                return {'status': False, 'message': '获取失败，可能需要重新登录', 'data': {}}
        except Exception as e:
            logger.exception(f"获取用户信息失败: {e}")
            return {'status': False, 'message': '获取用户信息失败，详情请查看日志', 'data': {}}

    async def get_person_center_info(self, access_token: str, openid: str, access_type: str = 'qc'):
        try:
            # 参数验证
            if not openid or not access_token:
                return {'status': False, 'message': '缺少参数', 'data': {}}
            
            # 创建cookie
            is_qq = access_type == 'qc'
            cookies = self.create_cookie(openid, access_token, is_qq)

            # 发送请求获取用户信息
            params = {
                'iChartId': 316969,
                'iSubChartId': 316969,
                'sIdeToken': 'NoOapI',
                'method': 'dfm/center.person.resource',
                'source': 2,
                'param': json.dumps({
                    "resourceType": "sol",
                    "seasonid": [1, 2, 3, 4, 5],
                    "isAllSeason": True
                    })
            }

            url = CONSTANTS['GAMEBASEURL']
            response = await self.client.post(url, params=params, cookies=cookies)

            data = response.json()
            if data['ret'] == 0:
                return {'status': True, 'message': '获取成功', 'data': data['jData']['data']['data']['solDetail']}
            else:
                logger.error(f"获取用户中心信息失败: {data}")
                return {'status': False, 'message': '获取失败，可能需要重新登录', 'data': {}}
        except Exception as e:
            logger.exception(f"获取用户中心信息失败: {e}")
            return {'status': False, 'message': '获取用户信息失败，详情请查看日志', 'data': {}}