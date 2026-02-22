FROM python:3.12-alpine3.19 AS builder

WORKDIR /usr/src/app

COPY requirements.txt .

RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    apk add --no-cache --virtual build-deps build-base cargo \
    && pip install --user -r requirements.txt \
    && apk del build-deps

COPY . .

FROM python:3.12-alpine3.19

RUN apk add --no-cache \
    bash \
    curl \
    deno \
    ffmpeg \
    mkvtoolnix \
    shadow \
    su-exec \
    tini \
    tzdata \
    util-linux

WORKDIR /usr/src/app

COPY --from=builder /usr/src/app .
COPY --from=builder /root/.local ./.local

ENV PATH="/usr/src/app/.local/bin:$PATH" \
    PYTHONPATH="/usr/src/app/.local/lib/python3.12/site-packages"

ENV USER=appuser \
    GROUP=appgroup \
    UID=1000 \
    GID=1000

RUN groupadd --gid $GID $GROUP \
    && useradd --home-dir $(pwd) --no-create-home --shell /bin/sh --gid $GID --uid $UID $USER \
    && chown -R $UID:$GID . \
    && chmod +x ./start.sh \
    && mkdir -p /gallery-dl \
    && chown -R $UID:$GID /gallery-dl

ENV CONTAINER_PORT=9080

EXPOSE $CONTAINER_PORT

VOLUME ["/gallery-dl"]

ENTRYPOINT ["/sbin/tini", "--"]

CMD ["./start.sh"]
