import { useEffect, useRef, useState } from 'react';
import { PromptAssetPicker } from './PromptAssetPicker.jsx';

// Reused by production, Skill storyboards and prompt documents. Linking occurs
// only after confirmation; retries skip successful links from a partial failure.
export function usePromptAssetLibrary({ request, resolveUrl, productionId, skillProjectId, scopeKey = '', beforeLink, onLinked }) {
  const [picker, setPicker] = useState(null);
  const scope = `${productionId || ''}:${skillProjectId || ''}:${scopeKey}`;
  const current = useRef(scope);
  current.current = scope;
  useEffect(() => { current.current = scope; setPicker(null); return () => { current.current = null; }; }, [scope]);
  function open(insert, options = {}) { setPicker({ insert, options, scope }); }
  function close() {
    const cancel = picker?.options.onCancel;
    setPicker(null);
    // Wait for native dialog focus restoration to finish, then restore caret.
    setTimeout(() => cancel?.(), 0);
  }
  const dialog = picker && <PromptAssetPicker key={picker.scope} request={request} resolveUrl={resolveUrl}
    {...picker.options} initialQuery={picker.options.query || ''} onClose={close}
    onSelect={async (assets) => {
      const check = () => { if (current.current !== picker.scope) throw new Error('项目已切换，请在当前项目中重新引用。'); };
      check();
      if (await beforeLink?.() === false) throw new Error('提示词尚未保存，请保存后重新引用。');
      check();
      let skillFacts;
      if (productionId) {
        const [detail, references] = await Promise.all([
          request(`/productions/${productionId}`), request(`/productions/${productionId}/references`),
        ]);
        check();
        let revision = detail.project.current_revision_id;
        const linked = new Set((Array.isArray(references) ? references : references.items || []).map((item) => (item.asset || item).id));
        for (const asset of assets) {
          check();
          if (linked.has(asset.id)) continue;
          const result = await request(`/productions/${productionId}/assets/${asset.id}/link`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ expected_revision_id: revision }),
          });
          revision = result.current_revision_id;
          linked.add(asset.id);
        }
      }
      if (skillProjectId) {
        for (const asset of assets) {
          check();
          skillFacts = await request(`/projects/${skillProjectId}/prompt-assets/${asset.id}`, { method: 'POST' });
        }
      }
      check();
      await onLinked?.(assets, skillFacts, check);
      check();
      picker.insert(assets);
      setPicker(null);
    }} />;
  return { open, dialog };
}
