import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { api } from "./api";
import { buildPrototypeDocument } from "./preview";
import type { Artifact, Requirement, Run, RunEvent, StageId } from "./types";

const stages: Array<{ id: StageId; label: string }> = [
  { id: "S1", label: "市场假设" },
  { id: "S2", label: "用户需求" },
  { id: "S3", label: "产品决策" },
  { id: "S4", label: "原型设计" },
  { id: "S5", label: "需求确认" },
  { id: "S6", label: "代码草案" },
  { id: "S7", label: "静态检查" },
  { id: "S8", label: "运维安全" },
];

interface RunConsoleProps {
  runId: string;
  onBack: () => void;
  onChanged: () => void;
  onError: (message: string) => void;
}

function RunConsole({ runId, onBack, onChanged, onError }: RunConsoleProps) {
  const [run, setRun] = useState<Run | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [selectedArtifactId, setSelectedArtifactId] = useState("");
  const [additionalBudget, setAdditionalBudget] = useState("");
  const [reviewChecked, setReviewChecked] = useState(false);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [nextRun, nextArtifacts, nextRequirements, nextEvents] = await Promise.all([
        api.run(runId),
        api.artifacts(runId),
        api.requirements(runId),
        api.log(runId),
      ]);
      setRun(nextRun);
      setArtifacts(nextArtifacts);
      setRequirements(nextRequirements);
      setEvents(nextEvents);
      setSelectedArtifactId((current) =>
        current && !nextArtifacts.some((artifact) => artifact.id === current) ? "" : current,
      );
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "无法读取 Run。");
    }
  }, [onError, runId]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 1_800);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    let active = true;
    let source: EventSource | undefined;
    void api
      .log(runId)
      .then((knownEvents) => {
        if (!active) return;
        const lastId = knownEvents.at(-1)?.id ?? 0;
        source = new EventSource(`/api/runs/${runId}/events?after_id=${lastId}`);
        source.onmessage = (message) => {
          try {
            const event = JSON.parse(message.data) as RunEvent;
            setEvents((current) =>
              current.some((item) => item.id === event.id)
                ? current
                : [...current, event].slice(-100),
            );
            void refresh();
            onChanged();
            if (["run.completed", "run.cancelled", "run.failed"].includes(event.event_type)) {
              source?.close();
            }
          } catch {
            onError("运行事件格式无效；页面状态仍会定时刷新。");
          }
        };
      })
      .catch((reason: unknown) => {
        if (active) onError(reason instanceof Error ? reason.message : "无法连接运行事件流。");
      });
    return () => {
      active = false;
      source?.close();
    };
  }, [onChanged, onError, refresh, runId]);

  const selectedArtifact = useMemo(() => {
    const explicit = artifacts.find((artifact) => artifact.id === selectedArtifactId);
    if (explicit) return explicit;
    return (
      [...artifacts].reverse().find((artifact) => artifact.kind === "prototype_html") ??
      artifacts.at(-1) ??
      null
    );
  }, [artifacts, selectedArtifactId]);

  async function perform(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      await refresh();
      onChanged();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "操作失败。");
    } finally {
      setBusy(false);
    }
  }

  if (!run) {
    return (
      <div className="loading-panel">
        <span className="loading-orbit" />
        正在读取运行现场…
      </div>
    );
  }

  const isS5Gate = run.status === "WAITING_HUMAN" && run.current_stage === "S5";
  const isS8Gate = run.status === "WAITING_HUMAN" && run.current_stage === "S8";
  const isPaused = run.status === "PAUSED";
  const budgetExhausted = run.total_tokens >= run.token_budget;
  const progress = Math.min(100, Math.round((run.total_tokens / run.token_budget) * 100));
  return (
    <div className="run-page">
      <div className="run-page-top">
        <button className="back-link" onClick={onBack} type="button">
          <span aria-hidden="true">←</span> 返回工作台
        </button>
        <span className={`status-pill pill-${run.status.toLowerCase()}`}>
          <span />
          {statusLabel(run.status)}
        </span>
      </div>
      <section className="run-heading">
        <div>
          <p className="card-kicker">RUN / {run.id.slice(0, 8).toUpperCase()}</p>
          <h1>{run.user_input}</h1>
          <p className="run-subtitle">
            {run.current_stage
              ? `${run.current_stage} · ${stages.find((stage) => stage.id === run.current_stage)?.label ?? ""}`
              : "正在生成执行计划"}
          </p>
        </div>
        <div className="budget-meter">
          <div className="budget-meter-head">
            <span>token 用量</span>
            <strong>
              {run.total_tokens.toLocaleString()}
              <i> / {run.token_budget.toLocaleString()}</i>
            </strong>
          </div>
          <div
            aria-label={`token 预算已使用 ${progress}%`}
            className="meter-track"
            role="progressbar"
            aria-valuenow={Math.min(100, Math.round((run.total_tokens / run.token_budget) * 100))}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <span style={{ width: `${Math.min(100, (run.total_tokens / run.token_budget) * 100)}%` }} />
          </div>
          <small>达到硬上限即暂停；续跑需明确增加预算</small>
        </div>
      </section>

      <div className="stage-track" aria-label="固定工作流阶段">
        {stages.map((stage, index) => {
          const complete = artifacts.some(
            (artifact) =>
              artifact.stage === stage.id &&
              !["feedback", "draft"].includes(artifact.kind),
          );
          const current = run.current_stage === stage.id && !complete;
          return (
            <div className={`stage-node ${complete ? "is-done" : ""} ${current ? "is-current" : ""}`} key={stage.id}>
              <span className="stage-node-index">
                {complete ? "✓" : String(index + 1).padStart(2, "0")}
              </span>
              <span className="stage-node-label">{stage.label}</span>
            </div>
          );
        })}
      </div>

      {run.plan && (
        <section className="goal-strip">
          <span className="goal-glyph">◎</span>
          <div>
            <p className="card-kicker">最终目标</p>
            <p>{run.plan.final_goal}</p>
          </div>
          <span className="goal-step-count">{run.plan.steps.length} STEPS</span>
        </section>
      )}

      {run.error && (
        <div className="run-error" role="alert">
          <strong>运行暂停说明</strong>
          <span>{run.error}</span>
        </div>
      )}

      {isS5Gate && (
        <GateCard
          title="需求点等待你确认"
          description="逐条编辑仅会标记关联步骤待更新；确认后工作流从 S6 继续。"
          actionLabel="确认需求并继续"
          busy={busy}
          onAction={() =>
            void perform(() => api.resume(run.id, "continue", "用户确认需求点"))
          }
        >
          <div className="requirement-list">
            {requirements.map((item) => (
              <RequirementEditor
                item={item}
                key={`${item.id}-${item.version}`}
                onSave={(updated) =>
                  void perform(() => api.updateRequirement(run.id, updated))
                }
              />
            ))}
          </div>
        </GateCard>
      )}

      {isS8Gate && (
        <GateCard
          title="方案已准备好，仍未应用"
          description="请检查运维与安全草案。确认只表示完成复核，不会自动修改配置或部署。"
          actionLabel="我已复核，完成本次 Run"
          busy={busy}
          disabled={!reviewChecked}
          onAction={() =>
            void perform(() =>
              api.resume(run.id, "approve_review", "人工复核完成；未应用任何变更"),
            )
          }
        >
          <label className="review-check">
            <input
              checked={reviewChecked}
              onChange={(event) => setReviewChecked(event.target.checked)}
              type="checkbox"
            />
            我已阅读草案，并理解它不代表安全认证或生产就绪。
          </label>
        </GateCard>
      )}

      {isPaused && (
        <section className="pause-card">
          <div className="pause-icon">Ⅱ</div>
          <div className="pause-copy">
            <p className="card-kicker">RUN PAUSED</p>
            <h2>{budgetExhausted ? "token 预算已用尽" : "运行已暂停"}</h2>
            <p>
              {budgetExhausted
                ? "只有明确提高本 Run 的 token 上限后，工作流才会继续。"
                : "修复配置或检查错误后，可明确选择继续；已完成阶段会保留。"}
            </p>
            {budgetExhausted && (
              <label className="budget-extension">
                增加 token 上限
                <input
                  aria-label="增加 token 上限"
                  min="1"
                  onChange={(event) => setAdditionalBudget(event.target.value)}
                  placeholder="例如 5000"
                  type="number"
                  value={additionalBudget}
                />
              </label>
            )}
            <div className="pause-actions">
              <button
                className="primary-button"
                disabled={
                  busy ||
                  (budgetExhausted && (!Number(additionalBudget) || Number(additionalBudget) < 1))
                }
                onClick={() =>
                  void perform(() =>
                    api.resume(
                      run.id,
                      "continue",
                      "用户明确续跑",
                      Number(additionalBudget) || 0,
                    ),
                  )
                }
                type="button"
              >
                明确续跑
              </button>
              <button
                className="subtle-button"
                disabled={busy}
                onClick={() => void perform(() => api.cancel(run.id))}
                type="button"
              >
                终止 Run
              </button>
            </div>
          </div>
        </section>
      )}

      <div className="run-columns">
        <section className="artifact-panel">
          <div className="panel-heading">
            <div>
              <p className="card-kicker">ARTIFACT ARCHIVE</p>
              <h2>阶段产物</h2>
            </div>
            <span className="result-count">{artifacts.length.toString().padStart(2, "0")} 项</span>
          </div>
          {artifacts.length === 0 ? (
            <div className="artifact-empty">
              <span className="empty-mark">⌁</span>
              <p>计划与产物会按阶段保存在这里。</p>
            </div>
          ) : (
            <>
              <div className="artifact-tabs">
                {artifacts.map((artifact) => (
                  <button
                    className={`artifact-tab ${selectedArtifact?.id === artifact.id ? "is-active" : ""}`}
                    key={artifact.id}
                    onClick={() => setSelectedArtifactId(artifact.id)}
                    type="button"
                  >
                    <span>{artifact.stage}</span>
                    <small>{artifact.kind.replaceAll("_", " ")} · v{artifact.version}</small>
                  </button>
                ))}
              </div>
              {selectedArtifact && (
                <ArtifactContent artifact={selectedArtifact} />
              )}
            </>
          )}
        </section>

        <aside className="event-panel">
          <div className="panel-heading">
            <div>
              <p className="card-kicker">RUN LOG</p>
              <h2>运行轨迹</h2>
            </div>
            <span className="live-mark">
              <span />
              LIVE
            </span>
          </div>
          <div className="event-list">
            {events.length === 0 ? (
              <p className="event-empty">等待第一条运行事件…</p>
            ) : (
              events.slice(-24).reverse().map((event) => (
                <article className="event-row" key={event.id}>
                  <span className="event-node" />
                  <time>{new Date(event.created_at).toLocaleTimeString()}</time>
                  <p>{event.message}</p>
                  {event.stage && <small>{event.stage}</small>}
                </article>
              ))
            )}
          </div>
          {run.status !== "COMPLETED" && run.status !== "CANCELLED" && (
            <button
              className="stop-run-button"
              disabled={busy}
              onClick={() => void perform(() => api.cancel(run.id))}
              type="button"
            >
              停止当前 Run
            </button>
          )}
        </aside>
      </div>
      <p className="run-disclaimer">
        S1 未连接实时来源；S6 代码未执行；S7 仅静态检查；S8 方案需人工复核。
      </p>
    </div>
  );
}

