// An interactive illustration of how a delivery link behaves, including what view-only can and can't do.
// Everything is local component state. Nothing is saved, sent or checked.
import { useEffect, useId, useRef, useState } from 'react';
import { Download, Eye, File, Link2, Lock, TriangleAlert } from 'lucide-react';

type Access = 'download' | 'view_only';
type Phase = 'none' | 'active' | 'revoked';

const FIRST_LOG = 'you uploaded brand-film-master.mov (3.8 GB, SHA-256 recorded)';

export function DeliveryDemo() {
  const [phase, setPhase] = useState<Phase>('none');
  const [access, setAccess] = useState<Access>('download');
  const [log, setLog] = useState<string[]>([FIRST_LOG]);
  const touched = useRef(false);
  const groupId = useId();

  const add = (line: string) => setLog((l) => [...l.slice(-5), line]);
  const label = (a: Access) => (a === 'download' ? 'view and download' : 'view only');

  const create = () => {
    touched.current = true;
    setPhase('active');
    add(`you created a ${label(access)} link`);
  };
  const revoke = () => { touched.current = true; setPhase('revoked'); add('you revoked the link'); };
  const again = () => { touched.current = true; setPhase('none'); };
  const reset = () => { touched.current = true; setPhase('none'); setAccess('download'); setLog([FIRST_LOG]); };

  // One automatic run so the idea lands in a couple of seconds. Skipped for reduced motion, cancelled by any click.
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const t = setTimeout(() => {
      if (!touched.current) {
        setPhase('active');
        setLog((l) => [...l, 'you created a view and download link']);
      }
    }, 2200);
    return () => clearTimeout(t);
  }, []);

  const chip =
    phase === 'none' ? 'Not shared yet' : phase === 'revoked' ? 'Link revoked' : `Link active · ${label(access)}`;

  return (
    <div className="demo">
      <div className="demo-head">
        <span>Brand film · final delivery</span>
        <span className="chip">
          <Lock size={14} aria-hidden="true" /> {chip}
        </span>
      </div>

      <div className="demo-pane">
        <p className="demo-label">What you do</p>
        <ul className="demo-files" aria-label="Uploaded file">
          <li><File size={15} aria-hidden="true" /> brand-film-master.mov <span>3.8 GB · stored as uploaded</span></li>
        </ul>
        <fieldset className="seg" disabled={phase === 'active'}>
          <legend className="demo-label">Link access</legend>
          <label htmlFor={`${groupId}-d`}>
            <input id={`${groupId}-d`} type="radio" name={groupId} checked={access === 'download'} onChange={() => setAccess('download')} />
            View and download
          </label>
          <label htmlFor={`${groupId}-v`}>
            <input id={`${groupId}-v`} type="radio" name={groupId} checked={access === 'view_only'} onChange={() => setAccess('view_only')} />
            View only
          </label>
        </fieldset>
        {phase === 'active' ? (
          <div className="demo-row">
            <p className="demo-url" aria-label="Example link">https://your-address/s/Xk9f…</p>
            <button type="button" className="btn btn-sm btn-danger" onClick={revoke}>Revoke link</button>
          </div>
        ) : (
          <div className="demo-row">
            <p className="muted">Payment is between you and your client.</p>
            {phase === 'revoked' ? (
              <button type="button" className="btn btn-sm btn-primary" onClick={again}>Create a new link</button>
            ) : (
              <button type="button" className="btn btn-sm btn-primary attn" onClick={create}>Create link</button>
            )}
          </div>
        )}
      </div>

      <div className="demo-pane">
        <p className="demo-label">What your client sees</p>
        {phase === 'none' && <p className="muted">Nothing yet. Create a link to send.</p>}
        {phase === 'revoked' && <p className="demo-state locked">This link is no longer active. Please contact the sender.</p>}
        {phase === 'active' && (
          <div className="demo-client">
            <p><strong>brand-film-master.mov</strong> <span className="muted">3.8 GB · SHA-256 shown</span></p>
            <div className="demo-row" style={{ justifyContent: 'flex-start' }}>
              <button type="button" className="btn btn-sm" onClick={() => add('client previewed the file')}>
                <Eye size={16} aria-hidden="true" /> Preview
              </button>
              {access === 'download' ? (
                <button type="button" className="btn btn-sm btn-accent" onClick={() => add('client downloaded the original')}>
                  <Download size={16} aria-hidden="true" /> Download original
                </button>
              ) : (
                <span className="muted small">No download button on this link.</span>
              )}
            </div>
            {access === 'view_only' && (
              <p className="demo-state">
                <TriangleAlert size={16} aria-hidden="true" />
                <span>View-only discourages casual saving. It can't stop someone who wants a copy: the browser still receives the file, and screens can be recorded.</span>
              </p>
            )}
            {access === 'download' && (
              <p className="muted small"><Link2 size={14} aria-hidden="true" /> The download is the original file, byte for byte. No watermark.</p>
            )}
          </div>
        )}
      </div>

      <ul className="demo-log" aria-live="polite" aria-label="Activity log">
        {log.map((e, i) => (<li key={i}>{e}</li>))}
      </ul>
      <div className="demo-foot">
        <span className="muted small">Interactive demo. Nothing is saved or sent. </span>
        <button type="button" className="linkbtn" onClick={reset}>Start over</button>
      </div>
    </div>
  );
}
