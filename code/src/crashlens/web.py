from __future__ import annotations

import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import inspect_directory, load_config, source_hashes
from .bundles import build_bundle, stream_bundle
from .engine import TERMINAL
from .manager import Manager

PACKAGE = Path(__file__).parent


class StartRequest(BaseModel):
    directory: str
    config: dict | None = None


class ReplayRequest(BaseModel):
    directory: str | None = None
    minimized: bool = True


def create_app(home: Path) -> FastAPI:
    manager = Manager(home)
    token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        yield
        manager.close()

    app = FastAPI(title="CrashLens", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.manager = manager
    app.state.token = token
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    app.mount("/static", StaticFiles(directory=PACKAGE / "static"), name="static")
    templates = Jinja2Templates(directory=PACKAGE / "templates")

    @app.middleware("http")
    async def local_api(request: Request, call_next):
        if request.method not in {"GET", "HEAD"}:
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
                return JSONResponse({"detail": "拒绝跨站请求"}, status_code=403)
            if not secrets.compare_digest(request.headers.get("x-crashlens-token", ""), token):
                return JSONResponse({"detail": "页面会话已过期，请刷新后重试"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"detail": "任务或证据不存在"}, status_code=404)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        examples = PACKAGE.parents[1] / "examples"
        return templates.TemplateResponse(request=request, name="index.html", context={
            "token": token, "buggy": str(examples / "datacraft-buggy") if examples.exists() else "",
            "fixed": str(examples / "datacraft-fixed") if examples.exists() else ""})

    @app.post("/api/inspect")
    def inspect(body: StartRequest):
        return inspect_directory(body.directory)

    @app.get("/api/jobs")
    def jobs():
        with manager.lock:
            manager.refresh()
            return manager.store.list()

    @app.post("/api/jobs", status_code=201)
    def start(body: StartRequest):
        return manager.start(body.directory, body.config)

    @app.get("/api/jobs/{job_id}")
    def detail(job_id: str):
        with manager.lock:
            manager.refresh()
            job = manager.store.get(job_id)
        job["findings"] = manager.store.findings(job_id)
        return job

    @app.post("/api/jobs/{job_id}/stop")
    def stop(job_id: str):
        return manager.stop(job_id)

    def find(job_id, finding_id):
        for finding in manager.store.findings(job_id):
            if finding["id"] == finding_id:
                return finding
        raise KeyError(finding_id)

    @app.get("/api/jobs/{job_id}/findings/{finding_id}/input")
    def download_input(job_id: str, finding_id: str, minimized: bool = False):
        find(job_id, finding_id)
        folder = manager.store.folder(job_id) / "findings" / finding_id
        path = folder / ("minimized.bin" if minimized else "input.bin")
        if not path.is_file():
            raise HTTPException(404, "没有经过验证的缩减输入")
        return FileResponse(path, media_type="application/octet-stream", filename=path.name)

    @app.get("/api/jobs/{job_id}/findings/{finding_id}/preview")
    def preview(job_id: str, finding_id: str):
        finding = find(job_id, finding_id)
        folder = manager.store.folder(job_id) / "findings" / finding_id
        data = (folder / "input.bin").read_bytes()
        reduced = (folder / "minimized.bin").read_bytes() if (folder / "minimized.bin").exists() else None
        return {"input": data[:16384].decode("utf-8", errors="replace"),
                "hex": data[:128].hex(" "), "truncated": len(data) > 16384,
                "minimized": reduced[:16384].decode("utf-8", errors="replace") if reduced is not None else None,
                "finding": finding}

    @app.post("/api/jobs/{job_id}/findings/{finding_id}/replay", status_code=201)
    def replay(job_id: str, finding_id: str, body: ReplayRequest):
        original = manager.store.get(job_id)
        if original["state"] not in TERMINAL:
            raise ValueError("请先等待原任务结束")
        finding = find(job_id, finding_id)
        folder = manager.store.folder(job_id) / "findings" / finding_id
        path = folder / "minimized.bin" if body.minimized and (folder / "minimized.bin").exists() else folder / "input.bin"
        directory = body.directory or original["directory"]
        if body.directory:
            root, config = load_config(directory)
        else:
            root, config = load_config(directory, original["config"])
            if source_hashes(root, config) != original["source_hashes"]:
                raise ValueError("目标源文件已变化；请填写回归目录以明确执行新版本")
        config.fuzz.minimize = False
        config.fuzz.max_cases = 1
        return manager.start(str(root), config.model_dump(), {
            "job_id": job_id, "finding_id": finding_id, "signature": finding["signature"],
            "input_variant": path.name, "kind": "regression" if body.directory else "replay", "data": path.read_bytes()})

    @app.get("/api/jobs/{job_id}/report.json")
    def json_report(job_id: str):
        report = detail(job_id)
        return JSONResponse(report, headers={"Content-Disposition": f'attachment; filename="crashlens-{job_id}.json"'})

    @app.get("/api/jobs/{job_id}/report.html", response_class=HTMLResponse)
    def html_report(request: Request, job_id: str):
        report = detail(job_id)
        return templates.TemplateResponse(request=request, name="report.html", context={"job": report},
                                          headers={"Content-Disposition": f'attachment; filename="crashlens-{job_id}.html"'})

    @app.get("/api/jobs/{job_id}/evidence.zip")
    def evidence_bundle(job_id: str):
        report = detail(job_id)
        if report["state"] not in TERMINAL:
            raise HTTPException(409, "请等待任务结束或先停止任务，再下载完整证据包")
        html = templates.env.get_template("report.html").render(job=report)
        stream = build_bundle(manager.store.folder(job_id), report, html)
        return StreamingResponse(stream_bundle(stream), media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="crashlens-{job_id}-evidence.zip"'})

    return app
