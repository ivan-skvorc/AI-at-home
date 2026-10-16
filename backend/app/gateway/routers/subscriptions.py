"""Administrator-only browser setup for shared subscription model access."""

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.gateway.deps import get_current_user_from_request, require_admin_user
from app.gateway.persistent_writes import run_drained_write
from deerflow.models import subscriptions as service


class SubscriptionRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                # FastAPI's default errors echo invalid input, including secrets.
                raise HTTPException(422, "Invalid subscription request") from None

        return guarded


router = APIRouter(prefix="/api/subscriptions", tags=["models"], route_class=SubscriptionRoute)
Provider = Literal["chatgpt", "grok", "kimi"]
_ADMIN = "Admin privileges are required to manage shared subscription connections."


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr | None = None
    connection: dict | None = None


class PollRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flow_id: str = Field(min_length=1, max_length=100)


def _call(func, *args):
    try:
        return func(*args)
    except service.SubscriptionError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except Exception:
        # Provider and validation exceptions can contain credentials. Never
        # include their text in HTTP responses or drained-write diagnostics.
        raise HTTPException(502, "Subscription connection failed; check access and try again") from None


async def _owner(request: Request) -> str:
    user = getattr(request.state, "user", None) or await get_current_user_from_request(request)
    return str(user.id)


@router.get("")
async def list_subscriptions(request: Request):
    await require_admin_user(request, detail=_ADMIN)
    return await asyncio.to_thread(_call, service.subscription_status)


@router.get("/chatgpt/helper")
async def download_chatgpt_helper(request: Request):
    await require_admin_user(request, detail=_ADMIN)
    from deerflow.models.chatgpt_subscription_auth import helper_source

    source = await asyncio.to_thread(_call, helper_source)
    return Response(source, media_type="text/x-python", headers={"Content-Disposition": 'attachment; filename="deerflow-chatgpt-login.py"', "Cache-Control": "no-store"})


@router.post("/{provider}/connect")
async def connect_subscription(provider: Provider, request: Request, body: ConnectRequest):
    await require_admin_user(request, detail=_ADMIN)
    if provider == "grok":
        func, argument = service.begin_grok_connection, await _owner(request)
    elif provider == "kimi":
        if body.api_key is None:
            raise HTTPException(422, "Enter a Kimi Code subscription API key")
        func, argument = service.connect_kimi, body.api_key.get_secret_value()
    else:
        if body.connection is None:
            raise HTTPException(422, "Upload the ChatGPT connection JSON from the sign-in helper")
        func, argument = service.connect_chatgpt, body.connection
    return await run_drained_write("Connect subscription", _call, (HTTPException,), func, argument)


@router.post("/grok/poll")
async def poll_grok(request: Request, body: PollRequest):
    await require_admin_user(request, detail=_ADMIN)
    owner = await _owner(request)
    return await run_drained_write("Complete subscription sign-in", _call, (HTTPException,), service.poll_grok_connection, owner, body.flow_id)


@router.post("/{provider}/refresh")
async def refresh_subscription(provider: Provider, request: Request):
    await require_admin_user(request, detail=_ADMIN)
    return await run_drained_write("Refresh subscription models", _call, (HTTPException,), service.refresh_subscription, provider)


@router.delete("/{provider}")
async def disconnect_subscription(provider: Provider, request: Request):
    await require_admin_user(request, detail=_ADMIN)
    return await run_drained_write("Disconnect subscription", _call, (HTTPException,), service.disconnect_subscription, provider)
