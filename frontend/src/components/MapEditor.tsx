/**
 * 校园地图编辑器（管理员）。
 *
 * - 左：素材面板（地面 / 建筑 / 摆件），点选后到画布上点一下即可放置
 * - 中：等距画布，拖动移动（半格吸附）、滚轮缩放、空白拖动平移
 * - 右：属性面板（位置 / 尺寸 / 高度 / 名称 / 绑定地点）
 * - 顶：撤销、复制、删除、网格、适应视图、保存
 *
 * 编辑中的草稿只存在本组件内；保存成功后写入 `useMap`，
 * 并依赖后端广播的 `map_updated` 同步给所有玩家。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { adminApi } from '../api/endpoints';
import type { CampusMapView, MapObjectInput, MapObjectView } from '../api/types';
import IsoMap, { type Viewport } from './IsoMap';
import { useMap } from '../store/map';

interface PaletteItem {
  kind: 'ground' | 'building' | 'prop';
  variant: string;
  label: string;
  tw: number;
  th: number;
  height?: number;
}

const PALETTE: { group: string; items: PaletteItem[] }[] = [
  {
    group: '地面',
    items: [
      { kind: 'ground', variant: 'grass', label: '草地', tw: 8, th: 6 },
      { kind: 'ground', variant: 'dirt', label: '土路', tw: 6, th: 2 },
      { kind: 'ground', variant: 'water', label: '水域', tw: 8, th: 6 },
      { kind: 'ground', variant: 'field_track', label: '跑道', tw: 9, th: 8 },
      { kind: 'ground', variant: 'plaza', label: '广场', tw: 6, th: 6 },
      { kind: 'ground', variant: 'sand', label: '沙地', tw: 6, th: 5 },
    ],
  },
  {
    group: '建筑',
    items: [
      { kind: 'building', variant: 'main', label: '教学楼', tw: 7, th: 6, height: 4 },
      { kind: 'building', variant: 'tower', label: '图书馆/塔楼', tw: 6, th: 5, height: 5.5 },
      { kind: 'building', variant: 'hall', label: '活动室', tw: 6, th: 5, height: 3 },
      { kind: 'building', variant: 'canteen', label: '食堂', tw: 6, th: 5, height: 3 },
      { kind: 'building', variant: 'dorm', label: '宿舍', tw: 8, th: 5, height: 4 },
      { kind: 'building', variant: 'shop', label: '小店', tw: 5, th: 4, height: 2 },
    ],
  },
  {
    group: '摆件',
    items: [
      { kind: 'prop', variant: 'tree', label: '阔叶树', tw: 1.4, th: 1.4 },
      { kind: 'prop', variant: 'pine', label: '松树', tw: 1.4, th: 1.4 },
      { kind: 'prop', variant: 'rock', label: '石块', tw: 1, th: 0.9 },
      { kind: 'prop', variant: 'bench', label: '长椅', tw: 1.6, th: 0.7 },
      { kind: 'prop', variant: 'lamp', label: '路灯', tw: 0.8, th: 0.8 },
      { kind: 'prop', variant: 'flower', label: '花坛', tw: 1.2, th: 1.2 },
      { kind: 'prop', variant: 'board', label: '公告板', tw: 1.6, th: 0.7 },
    ],
  },
];

const LAYER_OF: Record<string, number> = { ground: 0, prop: 10, building: 20 };
const HISTORY_MAX = 40;

const VARIANT_OPTIONS: Record<string, string[]> = {
  ground: PALETTE[0].items.map((i) => i.variant),
  building: PALETTE[1].items.map((i) => i.variant),
  prop: PALETTE[2].items.map((i) => i.variant),
};

let tempCounter = 0;
const newTempId = () => `mo_new_${Date.now().toString(36)}_${tempCounter++}`;

export default function MapEditor() {
  const serverMap = useMap((s) => s.map);
  const setServerMap = useMap((s) => s.setMap);
  const fetchMap = useMap((s) => s.fetch);

  const [draft, setDraft] = useState<MapObjectView[]>([]);
  const [title, setTitle] = useState('平行校园');
  const [cols, setCols] = useState(40);
  const [rows, setRows] = useState(30);
  const [selected, setSelected] = useState<string | null>(null);
  const [placing, setPlacing] = useState<PaletteItem | null>(null);
  const [view, setView] = useState<Viewport>({ zoom: 1, panX: 0, panY: 0 });
  const [showGrid, setShowGrid] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const history = useRef<MapObjectView[][]>([]);
  const dragSnapshot = useRef(false);
  /** 最新草稿（避免在 setState updater 里改 history —— StrictMode 会双调用） */
  const draftRef = useRef<MapObjectView[]>([]);
  draftRef.current = draft;

  useEffect(() => {
    void fetchMap();
  }, [fetchMap]);

  // 服务端地图到达时灌入草稿（编辑中不覆盖）
  useEffect(() => {
    if (!serverMap || dirty) return;
    setDraft(serverMap.objects ?? []);
    setTitle(serverMap.title ?? '平行校园');
    setCols(serverMap.cols);
    setRows(serverMap.rows);
  }, [serverMap, dirty]);

  const selectedObj = useMemo(
    () => draft.find((o) => o.id === selected) ?? null,
    [draft, selected],
  );

  /** 带历史快照的修改 */
  const commit = useCallback(
    (updater: (list: MapObjectView[]) => MapObjectView[]) => {
      const cur = draftRef.current;
      history.current = [...history.current.slice(-(HISTORY_MAX - 1)), cur];
      setDraft(updater(cur));
      setDirty(true);
    },
    [],
  );

  const undo = useCallback(() => {
    const prev = history.current.pop();
    if (!prev) {
      setMessage('没有可撤销的操作');
      return;
    }
    setDraft(prev);
    setDirty(true);
    setMessage('已撤销');
  }, []);

  const handleMove = useCallback(
    (id: string, tx: number, ty: number) => {
      if (!dragSnapshot.current) {
        history.current = [...history.current.slice(-(HISTORY_MAX - 1)), draftRef.current];
        dragSnapshot.current = true;
      }
      setDraft((cur) => cur.map((o) => (o.id === id ? { ...o, tx, ty } : o)));
      setDirty(true);
    },
    [],
  );

  const handlePlace = useCallback(
    (tx: number, ty: number) => {
      if (!placing) return;
      const obj: MapObjectView = {
        id: newTempId(),
        kind: placing.kind,
        variant: placing.variant,
        // 点击点作为对象中心
        tx: Math.round((tx - placing.tw / 2) * 2) / 2,
        ty: Math.round((ty - placing.th / 2) * 2) / 2,
        tw: placing.tw,
        th: placing.th,
        height: placing.height ?? 0,
        layer: LAYER_OF[placing.kind] ?? 0,
        name: '',
        location_id: null,
        props: { seed: Math.floor(Math.random() * 900) + 10 },
      };
      commit((list) => [...list, obj]);
      setSelected(obj.id);
      setMessage(`已放置「${placing.label}」，可拖动调整位置`);
      // 放置一次就退出放置模式：否则 placing 一直为真，
      // IsoMap 里 `if (placing) return` 会让后续所有拖动失效（无法拖动物体的根因）
      setPlacing(null);
    },
    [commit, placing],
  );

  const patchSelected = useCallback(
    (patch: Partial<MapObjectView>) => {
      if (!selected) return;
      commit((list) => list.map((o) => (o.id === selected ? { ...o, ...patch } : o)));
    },
    [commit, selected],
  );

  const removeSelected = useCallback(() => {
    if (!selected) return;
    commit((list) => list.filter((o) => o.id !== selected));
    setSelected(null);
    setMessage('已删除');
  }, [commit, selected]);

  const duplicateSelected = useCallback(() => {
    if (!selectedObj) return;
    const copy: MapObjectView = {
      ...selectedObj,
      id: newTempId(),
      tx: selectedObj.tx + 1,
      ty: selectedObj.ty + 1,
    };
    commit((list) => [...list, copy]);
    setSelected(copy.id);
    setMessage('已复制');
  }, [commit, selectedObj]);

  const save = useCallback(async () => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const objects: MapObjectInput[] = draft.map((o) => ({
        id: o.id.startsWith('mo_new_') ? null : o.id,
        kind: o.kind,
        variant: o.variant,
        tx: o.tx,
        ty: o.ty,
        tw: o.tw,
        th: o.th,
        height: o.height ?? 0,
        layer: o.layer ?? 0,
        name: o.name ?? '',
        location_id: o.location_id ?? null,
        props: o.props ?? {},
      }));
      const saved: CampusMapView = await adminApi.saveMap({ objects, title });
      setServerMap(saved);
      setDraft(saved.objects ?? []);
      history.current = [];
      setDirty(false);
      setMessage(`已保存 · 版本 v${saved.version} · 在线玩家会自动刷新`);
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setBusy(false);
    }
  }, [draft, setServerMap, title]);

  const reload = useCallback(() => {
    if (dirty && !window.confirm('放弃未保存的修改并重新载入服务端地图？')) return;
    history.current = [];
    setDirty(false);
    setSelected(null);
    setPlacing(null);
    void fetchMap();
  }, [dirty, fetchMap]);

  // 快捷键
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;
      if (e.key === 'Escape') {
        setPlacing(null);
        setSelected(null);
      } else if ((e.key === 'Delete' || e.key === 'Backspace') && selected) {
        e.preventDefault();
        removeSelected();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        undo();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        void save();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [removeSelected, save, selected, undo]);

  const fit = useCallback(() => setView({ zoom: 1, panX: 0, panY: 0 }), []);

  const previewMap: CampusMapView = {
    version: serverMap?.version ?? 0,
    cols,
    rows,
    title,
    objects: draft,
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[190px_minmax(0,1fr)_260px]">
      {/* ── 素材面板 ── */}
      <div className="card max-h-[70vh] space-y-4 overflow-auto p-3">
        <div>
          <p className="text-xs font-medium text-ink">素材</p>
          <p className="mt-1 text-[11px] leading-relaxed text-muted">
            选一个素材，然后在地图上点一下放置。
          </p>
        </div>
        {PALETTE.map((group) => (
          <div key={group.group}>
            <p className="mb-2 text-[11px] uppercase tracking-wide text-muted">{group.group}</p>
            <div className="grid grid-cols-2 gap-1.5">
              {group.items.map((item) => {
                const active = placing?.variant === item.variant && placing?.kind === item.kind;
                return (
                  <button
                    key={`${item.kind}-${item.variant}`}
                    type="button"
                    onClick={() => setPlacing(active ? null : item)}
                    className={`rounded-lg px-2 py-1.5 text-[11px] transition-colors ${
                      active ? 'bg-brand-500 text-white' : 'bg-black/[.04] text-ink hover:bg-black/[.07]'
                    }`}
                  >
                    {item.label}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* ── 画布 ── */}
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <button className="btn-outline text-xs" onClick={fit}>适应视图</button>
          <button className="btn-outline text-xs" onClick={() => setShowGrid((v) => !v)}>
            {showGrid ? '隐藏网格' : '显示网格'}
          </button>
          <button className="btn-outline text-xs" disabled={history.current.length === 0} onClick={undo}>
            撤销
          </button>
          <button className="btn-outline text-xs" disabled={!selected} onClick={duplicateSelected}>
            复制
          </button>
          <button className="btn-outline text-xs" disabled={!selected} onClick={removeSelected}>
            删除
          </button>
          <button className="btn-outline text-xs" disabled={busy} onClick={reload}>
            重新载入
          </button>
          <span className="ml-auto text-[11px] text-muted">
            {draft.length} 个对象 · {selected ? `已选 ${selectedObj?.name || selectedObj?.variant || ''}` : '未选中'}
          </span>
          <button className="btn-primary text-xs" disabled={busy || !dirty} onClick={() => void save()}>
            {busy ? '保存中…' : dirty ? '保存并同步' : '已保存'}
          </button>
        </div>

        {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        {message && <p role="status" className="rounded-xl bg-green-50 p-3 text-sm text-green-800">{message}</p>}

        <div className="card h-[62vh] min-h-[420px] overflow-hidden">
          <IsoMap
            map={previewMap}
            editable
            selectedId={selected}
            placing={placing ? { kind: placing.kind, variant: placing.variant } : null}
            onSelect={setSelected}
            onPlace={handlePlace}
            onMove={handleMove}
            onMoveEnd={() => { dragSnapshot.current = false; }}
            showGrid={showGrid}
            view={view}
            onViewChange={setView}
          />
        </div>
        <p className="text-[11px] text-muted">
          拖动移动（吸附半格）· 滚轮缩放 · 空白拖动平移 · Delete 删除 · Ctrl+Z 撤销 · Ctrl+S 保存
        </p>
      </div>

      {/* ── 属性面板 ── */}
      <div className="card max-h-[70vh] space-y-3 overflow-auto p-3">
        <p className="text-xs font-medium text-ink">属性</p>
        {!selectedObj ? (
          <p className="text-[11px] leading-relaxed text-muted">
            点击地图上的对象进行编辑。地图标题：
            <input
              className="mt-2 w-full rounded-lg border border-black/10 bg-white px-2 py-1 text-xs text-ink"
              value={title}
              maxLength={24}
              onChange={(e) => { setTitle(e.target.value); setDirty(true); }}
            />
          </p>
        ) : (
          <div className="space-y-2.5">
            <Field label="类型">
              <input className={inputCls} value={selectedObj.kind} readOnly />
            </Field>
            <Field label="样式">
              <select
                className={inputCls}
                value={selectedObj.variant}
                onChange={(e) => patchSelected({ variant: e.target.value })}
              >
                {(VARIANT_OPTIONS[selectedObj.kind] ?? []).map((v) => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            </Field>
            <Field label="名称">
              <input
                className={inputCls}
                value={selectedObj.name ?? ''}
                maxLength={24}
                placeholder="可留空"
                onChange={(e) => patchSelected({ name: e.target.value })}
              />
            </Field>
            <Field label="绑定地点">
              <select
                className={inputCls}
                value={selectedObj.location_id ?? ''}
                onChange={(e) => patchSelected({ location_id: e.target.value || null })}
              >
                <option value="">（不绑定）</option>
                {LOCATION_CHOICES.map((l) => (
                  <option key={l.id} value={l.id}>{l.name}</option>
                ))}
              </select>
            </Field>
            <div className="grid grid-cols-2 gap-2">
              <Num label="X" value={selectedObj.tx} step={0.5} onChange={(v) => patchSelected({ tx: v })} />
              <Num label="Y" value={selectedObj.ty} step={0.5} onChange={(v) => patchSelected({ ty: v })} />
              <Num label="宽" value={selectedObj.tw} step={0.5} min={0.5} onChange={(v) => patchSelected({ tw: v })} />
              <Num label="深" value={selectedObj.th} step={0.5} min={0.5} onChange={(v) => patchSelected({ th: v })} />
              <Num label="高度" value={selectedObj.height ?? 0} step={0.5} min={0} onChange={(v) => patchSelected({ height: v })} />
              <Num label="层级" value={selectedObj.layer ?? 0} step={1} onChange={(v) => patchSelected({ layer: v })} />
            </div>
            <div className="flex gap-2">
              <button
                className="btn-outline flex-1 text-xs"
                onClick={() => patchSelected({ layer: (selectedObj.layer ?? 0) + 10 })}
              >
                上移一层
              </button>
              <button
                className="btn-outline flex-1 text-xs"
                onClick={() => patchSelected({ layer: (selectedObj.layer ?? 0) - 10 })}
              >
                下移一层
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const LOCATION_CHOICES = [
  { id: 'teaching_a', name: '教学楼 A' },
  { id: 'library', name: '图书馆' },
  { id: 'club_room', name: '社团活动室' },
  { id: 'canteen', name: '第一食堂' },
  { id: 'field', name: '操场' },
  { id: 'lakeside', name: '湖边长椅' },
  { id: 'dorm', name: '宿舍区' },
  { id: 'milktea', name: '校门口奶茶店' },
];

const inputCls =
  'w-full rounded-lg border border-black/10 bg-white px-2 py-1 text-xs text-ink outline-none focus:border-brand-500';

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] text-muted">{label}</span>
      {children}
    </label>
  );
}

function Num({
  label, value, step = 0.5, min, onChange,
}: {
  label: string;
  value: number;
  step?: number;
  min?: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] text-muted">{label}</span>
      <input
        type="number"
        className={inputCls}
        value={value}
        step={step}
        min={min}
        onChange={(e) => {
          const v = Number(e.target.value);
          if (Number.isFinite(v)) onChange(v);
        }}
      />
    </label>
  );
}
