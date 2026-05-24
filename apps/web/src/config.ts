export interface SiteConfig {
  language: string
  title: string
  description: string
  brandName: string
}

export interface HeroConfig {
  titleText: string
  subtitleLines: string[]
  ctaLabel: string
  roomLabel: string
  /** Path from public/, e.g. "/images/hero.jpg". Empty → black background. */
  fluidImagePath: string
}

export interface WorkItem {
  id: string
  title: string
  type: string
  status: string
  metrics: string
  /** Path from public/, e.g. "/images/work-1.jpg". MUST be a topic-relevant image (generated via generate_image, or a downloaded relevant asset). Do NOT point this at placeholder services like picsum.photos, unsplash random, or lorem.space. */
  image: string
  artist: string
  location: string
  medium: string
  article: string
}

export interface GalleryConfig {
  eyebrowLabel: string
  titleLines: string[]
  stats: { label: string; value: string }[]
  sideLabel: string
  works: WorkItem[]
}

export interface InstantConfig {
  /** 3 text lines animated in sequence. Index 0 big serif, 1 assembly, 2 caption. */
  textLines: [string, string, string] | string[]
  /** Path from public/, e.g. "/videos/ambient.mp4". Empty → black background. */
  videoPath: string
  roomLabel: string
}

export interface NavLink {
  label: string
  href?: string
}

export interface FooterConfig {
  brandText: string
  taglineLines: string[]
  navigationHeading: string
  navigationLinks: NavLink[]
  contactHeading: string
  contactLinks: NavLink[]
  copyright: string
  creditText: string
}

export interface WorkDetailConfig {
  backLabel: string
  artistLabel: string
  locationLabel: string
  mediumLabel: string
  backToGalleryLabel: string
  metaRoomSuffix: string
  footerNote: string
  notFoundTitle: string
  notFoundLink: string
}

export const siteConfig: SiteConfig = {
  language: "",
  title: "",
  description: "",
  brandName: "",
}

export const heroConfig: HeroConfig = {
  titleText: "",
  subtitleLines: [],
  ctaLabel: "",
  roomLabel: "",
  fluidImagePath: "",
}

export const galleryConfig: GalleryConfig = {
  eyebrowLabel: "",
  titleLines: [],
  stats: [],
  sideLabel: "",
  works: [],
}

export const instantConfig: InstantConfig = {
  textLines: ["", "", ""],
  videoPath: "",
  roomLabel: "",
}

export const footerConfig: FooterConfig = {
  brandText: "",
  taglineLines: [],
  navigationHeading: "",
  navigationLinks: [],
  contactHeading: "",
  contactLinks: [],
  copyright: "",
  creditText: "",
}

export const workDetailConfig: WorkDetailConfig = {
  backLabel: "",
  artistLabel: "",
  locationLabel: "",
  mediumLabel: "",
  backToGalleryLabel: "",
  metaRoomSuffix: "",
  footerNote: "",
  notFoundTitle: "",
  notFoundLink: "",
}

// Helper map for WorkDetail lookups
export const worksById: Record<string, WorkItem> = Object.fromEntries(
  galleryConfig.works.map((w) => [w.id.toLowerCase(), w]),
)
