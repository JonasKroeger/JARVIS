# Neural brain HUD assets

- `brain-ref-side.png` — visual north star only (not painted). Used to extract the
  lateral silhouette polygon in `brain_outline_side.json`.
- `brain_outline_side.json` — closed `(z, y)` outline (anterior+, superior+) for
  **hard clip + dense outer-wall filaments**. Photo is never displayed.
- `brain-ref.png` — earlier reference (kept for history).
- Brain mesh itself is procedural in `hud_widgets.py`.
