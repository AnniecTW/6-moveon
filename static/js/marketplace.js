import { setupCarousel } from "./marketplace/carousel.js";
import { setupDrawer } from "./marketplace/drawer.js";
import { setupFavorites } from "./marketplace/favorites.js";
import { setupBrowse } from "./marketplace/browse.js";
import { setupHotspots } from "./marketplace/hotspots.js";
import { setupHeader } from "./marketplace/header.js?v=2";
import { setupDashboardNavigation } from "./marketplace/dashboard.js";
import { setupSellerSettings } from "./marketplace/settings.js";
import { setupBuyerPickups } from "./marketplace/buyer.js";

setupCarousel();
setupHotspots();
setupHeader();
setupDashboardNavigation();
setupSellerSettings();
setupBuyerPickups();
if (document.querySelector("[data-marketplace]")) {
  const favorites = setupFavorites();
  const drawer = setupDrawer();
  setupBrowse({ drawer, favorites });
}
document.documentElement.classList.add("enhanced");
