import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

import { api } from "./api";
import RunConsole from "./RunConsole";
import type { KnowledgeItem, Run, Settings, SkillItem, StageId } from "./types";

type Section = "home" | "knowledge" | "skills" | "settings";

const sectionLabels: Record<Section, string> = {
  home: "工作台",
  knowledge: "知识库",
  skills: "Skills",
  settings: "设置",
};

function App() {
  const [section, setSection] = useState<Section>("home");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [knowledge, setKnowledge] = useState<KnowledgeItem[]>([]);
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [tokenBudget, setTokenBudget] = useState("");
  const [externalAck, setExternalAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refreshRuns = useCallback(async () => {
    try {
      setRuns(await api.runs());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法读取运行列表。");
    }
  }, []);

  const refreshKnowledge = useCallback(async () => {
    try {
      setKnowledge(await api.knowledge());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法读取知识库。");
    }
  }, []);

  const refreshSkills = useCallback(async () => {
    try {
      setSkills(await api.skills());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法读取 Skills。");
    }
  }, []);

  useEffect(() => {
    void Promise.all([
      api.settings().then(setSettings),
      refreshRuns(),
      refreshKnowledge(),
      refreshSkills(),
    ]).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : "无法连接本地服务。");
    });
  }, [refreshKnowledge, refreshRuns, refreshSkills]);

  useEffect(() => {
    const timer = window.setInterval(() => void refreshRuns(), 4_000);
    return () => window.clearInterval(timer);
  }, [refreshRuns]);

  async function submitRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft.trim() || !Number(tokenBudget) || busy) return;
    setBusy(true);
    setError("");
    try {
      const run = await api.createRun(draft.trim(), Number(tokenBudget), externalAck);
      setActiveRunId(run.id);
      setSection("home");
      setDraft("");
      await refreshRuns();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法启动 Run。");
    } finally {
      setBusy(false);
    }
  }

  function navigate(next: Section) {
    setSection(next);
    setActiveRunId(null);
    setError("");
  }

  return (
    <div className="app-frame">
      <aside className="rail">
        <button className="brand-lockup" onClick={() => navigate("home")} type="button">
          <span className="brand-sigil" aria-hidden="true">
            ✳
          </span>
          <span className="brand-name">Agent 精灵</span>
        </button>
        <div className="rail-rule" />
        <nav className="primary-nav" aria-label="主导航">
          {(["home", "knowledge", "skills", "settings"] as Section[]).map((item) => (
            <button
              aria-current={section === item && !activeRunId ? "page" : undefined}
              className={`nav-item ${section === item && !activeRunId ? "is-active" : ""}`}
              key={item}
              onClick={() => navigate(item)}
              type="button"
            >
              <span className={`nav-glyph glyph-${item}`} aria-hidden="true" />
              {sectionLabels[item]}
            </button>
          ))}
        </nav>
        <div className="rail-section-heading">
          <span>最近运行</span>
          <button
            aria-label="新建 Run"
            className="icon-button"
            onClick={() => {
              setActiveRunId(null);
              setSection("home");
            }}
            type="button"
          >
            +
          </button>
        </div>
        <div className="run-list">
          {runs.length === 0 ? (
            <p className="empty-sidebar">还没有运行记录</p>
          ) : (
            runs.slice(0, 7).map((run) => (
              <button
                className={`run-link ${activeRunId === run.id ? "is-selected" : ""}`}
                key={run.id}
                onClick={() => setActiveRunId(run.id)}
                type="button"
              >
                <span className={`mini-status status-${run.status.toLowerCase()}`} />
                <span>{run.user_input}</span>
              </button>
            ))
          )}
        </div>
        <div className="rail-bottom">
          <span className="local-led" />
          本地工作区
          <span className="rail-version">MVP · P1</span>
        </div>
      </aside>

      <main className="main-column">
        <header className="masthead">
          <div className="breadcrumb">
            <span>Agent 精灵</span>
            <span className="crumb-slash">/</span>
            <span>{activeRunId ? "运行详情" : sectionLabels[section]}</span>
          </div>
          <div className="provider-indicator">
            <span className="provider-dot" />
            {settings?.provider === "openai-compatible"
              ? `外部模型 · ${settings.model}`
              : "本地演示模式"}
          </div>
        </header>

        {error && (
          <div className="global-alert" role="alert">
            <span>{error}</span>
            <button aria-label="关闭提示" onClick={() => setError("")} type="button">
              ×
            </button>
          </div>
        )}

        {activeRunId ? (
          <RunConsole
            key={activeRunId}
            runId={activeRunId}
            onBack={() => setActiveRunId(null)}
            onChanged={refreshRuns}
            onError={setError}
          />
        ) : section === "home" ? (
          <HomeView
            busy={busy}
            draft={draft}
            externalAck={externalAck}
            onDraftChange={setDraft}
            onExternalAckChange={setExternalAck}
            onOpenRun={setActiveRunId}
            onSubmit={submitRun}
            runs={runs}
            settings={settings}
            tokenBudget={tokenBudget}
            onTokenBudgetChange={setTokenBudget}
          />
        ) : section === "knowledge" ? (
          <KnowledgeView
            items={knowledge}
            onChanged={refreshKnowledge}
            onError={setError}
          />
        ) : section === "skills" ? (
          <SkillsView items={skills} onChanged={refreshSkills} onError={setError} />
        ) : (
          <SettingsView settings={settings} />
        )}
      </main>
    </div>
  );
}

