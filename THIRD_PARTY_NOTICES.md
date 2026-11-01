# Third-party software

Music Bingo includes or uses the following. Each keeps its own license.

| Component | Used for | License |
| --- | --- | --- |
| [qrcode-generator](http://www.d-project.com/) by Kazuhiko Arase (`app/static/qrcode.js`, vendored) | Drawing QR codes | MIT |
| [FastAPI](https://fastapi.tiangolo.com/), [Starlette](https://www.starlette.io/), [Uvicorn](https://www.uvicorn.org/), [Jinja2](https://jinja.palletsprojects.com/), [SQLAlchemy](https://www.sqlalchemy.org/), [itsdangerous](https://itsdangerous.palletsprojects.com/), [python-multipart](https://github.com/Kludex/python-multipart), [requests](https://requests.readthedocs.io/) | The web app | MIT, BSD or Apache-2.0 (see each project) |
| [psycopg2](https://www.psycopg.org/) | Talking to PostgreSQL | LGPL with exceptions |
| [PostgreSQL](https://www.postgresql.org/) (separate container) | The database | PostgreSQL License |
| [Spotify Web Playback SDK](https://developer.spotify.com/documentation/web-playback-sdk) | Playing music in the browser, loaded from Spotify's servers | Spotify Developer Terms |

Music Bingo is an independent project. It is **not made, endorsed or sponsored by Spotify**. Spotify is a trademark of
Spotify AB; it is used here only to say what the app connects to. Using Spotify's services through this app is subject to
Spotify's own terms and developer policy.
