export interface LaunchForm {
  capital: number; maxLoss: number;
}
// El servidor aplica el perfil afinado (watchlist, spread, grid, caps de
// exposición): desde el dashboard solo se eligen capital y pérdida máxima.
export interface LaunchBody {
  capital: number; max_loss: number;
}
export function buildLaunchBody(f: LaunchForm): LaunchBody {
  return { capital: f.capital, max_loss: f.maxLoss };
}
export async function postControl(action: string, body?: unknown): Promise<{ ok: boolean; status: number; data: unknown }> {
  const res = await fetch(`/api/control/${action}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  let data: unknown = null;
  try { data = await res.json(); } catch { /* sin cuerpo */ }
  return { ok: res.ok, status: res.status, data };
}