interface HomeViewProps {
  busy: boolean;
  draft: string;
  externalAck: boolean;
  onDraftChange: (value: string) => void;
  onExternalAckChange: (value: boolean) => void;
  onOpenRun: (id: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  runs: Run[];
  settings: Settings | null;
  tokenBudget: string;
  onTokenBudgetChange: (value: string) => void;
}

function HomeView({
  busy,
  draft,
  externalAck,
  onDraftChange,
  onExternalAckChange,
  onOpenRun,
  onSubmit,
  runs,
  settings,
  tokenBudget,
  onTokenBudgetChange,
}: HomeViewProps) {
  return (
    <div className="home-page">
      <section className="hero">
        <div className="hero-copy">
          <div className="overline">
            <span className="overline-rule" />
            产品构想 · 受控工作流
          </div>
          <h1>
            把一个想法，
            <br />
            <em>慢慢做成</em>一件事。
          </h1>
          <p>
            先理清目标与步骤，再逐段产出原型、需求与代码草案。
            每个关键决定，都留给你亲自确认。
          </p>
          <div className="hero-stats">
            <span>
              <strong>08</strong> 个固定阶段
            </span>
            <span>
              <strong>02</strong> 个人工确认门
            </span>
            <span>
              <strong>00</strong> 次代码执行
            </span>
          </div>
        </div>
        <div className="hero-illustration" aria-hidden="true">
          <div className="orbit orbit-one" />
          <div className="orbit orbit-two" />
          <div className="seed seed-one">✦</div>
          <div className="seed seed-two">✧</div>
          <div className="sprout">
            <span className="sprout-leaf leaf-left" />
            <span className="sprout-leaf leaf-right" />
            <span className="sprout-stem" />
            <span className="sprout-ground" />
          </div>
          <span className="illustration-caption">IDEAS TAKE ROOT HERE</span>
        </div>
      </section>

      <section className="workbench-grid">
        <form className="composer-card" onSubmit={onSubmit}>
          <div className="card-heading">
            <div>
              <p className="card-kicker">01 — 开始一段新的旅程</p>
              <h2>你想做什么？</h2>
            </div>
            <span className="card-stamp">NEW RUN</span>
          </div>
          <textarea
            aria-label="产品构想"
            className="idea-input"
            minLength={3}
            onChange={(event) => onDraftChange(event.target.value)}
            placeholder="例如：做一个帮助自由职业者跟踪项目进度和账单的轻量工具……"
            required
            rows={4}
            value={draft}
          />
          <div className="budget-row">
            <label htmlFor="budget-input">
              每次运行的 token 硬上限 <span>必填</span>
            </label>
            <div className="budget-control">
              <input
                id="budget-input"
                min="1"
                onChange={(event) => onTokenBudgetChange(event.target.value)}
                placeholder="20,000"
                required
                type="number"
                value={tokenBudget}
              />
              <span>tokens</span>
            </div>
          </div>
          {settings?.provider === "openai-compatible" && (
            <label className="consent-row">
              <input
                checked={externalAck}
                onChange={(event) => onExternalAckChange(event.target.checked)}
                required
                type="checkbox"
              />
              <span>{settings.external_data_disclosure}</span>
            </label>
          )}
          <div className="composer-actions">
            <span className="composer-hint">
              {settings?.provider === "openai-compatible"
                ? "外部调用会按服务商用量计费"
                : "演示输出为本地模板，不代表真实研究结论"}
            </span>
            <button
              className="primary-button"
              disabled={
                busy ||
                !draft.trim() ||
                Number(tokenBudget) < 1 ||
                (settings?.provider === "openai-compatible" && !externalAck)
              }
              type="submit"
            >
              {busy ? "正在启动…" : "整理目标"}
              <span aria-hidden="true">↗</span>
            </button>
          </div>
        </form>

        <aside className="guard-card">
          <div className="guard-emblem" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <p className="card-kicker">02 — 始终由你掌舵</p>
          <h3>安全，不是最后一步。</h3>
          <ul>
            <li>
              <span>01</span> 预算到顶，立即暂停
            </li>
            <li>
              <span>02</span> 需求修改，由你确认
            </li>
            <li>
              <span>03</span> 代码产出，不在本机运行
            </li>
            <li>
              <span>04</span> 安全方案，只做人工复核
            </li>
          </ul>
          <div className="guard-footnote">LOCAL FIRST · HUMAN IN CONTROL</div>
        </aside>
      </section>

      <section className="recent-section">
        <div className="section-title-row">
          <div>
            <p className="card-kicker">03 — 留下的工作痕迹</p>
            <h2>最近运行</h2>
          </div>
          <span className="result-count">{String(runs.length).padStart(2, "0")} 项</span>
        </div>
        {runs.length === 0 ? (
          <div className="empty-state">
            <span className="empty-mark">⌁</span>
            <span>第一段旅程，还在等你写下起点。</span>
          </div>
        ) : (
          <div className="recent-list">
            {runs.slice(0, 5).map((run, index) => (
              <button
                className="recent-row"
                key={run.id}
                onClick={() => onOpenRun(run.id)}
                type="button"
              >
                <span className="row-index">{String(index + 1).padStart(2, "0")}</span>
                <span className={`run-state state-${run.status.toLowerCase()}`} />
                <span className="recent-name">{run.user_input}</span>
                <span className="recent-meta">
                  {run.total_tokens.toLocaleString()} / {run.token_budget.toLocaleString()} tokens
                </span>
                <span className="row-arrow" aria-hidden="true">
                  ↗
                </span>
              </button>
            ))}
          </div>
        )}
      </section>
      <footer className="page-foot">
        <span>AGENT ELF · LOCAL WORKSPACE</span>
        <span>输出需复核 · 未执行代码 · 未应用部署配置</span>
      </footer>
    </div>
  );
}

interface KnowledgeViewProps {
  items: KnowledgeItem[];
  onChanged: () => void;
  onError: (message: string) => void;
}

function KnowledgeView({ items, onChanged, onError }: KnowledgeViewProps) {
  const [busy, setBusy] = useState(false);

  async function importFile(file?: File) {
    if (!file) return;
    setBusy(true);
    try {
      const filename = file.name.toLowerCase();
      const isDocument = filename.endsWith(".pdf") || filename.endsWith(".docx");
      const maxBytes = isDocument ? 20 * 1024 * 1024 : 1024 * 1024;
      if (file.size > maxBytes) {
        throw new Error(
          isDocument ? "PDF/DOCX 文档不能超过 20 MiB。" : "TXT/Markdown/CSV 文件不能超过 1 MiB。",
        );
      }
      if (isDocument) {
        await api.uploadKnowledge(file);
      } else {
        await api.addKnowledge(file.name, await file.text());
      }
      onChanged();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "导入失败。");
    } finally {
      setBusy(false);
    }
  }

