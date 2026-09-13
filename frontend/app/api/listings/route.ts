export async function GET() {
  try {
    const backendUrl = process.env.DJANGO_API_URL || "http://127.0.0.1:8000"
    const response = await fetch(new URL("/api/listings/", backendUrl), {
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
      headers: {
        Accept: "application/json",
      },
    })

    if (!response.ok) {
      return Response.json({ error: `Django API error: ${response.status}` }, { status: response.status })
    }

    const data = await response.json()
    if (!Array.isArray(data)) {
      return Response.json({ error: "Invalid listings response from Django" }, { status: 502 })
    }
    return Response.json(data.map((listing) => {
      if (!listing.imageUrl) return listing
      const imageUrl = new URL(listing.imageUrl, backendUrl)
      // Uploaded media must use the browser's origin, not Django's loopback address.
      if (imageUrl.origin === new URL(backendUrl).origin && imageUrl.pathname.startsWith("/media/")) {
        return { ...listing, imageUrl: `/api${imageUrl.pathname}${imageUrl.search}` }
      }
      return listing
    }))
  } catch (error) {
    console.error("Proxy to Django failed:", error)
    return Response.json({ error: "Failed to reach Django backend" }, { status: 502 })
  }
}
