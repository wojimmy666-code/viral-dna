import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle,
  CircleNotch,
  Code,
  Package,
  Prohibit,
  SealCheck,
  UploadSimple,
  WarningCircle,
} from "@phosphor-icons/react";

const STATUS_LABELS = {
  draft: "草稿",
  published: "已发布",
  deprecated: "已停用",
  blocked: "已封禁",
};

function formatDuration(value) {
  const milliseconds = Math.max(0, Number(value) || 0);
  if (milliseconds < 1000) return `${milliseconds} ms`;
  if (milliseconds < 60_000) return `${(milliseconds / 1000).toFixed(1)} 秒`;
  return `${(milliseconds / 60_000).toFixed(1)} 分`;
}

function formatCost(value) {
  return `¥${((Number(value) || 0) / 1_000_000).toFixed(2)}`;
}

export function PlatformSkillAdmin({ request }) {
  const [catalog, setCatalog] = useState({ skills: [], versions: [] });
  const [operations, setOperations] = useState({ total_runs: 0, succeeded_runs: 0, failed_runs: 0, blocked_runs: 0, items: [] });
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [validation, setValidation] = useState(null);
  const [packageFile, setPackageFile] = useState(null);
  const [changelog, setChangelog] = useState("");
  const [editor, setEditor] = useState(null);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [nextCatalog, nextOperations] = await Promise.all([
        request("/admin/skills"),
        request("/admin/skill-operations"),
      ]);
      setCatalog(nextCatalog);
      setOperations(nextOperations);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [request]); // eslint-disable-line react-hooks/exhaustive-deps

  const groups = useMemo(() => catalog.skills.map((skill) => ({
    skill,
    versions: catalog.versions
      .filter((version) => version.skill_id === skill.id)
      .sort((left, right) => right.revision_number - left.revision_number),
  })), [catalog]);

  async function importPackage(event) {
    event.preventDefault();
    if (!packageFile) return;
    setBusyId("import");
    setError("");
    try {
      const body = new FormData();
      body.append("package", packageFile);
      const query = changelog.trim() ? `?changelog=${encodeURIComponent(changelog.trim())}` : "";
      const version = await request(`/admin/skill-versions/import${query}`, { method: "POST", body });
      setPackageFile(null);
      setChangelog("");
      setValidation({ valid: true, message: `${version.manifest.metadata.name} ${version.version} 已导入为草稿` });
      await load();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusyId("");
    }
  }

  async function runAction(version, action) {
    setBusyId(version.id);
    setError("");
    try {
      const result = await request(`/admin/skill-versions/${version.id}/${action}`, { method: "POST" });
      if (action === "validate") {
        setValidation({ ...result, message: result.valid ? "清单与资源校验通过" : result.issues.join("；") });
      } else {
        setValidation({ valid: true, message: `${version.manifest.metadata.name} 已${({ publish: "发布", deprecate: "停用", block: "封禁" })[action]}` });
        await load();
      }
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusyId("");
    }
  }

  async function saveManifest(event) {
    event.preventDefault();
    setBusyId(editor?.version?.id || "new");
    setError("");
    try {
      const manifest = JSON.parse(editor.text);
      const payload = { manifest, changelog: editor.changelog || "" };
      const path = editor.version
        ? `/admin/skill-versions/${editor.version.id}`
        : "/admin/skill-versions";
      await request(path, {
        method: editor.version ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setEditor(null);
      setValidation({ valid: true, message: "Skill 草稿已保存" });
      await load();
    } catch (requestError) {
      setError(requestError instanceof SyntaxError ? "Manifest JSON 格式无效" : requestError.message);
    } finally {
      setBusyId("");
    }
  }

  return (
    <section className="admin-settings-section platform-skill-admin">
      <header>
        <div><h2>平台 Skill 目录</h2><p>目录属于平台；已发布版本不可修改，项目创建时会冻结版本快照。</p></div>
        <button className="secondary-button compact" onClick={() => setEditor({ version: null, text: "", changelog: "" })} type="button"><Code size={16} />新建清单</button>
      </header>

      <form className="platform-skill-import" onSubmit={importPackage}>
        <label><span>导入 Skill 包</span><input accept=".zip,application/zip" onChange={(event) => setPackageFile(event.target.files?.[0] || null)} type="file" /></label>
        <label><span>版本说明</span><input onChange={(event) => setChangelog(event.target.value)} placeholder="本次版本的变化" value={changelog} /></label>
        <button className="primary-button compact" disabled={!packageFile || busyId === "import"} type="submit">{busyId === "import" ? <CircleNotch className="spin" size={16} /> : <UploadSimple size={16} />}导入并校验</button>
      </form>

      {error && <div className="admin-settings-error" role="alert"><WarningCircle size={17} />{error}</div>}
      {validation && <div className={`platform-skill-validation ${validation.valid ? "is-valid" : "is-invalid"}`}>{validation.valid ? <CheckCircle size={17} weight="fill" /> : <WarningCircle size={17} />}<span>{validation.message}</span></div>}

      {!loading && <section className="platform-skill-operations" aria-labelledby="skill-operations-title">
        <div className="platform-skill-operations-heading"><div><h3 id="skill-operations-title">运行概览</h3><p>按已冻结的 Skill 版本汇总运行、退回、耗时与实际成本。</p></div><div className="platform-skill-operations-totals"><span><strong>{operations.total_runs}</strong>运行</span><span><strong>{operations.succeeded_runs}</strong>完成</span><span><strong>{operations.blocked_runs + operations.failed_runs}</strong>异常</span></div></div>
        <div className="platform-skill-operations-table" role="table">
          <div className="is-heading" role="row"><span>Skill</span><span>运行 / 完成</span><span>退回</span><span>平均耗时</span><span>平均成本</span></div>
          {operations.items.length ? operations.items.map((item) => <div key={item.skill_id} role="row"><span><strong>{item.skill_name}</strong><small>{item.skill_id}</small></span><span>{item.run_count} / {item.succeeded_count}</span><span>{item.revision_request_count}</span><span>{formatDuration(item.average_total_ms)}</span><span>{formatCost(item.average_actual_cost_micros)}</span></div>) : <p className="platform-skill-operations-empty">尚无 Skill 运行数据</p>}
        </div>
      </section>}

      {loading ? <div className="platform-skill-loading"><CircleNotch className="spin" size={20} />正在读取平台目录</div> : (
        <div className="platform-skill-groups">
          {groups.map(({ skill, versions }) => (
            <article key={skill.id}>
              <div className="platform-skill-group-heading">
                <div><strong>{skill.name}</strong><span>{skill.category} · {skill.id}</span></div>
                <span className={`platform-skill-status is-${skill.lifecycle}`}>{STATUS_LABELS[skill.lifecycle]}</span>
              </div>
              <div className="platform-skill-version-list">
                {versions.map((version) => (
                  <div key={version.id}>
                    <Package size={18} />
                    <span><strong>v{version.version}</strong><small>Revision {version.revision_number} · {version.content_digest.slice(0, 20)}…</small></span>
                    <span className={`platform-skill-status is-${version.status}`}>{STATUS_LABELS[version.status]}</span>
                    <div className="platform-skill-version-actions">
                      {version.status === "draft" && <>
                        <button disabled={busyId === version.id} onClick={() => setEditor({ version, text: JSON.stringify(version.manifest, null, 2), changelog: version.changelog || "" })} type="button"><Code size={15} />编辑</button>
                        <button disabled={busyId === version.id} onClick={() => runAction(version, "validate")} type="button"><ShieldCheckIcon />校验</button>
                        <button disabled={busyId === version.id} onClick={() => runAction(version, "publish")} type="button"><SealCheck size={15} />发布</button>
                      </>}
                      {version.status === "published" && <button disabled={busyId === version.id} onClick={() => runAction(version, "deprecate")} type="button">停用</button>}
                      {version.status !== "blocked" && <button className="danger" disabled={busyId === version.id} onClick={() => runAction(version, "block")} type="button"><Prohibit size={15} />封禁</button>}
                    </div>
                  </div>
                ))}
              </div>
            </article>
          ))}
        </div>
      )}

      {editor && (
        <div className="platform-skill-editor-backdrop">
          <form className="platform-skill-editor" onSubmit={saveManifest}>
            <header><div><h2>{editor.version ? `编辑 ${editor.version.manifest.metadata.name}` : "新建 Skill 清单"}</h2><p>只接受 ViralDNA VideoSkill v1；禁止脚本、命令、密钥与回调地址。</p></div><button onClick={() => setEditor(null)} type="button">关闭</button></header>
            <label><span>Manifest JSON</span><textarea onChange={(event) => setEditor((current) => ({ ...current, text: event.target.value }))} placeholder="粘贴 viraldna.video-skill/v1 清单" spellCheck="false" value={editor.text} /></label>
            <label><span>版本说明</span><input onChange={(event) => setEditor((current) => ({ ...current, changelog: event.target.value }))} value={editor.changelog} /></label>
            <footer><button className="secondary-button" onClick={() => setEditor(null)} type="button">取消</button><button className="primary-button" disabled={!editor.text.trim() || Boolean(busyId)} type="submit">保存草稿</button></footer>
          </form>
        </div>
      )}
    </section>
  );
}

function ShieldCheckIcon() {
  return <CheckCircle size={15} />;
}
