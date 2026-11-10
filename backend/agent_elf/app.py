from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agent_elf.controller import RunController
from agent_elf.document_import import MAX_UPLOAD_BYTES, DocumentImportError, extract_document
from agent_elf.models import (
    KnowledgeCreate,
    KnowledgeToggle,
    RequirementUpdate,
    ResumeRequest,
    RunCreate,
    RunStatus,
    SkillCreate,
    SkillToggle,
)
from agent_elf.provider import DemoProvider, ModelProvider, build_provider
from agent_elf.store import StateStore


def create_app(
    database_path: Path | None = None,
    provider: ModelProvider | None = None,
) -> FastAPI:
    store = StateStore(database_path or Path(os.getenv("AGENT_ELF_DB", "data/agent_elf.sqlite3")))
    model_provider = provider or build_provider()
    controller = RunController(store, model_provider)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await controller.recover_interrupted_runs()
        yield

    app = FastAPI(title="Agent 精灵", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    app.state.controller = controller
    app.state.provider = model_provider
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return response

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "agent-elf"}

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        is_demo = isinstance(model_provider, DemoProvider)
        return {
            "provider": "demo" if is_demo else "openai-compatible",
            "model": getattr(model_provider, "model", "configured"),
            "external_data_disclosure": (
                None
                if is_demo
                else "本次输入、启用知识与阶段上下文将发送给已配置的外部模型服务商。"
            ),
            "requires_token_budget": True,
            "default_token_budget": None,
        }

    @app.get("/api/runs")
    def list_runs(limit: int = Query(default=30, ge=1, le=100)) -> list[dict[str, Any]]:
        return store.list_runs(limit)

    @app.post("/api/runs", status_code=202)
    async def create_run(request: RunCreate) -> dict[str, Any]:
        if not isinstance(model_provider, DemoProvider) and not request.external_model_ack:
            raise HTTPException(
                status_code=400,
                detail="使用外部模型前必须确认输入会发送给配置的服务商。",
            )
        run = store.create_run(request.user_input, request.token_budget)
        controller.start(run["id"])
        return jsonable_encoder(run)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run 不存在。")
        return jsonable_encoder(run)

    @app.post("/api/runs/{run_id}/resume")
    async def resume_run(run_id: str, request: ResumeRequest) -> dict[str, Any]:
        try:
            run = await controller.resume(
                run_id,
                request.decision,
                request.comment,
                request.additional_token_budget,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return jsonable_encoder(run)

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: str) -> dict[str, Any]:
        try:
            return jsonable_encoder(controller.cancel(run_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/events")
    async def run_events(
        run_id: str,
        after_id: int = Query(default=0, ge=0),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        if store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Run 不存在。")
        try:
            resume_after = max(after_id, int(last_event_id or 0))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Last-Event-ID 必须是整数。") from exc

        async def stream():
            cursor = resume_after
            while True:
                events = store.events_after(run_id, cursor)
                for event in events:
                    cursor = event["id"]
                    payload = json.dumps(event, ensure_ascii=False)
                    yield f"id: {cursor}\ndata: {payload}\n\n"
                run = store.get_run(run_id)
                if run is None or run["status"] in {
                    RunStatus.COMPLETED,
                    RunStatus.CANCELLED,
                    RunStatus.FAILED,
                }:
                    return
                if not events:
                    yield ": keep-alive\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/runs/{run_id}/log")
    def run_log(run_id: str) -> list[dict[str, Any]]:
        if store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Run 不存在。")
        return store.events_after(run_id)

    @app.get("/api/runs/{run_id}/artifacts")
    def list_artifacts(run_id: str) -> list[dict[str, Any]]:
        if store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Run 不存在。")
        return store.list_artifacts(run_id)

    @app.get("/api/runs/{run_id}/artifacts/{artifact_id}")
    def get_artifact(run_id: str, artifact_id: str) -> dict[str, Any]:
        artifact = store.get_artifact(run_id, artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="产物不存在。")
        return artifact

    @app.get("/api/runs/{run_id}/requirements")
    def list_requirements(run_id: str) -> list[dict[str, Any]]:
        if store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Run 不存在。")
        return [item.model_dump() for item in store.list_requirements(run_id)]

    @app.put("/api/runs/{run_id}/requirements/{requirement_id}")
    def update_requirement(
        run_id: str,
        requirement_id: str,
        request: RequirementUpdate,
    ) -> dict[str, Any]:
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run 不存在。")
        if run["status"] != RunStatus.WAITING_HUMAN or run["current_stage"] != "S5":
            raise HTTPException(status_code=409, detail="仅可在 S5 需求确认门编辑需求点。")
        updated = store.update_requirement(run_id, requirement_id, request.model_dump())
        if updated is None:
            raise HTTPException(status_code=404, detail="需求点不存在。")
        return updated.model_dump()

    @app.get("/api/knowledge")
    def list_knowledge() -> list[dict[str, Any]]:
        return store.list_knowledge()

    @app.post("/api/knowledge", status_code=201)
    def add_knowledge(request: KnowledgeCreate) -> dict[str, Any]:
        if "://" in request.filename or "/" in request.filename or "\\" in request.filename:
            raise HTTPException(status_code=400, detail="仅接受本地文件名，不接受路径或 URL。")
        filename = Path(request.filename).name
        suffix = Path(filename).suffix.lower()
        if suffix not in {".txt", ".md", ".csv"}:
            raise HTTPException(
                status_code=415,
                detail="文本接口仅支持 TXT、Markdown 与 CSV；PDF/DOCX 请使用文件上传。",
            )
        if "\x00" in filename or not filename:
            raise HTTPException(status_code=400, detail="文件名无效。")
        if len(request.content.encode("utf-8")) > 1_000_000:
            raise HTTPException(status_code=413, detail="单个知识文件不能超过 1 MB。")
        return store.add_knowledge(filename, suffix[1:], request.content)

    @app.post("/api/knowledge/upload", status_code=201)
    async def upload_knowledge(file: UploadFile = File(...)) -> dict[str, Any]:
        filename = file.filename or ""
        payload = bytearray()
        try:
            while chunk := await file.read(64 * 1024):
                if len(payload) + len(chunk) > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="单个文档不能超过 20 MiB。")
                payload.extend(chunk)
        finally:
            await file.close()

        try:
            document = extract_document(filename, bytes(payload))
        except DocumentImportError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        return store.add_knowledge(
            document.filename,
            document.file_type,
            document.content,
            document.source_metadata,
        )

    @app.delete("/api/knowledge/{item_id}", status_code=204)
    def delete_knowledge(item_id: str) -> None:
        if not store.delete_knowledge(item_id):
            raise HTTPException(status_code=404, detail="知识条目不存在。")

    @app.put("/api/knowledge/{item_id}")
    def set_knowledge_enabled(item_id: str, request: KnowledgeToggle) -> dict[str, Any]:
        if not store.set_knowledge_enabled(item_id, request.enabled):
            raise HTTPException(status_code=404, detail="知识条目不存在。")
        return {"id": item_id, "enabled": request.enabled}

    @app.get("/api/skills")
    def list_skills() -> list[dict[str, Any]]:
        return store.list_skills()

    @app.post("/api/skills", status_code=201)
    def add_skill(request: SkillCreate) -> dict[str, Any]:
        return store.add_skill(
            request.name,
            request.description,
            request.content,
            request.stages,
            enabled=request.enabled,
        )

    @app.put("/api/skills/{skill_id}")
    def set_skill_enabled(skill_id: str, request: SkillToggle) -> dict[str, Any]:
        if not store.set_skill_enabled(skill_id, request.enabled):
            raise HTTPException(status_code=404, detail="Skill 不存在。")
        return {"id": skill_id, "enabled": request.enabled}

    return app


app = create_app()
