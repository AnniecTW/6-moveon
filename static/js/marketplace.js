import { setupCarousel } from "./marketplace/carousel.js";
import { setupDrawer } from "./marketplace/drawer.js";
import { setupFavorites } from "./marketplace/favorites.js";
import { setupBrowse } from "./marketplace/browse.js";
import { setupHotspots } from "./marketplace/hotspots.js";
import { setupHeader } from "./marketplace/header.js";
import { setupDashboardNavigation } from "./marketplace/dashboard.js";
import { setupSellerInsights } from "./marketplace/insights.js";
import { setupSellerPricing } from "./marketplace/pricing.js";
import { setupSellerSettings } from "./marketplace/settings.js";
import { setupBuyerPickups } from "./marketplace/buyer.js";

setupCarousel();
setupHotspots();
setupHeader();
setupDashboardNavigation();
setupSellerInsights();
setupSellerPricing();
setupSellerSettings();
setupBuyerPickups();
if (document.querySelector("[data-marketplace]")) {
  const favorites = setupFavorites();
  const drawer = setupDrawer();
  setupBrowse({ drawer, favorites });
}
document.documentElement.classList.add("enhanced");
