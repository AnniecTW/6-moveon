export async function GET(
  _request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params
  if (path.some((segment) => segment === "." || segment === ".." || /[\\/]/.test(segment))) {
    return new Response(null, { status: 400 })
  }

  try {
    const backendUrl = process.env.DJANGO_API_URL || "http://127.0.0.1:8000"
    const url = new URL(`/media/${path.map(encodeURIComponent).join("/")}`, backendUrl)
    const response = await fetch(url, { signal: AbortSignal.timeout(10000) })
    if (!response.ok) return new Response(null, { status: response.status })

    return new Response(response.body, {
      headers: {
        "Content-Type": response.headers.get("Content-Type") || "application/octet-stream",
        "X-Content-Type-Options": "nosniff",
      },
    })
  } catch {
    return new Response(null, { status: 502 })
  }
}