  async function removeItem(item: KnowledgeItem) {
    try {
      await api.deleteKnowledge(item.id);
      onChanged();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "删除失败。");
    }
  }

  async function toggleItem(item: KnowledgeItem) {
    try {
      await api.toggleKnowledge(item.id, !item.enabled);
      onChanged();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "无法更新知识条目。");
    }
  }

  return (
    <section className="management-page">
      <PageIntro
        eyebrow="REFERENCE SHELF"
        title="知识库"
        description="为每次运行提供可控的本地参考。PDF 与 DOCX 只提取内嵌文本，不做 OCR；原始文档不会保存。"
      />
      <label className={`upload-tile ${busy ? "is-busy" : ""}`}>
        <input
          accept=".txt,.md,.csv,.pdf,.docx,text/plain,text/csv,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          disabled={busy}
          onChange={(event) => {
            void importFile(event.target.files?.[0]);
            event.currentTarget.value = "";
          }}
          type="file"
        />
        <span className="upload-symbol">＋</span>
        <span>
          <strong>{busy ? "正在导入…" : "选择一个本地文件"}</strong>
          <small>.txt · .md · .csv（1 MB） · .pdf · .docx（20 MiB）</small>
        </span>
        <span className="upload-arrow">↗</span>
      </label>
      <div className="library-list">
        <div className="library-head">
          <span>文件名</span>
          <span>类型</span>
          <span>状态</span>
          <span>导入时间</span>
          <span />
        </div>
        {items.length === 0 ? (
          <div className="library-empty">还没有添加本地参考材料。</div>
        ) : (
          items.map((item) => (
            <div className="library-row" key={item.id}>
              <span
                className="file-name"
                title={
                  item.source_metadata
                    ? `SHA-256: ${item.source_metadata.sha256}\n来源大小: ${item.source_metadata.source_size_bytes} bytes\n提取方式: ${item.source_metadata.extraction_method}`
                    : item.filename
                }
              >
                <span className="file-glyph">▤</span>
                <span className="file-name-copy">
                  <span>{item.filename}</span>
                  {item.source_metadata && (
                    <small>
                      {item.source_metadata.extraction_method} ·{" "}
                      {item.source_metadata.extracted_bytes.toLocaleString()} bytes
                    </small>
                  )}
                </span>
              </span>
              <span className="file-type">{item.file_type.toUpperCase()}</span>
              <span className="file-state">{item.enabled ? "已启用" : "已停用"}</span>
              <span className="file-date">{new Date(item.created_at).toLocaleDateString()}</span>
              <span className="file-actions">
                <button
                  className="text-button"
                  onClick={() => void toggleItem(item)}
                  type="button"
                >
                  {item.enabled ? "停用" : "启用"}
                </button>
                <button
                  aria-label={`删除 ${item.filename}`}
                  className="text-button"
                  onClick={() => void removeItem(item)}
                  type="button"
                >
                  移除
                </button>
              </span>
            </div>
          ))
        )}
      </div>
      <p className="quiet-note">
        参考内容会在启用模型时被注入上下文；使用外部模型前请确认其中没有不应外发的信息。
      </p>
    </section>
  );
}