function ArtifactContent({ artifact }: { artifact: Artifact }) {
  if (artifact.kind === "prototype_html") {
    return (
      <div className="preview-wrap">
        <div className="preview-toolbar">
          <span className="preview-led" />
          <span>隔离静态预览</span>
          <span className="preview-path">产物 / {artifact.stage} / v{artifact.version}</span>
        </div>
        <iframe
          className="prototype-frame"
          referrerPolicy="no-referrer"
          sandbox=""
          srcDoc={buildPrototypeDocument(artifact.content)}
          title="生成的 HTML 原型隔离预览"
        />
        <p className="preview-note">脚本、表单、外部资源与顶层导航均被阻止。</p>
      </div>
    );
  }
  return (
    <div className="artifact-text-wrap">
      <div className="artifact-meta-line">
        <span>{artifact.kind.replaceAll("_", " ").toUpperCase()}</span>
        <time>{new Date(artifact.created_at).toLocaleString()}</time>
      </div>
      <pre className="artifact-content">{artifact.content}</pre>
    </div>
  );
}

function RequirementEditor({
  item,
  onSave,
}: {
  item: Requirement;
  onSave: (item: Requirement) => void;
}) {
  const [draft, setDraft] = useState(item);
  useEffect(() => setDraft(item), [item]);
  return (
    <article className="requirement-card">
      <div className="requirement-card-head">
        <span className="requirement-id">{item.id}</span>
        <span className={`priority priority-${item.priority.toLowerCase()}`}>{item.priority}</span>
        <span className="requirement-version">v{item.version}</span>
        {item.dirty && <span className="dirty-flag">待更新</span>}
      </div>
      <label>
        模块
        <input
          onChange={(event) => setDraft({ ...draft, module: event.target.value })}
          value={draft.module}
        />
      </label>
      <label>
        描述
        <textarea
          onChange={(event) => setDraft({ ...draft, description: event.target.value })}
          rows={2}
          value={draft.description}
        />
      </label>
      <label>
        验收口径
        <textarea
          onChange={(event) => setDraft({ ...draft, acceptance: event.target.value })}
          rows={2}
          value={draft.acceptance}
        />
      </label>
      <button
        className="requirement-save"
        onClick={() => onSave(draft)}
        type="button"
      >
        保存修改
      </button>
    </article>
  );
}

