"use client"

import { useEffect, useMemo, useState } from "react"
import type { Listing, MarketplaceFilters, SortOption } from "@/types/marketplace"
import { featuredBundles } from "@/data/featuredBundles"
import { defaultFilters } from "@/data/filters"
import { applyFilters, countActiveFilters } from "@/lib/marketplace-utils"
import { Header } from "@/components/Header"
import { MoveInBundlePromo } from "@/components/MoveInBundlePromo"
import { FeaturedBundleCarousel } from "@/components/FeaturedBundleCarousel"
import { MarketplaceToolbar } from "@/components/MarketplaceToolbar"
import { SelectedFilterChips } from "@/components/SelectedFilterChips"
import { ListingGrid } from "@/components/ListingGrid"
import { FilterDrawer } from "@/components/FilterDrawer"

function normalizeListing(item: any): Listing {
  const condition = item.condition
  let normalizedCondition: Listing["condition"] = "Good"

  if (condition === "Like New" || condition === "NEW" || condition === "New") {
    normalizedCondition = "Like New"
  } else if (condition === "Excellent") {
    normalizedCondition = "Excellent"
  } else if (condition === "Fair") {
    normalizedCondition = "Fair"
  } else if (condition === "Good") {
    normalizedCondition = "Good"
  }

  return {
    id: String(item.id),
    itemName: item.itemName ?? item.title ?? "Item",
    title: item.title ?? "Untitled listing",
    imageUrl: item.imageUrl || "/placeholder.svg",
    originalPrice: Number(item.originalPrice ?? 0),
    salePrice: Number(item.salePrice ?? 0),
    datePosted: item.datePosted ?? "Recent",
    seller: {
      id: String(item.seller?.id ?? "unknown"),
      name: item.seller?.name ?? "Seller",
    },
    condition: normalizedCondition,
    category: item.category ?? "Furniture",
    itemType: item.itemType ?? "Item",
    space: item.space ?? "Living Room",
    bundleEligible: Boolean(item.bundleEligible),
    distanceMiles: Number(item.distanceMiles ?? 0),
    deliveryOptions: Array.isArray(item.deliveryOptions) ? item.deliveryOptions : [],
    isSaved: Boolean(item.isSaved),
  }
}

export function MarketplaceApp() {
  const [search, setSearch] = useState("")
  const [filters, setFilters] = useState<MarketplaceFilters>(defaultFilters)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid")
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set())
  const [listings, setListings] = useState<Listing[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [retryCount, setRetryCount] = useState(0)

  useEffect(() => {
    let isMounted = true
    const controller = new AbortController()

    async function loadListings() {
      setIsLoading(true)
      setLoadError(null)
      try {
        const response = await fetch("/api/listings", {
          signal: controller.signal,
          cache: "no-store",
        })
        if (!response.ok) {
          throw new Error(`Request failed with status ${response.status}`)
        }

        const payload = await response.json()
        if (!Array.isArray(payload)) {
          throw new Error("Invalid listings response")
        }
        if (isMounted) {
          setListings(payload.map(normalizeListing))
        }
      } catch {
        if (isMounted) {
          setLoadError("We couldn’t load the listings. Please try again.")
        }
      } finally {
        if (isMounted) {
          setIsLoading(false)
        }
      }
    }

    loadListings()

    return () => {
      isMounted = false
      controller.abort()
    }
  }, [retryCount])

  const results = useMemo(
    () => applyFilters(listings, filters, search),
    [listings, filters, search],
  )
  const activeFilterCount = useMemo(() => countActiveFilters(filters), [filters])

  const toggleSave = (id: string) =>
    setSavedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const resetFilters = () => setFilters(defaultFilters)

  return (
    <div className="min-h-screen bg-background">
      <Header search={search} onSearchChange={setSearch} savedCount={savedIds.size} />

      <main className="mx-auto max-w-7xl px-4 py-6 md:px-6 md:py-10">
        <section className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_2fr] lg:items-center lg:gap-12">
          <MoveInBundlePromo />
          <FeaturedBundleCarousel bundles={featuredBundles} />
        </section>

        <div className="mt-12 space-y-5">
          <MarketplaceToolbar
            resultCount={results.length}
            activeFilterCount={activeFilterCount}
            sort={filters.sort}
            onSortChange={(sort: SortOption) => setFilters((f) => ({ ...f, sort }))}
            viewMode={viewMode}
            onViewModeChange={setViewMode}
            onOpenFilters={() => setDrawerOpen(true)}
          />

          <SelectedFilterChips filters={filters} onChange={setFilters} onReset={resetFilters} />

          {isLoading ? (
            <p role="status" className="py-12 text-center text-muted-foreground">Loading listings…</p>
          ) : loadError ? (
            <div role="alert" className="rounded-2xl border border-border bg-card p-8 text-center">
              <p>{loadError}</p>
              <button
                type="button"
                onClick={() => setRetryCount((count) => count + 1)}
                className="mt-4 rounded-full border border-border px-5 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Try again
              </button>
            </div>
          ) : <ListingGrid
            listings={results}
            savedIds={savedIds}
            onToggleSave={toggleSave}
            viewMode={viewMode}
            onResetFilters={resetFilters}
          />}
        </div>
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 px-4 py-8 text-sm text-muted-foreground sm:flex-row md:px-6">
          <p>MoveOn — a fresh start at a fair price.</p>
          <p>Curated secondhand furniture, built for move-in season.</p>
        </div>
      </footer>

      <FilterDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        filters={filters}
        onChange={setFilters}
        onReset={resetFilters}
        resultCount={results.length}
      />
    </div>
  )
}
