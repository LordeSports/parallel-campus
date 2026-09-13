/** 轻量 toast（spec/07 §6）。 */

import { useEffect } from 'react';

export default function Toast({ text, onClose }: { text: string; onClose: () => void }) {
  useEffect(() => {
    const t = window.setTimeout(onClose, 3200);
    return () => window.clearTimeout(t);
  }, [onClose, text]);

  return (
    <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 animate-fade-up">
      <div className="flex items-center gap-3 rounded-full bg-ink px-4 py-2 text-xs text-white shadow-lg">
        <span>{text}</span>
        <button type="button" className="opacity-60 hover:opacity-100" onClick={onClose}>
          ✕
        </button>
      </div>
    </div>
  );
}
