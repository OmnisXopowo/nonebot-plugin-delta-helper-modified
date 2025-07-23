def trans_num_easy_for_read(num: int|str) -> str:
    if isinstance(num, str):
        num = int(num)
    if num < 1000:
        return str(num)
    elif num < 1000000:
        return f"{num/1000:.1f}K"
    else:
        return f"{num/1000000:.1f}M"

def get_qr_token(qrsig):
    """生成QR token，对应PHP中的getQrToken方法"""
    if not qrsig:
        return 0
    
    # 对应PHP的getQrToken算法
    length = len(qrsig)
    hash_val = 0
    for i in range(length):
        # 对应PHP: $hash += (($hash << 5) & 2147483647) + ord($qrSig[$i]) & 2147483647;
        hash_val += ((hash_val << 5) & 2147483647) + ord(qrsig[i]) & 2147483647
        # 对应PHP: $hash &= 2147483647;
        hash_val &= 2147483647
    
    # 对应PHP: return $hash & 2147483647;
    return hash_val & 2147483647

def get_map_name(map_id: str) -> str:
    map_dict = {
        '2231': "零号大坝-前夜",
        '2232': "零号大坝-永夜",
        '2201': "零号大坝-常规",
        '2202': "零号大坝-机密",
        '1901': "长弓溪谷-常规",
        '1902': "长弓溪谷-机密",
        '3901': "航天基地-机密",
        '3902': "航天基地-绝密",
        '8102': "巴克什-机密",
        '8103': "巴克什-绝密",
        '8803': "潮汐监狱-绝密",
    }
    return map_dict.get(map_id, "未知地图")

def timestamp_to_readable(timestamp: int) -> str:
    """将时间戳转换为易读的时间格式
    
    Args:
        timestamp: Unix时间戳（秒）
        
    Returns:
        格式化的时间字符串，如 "2025-01-21 14:30:00"
    """
    import datetime
    try:
        dt = datetime.datetime.fromtimestamp(timestamp)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return "未知时间"

def seconds_to_duration(seconds: int) -> str:
    """将秒数转换为易读的时长格式
    
    Args:
        seconds: 秒数
        
    Returns:
        格式化的时长字符串，如 "2小时30分钟"
    """
    if seconds <= 0:
        return "已完成"
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    
    if hours > 0:
        if minutes > 0:
            return f"{hours}小时{minutes}分钟"
        else:
            return f"{hours}小时"
    else:
        if minutes > 0:
            return f"{minutes}分钟"
        else:
            return f"{seconds}秒"