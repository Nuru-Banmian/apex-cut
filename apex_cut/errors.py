"""API 错误处理 — 关键错误检测与传播.

当 LLM API 返回认证失败、资源不存在、频率限制等关键错误时，
不应静默回退，而应立即停止工作流并将错误展示给用户。
"""

from __future__ import annotations


class CriticalAPIError(Exception):
    """关键 API 错误 — 应终止工作流并告知用户."""

    def __init__(self, message: str, agent: str = "", status_code: str = ""):
        self.agent = agent
        self.status_code = status_code
        full_msg = f"[{agent}] {message}" if agent else message
        super().__init__(full_msg)


def is_critical_api_error(error: Exception) -> tuple[bool, str, str]:
    """检测是否为关键 API 错误，返回 (is_critical, status_code, hint).

    关键错误类型:
      - 401 Unauthorized: API Key 无效
      - 403 Forbidden: 无权限 / 账户欠费
      - 404 Not Found: 模型不存在或 Base URL 错误
      - 429 Rate Limit: 请求频率超限
      - Connection refused / timeout: 网络不通

    非关键错误（可回退）:
      - JSON 解析失败
      - LLM 返回格式异常（但请求成功）
      - 工具调用失败（ffmpeg, whisper 等本地工具）
    """
    msg = str(error).lower()
    # 也检查原始异常链中的错误
    cause = getattr(error, '__cause__', None)
    if cause:
        msg += ' ' + str(cause).lower()

    # 401
    if '401' in msg or 'unauthorized' in msg or 'invalid api key' in msg or 'incorrect api key' in msg:
        return True, '401', 'API Key 无效，请检查是否填写正确或已过期'
    # 403
    if '403' in msg or 'forbidden' in msg or 'permission' in msg or 'access denied' in msg:
        return True, '403', 'API 访问被拒绝，请检查账户余额或权限'
    # 404
    if '404' in msg or 'not found' in msg or 'model not found' in msg:
        return True, '404', '模型或接口不存在，请检查 Base URL 和模型名称是否正确'
    # 429
    if '429' in msg or 'rate limit' in msg or 'too many requests' in msg:
        return True, '429', '请求频率超限，请稍后重试或降低并发'
    # Connection
    if 'connection refused' in msg or 'connection error' in msg or 'name or service not known' in msg:
        return True, 'CONN', '无法连接到 API 服务器，请检查网络或 Base URL'
    if 'timeout' in msg or 'timed out' in msg:
        return True, 'TIMEOUT', 'API 请求超时，请检查网络连接'

    return False, '', ''


def check_and_raise(error: Exception, agent_name: str):
    """检查异常是否为关键 API 错误，如果是则抛出 CriticalAPIError."""
    is_critical, status_code, hint = is_critical_api_error(error)
    if is_critical:
        raise CriticalAPIError(
            f"{hint} (原始错误: {str(error)[:200]})",
            agent=agent_name,
            status_code=status_code,
        ) from error
