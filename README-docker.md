# protoRAG+ Docker Usage

## Build image

```bash
docker build -t protorag:latest .
```

## Run container with local data volume

```bash
docker run \
  --name protorag \
  -p 127.0.0.1:8000:8000 \
  -v /path/on/host:/app/data \
  protorag:latest
```

- Inside container the app runs at `http://0.0.0.0:8000` and serves both UI and API.
- All documents, Chroma DB files, and histories live under `/app/data` in the container, mapped to `/path/on/host` on the host.

## UI configuration inside container

In the Settings modal:

- Storage Path (Local): `./data`
- Provider: `ollama` (or as appropriate)
- Base URL: `http://<tailscale-llm-host>:11434/v1`
- API Key: as required by your remote service
- LLM Model / Embedding Model: names available on the remote host

The backend will resolve all paths under `/app/data`, which is persisted on the host via the volume mount.
