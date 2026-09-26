import React, { useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import '../../src/styles.css';
import '../../src/production-workflow.css';
import '../../src/asset-library.css';
import '../../src/accounts/accounts.css';
import '../../src/visual-styles/visual-style.css';
import '../../src/prompt-references/asset-reference-editor.css';
import { Button } from '../../src/ui/system/Button.jsx';
import { Dialog } from '../../src/ui/system/Dialog.jsx';
import { useActionDialog } from '../../src/ui/system/useActionDialog.jsx';
import { MediaLightbox } from '../../src/MediaLightbox.jsx';
import { AnchoredPopover } from '../../src/video-generation-controls/AnchoredPopover.jsx';
import { SessionReauthentication } from '../../src/accounts/SessionReauthentication.jsx';
import { AddToAssetsDialog } from '../../src/generated-assets/AddToAssetsDialog.jsx';
import '../../src/generated-assets/generated-assets.css';

// Isolated UI fixture. Requests below touch memory only; never a user project,
// login API, provider or paid generation endpoint. Do not import into the app.
function Showcase() {
  const [calls, setCalls] = useState(0), [last, setLast] = useState('尚未提交');
  const [mode, setMode] = useState('success'), [large, setLarge] = useState(false);
  const [preview, setPreview] = useState(false), [popover, setPopover] = useState(false);
  const [reauth, setReauth] = useState(false), [asset, setAsset] = useState(false);
  const [scope, setScope] = useState('current');
  const anchor = useRef(null), action = useActionDialog({ scopeKey: scope });
  async function write(value) {
    setCalls(n => n + 1);
    await new Promise(resolve => setTimeout(resolve, mode === 'slow' ? 3000 : 500));
    if (mode === 'failure') throw Object.assign(new Error('名称重复，请修改名称后重试。'), { status: 409 });
    if (mode === 'unknown') throw new TypeError('模拟网络中断');
    setLast(value || '已受理'); return { id: 'fixture-task' };
  }
  function open(kind, variant) {
    const options = kind === 'input' ? { kind, title: '重命名项目', label: '项目名称', initialValue: '旅行 Vlog', maxLength: 120, confirmLabel: '保存名称' }
      : kind === 'generation' ? { kind, title: '确认生成图片', details: [['生成对象', '分镜 1 · 画面 1'], ['候选数量', '1 张'], ['模型', 'image-2 · 本机工具'], ['尺寸', '1536 × 864']], warning: '本机工具无法提供可验证的费用信息。本次生成不代表免费，请核对本机工具或服务商账单。', confirmLabel: '生成 1 张' }
      : { title: '永久删除项目', description: '将永久删除所选 2 个项目。', warning: '项目记录与生成结果无法从回收站恢复；独立资产库素材不会删除。', variant, confirmLabel: '永久删除 2 个项目' };
    action.open({ ...options, onConfirm: ({ value, mutate }) => mutate(() => write(value)) });
  }
  const previewImage = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="225"><rect width="400" height="225" fill="#eeecff"/><text x="125" y="120" font-size="22" fill="#5b4df5">资产预览</text></svg>');
  const target = { name: '分镜 1 生成图片', assetType: 'scene', previewUrl: previewImage, request: async (url) => {
    if (url === '/context') return { active_workspace: { id: 'fixture' }, account: { id: 'fixture' } };
    if (url.endsWith('/asset-folders')) return [{ id: 'folder', name: '旅行素材' }];
    throw Object.assign(new Error('隔离页面不进行真实入库'), { status: 409 });
  } };
  return <main style={{ padding: 24, maxWidth: 1100, margin: 'auto', minHeight: 1200 }}>
    <h1>弹窗统一 · 隔离验收</h1>
    <p>只使用模拟请求，不调用模型，不操作项目数据。</p>
    <label>请求结果 <select value={mode} onChange={e => setMode(e.target.value)}><option value="success">成功</option><option value="failure">明确失败</option><option value="unknown">结果未知</option><option value="slow">慢速受理</option></select></label>
    <p role="status">请求次数：{calls}；最近结果：{last}</p>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
      <Button onClick={() => open('generation')}>图片费用确认</Button>
      <Button onClick={() => open('input')}>项目改名</Button>
      <Button onClick={() => open('confirm', 'danger')}>永久删除确认</Button>
      <Button onClick={() => setLarge(true)}>资产选择外壳</Button>
      <Button onClick={() => setAsset(true)}>素材入库表单</Button>
      <Button onClick={() => setReauth(true)}>会话恢复外壳</Button>
      <Button onClick={() => { open('generation'); setTimeout(() => setScope('changed'), 500); }}>模拟目标切换</Button>
    </div>
    {action.element}
    {large && <Dialog title="引用资产" size="wide" onClose={() => setLarge(false)} footer={<><span>已选择 1 项 / 上限 4 项</span><Button onClick={() => setLarge(false)}>取消</Button><Button variant="primary" onClick={() => setLarge(false)}>确认引用</Button></>}>
      <div className="ui-dialog-body" style={{ minHeight: 280 }}>
        <p>本账户资产库 / 旅行素材</p>
        <Button ref={anchor} onClick={() => setPopover(!popover)}>打开用途菜单</Button>
        <AnchoredPopover anchorRef={anchor} open={popover} onClose={() => setPopover(false)} labelledBy="purpose-title"><div style={{ padding: 24, background: 'white' }}><h3 id="purpose-title">引用用途</h3><Button onClick={() => setPopover(false)}>空间参考</Button></div></AnchoredPopover>
        <Button onClick={() => setPreview(true)}>放大查看资产</Button>
        <p>中文名称超长时应自然换行：旅行中的人物与空间关系参考，保留人物大小与镜头距离。</p>
        {preview && <MediaLightbox activeId="image" items={[{ id: 'image', src: previewImage, title: '本地验收预览' }]} onClose={() => setPreview(false)} />}
      </div>
    </Dialog>}
    {asset && <AddToAssetsDialog target={target} onClose={() => setAsset(false)} onAdded={() => setAsset(false)} />}
    {reauth && <SessionReauthentication session={{ username: '13800000000', user_id: 'fixture' }} onClose={() => setReauth(false)} onDone={() => setReauth(false)} />}
  </main>;
}
createRoot(document.getElementById('root')).render(<Showcase />);
