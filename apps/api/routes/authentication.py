from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel, Field, ConfigDict
from auth import cookie, clear_cookie, FLOW_SECONDS

router = APIRouter(prefix="/auth")


class Recovery(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    token: str = Field(min_length=1, max_length=128)


def enabled(request):
    service = request.app.state.auth
    if not service.settings.auth_enabled:
        raise HTTPException(503, "Google sign-in is not enabled yet.")
    return service


@router.get("/status")
def status(request: Request):
    service = request.app.state.auth
    active = service.settings.auth_enabled
    response = JSONResponse({"enabled": active, "user": service.current(request) if active else None,
        "local_recovery": active and service.local_recovery_allowed(request)})
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/login")
def login(request: Request, next: str = Query(default="/", max_length=2048)):
    service = enabled(request)
    url, binding, origin = service.begin(request, next)
    response = RedirectResponse(url, status_code=303)
    cookie(response, origin, binding, flow=True, age=FLOW_SECONDS)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/callback")
async def callback(request: Request, state: str = Query(default="", max_length=128),
                   code: str = Query(default="", max_length=2048), error: str = Query(default="", max_length=100)):
    service = enabled(request)
    origin = service.origin(request)
    try:
        token, next_path, origin = await service.finish(request, state, code if not error else "")
    except Exception:
        # Never log OAuth codes/tokens, secret-bearing provider errors or claims.
        response = RedirectResponse("/login?error=signin_failed", status_code=303)
    else:
        response = RedirectResponse(next_path, status_code=303)
        cookie(response, origin, token)
    clear_cookie(response, origin, flow=True)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.post("/recover")
def recover(request: Request, body: Recovery):
    service = enabled(request)
    token, origin = service.recover(request, body.token)
    response = JSONResponse({"ok": True})
    cookie(response, origin, token)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/logout")
def logout(request: Request):
    service = enabled(request)
    origin = service.logout(request)
    response = JSONResponse({"ok": True})
    clear_cookie(response, origin)
    response.headers["Cache-Control"] = "no-store"
    return response
