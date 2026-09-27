# Neural brain HUD assets

- `brain_mesh.obj` / `brain_mesh.npz` — anatomical cerebrum+brainstem mesh (Y-up).
  Source: FrankJohansson “Human brain, Cerebrum & Brainstem” (CC BY 4.0).
  See `THIRD_PARTY_BRAIN_MESH.md`. Used as the hard 3D outer wall + occupancy
  for interior filament constraints. Never painted as a photo sprite.
- `brain-ref-side.png` / `brain-ref.png` — visual north-star references only
  (not painted by the HUD).
- `brain_outline_side.json` — legacy 2D silhouette (superseded by mesh-derived
  outline baked into `brain_mesh.npz`; kept for reference).
