import { useEffect, useId, useRef, useState } from 'react';
import { accountSessionPaused, currentAccountSession, projectEditing, sameAccountSession } from '../../accounts/account-client.js';
import { Button } from './Button.jsx';
import { Dialog } from './Dialog.jsx';
import { InlineMessage } from './SystemPrimitives.jsx';
import { createDialogController } from './dialog-state.js';

function captureAuthority() {
  const user = currentAccountSession(), admin = currentAccountSession(true), editing = projectEditing();
  return { user, admin,
    editing: editing ? { token: editing.token, projectId: editing.projectId } : null };
}
function checkAuthority(previous) {
  const current = captureAuthority();
  return sameAccountSession(previous.user, current.user) && sameAccountSession(previous.admin, current.admin)
    && (!previous.user || !accountSessionPaused()) && (!previous.admin || !accountSessionPaused(true))
    && previous.editing?.token === current.editing?.token && previous.editing?.projectId === current.editing?.projectId;
}

function ActionDialog({ decision, controller }) {
  const [value, setValue] = useState(decision.initialValue || '');
  const [validation, setValidation] = useState('');
  const [discarding, setDiscarding] = useState(false);
  const id = useId();
  const input = decision.kind === 'input';
  const generation = decision.kind === 'generation';
  const dirty = input && value !== (decision.initialValue || '');
  function close() {
    if (decision.busy) return;
    if (dirty) setDiscarding(true); else controller.cancel();
  }
  function submit(event) {
    event.preventDefault();
    if (decision.busy || decision.uncertain) return;
    const next = value.trim();
    const issue = input && (!next ? `请填写${decision.label || '内容'}` : decision.validate?.(next));
    if (issue) { setValidation(issue); return; }
    setValidation(''); void controller.submit(next);
  }
  return <Dialog title={decision.title} size={input ? 'input' : generation ? 'generation' : 'confirm'}
    busy={decision.busy} onClose={close} initialFocus={input ? 'first' : 'cancel'}>
    {discarding ? <div className="ui-dialog-body">
      <p>尚有未提交的修改，是否舍弃？</p>
      <footer className="ui-dialog-footer"><Button onClick={() => setDiscarding(false)}>继续编辑</Button><Button variant="warning" onClick={() => controller.cancel()}>舍弃修改</Button></footer>
    </div> : <form className="ui-dialog-form" onSubmit={submit}>
      <div className="ui-dialog-body">
        {decision.description && <p className="ui-dialog-description">{decision.description}</p>}
        {decision.details?.length > 0 && <dl className="ui-dialog-facts">{decision.details.map(([label, content]) => <div key={label}><dt>{label}</dt><dd>{content || '—'}</dd></div>)}</dl>}
        {decision.warning && <InlineMessage tone="warning"><strong>{generation ? '费用暂不可估算' : '请确认操作影响'}</strong><p>{decision.warning}</p></InlineMessage>}
        {input && <label className="ui-dialog-field" htmlFor={`${id}-input`}><span>{decision.label}</span>
          {decision.multiline ? <textarea id={`${id}-input`} autoFocus rows={3} maxLength={decision.maxLength} disabled={decision.busy} value={value} onChange={event => { setValue(event.target.value); setValidation(''); }} aria-invalid={Boolean(validation)} aria-describedby={validation ? `${id}-validation` : undefined} />
            : <input id={`${id}-input`} autoFocus maxLength={decision.maxLength} disabled={decision.busy} value={value} onChange={event => { setValue(event.target.value); setValidation(''); }} aria-invalid={Boolean(validation)} aria-describedby={validation ? `${id}-validation` : undefined} />}
          {validation && <span id={`${id}-validation`} className="ui-dialog-validation" role="alert">{validation}</span>}
        </label>}
        {decision.error && <InlineMessage tone="danger">{decision.error}</InlineMessage>}
        {decision.uncertain && <InlineMessage tone="warning">请求结果尚未确认。请关闭窗口并核对任务或列表，勿再次提交同一操作。</InlineMessage>}
      </div>
      <footer className="ui-dialog-footer"><Button data-dialog-cancel disabled={decision.busy} onClick={close}>取消</Button>
        <Button variant={decision.variant || 'primary'} type="submit" loading={decision.busy} loadingLabel={decision.loadingLabel || '正在提交…'} disabled={decision.uncertain}>{decision.confirmLabel}</Button>
      </footer>
    </form>}
  </Dialog>;
}

/** Controlled decision + async action. Scope guards target identity; inputKey
 * guards the reviewed parameters before submission. onConfirm receives mutate
 * for the final write and assertCurrent for guards after draft preparation.
 */
export function useActionDialog({ scopeKey = '', inputKey = '' } = {}) {
  const latest = useRef(null);
  latest.current = { scopeKey, inputKey };
  const [decision, setDecision] = useState(null);
  const controller = useRef(null);
  if (!controller.current) controller.current = createDialogController({
    getScope: () => latest.current.scopeKey, getInput: () => latest.current.inputKey,
    captureAuthority, checkAuthority, notify: setDecision,
  });
  useEffect(() => { controller.current.activate(); return () => controller.current.dispose(); }, []);
  return { open: options => controller.current.open(options),
    element: decision ? <ActionDialog decision={decision} controller={controller.current} /> : null };
}