interface SkillsViewProps {
  items: SkillItem[];
  onChanged: () => void;
  onError: (message: string) => void;
}

const stageChoices = [
  ["S1", "市场假设"],
  ["S2", "用户需求"],
  ["S3", "产品决策"],
  ["S4", "原型设计"],
  ["S5", "需求清单"],
  ["S6", "代码产物"],
  ["S7", "静态检查"],
  ["S8", "运维安全"],
] as const;

function SkillsView({ items, onChanged, onError }: SkillsViewProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [content, setContent] = useState("");
  const [stages, setStages] = useState<StageId[]>(["S4"]);
  const [busy, setBusy] = useState(false);

  async function addSkill(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    try {
      await api.addSkill(name, description, content, stages);
      setName("");
      setDescription("");
      setContent("");
      onChanged();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Skill 导入失败。");
    } finally {
      setBusy(false);
    }
  }

  async function toggle(item: SkillItem) {
    try {
      await api.toggleSkill(item.id, !item.enabled);
      onChanged();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "无法更新 Skill。");
    }
  }

  return (
    <section className="management-page">
      <PageIntro
        eyebrow="PROMPT LIBRARY"
        title="Skills"
        description="管理按阶段启用的纯文本提示词。脚本和可执行插件不属于 P0，导入后默认停用。"
      />
      <div className="skills-layout">
        <form className="skill-form" onSubmit={(event) => void addSkill(event)}>
          <p className="card-kicker">新增纯文本 Skill</p>
          <label>
            名称
            <input onChange={(event) => setName(event.target.value)} required value={name} />
          </label>
          <label>
            用途说明
            <input
              onChange={(event) => setDescription(event.target.value)}
              required
              value={description}
            />
          </label>
          <label>
            提示词内容
            <textarea
              onChange={(event) => setContent(event.target.value)}
              required
              rows={5}
              value={content}
            />
          </label>
          <fieldset>
            <legend>适用阶段</legend>
            <div className="stage-checkboxes">
              {stageChoices.map(([id, label]) => (
                <label key={id}>
                  <input
                    checked={stages.includes(id)}
                    onChange={(event) =>
                      setStages((current) =>
                        event.target.checked
                          ? [...current, id]
                          : current.filter((value) => value !== id),
                      )
                    }
                    type="checkbox"
                  />
                  {label}
                </label>
              ))}
            </div>
          </fieldset>
          <button className="primary-button" disabled={busy || stages.length === 0} type="submit">
            {busy ? "正在添加…" : "添加并保持停用"}
            <span aria-hidden="true">↗</span>
          </button>
        </form>
        <div className="skill-list">
          <div className="section-title-row compact">
            <div>
              <p className="card-kicker">已注册</p>
              <h2>{items.length.toString().padStart(2, "0")} 个 Skills</h2>
            </div>
          </div>
          {items.length === 0 ? (
            <div className="library-empty">已注册的 Skill 会出现在这里。</div>
          ) : (
            items.map((item) => (
              <article className="skill-card" key={item.id}>
                <div className="skill-card-top">
                  <span className={`skill-led ${item.enabled ? "on" : ""}`} />
                  <button
                    aria-pressed={Boolean(item.enabled)}
                    className={`switch ${item.enabled ? "is-on" : ""}`}
                    onClick={() => void toggle(item)}
                    type="button"
                  >
                    <span />
                  </button>
                </div>
                <h3>{item.name}</h3>
                <p>{item.description}</p>
                <div className="tag-row">
                  {item.stages.map((stage) => (
                    <span className="stage-tag" key={stage}>
                      {stage}
                    </span>
                  ))}
                  <span className="safe-tag">纯文本</span>
                </div>
              </article>
            ))
          )}
        </div>
      </div>
    </section>
  );
}

