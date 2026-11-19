// Proxies the backend health check. BACKEND_URL is read at request time.
export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  try {
    const upstream = await fetch(`${process.env.BACKEND_URL}/health`, { cache: "no-store" });
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "content-type": "application/json" },
    });
  } catch {
    return Response.json({ status: "unreachable" }, { status: 502 });
  }
}
