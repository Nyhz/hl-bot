import { NextRequest, NextResponse } from "next/server";
import { controlAllowed } from "@/lib/ws";

export async function POST(req: NextRequest, ctx: { params: Promise<{ action: string }> }) {
  const { action } = await ctx.params;
  if (!controlAllowed(action)) {
    return NextResponse.json({ error: "accion no permitida" }, { status: 400 });
  }
  const base = process.env.BOT_API_URL ?? "http://localhost:3300";
  const token = process.env.CONTROL_TOKEN ?? "";
  const body = await req.text();
  const path = action === "limits" ? "/limits" : `/session/${action}`;
  const res = await fetch(`${base}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Control-Token": token },
    body: body || "{}",
  });
  const text = await res.text();
  return new NextResponse(text, { status: res.status, headers: { "Content-Type": "application/json" } });
}
