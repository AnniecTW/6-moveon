import { setupCarousel } from "./marketplace/carousel.js";
import { setupDrawer } from "./marketplace/drawer.js";
import { setupFavorites } from "./marketplace/favorites.js";
import { setupBrowse } from "./marketplace/browse.js";
import { setupHotspots } from "./marketplace/hotspots.js";
import { setupHeader } from "./marketplace/header.js";

setupCarousel();
setupHotspots();
setupHeader();
const favorites = setupFavorites();
const drawer = setupDrawer();
setupBrowse({ drawer, favorites });
document.documentElement.classList.add("enhanced");
