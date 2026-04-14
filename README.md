# gallery-dl-server

[![Docker Image](https://img.shields.io/badge/ghcr.io-jthickma%2Fgallery--dl--server-blue?logo=docker&style=for-the-badge)](https://github.com/jthickma/gallery-dl-server/pkgs/container/gallery-dl-server 'GHCR')
[![Build](https://img.shields.io/github/actions/workflow/status/jthickma/gallery-dl-server/docker-image.yaml?branch=main&style=for-the-badge)](https://github.com/jthickma/gallery-dl-server/actions 'GitHub Actions')
[![License](https://img.shields.io/badge/license-MIT-blue.svg?style=for-the-badge)](./LICENSE 'License')

![screenshot](https://raw.githubusercontent.com/qx6ghqkz/gallery-dl-server/refs/heads/main/images/gallery-dl-server.png)

Web UI for [`gallery-dl`](https://github.com/mikf/gallery-dl) with video support via [`yt-dlp`](https://github.com/yt-dlp/yt-dlp). Fork of [qx6ghqkz/gallery-dl-server](https://github.com/qx6ghqkz/gallery-dl-server) with simplified deploy, in-browser file browser + ZIP archive, CORS config, and a modern dark UI.

## Contents

- [Quick Start (Docker Compose)](#quick-start-docker-compose)
- [Docker Run](#docker-run)
- [Run with Python](#run-with-python)
- [Configuration](#configuration)
- [Options](#options)
- [Usage](#usage)
- [REST Endpoints](#rest-endpoints)
- [Implementation](#implementation)

## Quick Start (Docker Compose)

Repo ships a ready-to-use `compose.yaml` pulling the prebuilt GHCR image. From the repo root:

```shell
mkdir -p data/config data/archive data/downloads
docker compose up -d
```

Then open http://localhost:9080/gallery-dl (port is exposed internally — add a `ports:` mapping or reverse proxy as needed).

`compose.yaml` summary:

```yaml
services:
  gallery-dl:
    image: ghcr.io/jthickma/gallery-dl-server:latest
    container_name: gallery-dl-server
    pull_policy: always
    user: "1000:1000"
    expose:
      - "9080"
    environment:
      CONTAINER_PORT: "9080"
      UMASK: "022"
      TZ: "UTC"
    volumes:
      - ./data/config:/config
      - ./data/archive:/gallery-dl
      - ./data/downloads:/usr/src/app/Media/gallery-dl
    restart: unless-stopped
```

To publish the port directly, add:

```yaml
    ports:
      - "9080:9080"
```

Change `user: "1000:1000"` to match your host UID:GID (`id -u`, `id -g`). The container pre-creates mount targets owned by UID 1000 so first-run permission errors don't occur for the default case.

Update to latest image:

```shell
docker compose pull && docker compose up -d
```

## Docker Run

One-shot equivalent without compose:

```shell
mkdir -p data/config data/archive data/downloads
docker run -d \
  --name gallery-dl-server \
  --user 1000:1000 \
  -p 9080:9080 \
  -e CONTAINER_PORT=9080 \
  -e UMASK=022 \
  -e TZ=UTC \
  -v "$PWD/data/config:/config" \
  -v "$PWD/data/archive:/gallery-dl" \
  -v "$PWD/data/downloads:/usr/src/app/Media/gallery-dl" \
  --restart unless-stopped \
  ghcr.io/jthickma/gallery-dl-server:latest
```

### Build locally

```shell
docker build -t gallery-dl-server:local .
docker run --rm -p 9080:9080 --user 1000:1000 \
  -v "$PWD/data/config:/config" \
  -v "$PWD/data/archive:/gallery-dl" \
  gallery-dl-server:local
```

### VPN networking (Gluetun)

```yaml
services:
  gallery-dl:
    image: ghcr.io/jthickma/gallery-dl-server:latest
    network_mode: service:gluetun
    user: "1000:1000"
    environment:
      CONTAINER_PORT: "9080"
    volumes:
      - ./data/config:/config
      - ./data/archive:/gallery-dl
  gluetun:
    image: qmcgaw/gluetun:latest
    ports:
      - "9080:9080"
    # VPN settings...
```

Multi-instance behind one gluetun: set different `CONTAINER_PORT` per service.

## Run with Python

Requires Python 3.10+ (3.12 recommended).

From source:

```shell
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 -m gallery_dl_server --host 0.0.0.0 --port 9080
```

From PyPI:

```shell
pip install gallery-dl-server[full]
gallery-dl-server --host 0.0.0.0 --port 9080
```

Programmatic:

```python
import gallery_dl_server as server
server.run(host="0.0.0.0", port=9080, log_level="info")
```

Uvicorn:

```shell
python3 -m uvicorn gallery_dl_server.server:app --host 0.0.0.0 --port 9080
```

All CLI flags: `python3 -m gallery_dl_server --help`.

## Configuration

gallery-dl config file is required. Docker mounts `/config` — drop `gallery-dl.conf` (or `.yaml` / `.toml`) there. If missing on first run, a default is copied in automatically.

Accepted paths inside `/config`:

- `gallery-dl.{conf,toml,yaml,yml}`
- `config.{json,toml,yaml,yml}`

Set `base-directory` (or `extractor.base-directory`) to `/gallery-dl` and map your host downloads dir to `/gallery-dl` for the simplest setup. The shipped `compose.yaml` also maps `./data/downloads` → `/usr/src/app/Media/gallery-dl` so legacy `~/Media/gallery-dl` configs work unchanged.

Mount the config **directory**, not the file, so edits propagate without container restart.

Reference: [gallery-dl docs/configuration.rst](https://github.com/mikf/gallery-dl/blob/master/docs/configuration.rst).

## Options

CLI flags override env vars.

| Flag                   | Env Var              | Docker-only | Type   | Default   | Description                           |
| ---------------------- | -------------------- | ----------- | ------ | --------- | ------------------------------------- |
| `--host`               | `HOST`               |             | str    | `0.0.0.0` | Bind address                          |
| `--port`               | `PORT`               |             | int    | `0`       | Bind port (`0` = auto)                |
|                        | `CONTAINER_PORT`     | ✓           | int    | `9080`    | Internal container port               |
|                        | `UID`                | ✓           | int    | `1000`    | Run-as UID (legacy root entrypoint)   |
|                        | `GID`                | ✓           | int    | `1000`    | Run-as GID (legacy root entrypoint)   |
|                        | `UMASK`              | ✓           | int    | `022`     | File creation mask                    |
| `--log-dir`            | `LOG_DIR`            |             | str    | `~`       | Log file directory                    |
| `--log-level`          | `LOG_LEVEL`          |             | str    | `info`    | Download log level                    |
| `--server-log-level`   | `SERVER_LOG_LEVEL`   |             | str    | `info`    | Server log level                      |
| `--access-log`         | `ACCESS_LOG`         |             | bool   | `false`   | Uvicorn access log                    |
| `--cors-allow-origins` | `CORS_ALLOW_ORIGINS` |             | str    | `*`       | CORS origins (comma-separated or `*`) |

Note: when compose sets `user:` directly, runtime UID/GID switching is skipped — `UID`/`GID` env vars only apply if container starts as root.

## Usage

### Web UI

Navigate to `http://{host}:{port}/gallery-dl` and paste a URL. Dark-mode UI with violet palette is now default.

### Downloads Browser + ZIP

The UI includes a filebrowser-style Downloads pane:

- Browse folders under the active download root.
- View files inline.
- Download individual files.
- Download everything as a single ZIP (temporary disk = final ZIP size).

Download root resolution order:

1. `extractor.base-directory` in gallery-dl config
2. `base-directory` in gallery-dl config
3. Docker fallback `/gallery-dl`
4. Non-Docker fallback `./gallery-dl`

All file ops are sandboxed to the resolved root.

### REST Endpoints

| Method | Endpoint                                       | Description                      |
| ------ | ---------------------------------------------- | -------------------------------- |
| POST   | `/gallery-dl/q`                                | Queue a download (`url` form)    |
| GET    | `/gallery-dl/files?path={rel}`                 | List directory                   |
| GET    | `/gallery-dl/files/content?path={rel}`         | Inline file content              |
| GET    | `/gallery-dl/files/download?path={rel}`        | File as attachment               |
| GET    | `/gallery-dl/files/archive`                    | ZIP of all downloaded files      |

Examples:

```shell
curl -X POST --data-urlencode "url=https://example.com/post/123" \
  http://localhost:9080/gallery-dl/q

curl "http://localhost:9080/gallery-dl/files?path=artist/example"

curl -L -o downloads.zip "http://localhost:9080/gallery-dl/files/archive"
```

### Bookmarklet

```javascript
javascript:(function(){var url='http://HOST:9080/gallery-dl/q',t=window.open(url,'_blank'),f=t.document.createElement('form');f.action=url;f.method='POST';var i=t.document.createElement('input');i.name='url';i.type='hidden';i.value=location.href;f.appendChild(i);t.document.body.appendChild(f);f.submit();})();
```

## Implementation

- ASGI server: [`uvicorn`](https://github.com/encode/uvicorn) on [`starlette`](https://github.com/encode/starlette).
- Downloads: [`gallery-dl`](https://github.com/mikf/gallery-dl) + [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) (imported for video).
- Base image: `python:3.12-alpine`. Includes `ffmpeg`, `mkvtoolnix`, `deno`, `tini`, `su-exec`.

## Useful Links

- gallery-dl supported sites: [supportedsites.md](https://github.com/mikf/gallery-dl/blob/master/docs/supportedsites.md)
- gallery-dl config outline: [wiki/config-file-outline](https://github.com/mikf/gallery-dl/wiki/config-file-outline)
- yt-dlp supported sites: [supportedsites.md](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)
