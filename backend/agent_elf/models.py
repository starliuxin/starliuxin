from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(StrEnum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    WAITING_HUMAN = "WAITING_HUMAN"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class StageId(StrEnum):
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"
    S5 = "S5"
    S6 = "S6"
    S7 = "S7"
    S8 = "S8"


STAGE_LABELS: dict[StageId, str] = {
    StageId.S1: "市场调研（待核实）",
    StageId.S2: "用户需求分析",
    StageId.S3: "产品规划与决策",
    StageId.S4: "产品原型设计",
    StageId.S5: "功能需求确认",
    StageId.S6: "开发产物生成（不执行）",
    StageId.S7: "静态检查（未运行测试）",
    StageId.S8: "运维与安全方案（待人工复核）",
}


class PlanStep(BaseModel):
    id: str
    stage: StageId
    title: str
    mode: Literal["independent_llm_call", "transform_previous"] = "independent_llm_call"
    inputs: list[str] = Field(default_factory=list)
    expected_output: str
    depends_on: list[str] = Field(default_factory=list)
    acceptance: str


class Plan(BaseModel):
    final_goal: str = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    steps: list[PlanStep] = Field(min_length=1, max_length=8)
    done_definition: str


class ReviewFinding(BaseModel):
    dimension: Literal["事实性错误", "逻辑漏洞", "效率问题", "遗漏信息"]
    severity: Literal["high", "medium", "low"]
    location: str
    problem: str
    suggestion: str


class Feedback(BaseModel):
    verdict: Literal["pass", "needs_revision"]
    findings: list[ReviewFinding] = Field(default_factory=list)
    summary: str


class Requirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    module: str
    description: str
    priority: Literal["P0", "P1", "P2"] = "P1"
    acceptance: str
    prototype_element: str = ""
    related_steps: list[str] = Field(default_factory=list)
    version: int = 1
    dirty: bool = False


class RunCreate(BaseModel):
    user_input: str = Field(min_length=3, max_length=10_000)
    token_budget: int = Field(gt=0, le=2_000_000)
    external_model_ack: bool = False


class ResumeRequest(BaseModel):
    decision: Literal["continue", "approve_review", "cancel"]
    comment: str = Field(default="", max_length=2_000)
    additional_token_budget: int = Field(default=0, ge=0, le=2_000_000)


class RequirementUpdate(BaseModel):
    module: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2_000)
    priority: Literal["P0", "P1", "P2"]
    acceptance: str = Field(min_length=1, max_length=2_000)
    prototype_element: str = Field(default="", max_length=500)


class KnowledgeCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=1_000_000)


class KnowledgeToggle(BaseModel):
    enabled: bool


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=20_000)
    stages: list[StageId] = Field(min_length=1, max_length=8)
    enabled: Literal[False] = False


class SkillToggle(BaseModel):
    enabled: bool
