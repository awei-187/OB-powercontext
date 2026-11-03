"""真实错误处理。

PowerContext 客户端异常一律结构化透传，不吞掉、不伪造成功、不编造 request_id。
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from powercontext.client import (
    ClientError,
    ForbiddenResponseError,
    InvalidResponseError,
    ServerResponseError,
    TransportError,
    UnauthorizedResponseError,
    UnavailableResponseError,
)
from powercontext.errors import PowerContextError


class YanxuError(Exception):
    """研续自身的业务错误，消息为中文，直接展示给用户。"""

    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid_request",
        status: int = 400,
        details: dict[str, Any] | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.details = details or {}
        self.hint = hint


def _payload(
    code: str,
    status: int,
    message: str,
    *,
    server_code: str | None = None,
    request_id: str | None = None,
    details: dict[str, Any] | None = None,
    hint: str | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "status": status, "message": message}
    if server_code:
        error["server_code"] = server_code
    if request_id:
        error["request_id"] = request_id
    if details:
        error["details"] = details
    if hint:
        error["hint"] = hint
    return {"error": error}


_HINTS: dict[str, str] = {
    "text-too-long": "内容超过 PowerContext 单条记忆 8192 UTF-8 字节上限，请拆分或精简正文。",
    "revision_conflict": "记忆已被另一次修订推进，请刷新后基于最新版本重试。",
    "handoff_generation_unavailable": "该端点需要生成模型；研续不使用它，请改用「保存交接」的本人撰写流程。",
    "artifact_not_found": "该交接版本不存在，或不属于本项目（PowerContext 按 Scope 隔离交接工件）。",
}

_GATEWAY_STATUSES = frozenset({502, 503, 504})

_TRANSPORT_HINTS: dict[str, str] = {
    "ConnectTimeout": "连接内嵌 PowerContext Server 超时；若 Server 刚启动，请稍后重试。",
    "ReadTimeout": "PowerContext Server 已收到请求但未在超时内返回；该操作可能确实很慢或已卡住。",
    "WriteTimeout": "向 PowerContext Server 写入请求体超时。",
    "PoolTimeout": "httpx 连接池已满，通常是并发请求过多或有连接未释放。",
    "ConnectError": "TCP 连接被拒绝或不可达，通常意味着内嵌 Server 已退出。",
    "RemoteProtocolError": "连接在响应完成前被对端或中间层中断；本机若有网络拦截组件（TUN/代理），可能改写了回环连接。",
}


def describe_powercontext_error(exc: BaseException) -> tuple[int, dict[str, Any]]:
    """把 PowerContext 客户端异常翻译成 (HTTP 状态码, 响应体)。"""
    if isinstance(exc, ServerResponseError):
        server_code = exc.code or ""
        details = exc.details if isinstance(exc.details, dict) else {}
        detail_code = str(details.get("code", "")) if details else ""
        hint = _HINTS.get(detail_code) or _HINTS.get(server_code)
        if exc.server_message:
            message = exc.server_message
        else:
            message = f"PowerContext Server 返回 HTTP {exc.status_code}，且没有给出错误体。"
            if exc.status_code in _GATEWAY_STATUSES and hint is None:
                hint = (
                    "通常意味着内嵌 PowerContext Server 已停止或不可达；"
                    "本机若有网络拦截组件（TUN/代理），也可能在无监听端口上代答网关错误。"
                )
        return exc.status_code, _payload(
            "powercontext_server_response",
            exc.status_code,
            message,
            server_code=server_code or None,
            request_id=exc.request_id,
            details=details or None,
            hint=hint,
        )

    if isinstance(exc, TransportError):
        # SDK 用 `raise TransportError(path) from exc` 把真正的 httpx 失败链在 __cause__ 上；
        # 只显示 "无法连接" 会把超时、协议错误和拒绝连接混为一谈，因此把底层原因一并透传。
        cause = exc.__cause__
        details: dict[str, Any] = {"path": getattr(exc, "path", None)}
        if cause is not None:
            details["cause"] = f"{type(cause).__name__}: {cause}".strip()
        return 502, _payload(
            "powercontext_transport",
            502,
            f"无法连接 PowerContext Server（{exc}）。请确认内嵌 Server 仍在运行。",
            request_id=exc.request_id,
            details=details,
            hint=_TRANSPORT_HINTS.get(type(cause).__name__) if cause is not None else None,
        )

    if isinstance(exc, InvalidResponseError):
        return 502, _payload(
            "powercontext_invalid_response",
            502,
            f"PowerContext 响应不符合契约：{exc}",
            request_id=exc.request_id,
            details={"path": getattr(exc, "path", None)},
        )

    if isinstance(exc, (UnauthorizedResponseError, ForbiddenResponseError, UnavailableResponseError)):
        return getattr(exc, "status_code", 503), _payload(
            "powercontext_client",
            getattr(exc, "status_code", 503),
            str(exc),
            request_id=getattr(exc, "request_id", None),
        )

    if isinstance(exc, ClientError):
        return 500, _payload(
            "powercontext_client",
            500,
            f"PowerContext 客户端错误：{exc}",
            request_id=getattr(exc, "request_id", None),
        )

    return 500, _payload("internal_error", 500, f"未处理的服务端错误：{exc!r}")


async def yanxu_error_handler(_request: Request, exc: YanxuError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content=_payload(
            exc.code, exc.status, exc.message, details=exc.details or None, hint=exc.hint
        ),
    )


async def client_error_handler(_request: Request, exc: PowerContextError) -> JSONResponse:
    """PowerContext 异常（ClientError 及其 ServerResponseError / TransportError 等子类）。"""
    status, body = describe_powercontext_error(exc)
    return JSONResponse(status_code=status, content=body)


async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    status, body = describe_powercontext_error(exc)
    return JSONResponse(status_code=status, content=body)


async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """把 FastAPI 默认的 422 细节翻译成研续的错误信封。

    默认响应体是 {"detail": [...]}，前端 ApiError 读不到 message，
    用户只会看到一句「请求失败（HTTP 422）」——等于把真实原因藏起来。
    """
    parts: list[str] = []
    for item in exc.errors():
        location = ".".join(str(piece) for piece in item.get("loc", ()) if piece not in ("body", "query", "path"))
        message = str(item.get("msg", ""))
        parts.append(f"{location}：{message}" if location else message)
    return JSONResponse(
        status_code=422,
        content=_payload(
            "invalid_request",
            422,
            "请求参数不合法：" + "；".join(parts) if parts else "请求参数不合法。",
        ),
    )
