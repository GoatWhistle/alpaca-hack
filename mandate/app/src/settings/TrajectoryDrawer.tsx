import { Icon } from "../components/Icon";
import { useFocusTrap } from "./useFocusTrap";
import { CadenceSection, DiscoverySection, GatesSection } from "./TrajectoryFields";
import { useScrollLock, useTrajectoryForm } from "./useTrajectoryForm";

interface TrajectoryDrawerProps {
  trajectory: Record<string, unknown>;
  universe: string[];
  open: boolean;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}

export function TrajectoryDrawer({
  trajectory,
  universe,
  open,
  onClose,
  onSaved,
}: TrajectoryDrawerProps) {
  const { form, patch, toggleSymbol, reviewing, setReviewing, saving, message, save } =
    useTrajectoryForm(trajectory, universe, onSaved, onClose);
  const drawerRef = useFocusTrap(open, onClose);
  useScrollLock(open);

  if (!open) return null;

  return (
    <div
      className="mandate-chrome settings-backdrop"
      onMouseDown={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <aside
        ref={drawerRef as React.RefObject<HTMLElement>}
        className="settings-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="monitoring-settings-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="settings-drawer-header">
          <div>
            <h2 id="monitoring-settings-title">Monitoring settings</h2>
          </div>
          <button className="icon-button" aria-label="Close monitoring settings" onClick={onClose}>
            <Icon name="close" />
          </button>
        </header>

        <div className="settings-form">
          <CadenceSection form={form} patch={patch} />
          <GatesSection form={form} patch={patch} />
          <DiscoverySection form={form} patch={patch} />

          <section className="settings-section">
            <h3>Posture &amp; authority</h3>
            <div className="settings-grid">
              <label>
                Risk posture
                <select
                  value={form.risk_posture}
                  onChange={(event) => patch({ risk_posture: event.target.value })}
                >
                  <option value="defensive">Defensive</option>
                  <option value="balanced">Balanced</option>
                  <option value="opportunistic">Opportunistic</option>
                </select>
              </label>
              <label>
                Runner state
                <select
                  value={form.enabled ? "enabled" : "paused"}
                  onChange={(event) => patch({ enabled: event.target.value === "enabled" })}
                >
                  <option value="enabled">Enabled</option>
                  <option value="paused">Paused</option>
                </select>
              </label>
            </div>
            <div className="symbol-picker">
              <small>Monitored mandate universe</small>
              <div>
                {universe.map((symbol) => (
                  <button
                    key={symbol}
                    className={form.symbols.includes(symbol) ? "selected" : ""}
                    aria-pressed={form.symbols.includes(symbol)}
                    onClick={() => toggleSymbol(symbol)}
                  >
                    {symbol}
                  </button>
                ))}
              </div>
            </div>
            <label className="thesis-field">
              Research trajectory
              <textarea
                maxLength={2000}
                value={form.thesis}
                onChange={(event) => patch({ thesis: event.target.value })}
              />
            </label>
          </section>

          {!reviewing ? (
            <button
              className="settings-save"
              disabled={!form.symbols.length}
              onClick={() => setReviewing(true)}
            >
              Review changes
            </button>
          ) : (
            <div className="confirm-box">
              <p>
                This changes monitoring and proposal logic only. It cannot place an order,
                expand the mandate universe, or grant execution authority.
              </p>
              <button disabled={saving} onClick={() => void save()}>
                {saving ? "Applying…" : "Confirm & apply"}
              </button>
              <button onClick={() => setReviewing(false)}>Back</button>
            </div>
          )}

          {message && (
            <p className="settings-message" role="status" aria-live="polite">
              {message}
            </p>
          )}
        </div>
      </aside>
    </div>
  );
}
