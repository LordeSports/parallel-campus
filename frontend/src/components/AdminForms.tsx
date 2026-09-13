/** 控制台共用的表单布局，沿用全站视觉令牌。 */
import { cloneElement, useId, type ReactElement, type ReactNode } from 'react';
import type { LocationView } from '../api/types';

export const fieldClass = 'admin-input';

export function Field({ label, children, hint }: { label: string; children: ReactElement<{ id?: string; 'aria-describedby'?: string }>; hint?: string }) {
  const id = useId();
  return <div className="block min-w-0 space-y-1.5 text-sm text-ink">
    <label htmlFor={id} className="font-medium">{label}</label>
    {cloneElement(children, { id, 'aria-describedby': hint ? `${id}-hint` : undefined })}
    {hint && <span id={`${id}-hint`} className="block text-xs leading-relaxed text-muted">{hint}</span>}
  </div>;
}

export function LocationOptions({ locations }: { locations: LocationView[] }) {
  return <>{locations.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}</>;
}

export function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return <section className="card space-y-5 p-5 sm:p-6"><div><h2 className="text-lg font-semibold text-ink">{title}</h2>
    {description && <p className="mt-1 text-sm leading-relaxed text-muted">{description}</p>}</div>{children}</section>;
}

export type AdminAction = (operation: () => Promise<unknown>, message: string) => Promise<boolean>;