function GateCard({
  title,
  description,
  actionLabel,
  busy,
  disabled = false,
  onAction,
  children,
}: {
  title: string;
  description: string;
  actionLabel: string;
  busy: boolean;
  disabled?: boolean;
  onAction: () => void;
  children: ReactNode;
}) {
  return (
    <section className="gate-card">
      <div className="gate-sign" aria-hidden="true">
        ◇
      </div>
      <div className="gate-main">
        <div>
          <p className="card-kicker">HUMAN GATE · 需要你的决定</p>
          <h2>{title}</h2>
          <p className="gate-description">{description}</p>
        </div>
        {children}
        <div className="gate-footer">
          <span>工作流不会代替你默认同意。</span>
          <button
            className="primary-button"
            disabled={busy || disabled}
            onClick={onAction}
            type="button"
          >
            {actionLabel}
            <span aria-hidden="true">↗</span>
          </button>
        </div>
      </div>
    </section>
  );
}

function statusLabel(status: Run["status"]): string {
  const labels: Record<Run["status"], string> = {
    CREATED: "已创建",
    PLANNING: "正在规划",
    RUNNING: "运行中",
    WAITING_HUMAN: "等待人工确认",
    PAUSED: "已暂停",
    COMPLETED: "已完成",
    CANCELLED: "已终止",
    FAILED: "失败",
  };
  return labels[status];
}

export default RunConsole;
