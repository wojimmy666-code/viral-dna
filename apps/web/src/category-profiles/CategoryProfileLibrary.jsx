import {
  ArrowCounterClockwise,
  CircleNotch,
  MagnifyingGlass,
  Plus,
  Tag,
  Trash,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  InlineMessage,
  PageHeader,
  PageShell,
  StatusBadge,
  SurfacePanel,
} from "../ui/system/SystemPrimitives.jsx";
import {
  categoryProfileValidationMessage,
  draftToPayload,
  EMPTY_CATEGORY_PROFILE,
  profileSearchText,
  profileToDraft,
} from "./category-profile-ui.js";
import "./category-profiles.css";

function Field({ children, hint, label, required = false }) {
  return (
    <label className="category-field">
      <span>{label}{required && <em>必填</em>}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}

export function CategoryProfileLibrary({ onNotice, request }) {
  const [profiles, setProfiles] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [draft, setDraft] = useState({ ...EMPTY_CATEGORY_PROFILE });
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [deletePending, setDeletePending] = useState(false);
  const [lastDeleted, setLastDeleted] = useState(null);

  const load = useCallback(async (preferredId = "") => {
    setLoading(true);
    setError("");
    try {
      const payload = await request("/me/category-profiles");
      const items = payload?.items || [];
      setProfiles(items);
      const nextId = items.some((item) => item.id === preferredId)
        ? preferredId
        : items[0]?.id || "";
      setSelectedId(nextId);
      setDraft(profileToDraft(items.find((item) => item.id === nextId)));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }, [request]);

  useEffect(() => { load(); }, [load]);

  const filteredProfiles = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return needle
      ? profiles.filter((profile) => profileSearchText(profile).includes(needle))
      : profiles;
  }, [profiles, query]);

  function selectProfile(profile) {
    setSelectedId(profile.id);
    setDraft(profileToDraft(profile));
    setDeletePending(false);
    setError("");
  }

  function createProfile() {
    setSelectedId("");
    setDraft({ ...EMPTY_CATEGORY_PROFILE });
    setDeletePending(false);
    setError("");
  }

  function updateDraft(field, value) {
    setDraft((current) => ({ ...current, [field]: value }));
  }

  async function saveProfile(event) {
    event.preventDefault();
    const payload = draftToPayload(draft);
    const validationMessage = categoryProfileValidationMessage(payload);
    if (validationMessage) {
      setError(validationMessage);
      return;
    }
    setSaving(true);
    setError("");
    try {
      const saved = await request(
        selectedId ? `/me/category-profiles/${selectedId}` : "/me/category-profiles",
        {
          method: selectedId ? "PUT" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(selectedId ? { ...payload, revision: draft.revision } : payload),
        },
      );
      await load(saved.id);
      onNotice?.({ type: "success", message: selectedId ? "品类档案已保存" : "品类档案已创建" });
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  async function deleteProfile() {
    if (!selectedId || !draft.revision) return;
    setSaving(true);
    setError("");
    try {
      const deleted = await request(`/me/category-profiles/${selectedId}`, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revision: draft.revision }),
      });
      setLastDeleted(deleted);
      setDeletePending(false);
      await load();
      onNotice?.({ type: "success", message: "品类档案已删除，历史方案不受影响" });
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  async function restoreProfile() {
    if (!lastDeleted) return;
    setSaving(true);
    setError("");
    try {
      const restored = await request(`/me/category-profiles/${lastDeleted.id}/restore`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revision: lastDeleted.revision }),
      });
      setLastDeleted(null);
      await load(restored.id);
      onNotice?.({ type: "success", message: "品类档案已恢复" });
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <PageShell className="category-profile-page">
      <PageHeader
        title="品类库"
        description="为当前账户沉淀品牌、受众和卖点约束。生成方案时只需选择一个档案，历史方案会保留当时的完整快照。"
        actions={(
          <button className="primary-button" onClick={createProfile} type="button">
            <Plus size={18} weight="bold" />新建品类档案
          </button>
        )}
      />

      {lastDeleted && (
        <InlineMessage className="category-undo-message" tone="success">
          <span>“{lastDeleted.display_name}”已删除，历史方案仍可查看。</span>
          <button className="text-button compact" disabled={saving} onClick={restoreProfile} type="button">
            <ArrowCounterClockwise size={16} />撤销删除
          </button>
        </InlineMessage>
      )}
      {error && <InlineMessage tone="danger">{error}</InlineMessage>}

      <SurfacePanel className="category-profile-workspace">
        <aside className="category-profile-master">
          <div className="category-profile-search">
            <MagnifyingGlass size={17} />
            <input
              aria-label="搜索品类档案"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索品类、品牌或卖点"
              type="search"
              value={query}
            />
          </div>
          <div className="category-profile-list" aria-label="品类档案列表">
            {loading ? (
              <div className="category-profile-state"><CircleNotch className="spin" size={20} />正在读取品类库…</div>
            ) : filteredProfiles.length ? filteredProfiles.map((profile) => (
              <button
                aria-current={selectedId === profile.id ? "true" : undefined}
                className={selectedId === profile.id ? "active" : ""}
                key={profile.id}
                onClick={() => selectProfile(profile)}
                type="button"
              >
                <span className="category-profile-list-icon"><Tag size={17} /></span>
                <span>
                  <strong>{profile.display_name}</strong>
                  <small>{[profile.brand_name, profile.category_name].filter(Boolean).join(" · ")}</small>
                  <em>{profile.brief}</em>
                </span>
                {profile.usage_count > 0 && <StatusBadge>{profile.usage_count} 次</StatusBadge>}
              </button>
            )) : (
              <div className="category-profile-state">
                <strong>{profiles.length ? "没有匹配的档案" : "还没有品类档案"}</strong>
                <span>{profiles.length ? "换个关键词继续搜索。" : "建立一次，之后生成方案直接选择。"}</span>
              </div>
            )}
          </div>
        </aside>

        <form className="category-profile-editor" onSubmit={saveProfile}>
          <header>
            <div>
              <h2>{selectedId ? "编辑品类档案" : "新建品类档案"}</h2>
              <p>这些信息会约束三套方案的创意方向、逐镜头表达和禁用内容。</p>
            </div>
            {selectedId && <StatusBadge tone="success">修订 {draft.revision}</StatusBadge>}
          </header>

          <div className="category-form-grid">
            <Field label="档案名称" required>
              <input autoFocus={!selectedId} maxLength={80} onChange={(event) => updateDraft("display_name", event.target.value)} placeholder="例如：春季通勤女装" value={draft.display_name} />
            </Field>
            <Field label="所属品类" required>
              <input maxLength={80} onChange={(event) => updateDraft("category_name", event.target.value)} placeholder="例如：女装" value={draft.category_name} />
            </Field>
            <Field label="品牌（可选）">
              <input maxLength={120} onChange={(event) => updateDraft("brand_name", event.target.value)} placeholder="例如：森屿" value={draft.brand_name} />
            </Field>
            <Field label="一句话定位" required>
              <input maxLength={240} onChange={(event) => updateDraft("brief", event.target.value)} placeholder="为通勤女性提供利落、易搭配的轻职场女装" value={draft.brief} />
            </Field>
            <Field hint="用顿号或逗号分隔" label="目标人群" required>
              <input onChange={(event) => updateDraft("audiences", event.target.value)} placeholder="25–35 岁通勤女性、轻熟风用户" value={draft.audiences} />
            </Field>
            <Field hint="每行一项，生成时会优先围绕前几项展开" label="核心卖点" required>
              <textarea onChange={(event) => updateDraft("selling_points", event.target.value)} placeholder={"显瘦但不紧绷\n一衣多穿\n面料抗皱"} rows={4} value={draft.selling_points} />
            </Field>
            <Field hint="用顿号或逗号分隔" label="常用场景">
              <input onChange={(event) => updateDraft("scenes", event.target.value)} placeholder="上班通勤、客户会议、周末约会" value={draft.scenes} />
            </Field>
            <Field label="视觉风格">
              <textarea maxLength={500} onChange={(event) => updateDraft("visual_style", event.target.value)} placeholder="克制的都市感，自然光，中性低饱和色，真实面料质感" rows={3} value={draft.visual_style} />
            </Field>
            <Field hint="每行一项，写入生成约束" label="禁用表述">
              <textarea onChange={(event) => updateDraft("forbidden_claims", event.target.value)} placeholder={"绝对显瘦\n全网最低价\n夸大功效"} rows={3} value={draft.forbidden_claims} />
            </Field>
          </div>

          {deletePending && (
            <InlineMessage className="category-delete-confirm" tone="danger">
              <span>删除后不再出现在选择器中，但历史方案仍保留此档案快照。</span>
              <span>
                <button className="secondary-button compact" onClick={() => setDeletePending(false)} type="button">取消</button>
                <button className="danger-button compact" disabled={saving} onClick={deleteProfile} type="button">确认删除</button>
              </span>
            </InlineMessage>
          )}

          <footer>
            {selectedId && !deletePending ? (
              <button className="secondary-button category-delete-trigger" onClick={() => setDeletePending(true)} type="button">
                <Trash size={17} />删除档案
              </button>
            ) : <span />}
            <button className="primary-button" disabled={saving} type="submit">
              {saving && <CircleNotch className="spin" size={18} />}
              {selectedId ? "保存修改" : "创建档案"}
            </button>
          </footer>
        </form>
      </SurfacePanel>
    </PageShell>
  );
}