interface SettingsViewProps {
  settings: Settings | null;
}

function SettingsView({ settings }: SettingsViewProps) {
  return (
    <section className="management-page">
      <PageIntro
        eyebrow="LOCAL CONFIGURATION"
        title="设置"
        description="模型凭据只从服务端进程环境读取；本控制台不收集、不保存 API Key。"
      />
      <div className="settings-grid">
        <article className="settings-card">
          <p className="card-kicker">MODEL ADAPTER</p>
          <h2>{settings?.provider === "openai-compatible" ? "OpenAI-compatible" : "本地演示"}</h2>
          <dl>
            <div>
              <dt>当前模型</dt>
              <dd>{settings?.model ?? "读取中…"}</dd>
            </div>
            <div>
              <dt>凭据位置</dt>
              <dd>服务端环境变量，不写入数据库</dd>
            </div>
            <div>
              <dt>数据外发</dt>
              <dd>{settings?.provider === "demo" ? "无外部模型调用" : "每次运行前需确认"}</dd>
            </div>
          </dl>
          <p className="quiet-note">
            设置 AGENT_ELF_API_BASE、AGENT_ELF_API_KEY 与 AGENT_ELF_MODEL 后重启后端即可切换模型。
            请勿将密钥写入项目文件或提交到版本库。
          </p>
        </article>
        <article className="settings-card budget-settings">
          <p className="card-kicker">BUDGET & SAFETY</p>
          <h2>每次运行由你设定边界</h2>
          <ul>
            <li>每个 Run 必须填写 token 硬上限。</li>
            <li>到达上限后暂停；续跑必须明确增加上限。</li>
            <li>生成代码不会在本机执行。</li>
            <li>安全与运维产物不会自动应用或部署。</li>
          </ul>
          <div className="safety-seal">HUMAN REVIEW REQUIRED</div>
        </article>
      </div>
    </section>
  );
}

function PageIntro({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <header className="page-intro">
      <p className="card-kicker">{eyebrow}</p>
      <h1>{title}</h1>
      <p>{description}</p>
      <span className="intro-index">/ LOCAL</span>
    </header>
  );
}

export default App;
