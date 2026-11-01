"""Public landing pages, help and the host home."""
from fastapi import APIRouter, Request
from starlette.responses import Response
from fastapi.responses import HTMLResponse, RedirectResponse
from ..common import require_host, templates

router = APIRouter()


@router.get('/favicon.ico', include_in_schema=False)
async def favicon():
    return RedirectResponse(url='/static/favicon.ico')


@router.get("/enter", response_class=HTMLResponse)
def enter_game_code_page(request: Request):
    return templates.TemplateResponse(request, "enter_game_code.html", {"request": request})


@router.head("/")
async def head_root():
    # Some scanners use HEAD to fetch headers. Return 200 instead of 405.
    return Response(status_code=200)


@router.get("/", response_class=HTMLResponse)
def player_landing(request: Request):
    # Players land straight on Join; hosts use the "Host? Log in" link under it to reach /home
    return templates.TemplateResponse(request, "enter_game_code.html", {"request": request})


@router.get("/home", response_class=HTMLResponse)
def host_home(request: Request):
    # Host / Join / Play Alone chooser: hosts only (logs in first, then comes back here)
    r = require_host(request, next_path="/home")
    if r:
        return r
    return templates.TemplateResponse(request, "home.html", {"request": request})


@router.get('/help', response_class=HTMLResponse)
def help_page(request: Request):
    """Getting started: how the app works. Public, so players can read it too."""
    return templates.TemplateResponse(request, 'help.html', {'request': request})
