"use client"

import Image from "next/image"
import { useState } from "react"
import { Heart, MapPin } from "lucide-react"
import { cn } from "@/lib/utils"
import type { Listing } from "@/types/marketplace"
import { PriceDisplay } from "@/components/PriceDisplay"
import { ConditionBadge } from "@/components/ConditionBadge"
import { BundleBadge } from "@/components/BundleBadge"

interface ListingCardProps {
  listing: Listing
  saved: boolean
  onToggleSave: (id: string) => void
  layout?: "grid" | "list"
}

function SellerBadge({ name }: { name: string }) {
  const initial = name.trim().charAt(0).toUpperCase()
  return (
    <div className="flex items-center gap-2">
      <span
        aria-hidden="true"
        className="flex h-6 w-6 items-center justify-center rounded-full bg-secondary font-serif text-[0.72rem] font-semibold text-primary ring-1 ring-border"
      >
        {initial}
      </span>
      <span className="text-xs text-muted-foreground">{name}</span>
    </div>
  )
}

export function ListingCard({ listing, saved, onToggleSave, layout = "grid" }: ListingCardProps) {
  const isList = layout === "list"
  const [failedImageUrl, setFailedImageUrl] = useState<string | null>(null)

  return (
    <article
      className={cn(
        "group relative flex transition-all duration-300",
        isList
          ? "flex-row overflow-hidden rounded-2xl border border-border bg-card hover:-translate-y-0.5 hover:shadow-[0_18px_40px_-24px_rgba(60,45,30,0.45)]"
          : "flex-col",
      )}
    >
      <div
        className={cn(
          "relative shrink-0 overflow-hidden bg-secondary/60",
          isList ? "w-40 sm:w-56" : "aspect-[4/3] w-full rounded-2xl",
        )}
      >
        <Image
          src={listing.imageUrl && listing.imageUrl !== failedImageUrl ? listing.imageUrl : "/placeholder.svg"}
          onError={() => setFailedImageUrl(listing.imageUrl)}
          alt={listing.title}
          fill
          sizes={isList ? "224px" : "(min-width:1024px) 30vw, (min-width:640px) 45vw, 90vw"}
          className="object-cover transition-transform duration-500 ease-out group-hover:scale-[1.05]"
        />

        {listing.bundleEligible && <BundleBadge className="absolute left-3 top-3" />}

        <button
          type="button"
          onClick={() => onToggleSave(listing.id)}
          aria-pressed={saved}
          aria-label={saved ? `Remove ${listing.title} from saved items` : `Save ${listing.title}`}
          className="absolute right-3 top-3 flex h-9 w-9 items-center justify-center rounded-full bg-card/85 text-foreground shadow-sm ring-1 ring-border backdrop-blur-sm transition hover:bg-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Heart className={cn("h-4 w-4 transition", saved ? "fill-gold text-gold" : "text-muted-foreground")} />
        </button>

        {!isList && (
          <div className="pointer-events-none absolute inset-x-3 bottom-3 translate-y-3 opacity-0 transition-all duration-300 group-hover:translate-y-0 group-hover:opacity-100">
            <span className="pointer-events-auto flex items-center justify-center rounded-full bg-primary px-4 py-2 text-xs font-medium tracking-wide text-primary-foreground shadow-md">
              View Listing
            </span>
          </div>
        )}
      </div>

      <div className={cn("flex flex-1 flex-col gap-2.5 pt-3.5", isList && "justify-center p-4 sm:p-5")}>
        <div className="flex items-start justify-between gap-3">
          <h3 className="min-w-0 text-pretty font-serif text-base font-medium leading-snug text-foreground">
            {listing.title}
          </h3>
          <ConditionBadge condition={listing.condition} className="shrink-0" />
        </div>

        <PriceDisplay originalPrice={listing.originalPrice} salePrice={listing.salePrice} size="md" />

        <div className="mt-auto flex items-center justify-between gap-3 pt-1 text-xs text-muted-foreground">
          <SellerBadge name={listing.seller.name} />
          <div className="flex items-center gap-1">
            <MapPin className="h-3.5 w-3.5" aria-hidden="true" />
            {listing.distanceMiles} mi
          </div>
        </div>
      </div>
    </article>
  )
}
