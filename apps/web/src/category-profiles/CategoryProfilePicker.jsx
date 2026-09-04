import {
  CaretDown,
  Check,
  CircleNotch,
  MagnifyingGlass,
  Plus,
  Tag,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { profileSearchText } from "./category-profile-ui.js";
import "./category-profiles.css";

export function CategoryProfilePicker({ onChange, onManage, request, value }) {
  const [profiles, setProfiles] = useState([]);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const payload = await request("/me/category-profiles");
      const items = payload?.items || [];
      setProfiles(items);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }, [request]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (loading || !value || profiles.some((item) => item.id === value)) return;
    onChange("");
    setOpen(false);
    setQuery("");
  }, [loading, onChange, profiles, value]);

  const selected = profiles.find((profile) => profile.id === value) || null;
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return needle
      ? profiles.filter((profile) => profileSearchText(profile).includes(needle))
      : profiles;
  }, [profiles, query]);

  function choose(profile) {
    onChange(profile.id, profile);
    setOpen(false);
    setQuery("");
  }

  return (
    <section className="category-profile-picker" aria-label="本次生成使用的品类档案">
      {loading ? (
        <div className="category-picker-state"><CircleNotch className="spin" size={19} />正在读取品类库…</div>
      ) : error ? (
        <div className="category-picker-state error"><WarningCircle size={19} />{error}<button className="text-button compact" onClick={load} type="button">重试</button></div>
      ) : profiles.length === 0 ? (
        <div className="category-picker-empty">
          <span><Tag size={20} /><span><strong>还没有可用的品类档案</strong><small>先建立品牌与品类约束，再开始创作。</small></span></span>
          <button className="primary-button" onClick={onManage} type="button"><Plus size={17} />新建品类档案</button>
        </div>
      ) : (
        <>
          <div className="category-picker-control">
            <button
              aria-expanded={open}
              aria-haspopup="listbox"
              className="category-picker-trigger"
              onClick={() => setOpen((current) => !current)}
              type="button"
            >
              <span className="category-picker-icon"><Tag size={18} /></span>
              <span>
                <strong>{selected?.display_name || "选择本次使用的品类档案"}</strong>
                {selected && <small>{[selected.brand_name, selected.category_name].filter(Boolean).join(" · ")}</small>}
              </span>
              <CaretDown size={17} />
            </button>
            <button className="text-button compact" onClick={onManage} type="button">管理品类库</button>
          </div>
          {open && (
            <div className="category-picker-options">
              <label>
                <MagnifyingGlass size={17} />
                <input autoFocus onChange={(event) => setQuery(event.target.value)} placeholder="搜索品类、品牌或卖点" type="search" value={query} />
              </label>
              <div role="listbox" aria-label="选择品类档案">
                {filtered.map((profile) => (
                  <button
                    aria-selected={profile.id === value}
                    key={profile.id}
                    onClick={() => choose(profile)}
                    role="option"
                    type="button"
                  >
                    <span><strong>{profile.display_name}</strong><small>{[profile.brand_name, profile.category_name].filter(Boolean).join(" · ")}</small></span>
                    <em>{profile.brief}</em>
                    {profile.id === value && <Check size={17} weight="bold" />}
                  </button>
                ))}
                {!filtered.length && <p>没有匹配的品类档案</p>}
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
